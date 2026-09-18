import json
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from cryptography.fernet import Fernet
from app.classifier import Classifier
from app.schemas import Features, ModelResult
from app.config import Settings
from app.privacy import inspect_care

class FakeLocal:
    def __init__(self, fail=False):
        self.calls=[]
        self.fail=fail
    def classify(self, note, features):
        from app.local_model import LocalUnavailable
        self.calls.append((note, features))
        if self.fail: raise LocalUnavailable()
        return ModelResult(urgency='need', confidence=0.92)

@pytest.mark.parametrize('mode', ['disabled','local'])
@pytest.mark.parametrize('note', ['식사 도움', '홍길동 010-1234-5678', '당뇨약 복용을 잊었어요', '돌려서 표현한 알려지지 않은 민감한 사정'])
def test_every_care_record_is_local_only(mode, note, monkeypatch):
    local=FakeLocal()
    result=Classifier(SimpleNamespace(llm_mode=mode), local).classify(note, Features(category='meal'), True)
    assert result['privacy']['external_ai_allowed'] is False
    assert result['privacy']['allowed_destination'] == 'local_only'
    assert result['review_required']
    assert len(local.calls) == (1 if mode == 'local' else 0)

@pytest.mark.parametrize('note,tag', [
    ('010-1234-5678','identity_contact'), ('diary@example.com','identity_contact'),
    ('당뇨약 복용','health_care'), ('기초생활수급자','financial_welfare'), ('가정폭력 상담','family_counselling'),
])
def test_sensitivity_tags_are_only_categories(note, tag):
    metadata=inspect_care(note,Features(category='other')).metadata()
    assert tag in metadata['tags']
    assert note not in json.dumps(metadata, ensure_ascii=False)

@pytest.mark.parametrize('note', ['bedrock-api-key-FAKE-NOT-A-REAL-KEY','비밀번호=not-a-real-password','password: test-only', 'bedrock-api-\u200bkey-FAKE'])
def test_secrets_never_go_to_any_model(note):
    local=FakeLocal()
    result=Classifier(SimpleNamespace(llm_mode='local'),local).classify(note,Features(category='other'),True)
    assert result['source']=='secret_blocked' and not local.calls

def test_local_failure_never_falls_back_to_bedrock(monkeypatch):
    result=Classifier(SimpleNamespace(llm_mode='local'),FakeLocal(fail=True)).classify('식사 도움',Features(category='meal'),True)
    assert result['urgency']=='uncertain' and result['source']=='local_unavailable'

def test_local_consent_and_emergency():
    local=FakeLocal()
    c=Classifier(SimpleNamespace(llm_mode='local'),local)
    assert c.classify('도움',Features(category='meal'),False)['source']=='no_local_consent'
    assert c.classify('숨을 못 쉬겠어요',Features(category='other'),False)['urgency']=='danger'
    assert not local.calls

@pytest.mark.parametrize('features', [
    {'category':'임의 문장'}, {'category':'meal','signals':['주소 서울']},
    {'category':'meal','name':'홍길동'}, {'category':'meal','duration':'phone'},
])
def test_feature_schema_rejects_free_text(features):
    with pytest.raises(ValidationError): Features(**features)

def base_settings(**kwargs):
    return Settings(_env_file=None, jwt_secret='a'*48, data_key=Fernet.generate_key().decode(), **kwargs)

@pytest.mark.parametrize('mode', ['bedrock','hybrid','external'])
def test_external_modes_rejected(mode):
    with pytest.raises(ValidationError): base_settings(llm_mode=mode)

def test_explicit_local_review_required():
    with pytest.raises(ValidationError): base_settings(llm_mode='local')

def test_default_small_model():
    assert base_settings().local_model == 'qwen2.5:0.5b'
