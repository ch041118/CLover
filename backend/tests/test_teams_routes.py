import json
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from test_api import api,auth,make_request
from test_matching import prepare,slot,REGION,DAY
from app.models import CaregiverTeam,Booking,Availability,VisitRecord,RouteLocation

def care(c,h):
    cid=make_request(c);c.post('/api/worker/claim/'+cid,headers=h['worker1'])
    c.post('/api/worker/review/'+cid,headers=h['worker1'],json={'urgency':'need'});return cid

def test_team_link_and_assignment_enforced(api):
    c,app=api;h=prepare(c);sid=slot(c,h);cid=care(c,h)
    payload={'caregiver_id':'caregiver','worker_id':'worker2'}
    assert c.post('/api/admin/teams',headers=h['worker1'],json=payload).status_code==403
    assert c.post('/api/admin/teams',headers=h['admin'],json=payload).status_code==200
    assert c.get('/api/teams',headers=h['worker1']).json()['caregivers']==[]
    assert c.get('/api/teams',headers=h['caregiver']).json()['caregivers'][0]['worker_id']=='worker2'
    assert c.post('/api/worker/assign',headers=h['worker1'],json={'care_id':cid,'slot_id':sid,'contact_confirmed':True}).status_code==403
    c.post('/api/admin/teams',headers=h['admin'],json={**payload,'worker_id':'worker1'})
    r=c.post('/api/worker/assign',headers=h['worker1'],json={'care_id':cid,'slot_id':sid,'contact_confirmed':True})
    assert r.status_code==201
    assert c.post('/api/admin/teams',headers=h['admin'],json=payload).status_code==409
    assert c.post('/api/admin/teams',headers=h['admin'],json={**payload,'worker_id':'elder1'}).status_code==422

def test_operation_records_scoped_and_decrypted(api):
    c,app=api;h=prepare(c);sid=slot(c,h);cid=care(c,h)
    b=c.post('/api/worker/assign',headers=h['worker1'],json={'care_id':cid,'slot_id':sid,'contact_confirmed':True}).json()
    with app.state.factory() as db:
        db.get(Booking,b['id']).status='completed';db.get(Availability,sid).state='closed'
        db.add(VisitRecord(booking_id=b['id'],caregiver_id='caregiver',outcome='completed',encrypted_note=app.state.routing.cipher.encrypt('식사 준비 완료'.encode()).decode()));db.commit()
    path='/api/operations/history'
    for who in ['admin','worker1']:
        result=c.get(path,headers=h[who],params={'day_from':DAY,'day_to':DAY,'status':'completed'}).json()
        assert result['total']==1 and len(result['rows'])==1
        assert c.get(path+'/'+b['id'],headers=h[who]).json()['report']=='식사 준비 완료'
    assert c.get(path,headers=auth(c,'worker2')).json()['total']==0
    assert c.get(path+'/'+b['id'],headers=auth(c,'worker2')).status_code==404
    assert c.get(path,headers=h['caregiver']).status_code==403
    assert c.get(path,headers=h['admin'],params={'day_from':'2026-99-01'}).status_code==422


def setup_routes(c,app,h,duration=600000):
    route=app.state.routing;route.settings.routing_enabled=True
    route.settings.naver_maps_key_id=SecretStr('test-id');route.settings.naver_maps_key=SecretStr('test-key')
    calls=[]
    def transport(req):
        calls.append(req)
        assert req.url.host=='naveropenapi.apigw.ntruss.com'
        assert req.headers['x-ncp-apigw-api-key']=='test-key'
        assert '홍길동' not in str(req.url) and '도움' not in str(req.url)
        if 'geocode' in req.url.path:return httpx.Response(200,json={'addresses':[{'roadAddress':'서울 테스트로','x':'127.1','y':'37.5'}]})
        return httpx.Response(200,json={'code':0,'route':{'traoptimal':[{'summary':{'duration':duration}}]}})
    route.transport=httpx.MockTransport(transport)
    for i,uid in enumerate(['elder1','elder2','caregiver']):
        assert c.post('/api/location',headers=h[uid],json={'longitude':127+i*.01,'latitude':37.5,'consent':True,'departure':'08:00'}).status_code==200
    return calls

def test_route_guard_and_private_location(api):
    c,app=api;h=prepare(c);calls=setup_routes(c,app,h);cid=care(c,h);sid=slot(c,h)
    body={'care_id':cid,'slot_id':sid,'contact_confirmed':True}
    result=c.post('/api/worker/route-check',headers=h['worker1'],json=body).json()
    assert result['mode']=='naver_driving' and result['inbound_minutes']==25
    assert c.post('/api/worker/assign',headers=h['worker1'],json=body).status_code==201
    assert c.get('/api/location',headers=h['worker1']).status_code==403
    assert c.post('/api/location',headers=h['elder1'],json={'longitude':128,'latitude':37.5,'consent':True}).status_code==409
    with app.state.factory() as db:assert '127' not in db.get(RouteLocation,'elder1').encrypted_point
    assert calls

def test_travel_time_insufficient_and_no_fallback(api):
    c,app=api;h=prepare(c);setup_routes(c,app,h,duration=3600000);sid=slot(c,h);cid=care(c,h)
    body={'care_id':cid,'slot_id':sid,'contact_confirmed':True}
    assert c.post('/api/worker/assign',headers=h['worker1'],json=body).status_code==409
    assert c.post('/api/bookings',headers=h['elder1'],json={'slot_id':sid,'category':'meal'}).status_code==409
    assert not c.post('/api/worker/scheduler/run',headers=h['worker1'],json={}).json()['offered']
    app.state.routing.transport=httpx.MockTransport(lambda r:httpx.Response(503))
    assert c.post('/api/worker/route-check',headers=h['worker1'],json=body).status_code==409
    with app.state.factory() as db:assert db.get(Availability,sid).state=='open'

def test_next_visit_gap_and_geocode_consent(api):
    c,app=api;h=prepare(c);setup_routes(c,app,h);later=slot(c,h,'11:00','12:00')
    assert c.post('/api/bookings',headers=h['elder2'],json={'slot_id':later,'category':'meal'}).status_code==201
    sid=slot(c,h,'10:00','10:50');cid=care(c,h)
    assert c.post('/api/worker/route-check',headers=h['worker1'],json={'care_id':cid,'slot_id':sid}).status_code==409
    assert c.post('/api/location/search',headers=h['elder1'],json={'query':'서울 테스트로','consent':False}).status_code==422
    r=c.post('/api/location/search',headers=h['elder1'],json={'query':'서울 테스트로','consent':True})
    assert r.json()[0]['longitude']==127.1
    # Consent can always be withdrawn, even with a pending booking.
    assert c.post('/api/location',headers=h['elder2'],json={'longitude':127.01,'latitude':37.5,'consent':False,'departure':'08:00'}).status_code==200
    assert c.post('/api/worker/route-check',headers=h['worker1'],json={'care_id':cid,'slot_id':sid}).status_code==409
