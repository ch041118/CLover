import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from test_api import api,auth
from test_matching import prepare,slot,DAY,REGION
from test_teams_routes import setup_routes
from app.models import (VoiceJob,FlowEvent,ElderProfile,DeviceLink,AutoPolicy,Availability,Booking,Coordination,Care,FlowNotice)
from app.intent import Intent,window,TimeUnclear
from app.matching import KST

AUDIO=base64.b64encode(b'fake-audio'*80).decode()

def setup(c,app):
    h=prepare(c);setup_routes(c,app,h)
    assert c.post('/api/preferences',headers=h['elder1'],json={'local_ai':True}).status_code==200
    with app.state.factory() as db:
        db.add(ElderProfile(elder_id='elder1',worker_id='worker1',registered_by='caregiver',encrypted_details=app.state.flow.encode({'name':'테스트 어르신'})));db.commit()
    assert c.post('/api/caregiver/auto-policy',headers=h['caregiver'],json={'enabled':True,'categories':['meal','housekeeping']}).status_code==200
    app.state.flow.speech=SimpleNamespace(transcribe=lambda _:f'{DAY} 오후 두 시에 청소 도와줘')
    app.state.flow.parser=SimpleNamespace(parse=lambda text:Intent(category='housekeeping',urgency='normal',action='request',evidence='청소',time_text='오후 두 시'))
    return h

def send(c,h,key='request-key-0000001',reply=None):
    r=c.post('/api/flow/voice',headers=h['elder1'],json={'request_key':key,'audio_base64':AUDIO,'reply_to':reply})
    assert r.status_code==202,r.text
    return r.json()['id']


def test_assisted_enrollment_pair_refresh_revoke(api):
    c,app=api;h=prepare(c)
    body={'name':'테스트','region':REGION,'location':{'longitude':127,'latitude':37,'label':'테스트로 1','consent':True},'local_ai':True,'consent_confirmed':True}
    assert c.post('/api/caregiver/elders',headers=h['elder1'],json=body).status_code==403
    elder=c.post('/api/caregiver/elders',headers=h['caregiver'],json=body).json()['elder_id']
    code=c.post(f'/api/staff/elders/{elder}/pair',headers=h['caregiver'],json={}).json()['code']
    paired=c.post('/api/device/pair',json={'code':code}).json()
    assert c.post('/api/device/pair',json={'code':code}).status_code==401
    assert c.post('/api/device/refresh',json={'secret':paired['secret']}).status_code==200
    eh={'Authorization':'Bearer '+paired['access_token']}
    assert c.get('/api/me',headers=eh).json()['role']=='elder'
    assert c.get('/api/staff/elders',headers=eh).status_code==403
    assert c.post(f'/api/staff/elders/{elder}/revoke',headers=h['worker1'],json={}).status_code==200
    assert c.get('/api/me',headers=eh).status_code==401
    assert c.post('/api/device/refresh',json={'secret':paired['secret']}).status_code==401


def test_queue_then_auto_confirm_partial_block_and_idempotency(api):
    c,app=api;h=setup(c,app);sid=slot(c,h,'13:00','17:00');jid=send(c,h)
    assert c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json()['state']=='queued'
    assert send(c,h)==jid
    assert app.state.flow.process_one()
    job=c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json();assert job['state']=='assigned',job
    assert job['schedule']['start']=='14:00' and job['schedule']['end']=='14:30'
    with app.state.factory() as db:
        j=db.get(VoiceJob,jid);assert j.encrypted_audio is None
        assert db.get(Booking,j.booking_id).status=='accepted'
        assert db.get(Care,j.care_id).review_required is False
        assert db.scalar(select(Coordination).where(Coordination.care_id==j.care_id))
        open_slots=db.scalars(select(Availability).where(Availability.state=='open')).all()
        assert {(x.start,x.end) for x in open_slots}=={('13:00','14:00'),('14:30','17:00')}
    assert not app.state.flow.process_one()
    assert c.get('/api/flow/jobs/'+jid,headers=auth(c,'worker2')).status_code==404
    assert c.get('/api/flow/visits/'+job['booking_id'],headers=h['caregiver']).status_code==200


