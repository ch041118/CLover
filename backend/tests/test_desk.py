import json
from types import SimpleNamespace
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from test_api import api,auth
from test_matching import prepare,slot
from app.models import Care,CareDecision,ServiceRegion
from app.classifier import Classifier
from app.schemas import PreparedModelResult,Features
from app.desk import prepare_packet

@pytest.fixture
def ready(api,monkeypatch):
    c,app=api;h=prepare(c)
    original=Classifier.classify
    class Local:
        def classify(self,note,features):
            return PreparedModelResult(urgency='need',confidence=.94,summary='식사 준비 도움이 필요합니다.',evidence=[note])
    fake=Classifier(SimpleNamespace(llm_mode='local'),Local())
    monkeypatch.setattr(Classifier,'classify',lambda self,note,features,consent:original(fake,note,features,consent))
    def submit(note='식사 준비를 도와주세요',consent=True):
        r=c.post('/api/care-requests',headers=h['elder1'],json={'note':note,'features':{'category':'meal','signals':['meal_preparation']},'allow_local_ai':consent})
        assert r.status_code==201,r.text
        return r.json()['id']
    return c,app,h,submit

def desk(c,h):return c.get('/api/worker/desk',headers=h['worker1']).json()
def claim(c,h):assert c.post('/api/worker/desk/claim',headers=h['worker1'],json={}).status_code==200
def batch(c,h,rows):return c.post('/api/worker/desk/approve-batch',headers=h['worker1'],json={'items':[{'care_id':r['id'],'token':r['token']} for r in rows]})

def test_intake_prepare_claim_batch_handoff(ready):
    c,app,h,submit=ready;cid=submit();submit('식사 준비와 설거지 도움이 필요해요')
    assert desk(c,h)==[];claim(c,h);rows=desk(c,h)
    assert len(rows)==2 and all(r['lane']=='ready' for r in rows)
    assert batch(c,h,rows).json()=={'approved':2}
    assert batch(c,h,rows).status_code==409
    sid=slot(c,h)
    proposal=c.post('/api/worker/assign',headers=h['worker1'],json={'care_id':cid,'slot_id':sid,'contact_confirmed':True}).json()
    path='/api/caregiver/visits/'+proposal['id']+'/handoff'
    text=c.get(path,headers=h['caregiver']).json()['handoff']
    assert '식사 준비를 도와주세요' in text
    assert c.get(path,headers=h['elder2']).status_code==403
    with app.state.factory() as db:
        d=db.get(CareDecision,cid);assert '식사 준비' not in d.encrypted_handoff
        assert not db.get(Care,cid).review_required
    m=c.get('/api/worker/desk/metrics',headers=h['worker1']).json()
    assert m['unchanged']==2 and m['batch']==2

def test_emergency_repeat_missing_region_and_consent_are_not_batch(ready):
    c,app,h,submit=ready
    submit('숨을 못 쉬겠어요');submit(consent=False);submit('식사 준비가 힘듭니다');claim(c,h)
    rows=desk(c,h)
    assert all(r['lane']=='intervention' for r in rows)
    assert rows[0]['urgency']=='danger'
    assert batch(c,h,[rows[0]]).status_code==409
    for row in rows:assert row['repeat_count']==3
    with app.state.factory() as db: assert all(r.review_required for r in db.scalars(select(Care)))

def test_stale_context_batch_is_atomic(ready):
    c,app,h,submit=ready;submit();submit('설거지를 도와주세요');claim(c,h);rows=desk(c,h)
    # A repeat request arrived while the worker was reading: reject all selected items.
    submit('밥 준비를 도와주세요')
    assert batch(c,h,rows).status_code==409
    with app.state.factory() as db:assert not db.scalars(select(CareDecision)).all()

def test_single_edit_and_role_protection(ready):
    c,app,h,submit=ready;cid=submit(consent=False);claim(c,h);r=desk(c,h)[0]
    assert r['source']=='structured' and r['lane']=='intervention'
    body={'token':r['token'],'urgency':'need','handoff':'식사 준비를 도와주세요. 방문 전 시간을 확인해 주세요.','reviewed':True}
    path='/api/worker/desk/'+cid+'/approve'
    assert c.post(path,headers=auth(c,'worker2'),json=body).status_code==404
    assert c.post(path,headers=h['caregiver'],json=body).status_code==403
    assert c.post(path,headers=h['worker1'],json={**body,'reviewed':False}).status_code==422
    assert c.post(path,headers=h['worker1'],json={**body,'handoff':'password=secret'}).status_code==422
    assert c.post(path,headers=h['worker1'],json=body).status_code==200
    assert c.get('/api/worker/desk/metrics',headers=h['worker1']).json()['ai_prepared']==0

def test_bad_evidence_never_counts_as_ai_prepared():
    result={'source':'local_model','urgency':'need'}
    p=prepare_packet('식사 준비',Features(category='meal'),result,{'summary':'잘못된 내용','evidence':['방문 확정']})
    assert p['source']=='structured' and '방문 확정' not in p['handoff']

def test_region_change_and_other_owner_block_approval(ready):
    c,app,h,submit=ready;submit();claim(c,h);rows=desk(c,h)
    with app.state.factory() as db:
        for r in db.scalars(select(ServiceRegion).where(ServiceRegion.owner_id=='elder1')):db.delete(r)
        db.commit()
    assert batch(c,h,rows).status_code==409
    assert '이용자 지역 등록 필요' in desk(c,h)[0]['blockers']
    assert c.get('/api/worker/desk',headers=h['caregiver']).status_code==403
