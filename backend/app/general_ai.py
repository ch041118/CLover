"""General drafts use the same small local model. No cloud SDK or credentials."""
from pydantic import Field
from .schemas import GeneralTopic, StrictModel
from .local_model import LocalModel, LocalUnavailable

PROMPTS = {
    GeneralTopic.welcome_notice: '복지관 이용자 환영 문구를 한국어로 짧게 작성하세요.',
    GeneralTopic.volunteer_etiquette: '봉사자의 경청 예절을 한국어로 짧게 작성하세요.',
    GeneralTopic.service_introduction: '돌봄 요청 접수 서비스 소개를 한국어로 짧게 작성하세요.',
}
class DraftResult(StrictModel):
    draft: str = Field(min_length=1, max_length=1000)

class GeneralUnavailable(Exception):
    pass

class GeneralAI:
    def __init__(self, settings, local_model=None):
        self.settings=settings
        self.local_model=local_model or LocalModel(settings)

    def generate(self, topic: GeneralTopic, consent: bool):
        topic=GeneralTopic(topic)
        if not consent or self.settings.llm_mode!='local':
            raise GeneralUnavailable()
        try:
            result=self.local_model.complete(
                'JSON의 draft에 안내문 2문장만 쓰세요. 실제 이름·주소·사례·의료 조언을 만들지 마세요.',
                PROMPTS[topic],DraftResult,max_tokens=192)
            if not result.draft.strip():
                raise GeneralUnavailable()
            return {'draft':result.draft,'source':'local_model','human_review_required':True,
                    'privacy':{'sensitivity':'public_template','sent':'local_only','external_ai_allowed':False}}
        except LocalUnavailable:
            raise GeneralUnavailable() from None
