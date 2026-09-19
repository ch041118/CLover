"""Social workers coordinate; caregivers perform. Deterministic review assistance, never auto-dispatch."""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from fastapi import Depends, HTTPException, Query
from pydantic import Field, field_validator
from sqlalchemy import select, update, func
from .models import User, Care, Availability, Booking, Coordination, VisitRecord, RepeatCase, ServiceRegion
from .schemas import StrictModel, Category
from .matching import KST, slot_future
from .privacy import SECRET, normalize

WINDOW_DAYS=7
THRESHOLD=3
ACTIVE=('pending','accepted','in_progress')

def lock_users(session,*ids):
    for key in sorted(set(ids)):
        session.execute(update(User).where(User.id==key).values(status=User.status))

def repeat_counts(session,elder_id,category,since=None):
    cutoff=datetime.now(timezone.utc)-timedelta(days=WINDOW_DAYS)
    query=select(Care).where(Care.owner_id==elder_id,Care.category==category,Care.created_at>=cutoff)
    if since: query=query.where(Care.created_at>since)
    return session.scalars(query).all()

def update_repeat(session,elder_id,category,new_care=None):
    lock_users(session,elder_id)
    case=session.scalar(select(RepeatCase).where(RepeatCase.elder_id==elder_id,RepeatCase.category==category))
    rows=repeat_counts(session,elder_id,category,case.reviewed_at if case else None)
    if len(rows)>=THRESHOLD:
        if not case:
            case=RepeatCase(id=str(uuid.uuid4()),elder_id=elder_id,category=category,state='open');session.add(case)
        else: case.state='open'
    if case and new_care and case.auto_route and case.worker_id:
        worker=session.get(User,case.worker_id)
        if worker and worker.status=='approved' and worker.role=='social_worker':
            new_care.worker_id=worker.id  # Still requires independent human review, including emergencies.
    return case

class Confirm(StrictModel):
    contact_confirmed: bool = False

class Assign(Confirm):
    care_id: str = Field(max_length=36)
    slot_id: str = Field(max_length=36)

class Reschedule(Confirm):
    slot_id: str = Field(max_length=36)

class VisitInput(StrictModel):
    outcome: Literal['completed','unable','concern']
    note: str = Field(min_length=1,max_length=1500)
    @field_validator('note')
    @classmethod
    def note_ok(cls,v):
        if not v.strip() or SECRET.search(normalize(v)): raise ValueError('Check note')
        return v.strip()

class CaseDecision(StrictModel):
    decision: Literal['monitor','plan','close']
    note: str = Field(min_length=1,max_length=1500)
    followup_day: date | None = None
    auto_route: bool = False
    @field_validator('note')
    @classmethod
    def note_ok(cls,v): return VisitInput.note_ok(v)


