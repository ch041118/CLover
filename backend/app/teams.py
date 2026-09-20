from datetime import datetime
from fastapi import Depends,HTTPException,Query
from pydantic import Field
from sqlalchemy import select,or_,func
from .schemas import StrictModel
from .models import User,CaregiverTeam,Booking,Availability,Coordination,VisitRecord,ScheduleProposal,CareDecision
from .matching import KST

def require_team(session,caregiver_id,worker_id):
    link=session.get(CaregiverTeam,caregiver_id)
    if not link or link.worker_id!=worker_id: raise HTTPException(403,'담당 팀의 요양보호사에게만 제안할 수 있습니다.')
    worker=session.get(User,worker_id)
    if not worker or worker.status!='approved': raise HTTPException(409,'담당 사회복지사 계정 상태를 확인하세요.')

def managed(session,caregiver_id,worker_id):
    link=session.get(CaregiverTeam,caregiver_id)
    return bool(link and link.worker_id==worker_id)

class TeamChange(StrictModel):
    caregiver_id:str=Field(max_length=40)
    worker_id:str|None=Field(default=None,max_length=40)


def register_teams(app,db,role,audit,cipher):
    @app.get('/api/teams')
    def teams(user=Depends(role('admin','social_worker','caregiver')),session=Depends(db)):
        query=select(User,CaregiverTeam).outerjoin(CaregiverTeam,CaregiverTeam.caregiver_id==User.id).where(User.role=='caregiver')
        if user.role=='social_worker':query=query.where(CaregiverTeam.worker_id==user.id)
        if user.role=='caregiver':query=query.where(User.id==user.id)
        rows=[{'caregiver_id':u.id,'status':u.status,'worker_id':t.worker_id if t else None} for u,t in session.execute(query.order_by(User.id))]
        workers=[{'id':u.id} for u in session.scalars(select(User).where(User.role=='social_worker',User.status=='approved').order_by(User.id))] if user.role=='admin' else []
        return {'caregivers':rows,'workers':workers}

    @app.post('/api/admin/teams')
    def change(body:TeamChange,user=Depends(role('admin')),session=Depends(db)):
        from .coordination import lock_users
        lock_users(session,body.caregiver_id)
        cg=session.get(User,body.caregiver_id);worker=session.get(User,body.worker_id) if body.worker_id else None
        if not cg or cg.role!='caregiver' or (body.worker_id and (not worker or worker.role!='social_worker' or worker.status!='approved')):
            raise HTTPException(422,'요양보호사와 승인된 사회복지사를 선택하세요.')
        old=session.get(CaregiverTeam,cg.id)
        if old and old.worker_id==body.worker_id:return {'status':'unchanged'}
        active=session.scalar(select(Booking.id).join(Availability).where(Availability.caregiver_id==cg.id,
            Booking.status.in_(('pending','offered','accepted','in_progress'))))
        if active and old:raise HTTPException(409,'진행 중인 일정을 완료·취소한 후 담당자를 변경하세요.')
        if active and not old:
            mismatch=session.scalar(select(Coordination.booking_id).join(Booking).join(Availability).where(
                Availability.caregiver_id==cg.id,Booking.status.in_(('pending','offered','accepted','in_progress')),Coordination.worker_id!=body.worker_id))
            if mismatch:raise HTTPException(409,'기존 일정 담당자와 같은 사회복지사를 연결하세요.')
        if old:
            if body.worker_id:old.worker_id=body.worker_id
            else:session.delete(old)
        elif body.worker_id:session.add(CaregiverTeam(caregiver_id=cg.id,worker_id=body.worker_id))
        audit(session,user,'team_change',cg.id);session.commit();return {'status':'saved'}

    def history_query(user):
        q=select(Booking,Availability,Coordination).join(Availability).outerjoin(Coordination,Coordination.booking_id==Booking.id)
        if user.role=='social_worker':
            q=q.where(or_(Coordination.worker_id==user.id,Availability.caregiver_id.in_(select(CaregiverTeam.caregiver_id).where(CaregiverTeam.worker_id==user.id))))
        return q

    @app.get('/api/operations/history')
    def history(day_from:str=Query('',pattern=r'^$|^\d{4}-\d{2}-\d{2}$'),day_to:str=Query('',pattern=r'^$|^\d{4}-\d{2}-\d{2}$'),
                caregiver_id:str=Query('',max_length=40),status:str=Query('',max_length=20),offset:int=Query(0,ge=0),
                user=Depends(role('admin','social_worker')),session=Depends(db)):
        q=history_query(user)
        try:
            if day_from:datetime.strptime(day_from,'%Y-%m-%d')
            if day_to:datetime.strptime(day_to,'%Y-%m-%d')
        except ValueError:raise HTTPException(422,'날짜를 확인하세요.')
        if day_from and day_to and day_from>day_to:raise HTTPException(422,'기간을 확인하세요.')
        if day_from:q=q.where(Availability.day>=day_from)
        if day_to:q=q.where(Availability.day<=day_to)
        if caregiver_id:q=q.where(Availability.caregiver_id==caregiver_id)
        if status:q=q.where(Booking.status==status)
        base=q.subquery();counts=[{'status':s,'count':n} for s,n in session.execute(select(base.c.status,func.count()).group_by(base.c.status))]
        rows=[{'id':b.id,'elder_id':b.elder_id,'caregiver_id':slot.caregiver_id,'worker_id':co.worker_id if co else None,
            'day':slot.day,'start':slot.start,'end':slot.end,'category':b.category,'status':b.status} for b,slot,co in session.execute(q.order_by(Availability.day.desc(),Availability.start.desc(),Booking.id).offset(offset).limit(50))]
        audit(session,user,'history_list','operations');session.commit()
        return {'rows':rows,'counts':counts,'total':sum(x['count'] for x in counts)}

    @app.get('/api/operations/history/{bid}')
    def detail(bid:str,user=Depends(role('admin','social_worker')),session=Depends(db)):
        row=session.execute(history_query(user).where(Booking.id==bid)).first()
        if not row:raise HTTPException(404,'조회 가능한 기록이 없습니다.')
        b,slot,co=row;v=session.get(VisitRecord,bid);d=session.get(CareDecision,co.care_id) if co and co.care_id else None
        decrypt=lambda x:cipher.decrypt(x.encode()).decode() if x else None
        proposals=[{'stage':p.stage,'status':p.status,'caregiver_id':p.caregiver_id,'created_at':p.created_at,'reason':decrypt(p.encrypted_reason)} for p in session.scalars(select(ScheduleProposal).where(ScheduleProposal.booking_id==bid).order_by(ScheduleProposal.created_at))]
        result={'handoff':decrypt(d.encrypted_handoff) if d else None,'outcome':v.outcome if v else None,
            'report':decrypt(v.encrypted_note) if v else None,'recorded_at':v.recorded_at if v else None,'proposals':proposals}
        audit(session,user,'history_detail',bid);session.commit();return result
