from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from test_api import api,auth,make_request
from test_matching import prepare,slot
from app.models import ScheduleProposal,Booking,Availability

def reviewed(c,h,urgency='need'):
    cid=make_request(c)
    c.post('/api/worker/claim/'+cid,headers=h['worker1'])
    assert c.post('/api/worker/review/'+cid,headers=h['worker1'],json={'urgency':urgency}).status_code==200
    return cid

def decide(c,h,p,action='accept',reason=''):
    return c.post('/api/caregiver/proposals/'+p['proposal_id']+'/decision',headers=h['caregiver'],json={'action':action,'reason':reason})

def test_three_stages_and_provider_consent(api):
    c,app=api;h=prepare(c);sid=slot(c,h);cid=reviewed(c,h)
    emergency=reviewed(c,h,'danger');unreviewed=make_request(c)
    r=c.post('/api/worker/scheduler/run',headers=h['worker1'],json={}).json()
    assert len(r['offered'])==1 and len(r['skipped'])==1
    assert not c.post('/api/worker/scheduler/run',headers=h['worker1'],json={}).json()['offered']
    p=c.get('/api/caregiver/proposals',headers=h['caregiver']).json()[0]
    assert p['stage']=='initial' and p['status']=='offered'
    assert c.post('/api/caregiver/visits/'+p['id']+'/start',headers=h['caregiver'],json={}).status_code==409
    assert c.post('/api/caregiver/proposals/'+p['proposal_id']+'/decision',headers=h['worker1'],json={'action':'accept'}).status_code==403
    assert decide(c,h,p).json()['status']=='accepted'
    assert decide(c,h,p).status_code==409
    # Urgent work cannot evict an accepted booking.
    body={'care_id':emergency,'slot_id':sid,'contact_confirmed':True}
    assert c.post('/api/worker/assign',headers=h['worker1'],json=body).status_code==409
    body['slot_id']=slot(c,h,'11:00','12:00')
    urgent=c.post('/api/worker/assign',headers=h['worker1'],json=body).json()
    assert urgent['stage']=='urgent' and urgent['status']=='offered'
    assert decide(c,h,urgent,'decline','다른 방문 때문에 어렵습니다').json()['status']=='declined'
    cid2=reviewed(c,h);body.update(care_id=cid2,slot_id=slot(c,h,'13:00','14:00'))
    manual=c.post('/api/worker/assign',headers=h['worker1'],json=body).json()
    assert manual['stage']=='remaining' and manual['status']=='offered'
    assert decide(c,h,manual).status_code==200

def test_decline_reoffer_stale_decision_and_encryption(api):
    c,app=api;h=prepare(c);sid=slot(c,h);cid=reviewed(c,h)
    p=c.post('/api/worker/assign',headers=h['worker1'],json={'care_id':cid,'slot_id':sid,'contact_confirmed':True}).json()
    assert decide(c,h,p,'decline').status_code==422
    assert decide(c,h,p,'decline','개인 일정이 있습니다').status_code==200
    with app.state.factory() as db:
        assert '개인 일정' not in db.get(ScheduleProposal,p['proposal_id']).encrypted_reason
        assert db.get(Availability,sid).state=='closed'
    assert not c.post('/api/worker/scheduler/run',headers=h['worker1'],json={}).json()['offered']
    sid2=slot(c,h,'11:00','12:00')
    p2=c.post('/api/worker/schedules/'+p['id']+'/reschedule',headers=h['worker1'],json={'slot_id':sid2,'contact_confirmed':True}).json()
    assert p2['proposal_id']!=p['proposal_id'] and p2['status']=='offered'
    assert decide(c,h,p).status_code==409
    assert decide(c,h,p2).status_code==200
    assert decide(c,h,p2,'decline','시간 변경이 필요합니다').status_code==200
    assert len(c.get('/api/caregiver/proposals',headers=h['caregiver']).json())==2

def test_cancelled_proposal_cannot_be_accepted(api):
    c,_=api;h=prepare(c);sid=slot(c,h);cid=reviewed(c,h)
    p=c.post('/api/worker/assign',headers=h['worker1'],json={'care_id':cid,'slot_id':sid,'contact_confirmed':True}).json()
    assert c.post('/api/bookings/'+p['id']+'/decision',headers=h['elder1'],json={'action':'cancel'}).status_code==200
    assert decide(c,h,p).status_code==409

def test_scheduler_concurrent_idempotency_and_role(api):
    c,app=api;h=prepare(c);slot(c,h);reviewed(c,h)
    assert c.post('/api/worker/scheduler/run',headers=h['caregiver'],json={}).status_code==403
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:c.post('/api/worker/scheduler/run',headers=h['worker1'],json={}),range(2)))
    assert all(r.status_code==200 for r in results)
    assert sum(len(r.json()['offered']) for r in results)==1
    with app.state.factory() as db: assert len(db.scalars(select(Booking)).all())==1

def test_offered_booking_blocks_elder_overlap(api):
    c,app=api;h=prepare(c);sid=slot(c,h);cid=reviewed(c,h)
    from app.models import User
    from app.main import passwords
    from test_matching import REGION,DAY
    with app.state.factory() as db:
        db.add(User(id='caregiver2',role='caregiver',status='approved',password_hash=passwords.hash('test-password-12345')));db.commit()
    h2=auth(c,'caregiver2');c.post('/api/regions',headers=h2,json={'regions':[REGION]})
    sid2=c.post('/api/availability',headers=h2,json={'region':REGION,'day':DAY,'start':'09:30','end':'10:30'}).json()['id']
    p=c.post('/api/worker/assign',headers=h['worker1'],json={'care_id':cid,'slot_id':sid,'contact_confirmed':True}).json()
    assert c.post('/api/bookings',headers=h['elder1'],json={'slot_id':sid2,'category':'meal'}).status_code==409
    assert c.post('/api/caregiver/proposals/'+p['proposal_id']+'/decision',headers=h2,json={'action':'accept'}).status_code==404
    assert c.post('/api/worker/schedules/'+p['id']+'/cancel',headers=h['worker1'],json={}).status_code==200
    assert decide(c,h,p).status_code==409
