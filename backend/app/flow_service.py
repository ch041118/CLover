"""Durable voice processing and opt-in automatic visits. All state changes are transactional."""
import base64, hashlib, json, math, threading, uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import httpx
from fastapi import HTTPException
from sqlalchemy import select, update, or_, func
from .models import (User, Care, Preference, ServiceRegion, Availability, Booking, Coordination,
    ScheduleProposal, CareDecision, ElderProfile, AutoPolicy, VoiceJob, FlowEvent, FlowNotice, PushDevice, RouteLocation)
from .matching import KST
from .coordination import lock_users, ACTIVE
from .intent import Intent, IntentParser, window, TimeUnclear
from .local_model import LocalUnavailable
from .speech import SpeechInvalid, SpeechUnavailable
from .classifier import DANGER_WORDS
from .privacy import normalize, SECRET

WORDS={'meal':('식사','밥','반찬','요리'), 'housekeeping':('청소','정리','장보기','빨래','장 좀'), 'companionship':('말벗','이야기','외로'), 'mobility':('산책','병원','외출','동행')}
DURATIONS={'meal':45,'housekeeping':30,'companionship':30,'mobility':60}
REASONS={'unlinked':'담당 사회복지사 연결 필요','consent':'음성·AI 이용 동의 확인 필요',
 'unclear':'요청 내용 확인 필요','time':'희망 시간 확인 필요','danger':'긴급 확인 필요',
 'unsupported':'자동 배정 업무 범위 밖','no_slot':'조건에 맞는 빈 일정 없음','routing':'지도·이동 조건 확인 필요',
 'technical':'음성 또는 AI 처리 오류','declined':'요양보호사 수행 불가','attention':'수행 결과 확인 필요',
 'notification':'일정 알림 미확인','change':'기존 일정 변경 요청','cancel':'취소할 일정 확인 필요',
 'repeat':'반복되는 미해결 요청','missed':'방문 시작 확인 필요'}

def uid():return str(uuid.uuid4())
def utc():return datetime.now(timezone.utc)
def aware(t):return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t

def event(session,cipher,job,kind,note='',actor='system'):
    session.add(FlowEvent(id=uid(),job_id=job.id,actor=actor,kind=kind,encrypted_note=cipher.encrypt(note.encode()).decode()))
    job.updated_at=utc()

def notice(session,job,owner,kind):
    if owner:session.add(FlowNotice(id=uid(),owner_id=owner,job_id=job.id,kind=kind))

def exception(session,cipher,job,reason,note=''):
    job.state='exception';job.reason=reason;job.encrypted_audio=None
    event(session,cipher,job,'exception',note or REASONS.get(reason,reason))
    notice(session,job,job.worker_id,'exception');notice(session,job,job.elder_id,'exception')

