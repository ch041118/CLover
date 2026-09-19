import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import jwt
from cryptography.fernet import Fernet
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pwdlib import PasswordHash
from sqlalchemy import create_engine, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker, Session
from .config import Settings
from .models import Base, User, Care, Audit, Attendance, Preference
from .schemas import Signup, Login, CareCreate, Review, GeneralDraft
from .classifier import Classifier
from .general_ai import GeneralAI, GeneralUnavailable, template_result
from .matching import register_matching
from .coordination import register_coordination, update_repeat
from .speech import Speech, SpeechInput, SpeechUnavailable, SpeechInvalid, suggested_category

passwords = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)

def create_app(settings=None, classifier=None, general_ai=None, speech=None):
    settings = settings or Settings()
    engine = create_engine(settings.database_url, **({'connect_args': {'check_same_thread': False}} if settings.database_url.startswith('sqlite:') else {}))
    factory = sessionmaker(engine, expire_on_commit=False)
    cipher = Fernet(settings.data_key.encode())
    classifier = classifier or Classifier(settings)
    general_ai = general_ai or GeneralAI(settings)
    speech = speech or Speech(settings)
    dummy_hash = passwords.hash(uuid.uuid4().hex)

    @asynccontextmanager
    async def lifespan(app):
        # Development only; production schema creation is an explicit deployment command.
        if settings.app_env == 'development':
            Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title='CLover 생활 돌봄', lifespan=lifespan,
                  docs_url='/docs' if settings.app_env == 'development' else None,
                  redoc_url=None, openapi_url='/openapi.json' if settings.app_env == 'development' else None)
    app.state.factory = factory
    app.state.engine = engine
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_credentials=False, allow_methods=['GET','POST'], allow_headers=['Authorization','Content-Type'])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content={'detail': '입력 항목을 확인해 주세요.'})

    @app.exception_handler(Exception)
    async def generic_error(request, exc):
        return JSONResponse(status_code=500, content={'detail': '처리에 실패했습니다. 담당자에게 문의하세요.'})

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        # Deployment proxy must also enforce size and rate limits, including chunked requests.
        limit = 2_900_000 if request.url.path == '/api/speech/transcribe' else 32768
        if request.headers.get('content-length', '').isdigit() and int(request.headers['content-length']) > limit:
            return JSONResponse(status_code=413, content={'detail': '요청이 너무 큽니다.'})
        if request.method in ('POST', 'PUT', 'PATCH'):
            chunks = bytearray()
            async for chunk in request.stream():
                chunks.extend(chunk)
                if len(chunks) > limit:
                    return JSONResponse(status_code=413, content={'detail': '요청이 너무 큽니다.'}, headers={'Cache-Control':'no-store'})
            request._body = bytes(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    def db():
        with factory() as session:
            yield session

    def current(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), session: Session = Depends(db)):
        try:
            if credentials is None:
                raise ValueError()
            claims = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=['HS256'],
                                audience='care-api', issuer='care-api', options={'require':['sub','exp','iat','iss','aud']})
            user = session.get(User, claims['sub'])
            if user is None or user.status != 'approved':
                raise ValueError()
            return user
        except (jwt.PyJWTError, ValueError, TypeError):
            raise HTTPException(401, '로그인이 필요합니다.')

    def role(*allowed):
        def check(user: User = Depends(current)):
            if user.role not in allowed:
                raise HTTPException(403, '접근 권한이 없습니다.')
            return user
        return check

    def audit(session, user, action, target):
        session.add(Audit(actor=user.id, action=action, target=target))

    def public_user(user):
        return {'id': user.id, 'role': user.role, 'status': user.status}

    def care_view(row):
        return {'id': row.id, 'owner_id': row.owner_id, 'worker_id': row.worker_id,
                'category': row.category, 'urgency': row.urgency, 'source': row.source,
                'review_required': row.review_required, 'created_at': row.created_at,
                'emergency_notice': '즉시 위험한 상황이면 119에 연락하세요. 이 서비스는 자동 신고하지 않습니다.' if row.urgency == 'danger' else None}

    def permitted(row, user):
        return row.owner_id == user.id or row.worker_id == user.id

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.post('/api/signup', status_code=201)
    def signup(body: Signup, session: Session = Depends(db)):
        user = User(id=body.id, password_hash=passwords.hash(body.password), role=body.role, status='pending')
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, '사용할 수 없는 아이디입니다.')
        return public_user(user)

    @app.post('/api/login')
    def login(body: Login, session: Session = Depends(db)):
        user = session.get(User, body.id)
        valid = passwords.verify(body.password, user.password_hash if user else dummy_hash)
        if not user or not valid:
            raise HTTPException(401, '로그인 정보를 확인해 주세요.')
        if user.status != 'approved':
            raise HTTPException(403, '승인된 계정만 로그인할 수 있습니다.')
        now = datetime.now(timezone.utc)
        token = jwt.encode({'sub': user.id, 'iat': now, 'exp': now + timedelta(minutes=30),
                            'iss': 'care-api', 'aud': 'care-api'}, settings.jwt_secret, algorithm='HS256')
        return {'access_token': token, 'token_type': 'bearer'}

    @app.get('/api/me')
    def me(user: User = Depends(current)):
        return public_user(user)

    @app.get('/api/admin/pending-users')
    def pending(user=Depends(role('admin')), session: Session = Depends(db)):
        return [public_user(x) for x in session.scalars(select(User).where(User.status == 'pending').limit(100))]

    @app.post('/api/admin/approve/{user_id}')
    def approve(user_id: str, user=Depends(role('admin')), session: Session = Depends(db)):
        target = session.get(User, user_id)
        if not target:
            raise HTTPException(404, '사용자를 찾을 수 없습니다.')
        target.status = 'approved'
        audit(session, user, 'approve', target.id)
        session.commit()
        return public_user(target)

    @app.post('/api/care-requests', status_code=201)
    def submit(body: CareCreate, user=Depends(role('elder')), session: Session = Depends(db)):
        pref = session.get(Preference, user.id)
        consent = body.allow_local_ai if body.allow_local_ai is not None else bool(pref and pref.local_ai)
        result = classifier.classify(body.note, body.features, consent)
        privacy = result.pop("privacy")
        if privacy["sensitivity"] == "restricted":
            raise HTTPException(422, "인증키·비밀번호를 제거하고 다시 접수하세요. 긴급 상황이면 119에 연락하세요.")
        stored = {**body.model_dump(mode="json"), "allow_local_ai": consent, "privacy": privacy}
        row = Care(id=str(uuid.uuid4()), owner_id=user.id, category=body.features.category.value,
                   encrypted_content=cipher.encrypt(json.dumps(stored, ensure_ascii=False).encode()).decode(), **result)
        session.add(row)
        session.flush()
        update_repeat(session, user.id, row.category, new_care=row)
        audit(session, user, 'create_request', row.id)
        session.commit()
        return {**care_view(row), 'privacy': privacy}

    @app.get('/api/care-requests')
    def requests(user=Depends(current), session: Session = Depends(db)):
        query = select(Care)
        if user.role == 'elder':
            query = query.where(Care.owner_id == user.id)
        elif user.role == 'social_worker':
            query = query.where(Care.worker_id == user.id)
        else:
            raise HTTPException(403, '접근 권한이 없습니다.')
        return [care_view(x) for x in session.scalars(query.order_by(Care.created_at.desc()).limit(100))]

    @app.get('/api/care-requests/{care_id}')
    def detail(care_id: str, user=Depends(current), session: Session = Depends(db)):
        row = session.get(Care, care_id)
        if not row or not permitted(row, user):
            raise HTTPException(404, '요청을 찾을 수 없습니다.')
        audit(session, user, 'read_content', row.id)
        session.commit()
        return {**care_view(row), 'content': json.loads(cipher.decrypt(row.encrypted_content.encode()))}

    @app.get('/api/worker/unassigned')
    def unassigned(user=Depends(role('social_worker')), session: Session = Depends(db)):
        # Minimum queue metadata only; no owner ID or note before assignment.
        return [{'id': x.id, 'urgency': x.urgency, 'created_at': x.created_at} for x in
                session.scalars(select(Care).where(Care.worker_id.is_(None)).order_by(Care.created_at).limit(100))]

    @app.post('/api/worker/claim/{care_id}')
    def claim(care_id: str, user=Depends(role('social_worker')), session: Session = Depends(db)):
        from sqlalchemy import update
        result = session.execute(update(Care).where(Care.id == care_id, Care.worker_id.is_(None)).values(worker_id=user.id))
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(409, '다른 담당자가 배정되었거나 없는 요청입니다.')
        audit(session, user, 'claim', care_id)
        session.commit()
        return {'status': 'assigned'}

    @app.get('/api/worker/uncertain')
    def uncertain(user=Depends(role('social_worker')), session: Session = Depends(db)):
        return [care_view(x) for x in session.scalars(select(Care).where(Care.worker_id == user.id, Care.review_required.is_(True)).limit(100))]

    @app.post('/api/worker/review/{care_id}')
    def review(care_id: str, body: Review, user=Depends(role('social_worker')), session: Session = Depends(db)):
        row = session.get(Care, care_id)
        if not row or row.worker_id != user.id:
            raise HTTPException(404, '요청을 찾을 수 없습니다.')
        row.urgency, row.review_required, row.source = body.urgency, False, 'human_review'
        audit(session, user, 'review_' + body.urgency, row.id)
        session.commit()
        return care_view(row)

    @app.post('/api/attendance')
    def attendance(user=Depends(role('elder')), session: Session = Depends(db)):
        day = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
        session.add(Attendance(owner_id=user.id, day=day))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        return {'day': day, 'checked': True}

    @app.get('/api/patterns')
    def patterns(user=Depends(role('elder')), session: Session = Depends(db)):
        rows = session.execute(select(Care.category, func.count(Care.id)).where(
            Care.owner_id == user.id, Care.created_at >= datetime.now(timezone.utc)-timedelta(days=7)
        ).group_by(Care.category).having(func.count(Care.id) >= 3))
        return [{'category': category, 'count': count, 'suggestion': '담당 사회복지사와 정기 돌봄을 상담해 보세요.'} for category, count in rows]

    @app.post('/api/general-drafts')
    def general_draft(body: GeneralDraft, user=Depends(role('admin', 'social_worker')), session: Session = Depends(db)):
        if not body.allow_local_ai:
            raise HTTPException(400, '내부 AI 사용 선택이 필요합니다.')
        try:
            result = general_ai.generate(body.topic, body.allow_local_ai)
        except GeneralUnavailable:
            result = template_result(body.topic, 'local_disabled' if settings.llm_mode != 'local' else 'local_unavailable')
        audit(session, user, 'general_draft', body.topic.value)
        session.commit()
        return result

    @app.get('/api/admin/audit')
    def audit_list(user=Depends(role('admin')), session: Session = Depends(db)):
        return [{'actor': x.actor, 'action': x.action, 'target': x.target, 'created_at': x.created_at} for x in
                session.scalars(select(Audit).order_by(Audit.id.desc()).limit(100))]
    @app.get('/api/ai-status')
    def ai_status(user=Depends(current)):
        # Configuration readiness only; no private prompts are sent as a health check.
        from pathlib import Path
        return {'text_enabled':settings.llm_mode=='local',
                'speech_enabled':settings.speech_enabled,
                'speech_model_installed':(Path(settings.speech_model_path)/'model.bin').is_file(),
                'text_model':settings.local_model}

    @app.post('/api/speech/transcribe')
    def transcribe(body:SpeechInput,user=Depends(role('elder')),session=Depends(db)):
        if not body.consent: raise HTTPException(400,'음성 처리 안내를 확인하세요.')
        try: text=speech.transcribe(body.audio_base64)
        except SpeechInvalid: raise HTTPException(422,'음성을 다시 녹음해 주세요.')
        except SpeechUnavailable: raise HTTPException(503,'기관 음성 모델 설정을 확인하세요.')
        # Do not persist audio or transcription before an explicit care submission.
        audit(session,user,'transcribe','local');session.commit()
        return {'text':text,'category':suggested_category(text)}

    register_matching(app, db, current, role, audit)
    register_coordination(app, db, current, role, audit, cipher)
    return app
