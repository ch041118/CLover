"""Short recordings decoded on this server only. Never download models during a request."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from .local_model import INFERENCE_SLOT
from .privacy import SECRET, normalize
from .schemas import StrictModel
from pydantic import Field

class SpeechInput(StrictModel):
    audio_base64: str = Field(min_length=4,max_length=2800000)
    consent: bool = False

class SpeechUnavailable(Exception): pass
class SpeechInvalid(Exception): pass

class Speech:
    def __init__(self,settings): self.settings=settings

    def transcribe(self,encoded):
        if not self.settings.speech_enabled: raise SpeechUnavailable()
        model=Path(self.settings.speech_model_path).resolve()
        if not (model/'model.bin').is_file(): raise SpeechUnavailable()
        try: audio=base64.b64decode(encoded,validate=True)
        except ValueError: raise SpeechInvalid() from None
        if not 100 <= len(audio) <= 2_000_000: raise SpeechInvalid()
        if not INFERENCE_SLOT.acquire(blocking=False): raise SpeechUnavailable()
        try:
            env={k:v for k,v in os.environ.items() if not k.startswith('AWS_') and k.upper() not in
                 {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','JWT_SECRET','DATA_KEY','HF_TOKEN'}}
            env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
            result=subprocess.run([sys.executable,'-m','app.speech_worker',str(model)],input=audio,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=50,env=env,
                cwd=str(Path(__file__).resolve().parents[1]))
            if result.returncode: raise SpeechUnavailable()
            data=json.loads(result.stdout)
            text=data.get('text','').strip()
            if not text or len(text)>4000 or SECRET.search(normalize(text)): raise SpeechInvalid()
            return text
        except (subprocess.TimeoutExpired,OSError,ValueError,TypeError):
            raise SpeechUnavailable() from None
        finally: INFERENCE_SLOT.release()

CATEGORY_WORDS = [('medication',('약','복약')),('meal',('식사','밥','반찬','요리')),('mobility',('산책','병원','외출','동행')),
                  ('housekeeping',('청소','정리','장보기','빨래')),('companionship',('말벗','이야기','외로'))]
def suggested_category(text):
    return next((cat for cat,words in CATEGORY_WORDS if any(w in text for w in words)),'other')
