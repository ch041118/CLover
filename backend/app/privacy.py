"""Conservative application policy; tags are heuristics, NEVER an external-release gate."""
import re
import unicodedata
from dataclasses import dataclass
from .schemas import Features

POLICY_VERSION = 'care-local-v3'
SECRET = re.compile(r'bedrock-api-key-|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_ -]?key|password|비밀번호|인증키|토큰)\s*[:=]\s*\S+', re.I)
IDENTIFIERS = (
    re.compile(r'\b\d{6}\s*[- ]?\s*[1-8]\d{6}\b'),
    re.compile(r'(?<!\d)(?:\+82[- .]?)?0?1[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)'),
    re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I),
)
CUES = {
    'identity_contact': ('이름', '성명', '주소', '연락처', '주민등록', '전화번호', '생년월일'),
    'health_care': ('질환', '당뇨', '혈압', '치매', '장애', '복약', '약을', '진료', '병원', '통증', '우울', '자살'),
    'financial_welfare': ('수급', '소득', '재산', '채무', '빚', '계좌', '생활비', '기초생활'),
    'family_counselling': ('학대', '가정폭력', '성폭력', '상담', '가족', '보호자', '고독', '외로'),
}

@dataclass(frozen=True)
class PrivacyDecision:
    sensitivity: str
    tags: tuple[str, ...]
    blocked: bool = False

    def metadata(self):
        return {'policy_version': POLICY_VERSION, 'sensitivity': self.sensitivity,
                'tags': list(self.tags), 'allowed_destination': 'none' if self.blocked else 'local_only',
                'external_ai_allowed': False}

def normalize(text):
    value = unicodedata.normalize('NFKC', text)
    return ''.join(c for c in value if unicodedata.category(c) != 'Cf')

def inspect_care(note: str, features: Features) -> PrivacyDecision:
    text = normalize(note)
    tags = {'care_record'}  # Context alone is enough to keep all care data inside.
    for label, cues in CUES.items():
        if any(cue in text for cue in cues):
            tags.add(label)
    if any(pattern.search(text) for pattern in IDENTIFIERS):
        tags.add('identity_contact')
    if features.signals or features.category == 'medication':
        tags.add('health_care')
    if SECRET.search(text):
        tags.add('credential')
        return PrivacyDecision('restricted', tuple(sorted(tags)), True)
    return PrivacyDecision('confidential', tuple(sorted(tags)))

def minimize_local_note(note):
    # Secondary minimization only. Names/addresses/obfuscated PII may remain locally.
    text = normalize(note)
    for pattern in IDENTIFIERS:
        text = pattern.sub('[식별정보 삭제]', text)
    return text
