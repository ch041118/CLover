import re,uuid
from datetime import datetime,timedelta,timezone
from fastapi import Depends,HTTPException
from pydantic import Field
from sqlalchemy import select
from .models import Attendance,CheckinPreference,CheckinDay
from .schemas import StrictModel
from .speech import SpeechInvalid,SpeechUnavailable
from .matching import KST
from .coordination import lock_users

QUESTION='안녕하세요. 오늘 어떠세요? 제 말이 들리시면 네, 또는 잘 지내요라고 말씀해 주세요. 도움이 필요하면 도와주세요라고 말씀해 주세요.'
def clock():return datetime.now(timezone.utc)
def aware(t):return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t

def answer_kind(text):
    text=re.sub(r'[\s.,!?。！？]','',text)
    if any(x in text for x in ('도와','아파','힘들','안괜찮','괜찮지않','숨을못','숨이안')):return 'help'
    return 'answered' if text in ('네','예','네네','안녕하세요','잘지내요','잘지내고있어요','잘있어요','괜찮아요','네괜찮아요','좋아요','들려요','네들려요') else 'unconfirmed'

class Enable(StrictModel):
    enabled:bool
class Abort(StrictModel):
    token:str=Field(max_length=36)

class Response(StrictModel):
    token:str=Field(max_length=36)
    audio_base64:str=Field(min_length=4,max_length=2800000)

def register_checkin(app,db,role,audit,speech):
    def find(session,uid,today):return session.scalar(select(CheckinDay).where(CheckinDay.owner_id==uid,CheckinDay.day==today))
    def view(session,uid):
        now=clock();local=now.astimezone(KST);today=str(local.date())
        pref=session.get(CheckinPreference,uid);row=find(session,uid,today)
        checked=bool(session.scalar(select(Attendance.id).where(Attendance.owner_id==uid,Attendance.day==today)))
        attempts=row.attempts if row else 0
        state='help' if row and row.state=='help' else 'answered' if checked else row.state if row else 'waiting'
        enabled=bool(pref and pref.enabled);due=bool(enabled and not checked and attempts<3 and 9<=local.hour<20 and (not row or aware(row.next_at)<=now))
        if not checked and attempts>=3 and row and row.state=='listening' and aware(row.next_at)<=now:state='unconfirmed'
        return {'enabled':enabled,'day':today,'state':state,'attempts':attempts,'due':due,'next_at':aware(row.next_at).isoformat() if row else None,'retry_minutes':5,'max_attempts':3,'question':QUESTION}
    @app.get('/api/checkin')
    def status(user=Depends(role('elder')),session=Depends(db)):return view(session,user.id)
    @app.post('/api/checkin/settings')
    def settings(body:Enable,user=Depends(role('elder')),session=Depends(db)):
        lock_users(session,user.id);pref=session.get(CheckinPreference,user.id)
        if not pref:pref=CheckinPreference(owner_id=user.id);session.add(pref)
        pref.enabled=body.enabled
        if not body.enabled:
            row=find(session,user.id,str(clock().astimezone(KST).date()))
            if row:row.token=None;row.state='paused' if row.state=='listening' else row.state
        audit(session,user,'checkin_setting',user.id);session.commit();return view(session,user.id)
    @app.post('/api/checkin/start')
    def start(user=Depends(role('elder')),session=Depends(db)):
        lock_users(session,user.id);state=view(session,user.id)
        if not state['due']:raise HTTPException(409,'지금은 음성 확인 시간이 아닙니다.')
        row=find(session,user.id,state['day'])
        if not row:row=CheckinDay(id=str(uuid.uuid4()),owner_id=user.id,day=state['day'],attempts=0);session.add(row)
        row.attempts+=1;row.token=str(uuid.uuid4());row.state='listening';row.next_at=clock()+timedelta(minutes=5)
        audit(session,user,'checkin_start',row.id);session.commit()
        return {'token':row.token,'question':QUESTION}
    @app.post('/api/checkin/abort')
    def abort(body:Abort,user=Depends(role('elder')),session=Depends(db)):
        lock_users(session,user.id);row=find(session,user.id,str(clock().astimezone(KST).date()))
        if row and row.token==body.token and row.state=='listening':
            row.state='technical';row.token=None;session.commit()
        return view(session,user.id)
    @app.post('/api/checkin/respond')
    def respond(body:Response,user=Depends(role('elder')),session=Depends(db)):
        today=str(clock().astimezone(KST).date());row=find(session,user.id,today);pref=session.get(CheckinPreference,user.id)
        if not pref or not pref.enabled or not row or row.token!=body.token:raise HTTPException(409,'음성 확인이 중단되거나 만료됐습니다.')
        if row.state!='listening':return view(session,user.id)
        if aware(row.next_at)<=clock():raise HTTPException(409,'응답 시간이 만료됐습니다.')
        # Audio is never persisted, and no transcript is kept in attendance records.
        try:kind=answer_kind(speech.transcribe(body.audio_base64))
        except SpeechInvalid:kind='unconfirmed'
        except SpeechUnavailable:kind='technical'
        lock_users(session,user.id);session.refresh(row);session.refresh(pref)
        if not pref.enabled or row.token!=body.token or aware(row.next_at)<=clock():raise HTTPException(409,'음성 확인 상태가 바뀌었습니다.')
        if row.state!='listening':return view(session,user.id)
        row.state=kind;row.next_at=clock()+timedelta(minutes=5)
        if kind in ('answered','help') and not session.scalar(select(Attendance.id).where(Attendance.owner_id==user.id,Attendance.day==today)):
            session.add(Attendance(owner_id=user.id,day=today))
        audit(session,user,'checkin_'+kind,row.id);session.commit();return view(session,user.id)
