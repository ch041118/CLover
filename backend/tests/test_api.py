import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import create_app, passwords
from app.config import Settings
from app.models import User, Care, Attendance, Audit

@pytest.fixture
def api(tmp_path):
    settings = Settings(_env_file=None, jwt_secret='x'*48, data_key=Fernet.generate_key().decode(), database_url=f'sqlite:///{tmp_path}/test.db')
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.factory() as db:
            for name, role in [('admin','admin'),('elder1','elder'),('elder2','elder'),('worker1','social_worker'),('worker2','social_worker'),('caregiver','caregiver')]:
                db.add(User(id=name, password_hash=passwords.hash('test-password-12345'), role=role, status='approved'))
            db.commit()
        yield client, app

def auth(client, name):
    r = client.post('/api/login', json={'id':name,'password':'test-password-12345'})
    assert r.status_code == 200
    return {'Authorization': 'Bearer ' + r.json()['access_token']}

def make_request(client, name='elder1', note='홍길동 010-1234-5678 식사 도움이 필요해요'):
    r = client.post('/api/care-requests', headers=auth(client,name), json={'note':note,'features':{'category':'meal'}})
    assert r.status_code == 201, r.text
    return r.json()['id']

def test_signup_cannot_escalate_pending_cannot_login(api):
    c, app = api
    assert c.post('/api/signup', json={'id':'intruder','password':'long-password-123','role':'admin'}).status_code == 422
    assert c.post('/api/signup', json={'id':'newuser','password':'long-password-123','role':'elder'}).status_code == 201
    assert c.post('/api/login', json={'id':'newuser','password':'long-password-123'}).status_code == 403
    assert c.post('/api/admin/approve/newuser', headers=auth(c,'elder1')).status_code == 403
    assert c.post('/api/admin/approve/newuser', headers=auth(c,'admin')).status_code == 200
    assert c.post('/api/login', json={'id':'newuser','password':'long-password-123'}).status_code == 200

def test_ownership_assignment_and_encrypted_storage(api):
    c, app = api
    request_id = make_request(c)
    endpoint = '/api/care-requests/' + request_id
    assert c.get(endpoint).status_code == 401
    for person in ['elder2','worker1','admin','caregiver']:
        assert c.get(endpoint, headers=auth(c,person)).status_code == 404
    queue = c.get('/api/worker/unassigned', headers=auth(c,'worker1')).json()
    assert set(queue[0]) == {'id','urgency','created_at'}
    assert c.post('/api/worker/claim/'+request_id, headers=auth(c,'worker1')).status_code == 200
    assert c.post('/api/worker/claim/'+request_id, headers=auth(c,'worker2')).status_code == 409
    assert c.get(endpoint, headers=auth(c,'worker1')).json()['content']['note'].startswith('홍길동')
    assert c.get(endpoint, headers=auth(c,'worker2')).status_code == 404
    with app.state.factory() as db:
        row = db.get(Care, request_id)
        assert '홍길동' not in row.encrypted_content and '010-' not in row.encrypted_content
        assert row.review_required and row.urgency == 'uncertain'
        assert db.scalars(select(Audit).where(Audit.action == 'read_content')).first()
    result = c.post('/api/worker/review/'+request_id, headers=auth(c,'worker1'), json={'urgency':'need'})
    assert result.status_code == 200 and not result.json()['review_required']

def test_revoked_account_invalidates_existing_token(api):
    c, app = api
    header = auth(c,'elder1')
    with app.state.factory() as db:
        db.get(User,'elder1').status='suspended'
        db.commit()
    assert c.get('/api/me', headers=header).status_code == 401

def test_bad_input_does_not_echo_secret(api):
    c, _ = api
    secret = 'secret-person-010-1234-5678'
    response = c.post('/api/care-requests', headers=auth(c,'elder1'), json={'note':secret, 'features':{'category':secret}})
    assert response.status_code == 422 and secret not in response.text
    assert response.headers['Cache-Control'] == 'no-store'

def test_attendance_idempotent_and_patterns(api):
    c, app = api
    header = auth(c,'elder1')
    for _ in range(2): assert c.post('/api/attendance',headers=header).status_code == 200
    with app.state.factory() as db:
        assert len(db.scalars(select(Attendance)).all()) == 1
    for _ in range(3): make_request(c)
    assert c.get('/api/patterns',headers=header).json()[0]['count'] == 3
    assert c.get('/api/patterns',headers=auth(c,'elder2')).json() == []

def test_emergency_preserved_without_aws(api):
    c, _ = api
    request_id = make_request(c,note='숨을 못 쉬겠어요')
    row = c.get('/api/care-requests/'+request_id, headers=auth(c,'elder1')).json()
    assert row['urgency'] == 'danger' and '119' in row['emergency_notice']

def test_legacy_consent_never_enables_local_or_cloud(api):
    c, app = api
    result=c.post('/api/care-requests',headers=auth(c,'elder1'),json={'note':'식사 도움','features':{'category':'meal'},'allow_structured_ai':True})
    assert result.status_code==201
    assert result.json()['source']=='no_local_consent'
    assert result.json()['privacy']['external_ai_allowed'] is False
    request_id=result.json()['id']
    detail=c.get('/api/care-requests/'+request_id,headers=auth(c,'elder1')).json()
    assert detail['content']['privacy']['policy_version']=='care-local-v3'

def test_credentials_rejected_without_db_storage(api):
    c, app=api
    response=c.post('/api/care-requests',headers=auth(c,'elder1'),json={'note':'bedrock-api-key-FAKE-TEST-ONLY','features':{'category':'other'},'allow_local_ai':True})
    assert response.status_code==422
    assert 'FAKE-TEST' not in response.text
    with app.state.factory() as db:
        assert not db.scalars(select(Care)).all()

def test_general_drafts_authorization_and_no_free_text(api):
    c, app=api
    valid={'topic':'welcome_notice','allow_local_ai':True}
    assert c.post('/api/general-drafts',json=valid).status_code==401
    assert c.post('/api/general-drafts',headers=auth(c,'elder1'),json=valid).status_code==403
    assert c.post('/api/general-drafts',headers=auth(c,'worker1'),json={**valid,'note':'private'}).status_code==422
    result=c.post('/api/general-drafts',headers=auth(c,'worker1'),json=valid)
    assert result.status_code==200
    assert result.json()['source']=='template' and result.json()['reason']=='local_disabled'

def test_mobile_pending_approvals_require_admin_and_hide_passwords(api):
    c, _ = api
    body = {'id': 'mobile_new', 'password': 'synthetic-password-123', 'role': 'elder'}
    assert c.post('/api/signup', json=body).status_code == 201
    assert c.get('/api/admin/pending-users').status_code == 401
    for name in ['elder1', 'worker1', 'caregiver']:
        assert c.get('/api/admin/pending-users', headers=auth(c, name)).status_code == 403
    rows = c.get('/api/admin/pending-users', headers=auth(c, 'admin')).json()
    assert rows == [{'id': 'mobile_new', 'role': 'elder', 'status': 'pending'}]
    assert c.post('/api/admin/approve/mobile_new', headers=auth(c, 'admin'), json={}).status_code == 200
    assert c.get('/api/admin/pending-users', headers=auth(c, 'admin')).json() == []