def register_coordination(app,db,current,role,audit,cipher):
    def slot_data(slot):
        return {'slot_id':slot.id,'caregiver_id':slot.caregiver_id,'day':slot.day,'start':slot.start,'end':slot.end,
                'province':slot.province,'district':slot.district}

    def booking_data(session,b,slot):
        coord=session.get(Coordination,b.id);record=session.get(VisitRecord,b.id)
        return {**slot_data(slot),'id':b.id,'elder_id':b.elder_id,'category':b.category,'status':b.status,
                'worker_id':coord.worker_id if coord else None,'care_id':coord.care_id if coord else None,
                'outcome':record.outcome if record else None}

    def owned(session,bid,user,claim=False):
        b=session.get(Booking,bid)
        if not b: raise HTTPException(404,'신청을 찾을 수 없습니다.')
        slot=session.get(Availability,b.slot_id)
        lock_users(session,b.elder_id,slot.caregiver_id);session.refresh(b)
        if b.slot_id!=slot.id: raise HTTPException(409,'일정이 변경됐습니다. 새로고침하세요.')
        coord=session.get(Coordination,b.id)
        if coord and coord.worker_id!=user.id: raise HTTPException(403,'다른 사회복지사가 관리하는 일정입니다.')
        if not coord:
            if not claim: raise HTTPException(409,'먼저 일정 관리를 맡아 주세요.')
            coord=Coordination(booking_id=b.id,worker_id=user.id);session.add(coord)
        return b,slot,coord

    def check_slot(session,slot,elder_id,exclude=None):
        if not slot_future(slot) or slot.state!='open': raise HTTPException(409,'선택할 수 없는 일정입니다.')
        for uid,expected in [(elder_id,'elder'),(slot.caregiver_id,'caregiver')]:
            actor=session.get(User,uid)
            if not actor or actor.status!='approved' or actor.role!=expected: raise HTTPException(409,'계정 상태를 확인하세요.')
            reg=session.scalar(select(ServiceRegion.id).where(ServiceRegion.owner_id==uid,
                ServiceRegion.province==slot.province,ServiceRegion.district==slot.district))
            if not reg: raise HTTPException(409,'등록된 활동 지역이 다릅니다.')
        conflict=select(Booking.id).join(Availability).where(Booking.elder_id==elder_id,Booking.status.in_(ACTIVE),
            Availability.day==slot.day,Availability.start<slot.end,Availability.end>slot.start)
        if exclude: conflict=conflict.where(Booking.id!=exclude)
        if session.scalar(conflict): raise HTTPException(409,'이용자의 다른 일정과 겹칩니다.')

    @app.get('/api/worker/statistics')
    def statistics(days:int=Query(7,ge=1,le=90),user=Depends(role('social_worker')),session=Depends(db)):
        cutoff=datetime.now(timezone.utc)-timedelta(days=days)
        base=select(Care).where(Care.created_at>=cutoff).subquery()
        matrix=[{'category':c,'urgency':u,'count':n} for c,u,n in session.execute(select(base.c.category,base.c.urgency,func.count()).group_by(base.c.category,base.c.urgency))]
        total=session.scalar(select(func.count()).select_from(base))
        reviewed=session.scalar(select(func.count()).select_from(base).where(base.c.review_required.is_(False)))
        assigned=session.scalar(select(func.count()).select_from(base).where(base.c.worker_id.is_not(None)))
        visits=[{'status':status,'count':n} for status,n in session.execute(select(Booking.status,func.count()).where(Booking.created_at>=cutoff).group_by(Booking.status))]
        return {'days':days,'total':total,'review_pending':total-reviewed,'reviewed':reviewed,
                'unassigned':total-assigned,'assigned':assigned,'matrix':matrix,'bookings':visits,
                'scope':'single_institution','period':'created_at_rolling_days'}

    @app.get('/api/worker/schedules')
    def schedules(offset:int=Query(0,ge=0),user=Depends(role('social_worker')),session=Depends(db)):
        rows=session.execute(select(Booking,Availability).join(Availability).order_by(Booking.created_at.desc()).offset(offset).limit(100))
        return [booking_data(session,b,s) for b,s in rows]

    @app.post('/api/worker/schedules/{bid}/claim')
    def claim(bid:str,user=Depends(role('social_worker')),session=Depends(db)):
        b,slot,_=owned(session,bid,user,claim=True);audit(session,user,'coordinate_claim',bid);session.commit()
        return booking_data(session,b,slot)

    @app.post('/api/worker/schedules/{bid}/confirm')
    def confirm(bid:str,body:Confirm,user=Depends(role('social_worker')),session=Depends(db)):
        if not body.contact_confirmed: raise HTTPException(422,'당사자와 일정을 확인해 주세요.')
        b,slot,_=owned(session,bid,user)
        if b.status!='pending' or not slot_future(slot): raise HTTPException(409,'확정할 수 없는 일정입니다.')
        for uid in [b.elder_id,slot.caregiver_id]:
            actor=session.get(User,uid);session.refresh(actor)
            if actor.status!='approved': raise HTTPException(409,'계정 상태를 확인하세요.')
        b.status='accepted';audit(session,user,'coordinate_confirm',bid);session.commit()
        return booking_data(session,b,slot)

    @app.get('/api/worker/care/{care_id}/slots')
    def candidate_slots(care_id:str,user=Depends(role('social_worker')),session=Depends(db)):
        care=session.get(Care,care_id)
        if not care or care.worker_id!=user.id: raise HTTPException(404,'담당 요청을 찾을 수 없습니다.')
        regions=session.scalars(select(ServiceRegion).where(ServiceRegion.owner_id==care.owner_id)).all()
        region_set={(r.province,r.district) for r in regions}
        slots=session.scalars(select(Availability).join(User,User.id==Availability.caregiver_id).where(
            User.status=='approved',Availability.state=='open',Availability.day>=str(datetime.now(KST).date())).order_by(Availability.day,Availability.start))
        return [slot_data(s) for s in slots if slot_future(s) and (s.province,s.district) in region_set][:100]

    @app.post('/api/worker/assign',status_code=201)
    def assign(body:Assign,user=Depends(role('social_worker')),session=Depends(db)):
        if not body.contact_confirmed: raise HTTPException(422,'당사자와 일정을 확인해 주세요.')
        care=session.get(Care,body.care_id);slot=session.get(Availability,body.slot_id)
        if not care or care.worker_id!=user.id or not slot: raise HTTPException(404,'요청 또는 일정을 찾을 수 없습니다.')
        lock_users(session,care.owner_id,slot.caregiver_id);session.refresh(slot);session.refresh(care)
        if care.review_required: raise HTTPException(409,'요청 분류를 먼저 검토해 주세요.')
        if session.scalar(select(Coordination.booking_id).where(Coordination.care_id==care.id)): raise HTTPException(409,'이미 연결된 요청입니다. 기존 일정에서 변경하세요.')
        check_slot(session,slot,care.owner_id)
        b=Booking(id=str(uuid.uuid4()),slot_id=slot.id,elder_id=care.owner_id,category=care.category,status='accepted')
        slot.state='reserved';session.add(b);session.flush()
        session.add(Coordination(booking_id=b.id,worker_id=user.id,care_id=care.id))
        audit(session,user,'coordinate_assign',b.id);session.commit()
        return booking_data(session,b,slot)

    @app.post('/api/worker/schedules/{bid}/reschedule')
    def reschedule(bid:str,body:Reschedule,user=Depends(role('social_worker')),session=Depends(db)):
        if not body.contact_confirmed: raise HTTPException(422,'당사자와 변경 일정을 확인해 주세요.')
        b=session.get(Booking,bid);target=session.get(Availability,body.slot_id)
        if not b or not target: raise HTTPException(404,'일정을 찾을 수 없습니다.')
        old=session.get(Availability,b.slot_id);original=b.slot_id
        lock_users(session,b.elder_id,old.caregiver_id,target.caregiver_id);session.refresh(b);session.refresh(old);session.refresh(target)
        coord=session.get(Coordination,bid)
        if not coord or coord.worker_id!=user.id: raise HTTPException(403,'담당 일정만 변경할 수 있습니다.')
        if b.slot_id!=original or b.status not in ('pending','accepted'): raise HTTPException(409,'변경할 수 없는 일정입니다.')
        check_slot(session,target,b.elder_id,exclude=bid)
        old.state='closed'  # Explicitly close the superseded slot; provider can publish a new one.
        target.state='reserved';b.slot_id=target.id
        audit(session,user,'coordinate_reschedule',bid);session.commit()
        return booking_data(session,b,target)

    @app.get('/api/worker/open-slots')
    def open_slots(user=Depends(role('social_worker')),session=Depends(db)):
        rows=session.scalars(select(Availability).join(User,User.id==Availability.caregiver_id).where(User.status=='approved',
            Availability.state=='open',Availability.day>=str(datetime.now(KST).date())).order_by(Availability.day,Availability.start))
        return [slot_data(s) for s in rows if slot_future(s)][:200]

    @app.post('/api/worker/schedules/{bid}/cancel')
    def cancel(bid:str,user=Depends(role('social_worker')),session=Depends(db)):
        b,slot,_=owned(session,bid,user)
        if b.status not in ('pending','accepted'): raise HTTPException(409,'진행 중이거나 종료된 일정은 취소할 수 없습니다.')
        b.status='cancelled';slot.state='closed';audit(session,user,'coordinate_cancel',bid);session.commit()
        return {'status':b.status}

    @app.post('/api/caregiver/visits/{bid}/start')
    def start(bid:str,user=Depends(role('caregiver')),session=Depends(db)):
        b=session.get(Booking,bid);slot=session.get(Availability,b.slot_id) if b else None
        if not b or slot.caregiver_id!=user.id: raise HTTPException(404,'배정된 일정을 찾을 수 없습니다.')
        lock_users(session,b.elder_id,user.id);session.refresh(b)
        if b.slot_id!=slot.id or b.status!='accepted': raise HTTPException(409,'확정된 일정만 시작할 수 있습니다.')
        if slot.day!=str(datetime.now(KST).date()): raise HTTPException(409,'방문 당일에 시작해 주세요.')
        b.status='in_progress';audit(session,user,'visit_start',bid);session.commit()
        return {'status':b.status}

    @app.post('/api/caregiver/visits/{bid}/report')
    def report(bid:str,body:VisitInput,user=Depends(role('caregiver')),session=Depends(db)):
        b=session.get(Booking,bid);slot=session.get(Availability,b.slot_id) if b else None
        if not b or slot.caregiver_id!=user.id: raise HTTPException(404,'배정된 일정을 찾을 수 없습니다.')
        lock_users(session,b.elder_id,user.id);session.refresh(b)
        if b.slot_id!=slot.id or b.status not in ('accepted','in_progress'): raise HTTPException(409,'이미 보고했거나 배정이 변경됐습니다.')
        if body.outcome=='completed' and b.status!='in_progress': raise HTTPException(409,'돌봄 시작 후 완료해 주세요.')
        session.add(VisitRecord(booking_id=bid,caregiver_id=user.id,outcome=body.outcome,encrypted_note=cipher.encrypt(body.note.encode()).decode()))
        b.status='completed' if body.outcome=='completed' else 'attention';slot.state='closed'
        audit(session,user,'visit_'+body.outcome,bid);session.commit()
        return {'status':b.status}

    @app.get('/api/visits/{bid}/report')
    def read_report(bid:str,user=Depends(current),session=Depends(db)):
        record=session.get(VisitRecord,bid);b=session.get(Booking,bid);coord=session.get(Coordination,bid)
        if not record or not b or user.id not in (record.caregiver_id,b.elder_id,coord.worker_id if coord else None): raise HTTPException(404,'기록을 찾을 수 없습니다.')
        audit(session,user,'visit_read',bid);session.commit()
        return {'outcome':record.outcome,'note':cipher.decrypt(record.encrypted_note.encode()).decode(),'recorded_at':record.recorded_at}

    @app.post('/api/worker/repeats/scan')
    def scan(user=Depends(role('social_worker')),session=Depends(db)):
        groups=session.execute(select(Care.owner_id,Care.category).where(Care.created_at>=datetime.now(timezone.utc)-timedelta(days=WINDOW_DAYS)).group_by(Care.owner_id,Care.category).having(func.count()>=THRESHOLD)).all()
        for elder,cat in sorted(groups):update_repeat(session,elder,cat)
        audit(session,user,'repeat_scan','seven_days');session.commit()
        return {'scanned_groups':len(groups)}

    @app.get('/api/worker/repeats')
    def repeats(user=Depends(role('social_worker')),session=Depends(db)):
        rows=session.scalars(select(RepeatCase).where((RepeatCase.worker_id.is_(None))|(RepeatCase.worker_id==user.id)))
        today=str(datetime.now(KST).date());result=[]
        for case in rows:
            recent=repeat_counts(session,case.elder_id,case.category)
            new=repeat_counts(session,case.elder_id,case.category,case.reviewed_at)
            result.append({'id':case.id,'elder_id':case.elder_id,'category':case.category,'state':case.state,
                'worker_id':case.worker_id,'count_7d':len(recent),'new_count':len(new),'danger_count':sum(r.urgency=='danger' for r in recent),
                'followup_day':case.followup_day,'due':bool(case.followup_day and case.followup_day<=today),
                'auto_route':case.auto_route,'decision_note':cipher.decrypt(case.encrypted_decision.encode()).decode() if case.worker_id==user.id and case.encrypted_decision else None})
        return sorted(result,key=lambda r:(not r['due'],r['state']!='open',-r['count_7d']))

    @app.post('/api/worker/repeats/{case_id}/claim')
    def claim_case(case_id:str,user=Depends(role('social_worker')),session=Depends(db)):
        case=session.get(RepeatCase,case_id)
        if not case: raise HTTPException(404,'검토 건을 찾을 수 없습니다.')
        lock_users(session,case.elder_id);session.refresh(case)
        if case.worker_id and case.worker_id!=user.id: raise HTTPException(409,'다른 담당자가 맡았습니다.')
        case.worker_id=user.id
        # Group only unassigned records. Never take another worker's records.
        session.execute(update(Care).where(Care.owner_id==case.elder_id,Care.category==case.category,
            Care.worker_id.is_(None),Care.created_at>=datetime.now(timezone.utc)-timedelta(days=WINDOW_DAYS)).values(worker_id=user.id))
        audit(session,user,'repeat_claim',case.id);session.commit();return {'status':'claimed'}

    @app.post('/api/worker/repeats/{case_id}/decision')
    def decide_case(case_id:str,body:CaseDecision,user=Depends(role('social_worker')),session=Depends(db)):
        case=session.get(RepeatCase,case_id)
        if not case or case.worker_id!=user.id: raise HTTPException(404,'담당 검토 건을 찾을 수 없습니다.')
        lock_users(session,case.elder_id);session.refresh(case)
        if body.decision!='close' and (not body.followup_day or body.followup_day<datetime.now(KST).date()):raise HTTPException(422,'다음 확인 날짜를 지정하세요.')
        case.state={'monitor':'monitoring','plan':'planning','close':'closed'}[body.decision]
        case.followup_day=str(body.followup_day) if body.decision!='close' else None
        case.encrypted_decision=cipher.encrypt(body.note.encode()).decode();case.reviewed_at=datetime.now(timezone.utc)
        case.auto_route=body.auto_route if body.decision!='close' else False
        audit(session,user,'repeat_'+body.decision,case.id);session.commit()
        return {'state':case.state,'auto_route':case.auto_route}
