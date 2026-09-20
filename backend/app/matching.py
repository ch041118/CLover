"""Opt-in region and exact-date matching. No GPS, external geocoder, or public profiles."""
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Literal
from fastapi import Depends, HTTPException
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select, update, delete
from .models import User, Preference, ServiceRegion, Availability, Booking, CaregiverTeam
from .schemas import StrictModel, Category

PROVINCES = ['서울특별시','부산광역시','대구광역시','인천광역시','광주광역시','대전광역시','울산광역시','세종특별자치시','경기도','강원특별자치도','충청북도','충청남도','전북특별자치도','전라남도','경상북도','경상남도','제주특별자치도']
KST = ZoneInfo('Asia/Seoul')

class Region(StrictModel):
    province: str
    district: str = Field(min_length=1, max_length=30, pattern=r'^[가-힣 ]+$')

    @field_validator('province')
    @classmethod
    def province_known(cls, v):
        if v not in PROVINCES: raise ValueError('Select a province')
        return v

    @field_validator('district')
    @classmethod
    def district_normal(cls, v):
        v = ' '.join(v.split())
        if not v: raise ValueError('District required')
        return v

class Regions(StrictModel):
    regions: list[Region] = Field(max_length=10)

class Consent(StrictModel):
    local_ai: bool

class Window(StrictModel):
    day: date
    start: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    end: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')

    @model_validator(mode='after')
    def future(self):
        now = datetime.now(KST)
        if self.start >= self.end or self.day > now.date()+timedelta(days=90): raise ValueError('Invalid time window')
        if datetime.fromisoformat(f'{self.day}T{self.start}').replace(tzinfo=KST) <= now: raise ValueError('Future time required')
        return self

class SlotCreate(Window):
    region: Region

class MatchSearch(Window):
    region: Region

class Book(StrictModel):
    slot_id: str = Field(max_length=36)
    category: Category

class Decision(StrictModel):
    action: Literal['accept','decline','cancel']

def slot_future(slot):
    return datetime.fromisoformat(f'{slot.day}T{slot.start}').replace(tzinfo=KST) > datetime.now(KST)

