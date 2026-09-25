import base64,hashlib,json,secrets,uuid
from datetime import timedelta
import jwt
from fastapi import Depends,HTTPException
from pydantic import Field,field_validator
from sqlalchemy import select,update,func
from .schemas import StrictModel
from .models import (User,Preference,ServiceRegion,RouteLocation,ElderProfile,DeviceLink,AutoPolicy,
 VoiceJob,FlowEvent,FlowNotice,PushDevice,Booking,Availability,Coordination,Care,ScheduleProposal,VisitRecord)
from .matching import Region,slot_future
from .routing import Point
from .coordination import lock_users,ACTIVE,Assign,Reschedule
from .flow_service import utc,aware,uid,event,exception,notice,REASONS,DURATIONS
from .privacy import SECRET,normalize

class Enroll(StrictModel):
    name:str=Field(min_length=1,max_length=60)
    region:Region
    location:Point
    local_ai:bool
    consent_confirmed:bool
class Code(StrictModel):
    code:str=Field(min_length=20,max_length=150)
class Refresh(StrictModel):
    secret:str=Field(min_length=30,max_length=150)
class Policy(StrictModel):
    enabled:bool
    categories:list[str]=Field(max_length=4)
    @field_validator('categories')
    @classmethod
    def valid(cls,v):
        if any(x not in DURATIONS for x in v) or len(set(v))!=len(v):raise ValueError()
        return v
class VoiceSubmit(StrictModel):
    request_key:str=Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9-]+$')
    audio_base64:str=Field(min_length=4,max_length=2800000)
    reply_to:str|None=Field(default=None,max_length=36)
class Resolve(StrictModel):
    action:str=Field(pattern=r'^(assign|cancel|close)$')
    slot_id:str|None=Field(default=None,max_length=36)
    category:str=Field(default='other',max_length=30)
    note:str=Field(min_length=1,max_length=1500)
    confirmed:bool=False
    @field_validator('note')
    @classmethod
    def clean(cls,v):
        if not v.strip() or SECRET.search(normalize(v)):raise ValueError()
        return v.strip()
class Push(StrictModel):
    token:str=Field(pattern=r'^(ExponentPushToken|ExpoPushToken)\[[a-zA-Z0-9_-]+\]$',max_length=200)


