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
                PROMPTS[topic],DraftResult,max_tokens=384)
            if not result.draft.strip():
                raise GeneralUnavailable()
            return {'draft':result.draft,'source':'local_model','human_review_required':True,
                    'privacy':{'sensitivity':'public_template','sent':'local_only','external_ai_allowed':False}}
        except LocalUnavailable:
            raise GeneralUnavailable() from None


TEMPLATES = {
    GeneralTopic.welcome_notice: 'CLover에 오신 것을 환영합니다. 식사 준비, 외출 동행, 생활 속 도움이 필요할 때 편하게 요청해 주세요.',
    GeneralTopic.volunteer_etiquette: '상대방의 이야기를 충분히 듣고 필요한 도움을 먼저 여쭤보세요. 개인적인 이야기는 다른 사람에게 전달하지 않고 약속한 시간을 지켜 주세요.',
    GeneralTopic.service_introduction: 'CLover는 생활 속 도움 요청을 접수하고, 선택한 지역과 일정에 맞는 돌봄 연결을 돕습니다. 신청한 일정은 사회복지사가 이용자와 요양보호사에게 확인한 뒤 확정합니다.',
}

def template_result(topic, reason):
    return {'draft': TEMPLATES[topic], 'source': 'template', 'reason': reason,
            'human_review_required': True, 'privacy': {'external_ai_allowed': False}}
