"""Explicit initialization: no built-in administrator or fixed password."""
import argparse
import getpass
import re
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from pwdlib import PasswordHash
from app.config import Settings
from app.models import Base, User

parser = argparse.ArgumentParser()
parser.add_argument('command', choices=['init-db', 'create-admin'])
args = parser.parse_args()
settings = Settings()
engine = create_engine(settings.database_url)
if args.command == 'init-db':
    Base.metadata.create_all(engine)
    print('Database initialized. Existing schema migrations are not performed.')
else:
    user_id = input('Admin ID (3-40 ASCII letters/numbers/_/-): ').strip()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{3,40}', user_id):
        raise SystemExit('Invalid ID')
    password = getpass.getpass('New admin password (12+ characters): ')
    if not 12 <= len(password) <= 128 or password != getpass.getpass('Confirm password: '):
        raise SystemExit('Invalid password or confirmation')
    with Session(engine) as session:
        if session.get(User, user_id):
            raise SystemExit('ID already exists; no account was changed')
        session.add(User(id=user_id, password_hash=PasswordHash.recommended().hash(password), role='admin', status='approved'))
        session.commit()
    print('Administrator created')
