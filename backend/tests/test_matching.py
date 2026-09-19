from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from test_api import api,auth
from app.models import User,Preference,Booking
from app.main import passwords

REGION={'province':'서울특별시','district':'강남구'}
DAY=(datetime.now(ZoneInfo('Asia/Seoul'))+timedelta(days=2)).date().isoformat()

def prepare(c):
    h={name:auth(c,name) for name in ['elder1','elder2','caregiver','worker1','admin']}
    for name in ['elder1','elder2','caregiver']:
        assert c.post('/api/regions',headers=h[name],json={'regions':[REGION]}).status_code==200
    return h

def slot(c,h,start='09:00',end='10:00'):
    r=c.post('/api/availability',headers=h['caregiver'],json={'region':REGION,'day':DAY,'start':start,'end':end})
    assert r.status_code==201,r.text
    return r.json()['id']

def test_matching_lifecycle_and_scoped_access(api):
    c,_=api;h=prepare(c);sid=slot(c,h)
    search={'region':REGION,'day':DAY,'start':'08:00','end':'12:00'}
    assert c.post('/api/matches',json=search).status_code==401
    assert c.post('/api/matches',headers=h['caregiver'],json=search).status_code==403
    results=c.post('/api/matches',headers=h['elder1'],json=search).json()
    assert len(results)==1 and results[0]['id']==sid and 'elder_id' not in results[0]
    r=c.post('/api/bookings',headers=h['elder1'],json={'slot_id':sid,'category':'meal'})
    assert r.status_code==201;bid=r.json()['id']
    assert c.post('/api/bookings',headers=h['elder2'],json={'slot_id':sid,'category':'meal'}).status_code==409
    assert c.get('/api/bookings',headers=h['elder2']).json()==[]
    assert c.get('/api/bookings',headers=h['worker1']).status_code==403
    assert c.post(f'/api/bookings/{bid}/decision',headers=h['elder2'],json={'action':'cancel'}).status_code==404
    assert c.post(f'/api/bookings/{bid}/decision',headers=h['elder1'],json={'action':'accept'}).status_code==403
    assert c.post(f'/api/bookings/{bid}/decision',headers=h['caregiver'],json={'action':'accept'}).status_code==403
    assert c.post(f'/api/worker/schedules/{bid}/claim',headers=h['worker1'],json={}).status_code==200
    assert c.post(f'/api/worker/schedules/{bid}/confirm',headers=h['worker1'],json={'contact_confirmed':True}).json()['status']=='offered'
    assert c.post(f'/api/bookings/{bid}/decision',headers=h['caregiver'],json={'action':'decline'}).status_code==403
    assert c.post(f'/api/bookings/{bid}/decision',headers=h['elder1'],json={'action':'cancel'}).json()['status']=='cancelled'
    assert c.post('/api/bookings',headers=h['elder2'],json={'slot_id':sid,'category':'meal'}).status_code==201

def test_regions_future_overlap_and_suspension(api):
    c,app=api;h=prepare(c);sid=slot(c,h)
    body={'region':REGION,'day':DAY,'start':'09:30','end':'10:30'}
    assert c.post('/api/availability',headers=h['caregiver'],json=body).status_code==409
    assert c.post('/api/availability',headers=h['elder1'],json=body).status_code==403
    assert c.post('/api/availability',headers=h['caregiver'],json={**body,'day':'2020-01-01'}).status_code==422
    assert c.post('/api/regions',headers=h['elder1'],json={'regions':[{'province':'서울특별시','district':'강남구 101호'}]}).status_code==422
    search={'region':REGION,'day':DAY,'start':'08:00','end':'12:00'}
    with app.state.factory() as db:
        db.get(User,'caregiver').status='suspended';db.commit()
    assert c.post('/api/matches',headers=h['elder1'],json=search).json()==[]
    assert c.post('/api/bookings',headers=h['elder1'],json={'slot_id':sid,'category':'meal'}).status_code==409

def test_region_removal_closes_open_slots_without_erasing_bookings(api):
    c,_=api;h=prepare(c);sid=slot(c,h)
    bid=c.post('/api/bookings',headers=h['elder1'],json={'slot_id':sid,'category':'meal'}).json()['id']
    assert c.post('/api/regions',headers=h['caregiver'],json={'regions':[]}).status_code==200
    assert c.post(f'/api/bookings/{bid}/decision',headers=h['elder1'],json={'action':'cancel'}).status_code==200
    assert c.get('/api/availability',headers=h['caregiver']).json()[0]['state']=='closed'

def test_simultaneous_booking_has_one_winner(api):
    c,app=api;h=prepare(c);sid=slot(c,h)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda name:c.post('/api/bookings',headers=h[name],json={'slot_id':sid,'category':'meal'}).status_code,['elder1','elder2']))
    assert sorted(results)==[201,409]
    with app.state.factory() as db: assert len(db.scalars(select(Booking)).all())==1

def test_elder_cannot_book_overlapping_caregivers(api):
    c,app=api;h=prepare(c);sid=slot(c,h)
    with app.state.factory() as db:
        db.add(User(id='caregiver2',role='caregiver',status='approved',password_hash=passwords.hash('test-password-12345')));db.commit()
    h2=auth(c,'caregiver2');c.post('/api/regions',headers=h2,json={'regions':[REGION]})
    sid2=c.post('/api/availability',headers=h2,json={'region':REGION,'day':DAY,'start':'09:30','end':'10:30'}).json()['id']
    assert c.post('/api/bookings',headers=h['elder1'],json={'slot_id':sid,'category':'meal'}).status_code==201
    assert c.post('/api/bookings',headers=h['elder1'],json={'slot_id':sid2,'category':'meal'}).status_code==409

def test_consent_persists_but_never_enables_another_user(api):
    c,app=api;h=prepare(c)
    assert c.get('/api/preferences',headers=h['elder1']).json()=={'local_ai':False,'reviewed':False}
    assert c.post('/api/preferences',headers=h['elder1'],json={'local_ai':True}).json()=={'local_ai':True,'reviewed':True}
    body={'note':'식사 준비를 도와주세요','features':{'category':'meal','signals':['meal_preparation']}}
    r=c.post('/api/care-requests',headers=h['elder1'],json=body)
    assert r.status_code==201 and r.json()['source']=='local_disabled'
    assert c.post('/api/care-requests',headers=h['elder2'],json=body).json()['source']=='no_local_consent'
    assert c.post('/api/care-requests',headers=h['elder1'],json={**body,'allow_local_ai':False}).json()['source']=='no_local_consent'
    c.post('/api/preferences',headers=h['elder1'],json={'local_ai':False})
    assert c.post('/api/care-requests',headers=h['elder1'],json=body).json()['source']=='no_local_consent'