def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def register_flow(app,db,current,role,audit,cipher,passwords,settings):
    service=app.state.flow
    def encode(value):return service.encode(value)
    def accessible(session,user,elder):
        profile=session.get(ElderProfile,elder)
        if not profile:raise HTTPException(404,'등록 이용자가 없습니다.')
        from .models import CaregiverTeam
        team=session.get(CaregiverTeam,user.id)
        if user.role!='admin' and not (user.role=='social_worker' and profile.worker_id==user.id) and not (user.role=='caregiver' and team and team.worker_id==profile.worker_id):raise HTTPException(403,'담당 팀의 이용자만 관리할 수 있습니다.')
        return profile
    def token(device):
        now=utc()
        return jwt.encode({'sub':device.elder_id,'device_id':device.id,'iss':'care-api','aud':'care-api','iat':now,'exp':now+timedelta(minutes=30)},settings.jwt_secret,algorithm='HS256')
    def device_result(d):return {'access_token':token(d),'user':{'id':d.elder_id,'role':'elder','status':'approved'}}
    def view(session,job,details=False):
        b=session.get(Booking,job.booking_id) if job.booking_id else None
        if not b and job.care_id:
            coord=session.scalar(select(Coordination).where(Coordination.care_id==job.care_id))
            if coord:b=session.get(Booking,coord.booking_id)
        slot=session.get(Availability,b.slot_id) if b else None
        message={'queued':'요청을 받았습니다. 가능한 일정을 찾고 있어요.','processing':'말씀하신 내용을 확인하고 있어요.',
            'clarify':'도움 내용과 날짜, 오전이나 오후 시간을 함께 다시 말씀해 주세요.',
            'exception':'담당자가 요청과 일정을 확인하고 있습니다.','rescheduling':'방문 일정을 다시 조율하고 있어요.',
            'completed':'요청 처리를 마쳤습니다.','cancelled':'요청을 취소했습니다.','in_progress':'돌봄을 진행하고 있습니다.'}.get(job.state,'')
        if slot and job.state=='assigned':message=f'{slot.day} {slot.start}에 요양보호사가 방문합니다.'
        if job.reason=='danger':message='급한 위험 상황이면 119에 연락해 주세요. 담당자에게도 확인 요청을 남겼습니다.'
        result={'id':job.id,'state':job.state,'reason':job.reason,'message':message,'updated_at':job.updated_at,'created_at':job.created_at,'care_id':job.care_id,'booking_id':b.id if b else None,
            'schedule':{'day':slot.day,'start':slot.start,'end':slot.end,'caregiver_id':slot.caregiver_id,'status':b.status} if slot else None}
        if details:
            result.update(elder_id=job.elder_id,worker_id=job.worker_id,reason_label=REASONS.get(job.reason,''),text=service.decode(job.encrypted_text) if job.encrypted_text else '',plan=service.decode(job.encrypted_plan) if job.encrypted_plan else None,
                events=[{'kind':x.kind,'actor':x.actor,'note':cipher.decrypt(x.encrypted_note.encode()).decode(),'at':x.created_at} for x in session.scalars(select(FlowEvent).where(FlowEvent.job_id==job.id).order_by(FlowEvent.created_at))])
        return result
    @app.post('/api/caregiver/elders',status_code=201)
    def enroll(body:Enroll,user=Depends(role('caregiver')),session=Depends(db)):
        from .models import CaregiverTeam
        if not body.consent_confirmed:raise HTTPException(422,'이용자 안내와 동의 확인이 필요합니다.')
        lock_users(session,user.id)
        team=session.get(CaregiverTeam,user.id)
        if not team or session.get(User,team.worker_id).status!='approved':raise HTTPException(409,'담당 사회복지사를 먼저 연결하세요.')
        if SECRET.search(normalize(body.name)):raise HTTPException(422,'등록 내용을 확인하세요.')
        elder='elder_'+secrets.token_hex(8)
        session.add(User(id=elder,password_hash=passwords.hash(secrets.token_urlsafe(48)),role='elder',status='approved'));session.flush()
        session.add(ElderProfile(elder_id=elder,worker_id=team.worker_id,registered_by=user.id,encrypted_details=encode({'name':body.name})))
        session.add(ServiceRegion(owner_id=elder,**body.region.model_dump()))
        p=body.location
        session.add(RouteLocation(owner_id=elder,encrypted_point=encode([p.longitude,p.latitude,p.label]),consent=p.consent,departure=p.departure))
        session.add(Preference(owner_id=elder,local_ai=body.local_ai,reviewed=True))
        audit(session,user,'assisted_enroll',elder);session.commit();return {'elder_id':elder}
    @app.post('/api/caregiver/elders/{elder}/attach')
    def attach(elder:str,user=Depends(role('caregiver')),session=Depends(db)):
        from .models import CaregiverTeam
        lock_users(session,elder,user.id)
        team=session.get(CaregiverTeam,user.id);target=session.get(User,elder)
        if not team or not target or target.role!='elder' or target.status!='approved':raise HTTPException(404,'승인된 어르신과 담당 팀을 확인하세요.')
        if session.get(ElderProfile,elder):raise HTTPException(409,'이미 담당 관계가 있습니다.')
        existing=session.scalar(select(Care.id).where(Care.owner_id==elder,Care.worker_id==team.worker_id))
        if not existing:raise HTTPException(403,'담당 사회복지사가 기존 요청을 맡은 이용자만 연결할 수 있습니다.')
        session.add(ElderProfile(elder_id=elder,worker_id=team.worker_id,registered_by=user.id,encrypted_details=encode({'name':elder})))
        audit(session,user,'legacy_elder_attach',elder);session.commit();return {'elder_id':elder}
    @app.get('/api/staff/elders')
    def elders(user=Depends(role('caregiver','social_worker','admin')),session=Depends(db)):
        from .models import CaregiverTeam
        q=select(ElderProfile)
        if user.role=='social_worker':q=q.where(ElderProfile.worker_id==user.id)
        elif user.role=='caregiver':
            team=session.get(CaregiverTeam,user.id)
            if not team:return []
            q=q.where(ElderProfile.worker_id==team.worker_id)
        return [{'elder_id':x.elder_id,'worker_id':x.worker_id,**service.decode(x.encrypted_details)} for x in session.scalars(q)]
    @app.post('/api/staff/elders/{elder}/pair')
    def pair(elder:str,user=Depends(role('caregiver','social_worker','admin')),session=Depends(db)):
        accessible(session,user,elder);lock_users(session,elder)
        # Issuing a replacement code retires prior devices for a lost/replaced phone.
        session.execute(update(DeviceLink).where(DeviceLink.elder_id==elder).values(revoked=True))
        raw=secrets.token_urlsafe(24)
        session.add(DeviceLink(id=uid(),elder_id=elder,code_hash=digest(raw),expires=utc()+timedelta(minutes=10)))
        audit(session,user,'device_pair_code',elder);session.commit();return {'code':raw,'expires_minutes':10}
    @app.post('/api/device/pair')
    def exchange(body:Code,session=Depends(db)):
        d=session.scalar(select(DeviceLink).where(DeviceLink.code_hash==digest(body.code),DeviceLink.revoked.is_(False)))
        if not d:raise HTTPException(401,'연결 코드를 확인하세요.')
        lock_users(session,d.elder_id);session.refresh(d)
        if d.code_hash!=digest(body.code) or d.revoked or aware(d.expires)<utc():raise HTTPException(401,'연결 코드가 만료됐습니다.')
        raw=secrets.token_urlsafe(48);d.secret_hash=digest(raw);d.code_hash=None;d.expires=utc()+timedelta(days=90)
        result=device_result(d);session.commit();return {**result,'secret':raw}
    @app.post('/api/device/refresh')
    def refresh(body:Refresh,session=Depends(db)):
        d=session.scalar(select(DeviceLink).where(DeviceLink.secret_hash==digest(body.secret),DeviceLink.revoked.is_(False)))
        if not d or aware(d.expires)<utc() or session.get(User,d.elder_id).status!='approved':raise HTTPException(401,'직원에게 기기 재연결을 요청해 주세요.')
        return device_result(d)
    @app.post('/api/staff/elders/{elder}/revoke')
    def revoke(elder:str,user=Depends(role('caregiver','social_worker','admin')),session=Depends(db)):
        accessible(session,user,elder);lock_users(session,elder)
        session.execute(update(DeviceLink).where(DeviceLink.elder_id==elder).values(revoked=True));audit(session,user,'device_revoke',elder);session.commit();return {'status':'revoked'}
    @app.get('/api/caregiver/auto-policy')
    def policy(user=Depends(role('caregiver')),session=Depends(db)):
        row=session.get(AutoPolicy,user.id)
        return {'enabled':bool(row and row.enabled),'categories':json.loads(row.categories) if row else []}
    @app.post('/api/caregiver/auto-policy')
    def save_policy(body:Policy,user=Depends(role('caregiver')),session=Depends(db)):
        lock_users(session,user.id)
        if body.enabled and not body.categories:raise HTTPException(422,'자동 배정할 업무를 선택하세요.')
        row=session.get(AutoPolicy,user.id)
        if not row:row=AutoPolicy(caregiver_id=user.id);session.add(row)
        row.enabled=body.enabled;row.categories=json.dumps(body.categories);audit(session,user,'auto_policy',user.id);session.commit();return body.model_dump()
    @app.post('/api/flow/voice',status_code=202)
    def submit(body:VoiceSubmit,user=Depends(role('elder')),session=Depends(db)):
        try:audio=base64.b64decode(body.audio_base64,validate=True)
        except ValueError:raise HTTPException(422,'녹음 형식을 확인하세요.')
        if not 100<=len(audio)<=2_000_000:raise HTTPException(422,'녹음 길이를 확인하세요.')
        lock_users(session,user.id)
        old=session.scalar(select(VoiceJob).where(VoiceJob.elder_id==user.id,VoiceJob.request_key==body.request_key))
        payload=digest(body.audio_base64)
        if old:
            if old.payload_hash!=payload:raise HTTPException(409,'같은 접수번호의 내용이 다릅니다.')
            return view(session,old)
        pref=session.get(Preference,user.id)
        if not pref or not pref.local_ai:raise HTTPException(409,'직원에게 음성·AI 이용 설정을 요청해 주세요.')
        if session.scalar(select(func.count()).select_from(VoiceJob).where(VoiceJob.elder_id==user.id,VoiceJob.state.in_(('queued','processing'))))>=2:raise HTTPException(409,'먼저 보낸 요청을 처리하고 있습니다.')
        profile=session.get(ElderProfile,user.id)
        job=VoiceJob(id=uid(),elder_id=user.id,worker_id=profile.worker_id if profile else None,request_key=body.request_key,payload_hash=payload,encrypted_audio=cipher.encrypt(body.audio_base64.encode()).decode(),state='queued')
        if body.reply_to:
            parent=session.get(VoiceJob,body.reply_to)
            if not parent or parent.elder_id!=user.id or parent.state!='clarify':raise HTTPException(409,'다시 확인할 요청이 없습니다.')
            parent.state='superseded';job.clarifications=parent.clarifications+1;job.created_at=parent.created_at
            event(session,cipher,parent,'clarified','다시 말한 접수로 연결',user.id)
        session.add(job);session.flush();event(session,cipher,job,'received','음성 접수 저장',user.id);session.commit();return view(session,job)
    @app.get('/api/flow/jobs')
    def jobs(user=Depends(role('elder','social_worker','admin')),session=Depends(db)):
        q=select(VoiceJob)
        if user.role=='elder':q=q.where(VoiceJob.elder_id==user.id)
        elif user.role=='social_worker':q=q.where(VoiceJob.worker_id==user.id)
        return [view(session,x,user.role!='elder') for x in session.scalars(q.order_by(VoiceJob.created_at.desc()).limit(100))]
    @app.get('/api/flow/statistics')
    def statistics(user=Depends(role('social_worker','admin')),session=Depends(db)):
        base=select(VoiceJob).where(VoiceJob.state!='superseded')
        if user.role=='social_worker':base=base.where(VoiceJob.worker_id==user.id)
        q=base.subquery()
        totals=[{'state':state,'count':count} for state,count in session.execute(select(q.c.state,func.count()).group_by(q.c.state))]
        kinds=[{'category':category or 'other','state':state,'count':count} for category,state,count in session.execute(select(Care.category,q.c.state,func.count()).select_from(q).outerjoin(Care,Care.id==q.c.care_id).group_by(Care.category,q.c.state))]
        interventions=select(FlowEvent.job_id).where(FlowEvent.kind.in_(('worker_adjust','worker_close','worker_cancel')))
        automatic=session.scalar(select(func.count()).select_from(q).where(q.c.state=='completed',~q.c.id.in_(interventions)))
        return {'total':sum(x['count'] for x in totals),'automatic_completed':automatic,'states':totals,'categories':kinds,'scope':'assigned_team' if user.role!='admin' else 'institution'}
    @app.get('/api/flow/request/{key}')
    def by_key(key:str,user=Depends(role('elder')),session=Depends(db)):
        x=session.scalar(select(VoiceJob).where(VoiceJob.elder_id==user.id,VoiceJob.request_key==key))
        return view(session,x) if x else None
    @app.get('/api/flow/jobs/{jid}')
    def get_job(jid:str,user=Depends(current),session=Depends(db)):
        x=session.get(VoiceJob,jid)
        if not x or not (user.id in (x.elder_id,x.worker_id) or user.role=='admin'):raise HTTPException(404,'접수를 찾을 수 없습니다.')
        return view(session,x,user.role!='elder')
    @app.post('/api/worker/flow/{jid}/resolve')
    def resolve(jid:str,body:Resolve,user=Depends(role('social_worker')),session=Depends(db)):
        job=session.get(VoiceJob,jid)
        if not job or job.worker_id!=user.id:raise HTTPException(404,'담당 요청이 없습니다.')
        lock_users(session,*session.scalars(select(User.id).where(User.role.in_(('elder','caregiver','social_worker')))).all());session.refresh(job)
        if not job.booking_id and job.care_id:
            existing=session.scalar(select(Coordination).where(Coordination.care_id==job.care_id))
            if existing:job.booking_id=existing.booking_id
        if job.state not in ('exception','clarify','rescheduling'):raise HTTPException(409,'현재 조율할 요청이 아닙니다.')
        if not body.confirmed:raise HTTPException(422,'이용자와 조율 내용을 확인하세요.')
        if body.action=='assign':
            if body.category not in ('meal','mobility','housekeeping','companionship','medication','other') or not body.slot_id:raise HTTPException(422,'업무와 일정을 선택하세요.')
            if not job.care_id:
                care=Care(id=uid(),owner_id=job.elder_id,worker_id=user.id,category=body.category,encrypted_content=encode({'note':body.note,'features':{'category':body.category}}),urgency='need',source='human_flow',confidence=0,review_required=False);session.add(care);session.flush();job.care_id=care.id
            else:
                care=session.get(Care,job.care_id);care.category=body.category;care.review_required=False;care.urgency='need';care.source='human_flow'
            from .models import CareDecision
            decision=session.get(CareDecision,job.care_id)
            if not decision:
                decision=CareDecision(care_id=job.care_id,worker_id=user.id,method='manual',suggested_urgency='uncertain',final_urgency='need');session.add(decision)
            decision.encrypted_handoff=cipher.encrypt(body.note.encode()).decode()
            # Existing guarded endpoints commit the assignment. Pre-save the job/event so recovery can locate it by care_id.
            job.state='rescheduling';event(session,cipher,job,'worker_adjust',body.note,user.id);session.flush()
            if job.booking_id and session.get(Booking,job.booking_id).status=='attention':
                previous=session.get(Coordination,job.booking_id)
                if previous:previous.care_id=None
                event(session,cipher,job,'previous_visit',job.booking_id,user.id)
                job.booking_id=None
            if job.booking_id:result=app.state.flow_reschedule(job.booking_id,Reschedule(slot_id=body.slot_id,contact_confirmed=True),user,session)
            else:result=app.state.flow_assign(Assign(care_id=job.care_id,slot_id=body.slot_id,contact_confirmed=True),user,session)
            job.booking_id=result['id'];session.commit()
        else:
            if job.booking_id:
                b=session.get(Booking,job.booking_id)
                if b.status=='in_progress':raise HTTPException(409,'방문 진행 중에는 수행 결과를 먼저 확인하세요.')
                if body.action=='close' and b.status in ('accepted','offered','pending'):raise HTTPException(409,'진행할 일정이 남아 있습니다. 취소 또는 재조율해 주세요.')
                if body.action=='cancel' and b.status in ('accepted','offered','pending','declined'):
                    old_slot=session.get(Availability,b.slot_id)
                    b.status='cancelled';old_slot.state='open' if slot_future(old_slot) else 'closed'
                    for p in session.scalars(select(ScheduleProposal).where(ScheduleProposal.booking_id==b.id)):p.status='withdrawn'
            job.state='cancelled' if body.action=='cancel' else 'completed';job.reason=''
            event(session,cipher,job,'worker_'+body.action,body.note,user.id);notice(session,job,job.elder_id,job.state);session.commit()
        return view(session,job,True)
    @app.get('/api/flow/visits/{bid}')
    def visit_info(bid:str,user=Depends(role('caregiver')),session=Depends(db)):
        b=session.get(Booking,bid);slot=session.get(Availability,b.slot_id) if b else None
        if not slot or slot.caregiver_id!=user.id or b.status not in ('accepted','in_progress','completed','attention','offered'):raise HTTPException(404,'배정된 방문이 없습니다.')
        coord=session.get(Coordination,bid);care=session.get(Care,coord.care_id) if coord and coord.care_id else None
        profile=session.get(ElderProfile,b.elder_id);loc=session.get(RouteLocation,b.elder_id)
        raw=service.decode(care.encrypted_content) if care else {}
        flow_job=session.scalar(select(VoiceJob).where(VoiceJob.booking_id==bid))
        packet=service.decode(flow_job.encrypted_plan) if flow_job and flow_job.encrypted_plan else {}
        from .models import CareDecision
        decision=session.get(CareDecision,care.id) if care else None
        handoff=packet.get('evidence','') if care and care.source=='auto_policy_v2' else cipher.decrypt(decision.encrypted_handoff.encode()).decode() if decision and decision.encrypted_handoff else '담당자에게 필요한 수행 내용을 확인해 주세요.'
        audit(session,user,'flow_visit_read',bid);session.commit()
        point=service.decode(loc.encrypted_point) if loc else []
        return {'name':service.decode(profile.encrypted_details)['name'] if profile else b.elder_id,'address':point[2] if len(point)>2 else '담당자에게 확인','note':handoff,'prepared_by':'자동 접수 내용' if care and care.source=='auto_policy_v2' else '담당자 조율 내용'}
    @app.get('/api/flow/notices')
    def notices(user=Depends(current),session=Depends(db)):
        return [{'id':n.id,'job_id':n.job_id,'kind':n.kind,'read':n.read,'push_state':n.push_state} for n in session.scalars(select(FlowNotice).where(FlowNotice.owner_id==user.id).order_by(FlowNotice.created_at.desc()).limit(50))]
    @app.post('/api/flow/notices/{nid}/read')
    def mark_read(nid:str,user=Depends(current),session=Depends(db)):
        n=session.get(FlowNotice,nid)
        if not n or n.owner_id!=user.id:raise HTTPException(404,'알림을 찾을 수 없습니다.')
        n.read=True;session.commit();return {'read':True}
    @app.post('/api/flow/push-device')
    def push_device(body:Push,user=Depends(current),session=Depends(db)):
        lock_users(session,user.id);d=session.get(PushDevice,user.id)
        if not d:d=PushDevice(owner_id=user.id);session.add(d)
        d.encrypted_token=cipher.encrypt(body.token.encode()).decode();session.commit();return {'status':'saved'}
