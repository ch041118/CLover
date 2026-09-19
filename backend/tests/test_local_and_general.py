import json
from types import SimpleNamespace
import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from app.schemas import Features, GeneralDraft, GeneralTopic
from app.local_model import LocalModel, LocalUnavailable, LocalInputTooLong, INFERENCE_SLOT
from app.general_ai import GeneralAI, GeneralUnavailable, PROMPTS
from app.config import Settings

def local_settings(**kwargs):
    return SimpleNamespace(llm_mode='local',local_privacy_reviewed=True,local_model='qwen2.5:0.5b',local_model_url='http://127.0.0.1:11434',**kwargs)

def envelope(content='{"urgency":"need","confidence":0.95}', done=True, reason='stop'):
    return {'done':done,'done_reason':reason,'message':{'role':'assistant','content':content}}

def test_local_request_contract_minimization_no_proxies(monkeypatch):
    monkeypatch.setenv('HTTP_PROXY','http://must-not-be-used.invalid:8080')
    calls=[]
    def handle(request):
        calls.append(request)
        assert str(request.url)=='http://127.0.0.1:11434/api/chat'
        body=json.loads(request.content)
        assert '010-1234-5678' not in body['messages'][1]['content']
        assert '당뇨' in body['messages'][1]['content']
        assert not body['stream'] and body['keep_alive']==0
        assert 'tools' not in body
        assert 'authorization' not in request.headers
        return httpx.Response(200,json=envelope())
    result=LocalModel(local_settings(),httpx.MockTransport(handle)).classify('당뇨 상담 010-1234-5678',Features(category='medication'))
    assert result.urgency=='need' and len(calls)==1

@pytest.mark.parametrize('response',[
    httpx.Response(302,headers={'Location':'https://external.invalid'}),
    httpx.Response(500,text='do not log this body'),
    httpx.Response(200,json=envelope('not JSON')),
    httpx.Response(200,json=envelope('{"urgency":"need","confidence":NaN}')),
    httpx.Response(200,json=envelope('{"urgency":"need","confidence":0.9,"name":"PII"}')),
    httpx.Response(200,json=envelope(done=False)),
    httpx.Response(200,json=envelope(reason='length')),
    httpx.Response(200,content=b'x'*65537),
])
def test_invalid_local_responses_and_redirects_fail_closed(response):
    calls=[]
    def handle(request):
        calls.append(request)
        return response
    with pytest.raises(LocalUnavailable):
        LocalModel(local_settings(),httpx.MockTransport(handle)).classify('도움',Features(category='meal'))
    assert len(calls)==1

def test_local_timeout_fail_closed():
    def handle(request): raise httpx.ReadTimeout('timeout')
    with pytest.raises(LocalUnavailable):
        LocalModel(local_settings(),httpx.MockTransport(handle)).classify('도움',Features(category='meal'))

@pytest.mark.parametrize('url',['https://external.example','http://localhost:11434','http://10.0.0.1:11434','http://127.0.0.1:11434@external.example','http://127.0.0.1:11434/path'])
def test_local_destination_config_restricted(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None,jwt_secret='x'*48,data_key=Fernet.generate_key().decode(),llm_mode='local',local_model='qwen2.5:0.5b',local_privacy_reviewed=True,local_model_url=url)

@pytest.mark.parametrize('model',['test-cloud:1','test:cloud','cloud-provider/test:1','test','http://external'])
def test_cloud_or_untagged_model_rejected(model):
    with pytest.raises(ValidationError):
        Settings(_env_file=None,jwt_secret='x'*48,data_key=Fernet.generate_key().decode(),llm_mode='local',local_model=model,local_privacy_reviewed=True)

@pytest.mark.parametrize('topic',list(GeneralTopic))
def test_general_uses_same_local_model(topic):
    calls=[]
    def handle(request):
        body=json.loads(request.content); calls.append(body)
        assert str(request.url)=='http://127.0.0.1:11434/api/chat'
        assert body['model']=='qwen2.5:0.5b'
        assert body['options']['num_ctx']==2048
        assert body['options']['num_predict']==384
        assert body['messages'][1]['content']==PROMPTS[topic]
        return httpx.Response(200,json=envelope('{"draft":"환영합니다. 함께해요."}'))
    settings=local_settings()
    result=GeneralAI(settings,LocalModel(settings,httpx.MockTransport(handle))).generate(topic,True)
    assert result['source']=='local_model' and result['human_review_required']
    assert len(calls)==1

@pytest.mark.parametrize('body',[
    {'topic':'welcome_notice','note':'민감한 상담 기록'},
    {'topic':'welcome_notice','patient_id':'person1'},
    {'topic':'김철수의 당뇨 상담'},
    {'topic':'welcome_notice','allow_external_ai':True},
])
def test_general_api_schema_cannot_accept_patient_data(body):
    with pytest.raises(ValidationError): GeneralDraft(**body)

@pytest.mark.parametrize('mode,consent',[('disabled',True),('local',False)])
def test_general_requires_local_mode_and_consent(mode,consent):
    with pytest.raises(GeneralUnavailable): GeneralAI(SimpleNamespace(llm_mode=mode)).generate(GeneralTopic.welcome_notice,consent)

def test_long_input_is_not_silently_truncated():
    def handle(request): pytest.fail('long note must not be sent')
    with pytest.raises(LocalInputTooLong):
        LocalModel(local_settings(),httpx.MockTransport(handle)).classify('상담 내용'*500,Features(category='meal'))

def test_busy_model_fails_without_second_request():
    INFERENCE_SLOT.acquire()
    try:
        with pytest.raises(LocalUnavailable):
            LocalModel(local_settings(),httpx.MockTransport(lambda r: pytest.fail('must not call'))).classify('도움',Features(category='meal'))
    finally: INFERENCE_SLOT.release()

def test_no_external_sdk_dependencies_or_clients():
    from pathlib import Path
    import ast
    root=Path(__file__).resolve().parents[1]
    forbidden={'boto3','botocore','anthropic','openai'}
    for path in (root/'app').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.Import):
                assert not ({a.name.split('.')[0] for a in node.names} & forbidden)
            if isinstance(node,ast.ImportFrom):
                assert (node.module or '').split('.')[0] not in forbidden
    assert all(name not in (root/'requirements.txt').read_text() for name in forbidden)
