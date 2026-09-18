from pathlib import Path
import secrets
from cryptography.fernet import Fernet
path = Path('.env')
with path.open('x', encoding='utf-8') as f:
    f.write(f'JWT_SECRET={secrets.token_urlsafe(48)}\nDATA_KEY={Fernet.generate_key().decode()}\nLLM_MODE=disabled\nLOCAL_MODEL=qwen2.5:0.5b\nLOCAL_MODEL_URL=http://127.0.0.1:11434\nLOCAL_PRIVACY_REVIEWED=false\nAPP_ENV=development\nDATABASE_URL=sqlite:///./care.db\n')
path.chmod(0o600)
print('.env created. Keep it private and back up DATA_KEY securely.')