class FlowService:
    def __init__(self,settings,factory,cipher,speech,routing,parser=None):
        self.settings=settings;self.factory=factory;self.cipher=cipher;self.speech=speech;self.routing=routing
        self.parser=parser or IntentParser(settings);self.stop=threading.Event();self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.loop,name='clover-voice-worker',daemon=True);self.thread.start()
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=2)
    def loop(self):
        while not self.stop.is_set():
            try:
                self.reconcile();worked=self.process_one();self.deliver()
            except Exception:
                # Avoid logging audio/transcripts/tokens; leases allow recovery after interruption.
                worked=False
            self.stop.wait(.1 if worked else 2)
    def encode(self,value):return self.cipher.encrypt(json.dumps(value,ensure_ascii=False).encode()).decode()
    def decode(self,value):return json.loads(self.cipher.decrypt(value.encode()))
    def process_one(self):
        with self.factory() as db:
            now=utc()
            eligible=or_(VoiceJob.state=='queued',(VoiceJob.state=='processing')&(VoiceJob.lease_until<now))
            job=db.scalar(select(VoiceJob).where(eligible).order_by(VoiceJob.created_at).limit(1))
            if not job:return False
            lease=uid()
            result=db.execute(update(VoiceJob).where(VoiceJob.id==job.id,eligible).values(state='processing',lease=lease,lease_until=now+timedelta(minutes=4),attempts=VoiceJob.attempts+1).execution_options(synchronize_session=False))
            if result.rowcount!=1:db.rollback();return True
            db.commit();db.refresh(job);jid=job.id;audio=job.encrypted_audio
            if job.attempts>3 or aware(job.created_at)<now-timedelta(hours=1):
                exception(db,self.cipher,job,'technical');db.commit();return True
            pref=db.get(Preference,job.elder_id)
            user=db.get(User,job.elder_id)
            if not pref or not pref.local_ai or not user or user.status!='approved':
                exception(db,self.cipher,job,'consent');db.commit();return True
        text=None;plan=None;failure=None
        try:
            text=self.speech.transcribe(self.cipher.decrypt(audio.encode()).decode()) if audio else ''
            if not text.strip() or SECRET.search(normalize(text)):raise SpeechInvalid()
            if any(x in normalize(text) for x in DANGER_WORDS):failure='danger'
            else:
                plan=Intent.model_validate(self.parser.parse(text).model_dump())
                if plan.evidence not in text or (plan.time_text and plan.time_text not in text):failure='unclear'
        except SpeechInvalid:text=None;failure='unclear'
        except (SpeechUnavailable,LocalUnavailable,ValueError,TypeError):failure='technical'
        with self.factory() as db:
            job=db.get(VoiceJob,jid)
            # All workflow schedule changes use the same stable user lock ordering as legacy routes.
            ids=db.scalars(select(User.id).where(User.role.in_(('elder','caregiver','social_worker')))).all()
            lock_users(db,*ids);db.refresh(job)
            if job.state!='processing' or job.lease!=lease:return True
            profile=db.get(ElderProfile,job.elder_id);pref=db.get(Preference,job.elder_id)
            if profile:job.worker_id=profile.worker_id
            if not pref or not pref.local_ai or db.get(User,job.elder_id).status!='approved':failure='consent'
            if failure=='technical' and job.attempts<3:
                job.state='queued';job.lease=None;event(db,self.cipher,job,'retry','음성·AI 처리 재시도');db.commit();return True
            if text:job.encrypted_text=self.encode(text)
            job.encrypted_audio=None
            if text and not SECRET.search(normalize(text)):
                category=plan.category if plan else 'other'
                care=Care(id=uid(),owner_id=job.elder_id,worker_id=job.worker_id,category=category,
                    encrypted_content=self.encode({'note':text,'features':{'category':category},'allow_local_ai':True}),
                    urgency='danger' if failure=='danger' or (plan and plan.urgency=='danger') else 'uncertain',
                    source='voice_flow',confidence=0,review_required=True)
                db.add(care);db.flush();job.care_id=care.id
            if not profile:failure='unlinked'
            if failure:
                self.fail_or_ask(db,job,failure);db.commit();return True
            job.encrypted_plan=self.encode(plan.model_dump())
            if plan.urgency!='normal':exception(db,self.cipher,job,'danger' if plan.urgency=='danger' else 'unclear')
            elif plan.action=='cancel':self.cancel_recent(db,job,text)
            elif plan.action=='change':exception(db,self.cipher,job,'change')
            elif plan.action!='request':exception(db,self.cipher,job,'unclear')
            elif plan.category not in DURATIONS:exception(db,self.cipher,job,'unsupported')
            elif not any(w in text for w in WORDS[plan.category]) or any(w in text for w in ('하지 마','하지마','필요 없','필요없','안 와','안와')):exception(db,self.cipher,job,'unclear')
            else:
                try:
                    earliest,latest=window(text,aware(job.created_at))
                    if earliest>utc().astimezone(KST)+timedelta(days=7):raise TimeUnclear()
                    self.assign(db,job,plan.category,earliest,latest)
                except TimeUnclear:self.fail_or_ask(db,job,'time')
            db.commit()
        return True
    def fail_or_ask(self,db,job,reason):
        if reason in ('unclear','time') and job.clarifications==0:
            job.state='clarify';job.reason=reason
            event(db,self.cipher,job,'clarify','도움 내용과 날짜·오전/오후 시간을 함께 다시 말씀해 주세요.')
        else:exception(db,self.cipher,job,reason)
    def cancel_recent(self,db,job,text):
        others=db.scalars(select(VoiceJob).where(VoiceJob.elder_id==job.elder_id,VoiceJob.booking_id.is_not(None),VoiceJob.id!=job.id).order_by(VoiceJob.created_at.desc())).all()
        active=[x for x in others if db.get(Booking,x.booking_id).status in ('accepted','offered','pending')]
        if len(active)!=1 or not any(x in text for x in ('방금','최근')):
            exception(db,self.cipher,job,'cancel');return
        target=active[0];b=db.get(Booking,target.booking_id);slot=db.get(Availability,b.slot_id)
        b.status='cancelled';slot.state='open'
        for p in db.scalars(select(ScheduleProposal).where(ScheduleProposal.booking_id==b.id)):p.status='withdrawn'
        target.state='cancelled';job.state='cancelled'
        event(db,self.cipher,target,'cancelled','어르신 음성 취소',job.elder_id)
        event(db,self.cipher,job,'cancelled','최근 일정 취소',job.elder_id)
        notice(db,target,slot.caregiver_id,'cancelled');notice(db,job,job.elder_id,'cancelled')
    def assign(self,db,job,category,earliest,latest):
        from .models import CaregiverTeam
        profile=db.get(ElderProfile,job.elder_id)
        if not profile or db.get(User,profile.worker_id).status!='approved':exception(db,self.cipher,job,'unlinked');return
        # Repeated unresolved requests become one worker's responsibility rather than more visits.
        recent=db.scalar(select(func.count()).select_from(VoiceJob).where(VoiceJob.elder_id==job.elder_id,VoiceJob.id!=job.id,VoiceJob.state.in_(('exception','clarify')),VoiceJob.created_at>=utc()-timedelta(days=7)))
        if recent>=2:exception(db,self.cipher,job,'repeat');return
        if not self.routing.settings.routing_enabled:exception(db,self.cipher,job,'routing','자동 확정에는 지도 이동 검증 설정이 필요합니다.');return
        regions={(r.province,r.district) for r in db.scalars(select(ServiceRegion).where(ServiceRegion.owner_id==job.elder_id))}
        duration=DURATIONS[category];candidates=[];now=utc().astimezone(KST)
        for slot,policy in db.execute(select(Availability,AutoPolicy).join(AutoPolicy,AutoPolicy.caregiver_id==Availability.caregiver_id).join(CaregiverTeam,CaregiverTeam.caregiver_id==Availability.caregiver_id).join(User,User.id==Availability.caregiver_id).where(Availability.state=='open',Availability.day>=str(earliest.date()),Availability.day<=str(latest.date()),AutoPolicy.enabled.is_(True),CaregiverTeam.worker_id==profile.worker_id,User.status=='approved').order_by(Availability.day,Availability.start).limit(300)):
            if (slot.province,slot.district) not in regions or category not in json.loads(policy.categories):continue
            cg_regions={(r.province,r.district) for r in db.scalars(select(ServiceRegion).where(ServiceRegion.owner_id==slot.caregiver_id))}
            if (slot.province,slot.district) not in cg_regions:continue
            start=datetime.fromisoformat(f'{slot.day}T{slot.start}').replace(tzinfo=KST)
            end=datetime.fromisoformat(f'{slot.day}T{slot.end}').replace(tzinfo=KST)
            start=max(start,earliest,now+timedelta(minutes=5))
            # Minute grid; never round exact requested time into another time.
            if start.second or start.microsecond:start=start.replace(second=0,microsecond=0)+timedelta(minutes=1)
            if start>latest or start+timedelta(minutes=duration)>end:continue
            point=db.get(RouteLocation,slot.caregiver_id);dest=db.get(RouteLocation,job.elder_id)
            distance=999999.0
            if point and dest:
                a=json.loads(self.cipher.decrypt(point.encrypted_point.encode()));b=json.loads(self.cipher.decrypt(dest.encrypted_point.encode()))
                distance=(a[0]-b[0])**2+(a[1]-b[1])**2
            load=db.scalar(select(func.count()).select_from(Booking).join(Availability).where(Availability.caregiver_id==slot.caregiver_id,Availability.day==slot.day,Booking.status.in_(ACTIVE)))
            candidates.append((start,distance,load,slot.id,end))
        candidates.sort(key=lambda x:x[:4]);ctx=self.routing.context();valid=[];failures=[]
        for start,distance,load,sid,end in candidates[:6]:
            slot=db.get(Availability,sid)
            # Scan 15-minute increments inside the same block for earliest route-feasible start.
            probe=start
            while probe<=latest and probe+timedelta(minutes=duration)<=end and ctx['calls']<12:
                finish=probe+timedelta(minutes=duration)
                if earliest==latest and probe!=earliest:break
                overlap=db.scalar(select(Booking.id).join(Availability).where(Booking.elder_id==job.elder_id,Booking.status.in_(ACTIVE),Availability.day==slot.day,Availability.start<finish.strftime('%H:%M'),Availability.end>probe.strftime('%H:%M')))
                trial=SimpleNamespace(id=slot.id,caregiver_id=slot.caregiver_id,day=slot.day,start=probe.strftime('%H:%M'),end=finish.strftime('%H:%M'))
                try:
                    if overlap:raise HTTPException(409,'이용자 일정 겹침')
                    route=self.routing.check(db,trial,job.elder_id,ctx=ctx)
                    if route['mode']!='naver_driving':raise HTTPException(409,'이동 시간 미검증')
                    valid.append((probe,route['inbound_minutes']+route['outbound_minutes'],load,sid,finish));break
                except HTTPException as error:
                    failures.append(str(error.detail))
                    if error.status_code==429:break
                probe+=timedelta(minutes=15)
        if not valid:
            exception(db,self.cipher,job,'routing' if failures else 'no_slot','; '.join(failures[:3]) if failures else '희망 시간·근무 범위 안에서 가능한 후보 없음');return
        start,travel,load,sid,finish=min(valid);slot=db.get(Availability,sid)
        old_start,old_end=slot.start,slot.end
        slot.start=start.strftime('%H:%M');slot.end=finish.strftime('%H:%M');slot.state='reserved'
        for begin,end in [(old_start,slot.start),(slot.end,old_end)]:
            if begin<end:db.add(Availability(id=uid(),caregiver_id=slot.caregiver_id,province=slot.province,district=slot.district,day=slot.day,start=begin,end=end,state='open'))
        b=Booking(id=uid(),slot_id=slot.id,elder_id=job.elder_id,category=category,status='accepted');db.add(b);db.flush()
        db.add(Coordination(booking_id=b.id,worker_id=profile.worker_id,care_id=job.care_id))
        db.add(ScheduleProposal(id=uid(),booking_id=b.id,slot_id=slot.id,caregiver_id=slot.caregiver_id,stage='automatic',status='accepted'))
        care=db.get(Care,job.care_id);care.review_required=False;care.urgency='need';care.source='auto_policy_v2'
        # Handoff is explicitly system prepared; never falsely attributed to human review.
        job.booking_id=b.id;job.state='assigned';job.reason=''
        event(db,self.cipher,job,'assigned',f'{slot.day} {slot.start}–{slot.end} / {slot.caregiver_id} / 이동검증 {travel}분')
        notice(db,job,job.elder_id,'assigned');notice(db,job,slot.caregiver_id,'assigned')
    def reconcile(self):
        with self.factory() as db:
            ids=db.scalars(select(User.id).where(User.role.in_(('elder','caregiver','social_worker')))).all()
            lock_users(db,*ids)
            for job in db.scalars(select(VoiceJob).where(VoiceJob.booking_id.is_not(None),VoiceJob.state.in_(('assigned','in_progress','exception','rescheduling')))):
                b=db.get(Booking,job.booking_id);slot=db.get(Availability,b.slot_id)
                if b.status in ('declined','attention') and job.reason!=b.status:
                    proposal=db.scalar(select(ScheduleProposal).where(ScheduleProposal.booking_id==b.id).order_by(ScheduleProposal.created_at.desc()))
                    reason=self.cipher.decrypt(proposal.encrypted_reason.encode()).decode() if proposal and proposal.encrypted_reason else ''
                    exception(db,self.cipher,job,b.status,reason)
                elif b.status=='completed' and job.state!='completed':job.state='completed';job.reason='';event(db,self.cipher,job,'completed');notice(db,job,job.elder_id,'completed')
                elif b.status=='cancelled':job.state='cancelled';event(db,self.cipher,job,'cancelled');notice(db,job,job.elder_id,'cancelled')
                elif b.status=='in_progress' and job.state!='in_progress':job.state='in_progress';event(db,self.cipher,job,'in_progress')
                elif b.status=='offered' and job.state!='rescheduling':job.state='rescheduling';job.reason='';event(db,self.cipher,job,'rescheduling');notice(db,job,slot.caregiver_id,'rescheduling')
                elif b.status=='accepted' and job.state=='rescheduling':job.state='assigned';event(db,self.cipher,job,'assigned');notice(db,job,job.elder_id,'assigned')
                elif b.status=='accepted' and job.state=='assigned':
                    visit=datetime.fromisoformat(f'{slot.day}T{slot.start}').replace(tzinfo=KST)
                    unread=db.scalar(select(FlowNotice.id).where(FlowNotice.job_id==job.id,FlowNotice.owner_id==slot.caregiver_id,FlowNotice.read.is_(False)))
                    if utc().astimezone(KST)>visit+timedelta(minutes=15):exception(db,self.cipher,job,'missed')
                    elif unread and utc().astimezone(KST)>visit-timedelta(minutes=30):exception(db,self.cipher,job,'notification')
            # A clarification cannot remain unseen forever.
            for job in db.scalars(select(VoiceJob).where(VoiceJob.state=='clarify',VoiceJob.updated_at<utc()-timedelta(minutes=10))):exception(db,self.cipher,job,job.reason)
            db.commit()
    def deliver(self):
        if not self.settings.flow_push_enabled:return
        with self.factory() as db:
            rows=db.scalars(select(FlowNotice).where(FlowNotice.push_state=='pending',FlowNotice.attempts<3).limit(10)).all()
            for n in rows:
                device=db.get(PushDevice,n.owner_id)
                if not device:continue
                n.attempts+=1;db.commit()
                try:
                    with httpx.Client(timeout=5,follow_redirects=False) as client:
                        r=client.post('https://exp.host/--/api/v2/push/send',json={'to':self.cipher.decrypt(device.encrypted_token.encode()).decode(),'title':'CLover','body':'새 일정 또는 확인할 요청이 있습니다. 앱에서 확인해 주세요.','data':{'notice_id':n.id}})
                    if r.status_code!=200 or r.json().get('data',{}).get('status')!='ok':raise ValueError()
                    n.push_state='submitted'
                except (httpx.HTTPError,ValueError,TypeError):
                    if n.attempts>=3:n.push_state='failed'
                db.commit()
