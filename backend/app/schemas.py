from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Category(StrEnum):
    meal='meal'
    mobility='mobility'
    housekeeping='housekeeping'
    companionship='companionship'
    medication='medication'
    other='other'

class Signal(StrEnum):
    breathing_difficulty='breathing_difficulty'
    unconscious='unconscious'
    severe_bleeding='severe_bleeding'
    fall='fall'
    missed_meal='missed_meal'
    missed_medication='missed_medication'
    loneliness='loneliness'
    meal_preparation='meal_preparation'
    walk_companion='walk_companion'
    light_housework='light_housework'
    shopping_help='shopping_help'
    conversation='conversation'
    medication_reminder='medication_reminder'

class Features(StrictModel):
    category: Category
    signals: list[Signal] = Field(default_factory=list, max_length=13)
    duration: str = Field(default='unknown', pattern='^(today|several_days|unknown)$')
    can_self_manage: bool = False

class Signup(StrictModel):
    id: str = Field(min_length=3, max_length=40, pattern=r'^[a-zA-Z0-9_-]+$')
    password: str = Field(min_length=12, max_length=128)
    role: str = Field(pattern='^(elder|caregiver|social_worker)$')

class Login(StrictModel):
    id: str = Field(max_length=40)
    password: str = Field(max_length=128)

class CareCreate(StrictModel):
    note: str = Field(min_length=1, max_length=4000)
    features: Features
    # Legacy field accepted but NEVER grants local or external care processing consent.
    allow_structured_ai: bool = False
    allow_local_ai: bool | None = None

    @field_validator('note')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('Empty note')
        return value

class ModelResult(StrictModel):
    urgency: str = Field(pattern='^(danger|need|self_care|uncertain)$')
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)

class Review(StrictModel):
    urgency: str = Field(pattern='^(danger|need|self_care)$')


class GeneralTopic(StrEnum):
    welcome_notice = 'welcome_notice'
    volunteer_etiquette = 'volunteer_etiquette'
    service_introduction = 'service_introduction'

class GeneralDraft(StrictModel):
    topic: GeneralTopic
    allow_local_ai: bool = False
