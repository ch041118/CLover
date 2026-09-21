from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from test_api import api,auth
from app.models import Attendance,CheckinDay
from app.speech import Speech,SpeechInvalid,SpeechUnavailable
from app.checkin import answer_kind

@pytest.fixture
def enabled(api,monkeypatch):
    c,app=api;t=[datetime(2026,9,21,3,tzinfo=timezone.utc)]
    monkeypatch.setattr('app.checkin.clock',lambda:t[0]);h=auth(c,'elder1')
    assert c.post('/api/checkin/settings',headers=h,json={'enabled':True}).status_code==200
    monkeypatch.setattr(Speech,'transcribe',lambda self,audio:'네')
    return c,app,h,t

def start(c,h):
    r=c.post('/api/checkin/start',headers=h,json={});assert r.status_code==200,r.text;return r.json()['token']
def respond(c,h,token):return c.post('/api/checkin/respond',headers=h,json={'token':token,'audio_base64':'YWJjZA=='})

def test_voice_response_marks_once_and_stops_questions(enabled):
    c,app,h,t=enabled;token=start(c,h)
    assert c.post('/api/checkin/start',headers=h,json={}).status_code==409
    assert respond(c,h,token).json()['state']=='answered'
    assert respond(c,h,token).json()['state']=='answered'
    assert c.get('/api/checkin',headers=h).json()['due'] is False
    with app.state.factory() as db:assert len(db.scalars(select(Attendance)).all())==1

def test_no_response_retries_then_caps_and_new_day(enabled,monkeypatch):
    c,app,h,t=enabled
    def silence(*a):raise SpeechInvalid()
    monkeypatch.setattr(Speech,'transcribe',silence)
    for i in range(3):
        token=start(c,h);r=respond(c,h,token).json();assert r['state']=='unconfirmed' and r['attempts']==i+1
        assert not c.get('/api/checkin',headers=h).json()['due'];t[0]+=timedelta(minutes=5)
    assert not c.get('/api/checkin',headers=h).json()['due']
    with app.state.factory() as db:assert not db.scalars(select(Attendance)).all()
    t[0]+=timedelta(days=1);assert c.get('/api/checkin',headers=h).json()['due']

def test_revocation_expiry_and_quiet_hours(enabled):
    c,app,h,t=enabled;token=start(c,h)
    assert respond(c,auth(c,'elder2'),token).status_code==409
    assert c.post('/api/checkin/start',headers=auth(c,'caregiver'),json={}).status_code==403
    c.post('/api/checkin/settings',headers=h,json={'enabled':False})
    assert respond(c,h,token).status_code==409
    c.post('/api/checkin/settings',headers=h,json={'enabled':True});t[0]+=timedelta(minutes=5)
    token=start(c,h);t[0]+=timedelta(minutes=5);assert respond(c,h,token).status_code==409
    t[0]=datetime(2026,9,22,12,tzinfo=timezone.utc)
    assert not c.get('/api/checkin',headers=h).json()['due']

def test_technical_problem_is_not_an_attendance(enabled,monkeypatch):
    c,app,h,t=enabled
    def failed(*a):raise SpeechUnavailable()
    monkeypatch.setattr(Speech,'transcribe',failed)
    assert respond(c,h,start(c,h)).json()['state']=='technical'
    with app.state.factory() as db:assert not db.scalars(select(Attendance)).all()

def test_help_reply_does_not_claim_wellbeing(enabled,monkeypatch):
    c,app,h,t=enabled;monkeypatch.setattr(Speech,'transcribe',lambda *a:'괜찮지 않아요. 도와주세요')
    r=respond(c,h,start(c,h)).json();assert r['state']=='help' and not r['due']
    assert answer_kind('안 괜찮아요')=='help'
    assert answer_kind('시청해 주셔서 감사합니다')=='unconfirmed'

def test_abort_and_concurrent_start(enabled):
    c,app,h,t=enabled
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(lambda _:c.post('/api/checkin/start',headers=h,json={}),range(2)))
    assert sorted(r.status_code for r in rows)==[200,409]
    token=next(r.json()['token'] for r in rows if r.status_code==200)
    assert c.post('/api/checkin/abort',headers=h,json={'token':token}).json()['state']=='technical'
    assert respond(c,h,token).status_code==409