def test_decline_worker_reassign_and_timeline(api):
    c,app=api;h=setup(c,app);slot(c,h,'13:00','17:00');jid=send(c,h);app.state.flow.process_one()
    p=c.get('/api/caregiver/proposals',headers=h['caregiver']).json()[0]
    assert p['stage']=='automatic'
    assert c.post('/api/caregiver/proposals/'+p['proposal_id']+'/decision',headers=h['caregiver'],json={'action':'decline','reason':'개인 사정으로 이번 방문 불가'}).status_code==200
    app.state.flow.reconcile()
    j=c.get('/api/flow/jobs/'+jid,headers=h['worker1']).json();assert j['reason']=='declined'
    assert any('개인 사정' in e['note'] for e in j['events'])
    assert c.get('/api/flow/jobs',headers=auth(c,'worker2')).json()==[]
    target=next(x for x in c.get('/api/worker/open-slots',headers=h['worker1']).json() if x['start']=='14:30')
    body={'action':'assign','slot_id':target['slot_id'],'category':'housekeeping','note':'이용자와 14시30분으로 조율','confirmed':True}
    assert c.post('/api/worker/flow/'+jid+'/resolve',headers=h['worker1'],json=body).status_code==200
    handoff=c.get('/api/flow/visits/'+j['booking_id'],headers=h['caregiver']).json()
    assert handoff['note']==body['note'] and handoff['prepared_by']=='담당자 조율 내용'
    props=c.get('/api/caregiver/proposals',headers=h['caregiver']).json()
    new=next(x for x in props if x['proposal_status']=='offered')
    assert c.post('/api/caregiver/proposals/'+new['proposal_id']+'/decision',headers=h['caregiver'],json={'action':'accept'}).status_code==200
    app.state.flow.reconcile()
    assert c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json()['state']=='assigned'


@pytest.mark.parametrize('failure',['policy','route','no_slot','declared_time'])
def test_auto_dispatch_never_relaxes_constraints(api,failure):
    c,app=api;h=setup(c,app)
    if failure!='no_slot':slot(c,h,'15:00' if failure=='declared_time' else '13:00','17:00')
    if failure=='policy':c.post('/api/caregiver/auto-policy',headers=h['caregiver'],json={'enabled':False,'categories':[]})
    if failure=='route':app.state.routing.settings.routing_enabled=False
    jid=send(c,h);app.state.flow.process_one()
    row=c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json()
    assert row['state']=='exception' and row['booking_id'] is None


def test_time_clarification_once_and_encrypted_audio_removed(api):
    c,app=api;h=setup(c,app);slot(c,h,'13:00','17:00')
    app.state.flow.speech=SimpleNamespace(transcribe=lambda _:'내일 세 시에 청소 도와줘')
    app.state.flow.parser=SimpleNamespace(parse=lambda text:Intent(category='housekeeping',urgency='normal',action='request',evidence='청소',time_text='세 시'))
    jid=send(c,h);app.state.flow.process_one()
    assert c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json()['state']=='clarify'
    jid2=send(c,h,'request-key-0000002',jid);app.state.flow.process_one()
    assert c.get('/api/flow/jobs/'+jid2,headers=h['elder1']).json()['state']=='exception'
    with app.state.factory() as db:assert db.get(VoiceJob,jid2).encrypted_audio is None


def test_concurrent_processing_and_booking_conflict(api):
    c,app=api;h=setup(c,app);slot(c,h,'13:00','17:00');jid=send(c,h)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:app.state.flow.process_one(),range(2)))
    with app.state.factory() as db:assert len(db.scalars(select(Booking)).all())==1
    second=send(c,h,'request-key-0000002');app.state.flow.process_one()
    assert c.get('/api/flow/jobs/'+second,headers=h['elder1']).json()['state']=='exception'


def test_technical_retry_limit_and_no_false_success(api):
    from app.speech import SpeechUnavailable
    c,app=api;h=setup(c,app)
    def fail(_):raise SpeechUnavailable()
    app.state.flow.speech=SimpleNamespace(transcribe=fail)
    jid=send(c,h)
    for _ in range(3):assert app.state.flow.process_one()
    assert not app.state.flow.process_one()
    row=c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json()
    assert row['state']=='exception' and row['reason']=='technical' and row['booking_id'] is None


def test_window_asap_and_explicit_times():
    now=datetime(2026,9,25,10,0,tzinfo=KST)
    a,b=window('청소 좀 도와주세요',now);assert a>now and b.date()==(now+timedelta(days=7)).date()
    a,b=window('내일 오후 두 시에 청소',now);assert a==b and a.day==26 and a.hour==14
    a,b=window('9월 26일 오전 청소',now);assert a.hour==9 and b.hour==11
    for text in ['내일 두 시','지난 화요일','오늘 오전 9시','내일 두 시 안 되면 세 시','모레 병원 오후 두 시','매일 오전에 청소']:
        with pytest.raises(TimeUnclear):window(text,now)


