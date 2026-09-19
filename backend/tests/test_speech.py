import base64
import json
import subprocess
from types import SimpleNamespace
import pytest
from test_api import api,auth
from app.speech import Speech,SpeechInvalid,SpeechUnavailable,suggested_category
from app.local_model import INFERENCE_SLOT

AUDIO=base64.b64encode(b'test-audio'*20).decode()

def settings(tmp_path):
    (tmp_path/'model.bin').write_bytes(b'fake-model-for-test')
    return SimpleNamespace(speech_enabled=True,speech_model_path=str(tmp_path))

def test_speech_api_requires_role_consent_and_local_install(api):
    c,_=api;body={'audio_base64':AUDIO,'consent':True}
    assert c.post('/api/speech/transcribe',json=body).status_code==401
    assert c.post('/api/speech/transcribe',headers=auth(c,'caregiver'),json=body).status_code==403
    assert c.post('/api/speech/transcribe',headers=auth(c,'elder1'),json={**body,'consent':False}).status_code==400
    assert c.post('/api/speech/transcribe',headers=auth(c,'elder1'),json=body).status_code==503
    assert c.post('/api/speech/transcribe',headers=auth(c,'elder1'),content=b'x'*2_900_001).status_code==413

def test_worker_offline_environment_and_no_audio_files(tmp_path,monkeypatch):
    monkeypatch.setenv('HF_TOKEN','private');monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','private')
    monkeypatch.setenv('HTTPS_PROXY','https://example.invalid');seen=[]
    def run(cmd,**kwargs):
        seen.append(kwargs)
        assert kwargs['env']['HF_HUB_OFFLINE']=='1'
        assert not {'HF_TOKEN','AWS_SECRET_ACCESS_KEY','HTTPS_PROXY'} & set(kwargs['env'])
        assert kwargs['input']==base64.b64decode(AUDIO) and kwargs['timeout']==50
        return SimpleNamespace(returncode=0,stdout=json.dumps({'text':'식사 준비 도움'}).encode())
    monkeypatch.setattr(subprocess,'run',run)
    assert Speech(settings(tmp_path)).transcribe(AUDIO)=='식사 준비 도움'
    assert len(seen)==1 and list(tmp_path.iterdir())==[tmp_path/'model.bin']

@pytest.mark.parametrize('text',['','비밀번호=TEST-ONLY','x'*4001])
def test_invalid_transcripts_are_rejected(tmp_path,monkeypatch,text):
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps({'text':text}).encode()))
    with pytest.raises(SpeechInvalid):Speech(settings(tmp_path)).transcribe(AUDIO)

def test_timeout_releases_shared_inference_slot(tmp_path,monkeypatch):
    def timeout(*a,**kw):raise subprocess.TimeoutExpired('worker',50)
    monkeypatch.setattr(subprocess,'run',timeout)
    with pytest.raises(SpeechUnavailable):Speech(settings(tmp_path)).transcribe(AUDIO)
    assert INFERENCE_SLOT.acquire(blocking=False);INFERENCE_SLOT.release()

def test_missing_model_never_starts_worker(tmp_path,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:pytest.fail('must not launch'))
    with pytest.raises(SpeechUnavailable):Speech(SimpleNamespace(speech_enabled=True,speech_model_path=str(tmp_path))).transcribe(AUDIO)

def test_malformed_base64(tmp_path):
    with pytest.raises(SpeechInvalid):Speech(settings(tmp_path)).transcribe('!!!!')

def test_category_suggestions():
    assert suggested_category('산책 동행 부탁합니다')=='mobility'
    assert suggested_category('잘 모르겠어요')=='other'
