from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from test_api import api,auth,make_request
from test_matching import prepare,slot,REGION,DAY
from app.models import Care,Booking,RepeatCase,VisitRecord,Availability,User
from app.matching import KST

def booking(c,h):
    sid=slot(c,h)
    return c.post('/api/bookings',headers=h['elder1'],json={'slot_id':sid,'category':'meal'}).json()['id']

def confirm(c,h,bid):
    assert c.post(f'/api/worker/schedules/{bid}/claim',headers=h['worker1'],json={}).status_code==200
    assert c.post(f'/api/worker/schedules/{bid}/confirm',headers=h['worker1'],json={'contact_confirmed':True}).status_code==200
    p=c.get('/api/caregiver/proposals',headers=h['caregiver']).json()[0]
    assert c.post('/api/caregiver/proposals/'+p['proposal_id']+'/decision',headers=h['caregiver'],json={'action':'accept'}).json()['status']=='accepted'

def test_worker_coordinates_and_caregiver_performs(api):
    c,app=api;h=prepare(c);bid=booking(c,h)
    assert c.post(f'/api/bookings/{bid}/decision',headers=h['caregiver'],json={'action':'accept'}).status_code==403
    assert c.post(f'/api/caregiver/visits/{bid}/start',headers=h['caregiver'],json={}).status_code==409
    assert c.get('/api/worker/schedules',headers=h['caregiver']).status_code==403
    assert c.post(f'/api/worker/schedules/{bid}/confirm',headers=h['worker1'],json={'contact_confirmed':False}).status_code==422
    confirm(c,h,bid)
    assert c.post(f'/api/worker/schedules/{bid}/cancel',headers=auth(c,'worker2'),json={}).status_code==403
    assert c.post(f'/api/caregiver/visits/{bid}/start',headers=h['worker1'],json={}).status_code==403
    assert c.post(f'/api/caregiver/visits/{bid}/start',headers=h['caregiver'],json={}).status_code==409
    with app.state.factory() as db:
        b=db.get(Booking,bid);db.get(Availability,b.slot_id).day=str(datetime.now(KST).date());db.commit()
    assert c.post(f'/api/caregiver/visits/{bid}/start',headers=h['caregiver'],json={}).json()['status']=='in_progress'
    assert c.post(f'/api/bookings/{bid}/decision',headers=h['elder1'],json={'action':'cancel'}).status_code==409
    note='식사 준비와 주방 정리를 도왔습니다.'
    result=c.post(f'/api/caregiver/visits/{bid}/report',headers=h['caregiver'],json={'outcome':'completed','note':note})
    assert result.json()['status']=='completed'
    assert c.post(f'/api/caregiver/visits/{bid}/report',headers=h['caregiver'],json={'outcome':'completed','note':note}).status_code==409
    assert c.get(f'/api/visits/{bid}/report',headers=h['worker1']).json()['note']==note
    for who in ['worker2','elder2','admin']:
        assert c.get(f'/api/visits/{bid}/report',headers=auth(c,who)).status_code==404
    with app.state.factory() as db:assert note not in db.get(VisitRecord,bid).encrypted_note

def test_coordinator_ownership_and_reschedule(api):
    c,_=api;h=prepare(c);bid=booking(c,h);confirm(c,h,bid);sid2=slot(c,h,'11:00','12:00')
    assert c.post(f'/api/worker/schedules/{bid}/reschedule',headers=h['caregiver'],json={'slot_id':sid2,'contact_confirmed':True}).status_code==403
    assert c.post(f'/api/worker/schedules/{bid}/reschedule',headers=auth(c,'worker2'),json={'slot_id':sid2,'contact_confirmed':True}).status_code==403
    assert c.post(f'/api/worker/schedules/{bid}/reschedule',headers=h['worker1'],json={'slot_id':sid2,'contact_confirmed':True}).json()['start']=='11:00'
    assert c.get('/api/bookings',headers=h['caregiver']).json()[0]['start']=='11:00'

def test_request_assignment_requires_review_and_does_not_duplicate(api):
    c,_=api;h=prepare(c);sid=slot(c,h);cid=make_request(c)
    c.post('/api/worker/claim/'+cid,headers=h['worker1'])
    payload={'care_id':cid,'slot_id':sid,'contact_confirmed':True}
    assert c.post('/api/worker/assign',headers=h['worker1'],json=payload).status_code==409
    c.post('/api/worker/review/'+cid,headers=h['worker1'],json={'urgency':'need'})
    assert c.post('/api/worker/assign',headers=h['worker1'],json=payload).status_code==201
    assert c.post('/api/worker/assign',headers=h['worker1'],json=payload).status_code==409
    assert c.get('/api/care-requests/'+cid,headers=h['caregiver']).status_code==404