def test_restart_recovers_expired_lease_and_rechecks_consent(api):
    from app.flow_service import FlowService
    c,app=api;h=setup(c,app);slot(c,h,'13:00','17:00');jid=send(c,h)
    with app.state.factory() as db:
        j=db.get(VoiceJob,jid);j.state='processing';j.lease='old-lease';j.lease_until=datetime.now(timezone.utc)-timedelta(minutes=1);j.attempts=1;db.commit()
    old=app.state.flow
    new=FlowService(old.settings,old.factory,old.cipher,old.speech,old.routing,old.parser)
    assert new.process_one()
    assert c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json()['state']=='assigned'
    second=send(c,h,'request-key-0000002')
    c.post('/api/preferences',headers=h['elder1'],json={'local_ai':False})
    new.process_one()
    assert c.get('/api/flow/jobs/'+second,headers=h['elder1']).json()['reason']=='consent'


def test_cancel_voice_and_stats_never_treat_cancel_as_completed_care(api):
    c,app=api;h=setup(c,app);slot(c,h,'13:00','17:00');jid=send(c,h);app.state.flow.process_one()
    app.state.flow.speech=SimpleNamespace(transcribe=lambda _:'방금 요청 취소해 주세요')
    app.state.flow.parser=SimpleNamespace(parse=lambda _:Intent(category='other',urgency='normal',action='cancel',evidence='취소',time_text=''))
    jid2=send(c,h,'request-key-0000002');app.state.flow.process_one()
    assert c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json()['state']=='cancelled'
    assert c.get('/api/flow/jobs/'+jid2,headers=h['elder1']).json()['state']=='cancelled'
    stats=c.get('/api/flow/statistics',headers=h['worker1']).json()
    assert stats['automatic_completed']==0 and stats['total']==2
    assert c.get('/api/flow/statistics',headers=auth(c,'worker2')).json()['total']==0
    assert c.get('/api/flow/statistics',headers=h['elder1']).status_code==403


def test_completion_requires_no_worker_approval_and_result_retained(api):
    c,app=api;h=setup(c,app);slot(c,h,'13:00','17:00');jid=send(c,h);app.state.flow.process_one()
    job=c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json();bid=job['booking_id']
    # The existing start endpoint is separately tested for visit-day restrictions.
    with app.state.factory() as db:db.get(Booking,bid).status='in_progress';db.commit()
    assert c.post('/api/caregiver/visits/'+bid+'/report',headers=h['caregiver'],json={'outcome':'completed','note':'청소를 마쳤습니다'}).status_code==200
    app.state.flow.reconcile()
    assert c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json()['state']=='completed'
    assert c.get('/api/flow/statistics',headers=h['worker1']).json()['automatic_completed']==1
    assert c.get('/api/operations/history/'+bid,headers=h['worker1']).json()['report']=='청소를 마쳤습니다'


def test_duplicate_key_different_audio_and_nonowner_read_rejected(api):
    c,app=api;h=setup(c,app);jid=send(c,h)
    assert c.post('/api/flow/voice',headers=h['elder1'],json={'request_key':'request-key-0000001','audio_base64':base64.b64encode(b'different'*80).decode()}).status_code==409
    assert c.get('/api/flow/jobs/'+jid,headers=h['elder2']).status_code==404
    assert c.get('/api/flow/request/request-key-0000001',headers=h['elder2']).json() is None


def test_no_dispatch_after_hallucinated_category_or_unsupported_evidence(api):
    c,app=api;h=setup(c,app);slot(c,h,'13:00','17:00')
    app.state.flow.speech=SimpleNamespace(transcribe=lambda _:'안녕하세요')
    app.state.flow.parser=SimpleNamespace(parse=lambda _:Intent(category='housekeeping',urgency='normal',action='request',evidence='안녕하세요',time_text=''))
    jid=send(c,h);app.state.flow.process_one()
    assert c.get('/api/flow/jobs/'+jid,headers=h['elder1']).json()['booking_id'] is None
    with app.state.factory() as db:assert not db.scalars(select(Booking)).all()


def test_staff_cannot_attach_unrelated_elder_or_cross_team_pair(api):
    c,app=api;h=prepare(c)
    assert c.post('/api/caregiver/elders/elder1/attach',headers=h['caregiver'],json={}).status_code==403
    body={'name':'테스트','region':REGION,'location':{'longitude':127,'latitude':37,'consent':True},'local_ai':True,'consent_confirmed':True}
    elder=c.post('/api/caregiver/elders',headers=h['caregiver'],json=body).json()['elder_id']
    assert c.post('/api/staff/elders/'+elder+'/pair',headers=auth(c,'worker2'),json={}).status_code==403