def register_matching(app, db, current, role, audit):
    def lock(session, *ids):
        # Serialize all schedule mutations on stable participant rows. This also works in SQLite.
        for key in sorted(set(ids)):
            session.execute(update(User).where(User.id == key).values(status=User.status))

    def owns_region(session, user_id, region):
        return session.scalar(select(ServiceRegion.id).where(ServiceRegion.owner_id == user_id,
            ServiceRegion.province == region.province, ServiceRegion.district == region.district)) is not None

    def slot_view(row):
        return {'id':row.id,'caregiver_id':row.caregiver_id,'province':row.province,'district':row.district,
                'day':row.day,'start':row.start,'end':row.end,'state':row.state}

    @app.get('/api/preferences')
    def preferences(user=Depends(current), session=Depends(db)):
        p = session.get(Preference,user.id)
        return {'local_ai':bool(p and p.local_ai),'reviewed':bool(p and p.reviewed)}

    @app.post('/api/preferences')
    def preferences_save(body: Consent, user=Depends(current), session=Depends(db)):
        lock(session,user.id)
        p = session.get(Preference,user.id)
        if p is None: p=Preference(owner_id=user.id); session.add(p)
        p.local_ai=body.local_ai; p.reviewed=True; p.updated_at=datetime.now(KST)
        audit(session,user,'ai_consent_on' if body.local_ai else 'ai_consent_off',user.id)
        session.commit()
        return {'local_ai':p.local_ai,'reviewed':True}

    @app.get('/api/regions')
    def regions(user=Depends(role('elder','caregiver')), session=Depends(db)):
        rows=session.scalars(select(ServiceRegion).where(ServiceRegion.owner_id==user.id)).all()
        return {'provinces':PROVINCES,'regions':[{'province':r.province,'district':r.district} for r in rows]}

    @app.post('/api/regions')
    def regions_save(body: Regions,user=Depends(role('elder','caregiver')),session=Depends(db)):
        lock(session,user.id)
        if len({(r.province,r.district) for r in body.regions}) != len(body.regions): raise HTTPException(422,'중복 지역')
        session.execute(delete(ServiceRegion).where(ServiceRegion.owner_id==user.id))
        for r in body.regions: session.add(ServiceRegion(owner_id=user.id,**r.model_dump()))
        # Unbooked slots in removed regions must no longer be discoverable.
        for slot in session.scalars(select(Availability).where(Availability.caregiver_id==user.id,Availability.state=='open')):
            if (slot.province,slot.district) not in {(r.province,r.district) for r in body.regions}: slot.state='closed'
        audit(session,user,'update_regions',user.id); session.commit()
        return {'status':'saved'}

    @app.post('/api/availability',status_code=201)
    def availability_create(body: SlotCreate,user=Depends(role('caregiver')),session=Depends(db)):
        lock(session,user.id)
        if not owns_region(session,user.id,body.region): raise HTTPException(422,'먼저 활동 지역을 저장하세요.')
        conflict=session.scalar(select(Availability.id).where(Availability.caregiver_id==user.id,
            Availability.day==str(body.day),Availability.state!='closed',Availability.start<body.end,Availability.end>body.start))
        if conflict: raise HTTPException(409,'시간이 겹칩니다.')
        slot=Availability(id=str(uuid.uuid4()),caregiver_id=user.id,**body.region.model_dump(),day=str(body.day),start=body.start,end=body.end)
        session.add(slot);audit(session,user,'create_availability',slot.id);session.commit()
        return slot_view(slot)

    @app.get('/api/availability')
    def availability_list(user=Depends(role('caregiver')),session=Depends(db)):
        return [slot_view(r) for r in session.scalars(select(Availability).where(Availability.caregiver_id==user.id,
            Availability.day>=str(datetime.now(KST).date())).order_by(Availability.day,Availability.start).limit(200))]

    @app.post('/api/availability/{slot_id}/close')
    def availability_close(slot_id:str,user=Depends(role('caregiver')),session=Depends(db)):
        lock(session,user.id)
        r=session.get(Availability,slot_id)
        if not r or r.caregiver_id!=user.id: raise HTTPException(404,'일정을 찾을 수 없습니다.')
        if r.state=='reserved': raise HTTPException(409,'신청 건을 먼저 취소하세요.')
        r.state='closed';audit(session,user,'close_availability',slot_id);session.commit()
        return slot_view(r)

    @app.post('/api/matches')
    def matches(body: MatchSearch,user=Depends(role('elder')),session=Depends(db)):
        if not owns_region(session,user.id,body.region): raise HTTPException(422,'먼저 원하는 지역을 저장하세요.')
        slots=session.scalars(select(Availability).join(User,User.id==Availability.caregiver_id).where(
            User.status=='approved',User.role=='caregiver',Availability.state=='open',Availability.day==str(body.day),
            Availability.province==body.region.province,Availability.district==body.region.district,
            Availability.start>=body.start,Availability.end<=body.end).order_by(Availability.start).limit(100))
        return [slot_view(r) for r in slots if slot_future(r) and session.get(CaregiverTeam,r.caregiver_id)]

    @app.post('/api/bookings',status_code=201)
    def book(body: Book,user=Depends(role('elder')),session=Depends(db)):
        slot=session.get(Availability,body.slot_id)
        if not slot: raise HTTPException(404,'일정을 찾을 수 없습니다.')
        lock(session,user.id,slot.caregiver_id)
        session.refresh(slot)
        cg=session.get(User,slot.caregiver_id);session.refresh(cg)
        if cg.status!='approved' or cg.role!='caregiver' or slot.state!='open' or not slot_future(slot): raise HTTPException(409,'예약할 수 없는 일정입니다.')
        region=Region(province=slot.province,district=slot.district)
        if not owns_region(session,user.id,region) or not owns_region(session,cg.id,region): raise HTTPException(409,'활동 지역을 다시 확인하세요.')
        conflict=session.scalar(select(Booking.id).join(Availability).where(Booking.elder_id==user.id,
            Booking.status.in_(['pending','offered','accepted','in_progress']),Availability.day==slot.day,Availability.start<slot.end,Availability.end>slot.start))
        if conflict: raise HTTPException(409,'신청한 시간과 겹칩니다.')
        team=session.get(CaregiverTeam,cg.id)
        if not team:raise HTTPException(409,'담당 사회복지사 연결이 필요합니다.')
        from .teams import require_team
        require_team(session,cg.id,team.worker_id)
        app.state.routing.check(session,slot,user.id)
        row=Booking(id=str(uuid.uuid4()),slot_id=slot.id,elder_id=user.id,category=body.category.value)
        slot.state='reserved';session.add(row);audit(session,user,'request_booking',row.id);session.commit()
        return {'id':row.id,'status':row.status}

    @app.get('/api/bookings')
    def booking_list(user=Depends(role('elder','caregiver')),session=Depends(db)):
        query=select(Booking,Availability).join(Availability)
        query=query.where(Booking.elder_id==user.id) if user.role=='elder' else query.where(Availability.caregiver_id==user.id)
        return [{**slot_view(slot),'id':b.id,'slot_id':slot.id,'status':b.status,'category':b.category,
                 'elder_id':b.elder_id} for b,slot in session.execute(query.order_by(Booking.created_at.desc()).limit(100))]

    @app.post('/api/bookings/{booking_id}/decision')
    def decision(booking_id:str,body:Decision,user=Depends(role('elder','caregiver')),session=Depends(db)):
        if user.role!='elder' or body.action!='cancel':
            raise HTTPException(403,'일정 확정·조율은 사회복지사가 담당합니다. 요양보호사는 수행 화면에서 보고해 주세요.')
        b=session.get(Booking,booking_id)
        slot=session.get(Availability,b.slot_id) if b else None
        if not b or user.id not in (b.elder_id,slot.caregiver_id): raise HTTPException(404,'신청을 찾을 수 없습니다.')
        lock(session,b.elder_id,slot.caregiver_id);session.refresh(b);session.refresh(slot)
        if b.status not in ('pending','offered','accepted'): raise HTTPException(409,'이미 처리된 신청입니다.')
        if b.slot_id!=slot.id:
            raise HTTPException(409,'일정이 변경됐습니다. 새로고침하세요.')
        session.refresh(slot)
        b.status='cancelled'
        region=Region(province=slot.province,district=slot.district)
        slot.state='open' if slot_future(slot) and owns_region(session,slot.caregiver_id,region) else 'closed'
        audit(session,user,'booking_'+body.action,b.id);session.commit()
        return {'id':b.id,'status':b.status}
