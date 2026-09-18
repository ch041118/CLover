import re
from typing import Literal
from cryptography.fernet import Fernet
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_env: Literal['development', 'production'] = 'development'
    database_url: str = 'sqlite:///./care.db'
    jwt_secret: str
    data_key: str
    llm_mode: Literal['disabled', 'local'] = 'disabled'
    local_model: Literal['qwen2.5:0.5b'] = 'qwen2.5:0.5b'
    local_model_url: str = 'http://127.0.0.1:11434'
    local_privacy_reviewed: bool = False
    cors_origins: list[str] = ['http://localhost:3000']

    @model_validator(mode='after')
    def secure(self):
        if len(self.jwt_secret) < 40 or 'change-me' in self.jwt_secret:
            raise ValueError('JWT_SECRET must be a newly generated secret, at least 40 characters')
        Fernet(self.data_key.encode())
        if self.llm_mode == 'local':
            if not self.local_privacy_reviewed:
                raise ValueError('Review offline Ollama, cloud disabled, egress firewall and local model before enabling')
            if self.local_model_url != 'http://127.0.0.1:11434':
                raise ValueError('Only same-host loopback Ollama is allowed')
            if not re.fullmatch(r'[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+', self.local_model) or 'cloud' in self.local_model.lower():
                raise ValueError('Use an explicitly tagged, locally installed non-cloud model')
        if self.app_env == 'production':
            if not self.database_url.startswith('postgresql+psycopg://'):
                raise ValueError('Production requires PostgreSQL')
            if not self.cors_origins or any(not x.startswith('https://') or '*' in x for x in self.cors_origins):
                raise ValueError('Production requires explicit HTTPS frontend origins')
        return self
