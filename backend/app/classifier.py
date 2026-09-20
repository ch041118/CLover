"""All care data is local-only. No external model clients exist."""
from .schemas import Features, Signal, PreparedModelResult
from .privacy import inspect_care, normalize
from .local_model import LocalModel, LocalUnavailable, LocalInputTooLong

EMERGENCY = {Signal.breathing_difficulty, Signal.unconscious, Signal.severe_bleeding}
DANGER_WORDS = ('숨을 못', '숨이 안', '호흡곤란', '의식이 없', '정신을 잃', '피가 멈추지', '가슴 통증', '흉통', '죽고 싶', '극단적 선택')

class Classifier:
    def __init__(self, settings, local_model=None):
        self.settings = settings
        self.local_model = local_model or LocalModel(settings)

    def classify(self, note: str, features: Features, consent: bool):
        features = Features.model_validate(features.model_dump(mode='json'))
        privacy = inspect_care(note, features).metadata()
        def result(urgency, source, confidence=0.0):
            return {'urgency': urgency, 'source': source, 'confidence': confidence,
                    'review_required': True, 'privacy': {**privacy, 'actual_processor': source}}
        emergency = bool(EMERGENCY.intersection(features.signals)) or any(word in normalize(note) for word in DANGER_WORDS)
        if privacy['sensitivity'] == 'restricted':
            # Secrets are rejected by the submit endpoint; never passed to ANY model.
            return result('danger' if emergency else 'uncertain', 'secret_blocked')
        if emergency:
            return result('danger', 'local_rule', 1.0)
        if not consent:
            return result('uncertain', 'no_local_consent')
        if self.settings.llm_mode != 'local':
            return result('uncertain', 'local_disabled')
        try:
            parsed = self.local_model.classify(note, features)
            parsed = PreparedModelResult.model_validate(parsed.model_dump())
            if parsed.confidence < 0.85:
                return result('uncertain', 'local_low_confidence', parsed.confidence)
            urgency = parsed.urgency
            if urgency == 'self_care' and ({Signal.fall, Signal.missed_medication} & set(features.signals)):
                urgency = 'need'
            answer=result(urgency, 'local_model', parsed.confidence)
            answer['preparation']={'summary':parsed.summary,'evidence':parsed.evidence}
            return answer
        except LocalInputTooLong:
            return result('uncertain', 'local_input_too_long')
        except (LocalUnavailable, ValueError, TypeError):
            return result('uncertain', 'local_unavailable')
