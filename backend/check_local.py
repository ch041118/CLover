"""Synthetic-data smoke test. Requires a real local Ollama daemon and model."""
from app.config import Settings
from app.local_model import LocalModel, LocalUnavailable
from app.schemas import Features, GeneralTopic
from app.general_ai import GeneralAI, GeneralUnavailable

settings=Settings()
if settings.llm_mode!='local':
    raise SystemExit('Set LLM_MODE=local and complete the local configuration first.')
try:
    model=LocalModel(settings)
    result=model.classify('식사 준비에 도움이 필요합니다.',Features(category='meal'))
    GeneralAI(settings,model).generate(GeneralTopic.welcome_notice,True)
    print('PASS: local classification and general draft returned valid JSON.')
    print('This checks connectivity and format only, not clinical accuracy or network isolation.')
except (LocalUnavailable,GeneralUnavailable):
    raise SystemExit('FAIL: local inference unavailable or invalid response. Check the daemon, downloaded model and available memory. No external fallback was attempted.')