def test_repeat_intervention_and_opt_in_auto_routing(api):
    c,app=api;h=prepare(c)
    for _ in range(3):make_request(c)
    rows=c.get('/api/worker/repeats',headers=h['worker1']).json()
    assert len(rows)==1 and rows[0]['count_7d']==3 and rows[0]['state']=='open';rid=rows[0]['id']
    assert c.get('/api/worker/repeats',headers=h['caregiver']).status_code==403
    assert c.post(f'/api/worker/repeats/{rid}/claim',headers=h['worker1'],json={}).status_code==200
    assert c.post(f'/api/worker/repeats/{rid}/claim',headers=auth(c,'worker2'),json={}).status_code==409
    body={'decision':'plan','note':'이용자와 정기 식사 도움을 상담할 예정','followup_day':DAY,'auto_route':True}
    assert c.post(f'/api/worker/repeats/{rid}/decision',headers=h['worker1'],json=body).json()['state']=='planning'
    cid=make_request(c,note='숨을 못 쉬겠어요')
    with app.state.factory() as db:
        care=db.get(Care,cid);assert care.worker_id=='worker1' and care.review_required and care.urgency=='danger'
        assert not db.scalars(select(Booking)).all()
        case=db.get(RepeatCase,rid);assert body['note'] not in case.encrypted_decision
    for _ in range(2):make_request(c)
    row=c.get('/api/worker/repeats',headers=h['worker1']).json()[0]
    assert row['state']=='open' and row['new_count']==3 and row['danger_count']==1
    c.post(f'/api/worker/repeats/{rid}/decision',headers=h['worker1'],json={**body,'decision':'close'})
    cid=make_request(c)
    with app.state.factory() as db:assert db.get(Care,cid).worker_id is None

def test_repeat_scan_is_idempotent_and_due_date_is_shown(api):
    c,app=api;h=prepare(c)
    for _ in range(3):make_request(c)
    for _ in range(2):assert c.post('/api/worker/repeats/scan',headers=h['worker1'],json={}).status_code==200
    row=c.get('/api/worker/repeats',headers=h['worker1']).json()[0];rid=row['id']
    c.post(f'/api/worker/repeats/{rid}/claim',headers=h['worker1'],json={})
    body={'decision':'monitor','note':'오늘 통화하기','followup_day':str(datetime.now(KST).date()),'auto_route':False}
    assert c.post(f'/api/worker/repeats/{rid}/decision',headers=h['worker1'],json=body).status_code==200
    c.post('/api/worker/repeats/scan',headers=h['worker1'],json={})
    rows=c.get('/api/worker/repeats',headers=h['worker1']).json()
    assert len(rows)==1 and rows[0]['due'] and rows[0]['state']=='monitoring' and rows[0]['new_count']==0

def test_statistics_count_full_dataset_and_current_classification(api):
    c,app=api;h=prepare(c);cid=make_request(c)
    c.post('/api/worker/claim/'+cid,headers=h['worker1']);c.post('/api/worker/review/'+cid,headers=h['worker1'],json={'urgency':'need'})
    with app.state.factory() as db:
        for i in range(105):db.add(Care(id=f'stats-{i}',owner_id='elder2',encrypted_content='test-only',category='mobility',urgency='uncertain',source='test',confidence=0,review_required=True))
        db.add(Care(id='old',owner_id='elder2',encrypted_content='test-only',category='meal',urgency='need',source='test',confidence=0,created_at=datetime.now(timezone.utc)-timedelta(days=100)))
        db.commit()
    assert c.get('/api/worker/statistics',headers=h['caregiver']).status_code==403
    result=c.get('/api/worker/statistics?days=7',headers=h['worker1']).json()
    assert result['total']==106 and result['reviewed']==1 and result['review_pending']==105
    assert sum(r['count'] for r in result['matrix'])==106
    assert {'category':'meal','urgency':'need','count':1} in result['matrix']
    assert c.get('/api/worker/statistics?days=1000',headers=h['worker1']).status_code==422

def test_only_one_worker_claims_schedule(api):
    c,_=api;h=prepare(c);h['worker2']=auth(c,'worker2');bid=booking(c,h)
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(lambda name:c.post(f'/api/worker/schedules/{bid}/claim',headers=h[name],json={}).status_code,['worker1','worker2']))
    assert sorted(statuses)==[200,403]
