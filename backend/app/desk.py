"""Prepare once at intake, then support explicit human approval and selective handoff."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select, update, case, func
from .models import Care, CareDecision, ServiceRegion, Coordination, Booking, Availability
from .schemas import StrictModel, Review
from .privacy import minimize_local_note, SECRET, normalize
from .coordination import lock_users, repeat_counts

LABELS={'meal':'식사 도움','mobility':'이동 도움','housekeeping':'집안일 도움','companionship':'말벗','medication':'복약 도움','other':'생활 도움'}
RISK=('통증','다쳤','넘어','출혈','호흡','의식','죽고','자살','학대','폭력','약을','복약','어지','가슴','숨이','숨을')
SIMPLE={'meal_preparation','walk_companion','light_housework','shopping_help','conversation'}

def prepare_packet(note,features,result,prepared):
    clean=minimize_local_note(note)
    evidence=prepared.get('evidence') or []
    valid=bool(prepared.get('summary','').strip() and evidence and all(v.strip() and v in clean for v in evidence))
    valid=valid and not SECRET.search(normalize(prepared.get('summary','')))
    ai=result['source']=='local_model' and valid
    excerpts=evidence if ai else [clean[:180]]
    return {'source':'local_model' if ai else 'structured',
            'summary':prepared['summary'].strip() if ai else LABELS[features.category.value]+' 요청 · 원문을 확인해 주세요.',
            'evidence':excerpts,'suggested_urgency':result['urgency'],
            'handoff':LABELS[features.category.value]+' 요청입니다. 이용자 표현: '+ ' / '.join(excerpts)+
                '\n방문 시간과 구체적인 도움 범위는 담당자와 확인해 주세요.'}

def record_decision(session,row,user,urgency,method,handoff,ai,cipher):
    stored=json.loads(cipher.decrypt(row.encrypted_content.encode()))
    packet=stored.get('assistant',{})
    d=session.get(CareDecision,row.id)
    if not d:
        d=CareDecision(care_id=row.id,worker_id=user.id);session.add(d)
    d.worker_id=user.id;d.method=method;d.suggested_urgency=packet.get('suggested_urgency',row.urgency)
    d.final_urgency=urgency;d.ai_prepared=ai
    d.edited=urgency!=d.suggested_urgency or (handoff is not None and handoff!=packet.get('handoff'))
    d.encrypted_handoff=cipher.encrypt(handoff.encode()).decode() if handoff else None
    d.reviewed_at=datetime.now(timezone.utc)

class Item(StrictModel):
    care_id: str = Field(max_length=36)
    token: str = Field(max_length=64)
class Batch(StrictModel):
    items: list[Item] = Field(min_length=1,max_length=20)
class Decision(Review):
    token: str = Field(max_length=64)
    handoff: str = Field(min_length=1,max_length=1200)
    reviewed: bool = False


def register_desk(app,db,role,audit,cipher):
    def packet_data(session,row):
        stored=json.loads(cipher.decrypt(row.encrypted_content.encode()))
        from .schemas import Features
        packet=stored.get('assistant') or prepare_packet(stored['note'],Features.model_validate(stored['features']),
            {'source':row.source,'urgency':row.urgency},{})
        repeat=len(repeat_counts(session,row.owner_id,row.category))
        region=bool(session.scalar(select(ServiceRegion.id).where(ServiceRegion.owner_id==row.owner_id)))
        blockers=[]
        if row.urgency=='danger': blockers.append('긴급 요청 · 직접 확인')
        if row.urgency=='uncertain' or packet['source']!='local_model' or row.confidence<0.85: blockers.append('AI 정리 미완료 또는 불확실')
        if row.category in ('medication','other') or set(stored['features'].get('signals',[]))-SIMPLE or any(w in normalize(stored['note']) for w in RISK): blockers.append('건강·상담 또는 추가 확인 항목')
        if repeat>=3: blockers.append('최근 7일 같은 종류 3회 이상 · 반복 검토')
        if not region: blockers.append('이용자 지역 등록 필요')
        if not row.review_required: blockers.append('이미 검토 완료')
        token=hashlib.sha256(json.dumps([row.id,row.worker_id,row.urgency,row.review_required,repeat,region,packet],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return {'id':row.id,'elder_id':row.owner_id,'category':row.category,'urgency':row.urgency,
                'review_required':row.review_required,'created_at':row.created_at,'note':stored['note'],**packet,
                'blockers':blockers,'lane':'intervention' if blockers else 'ready','repeat_count':repeat,
                'checks':['희망 날짜·시간 확인','구체적 도움 범위 확인','전달할 개인정보 최소화'], 'token':token}

    @app.post('/api/worker/desk/claim')
    def claim_batch(user=Depends(role('social_worker')),session=Depends(db)):
        ids=session.scalars(select(Care.id).where(Care.worker_id.is_(None)).order_by(
            case((Care.urgency=='danger',0),(Care.urgency=='uncertain',1),else_=2),Care.created_at).limit(20)).all()
        claimed=0
        for cid in ids:
            changed=session.execute(update(Care).where(Care.id==cid,Care.worker_id.is_(None)).values(worker_id=user.id)).rowcount
            if changed: claimed+=1;audit(session,user,'desk_claim',cid)
        session.commit();return {'claimed':claimed}

    @app.get('/api/worker/desk')
    def desk(offset:int=Query(0,ge=0),user=Depends(role('social_worker')),session=Depends(db)):
        rows=session.scalars(select(Care).where(Care.worker_id==user.id,Care.review_required.is_(True)).order_by(
            case((Care.urgency=='danger',0),(Care.urgency=='uncertain',1),else_=2),Care.created_at).offset(offset).limit(50)).all()
        items=[packet_data(session,row) for row in rows]
        audit(session,user,'desk_read','assigned');session.commit()
        return items

    def approve(session,row,user,data,urgency,handoff,method):
        if SECRET.search(normalize(handoff)) or not handoff.strip(): raise HTTPException(422,'전달 내용을 확인하세요.')
        record_decision(session,row,user,urgency,method,handoff,data['source']=='local_model',cipher)
        row.urgency=urgency;row.review_required=False;row.source='human_review'
        audit(session,user,'desk_'+method,row.id)

    @app.post('/api/worker/desk/approve-batch')
    def batch(body:Batch,user=Depends(role('social_worker')),session=Depends(db)):
        if len({i.care_id for i in body.items})!=len(body.items): raise HTTPException(422,'중복 선택입니다.')
        rows=[session.get(Care,i.care_id) for i in body.items]
        if any(not r or r.worker_id!=user.id for r in rows): raise HTTPException(404,'담당 요청을 확인하세요.')
        lock_users(session,*(r.owner_id for r in rows))
        checked=[]
        for item,row in zip(body.items,rows):
            session.refresh(row);data=packet_data(session,row)
            if row.worker_id!=user.id or data['token']!=item.token or data['lane']!='ready':
                raise HTTPException(409,'상태가 바뀌었거나 개별 확인이 필요한 건입니다. 새로고침하세요.')
            checked.append((row,data))
        for row,data in checked: approve(session,row,user,data,row.urgency,data['handoff'],'batch')
        session.commit();return {'approved':len(checked)}

    @app.post('/api/worker/desk/{cid}/approve')
    def single(cid:str,body:Decision,user=Depends(role('social_worker')),session=Depends(db)):
        row=session.get(Care,cid)
        if not row or row.worker_id!=user.id: raise HTTPException(404,'담당 요청을 확인하세요.')
        lock_users(session,row.owner_id);session.refresh(row);data=packet_data(session,row)
        if row.worker_id!=user.id or data['token']!=body.token or not row.review_required: raise HTTPException(409,'상태가 바뀌었습니다. 새로고침하세요.')
        if not body.reviewed: raise HTTPException(422,'원문과 전달문을 확인해 주세요.')
        approve(session,row,user,data,body.urgency,body.handoff.strip(),'single');session.commit()
        return {'status':'reviewed'}

    @app.get('/api/worker/desk/metrics')
    def metrics(user=Depends(role('social_worker')),session=Depends(db)):
        rows=session.scalars(select(CareDecision).where(CareDecision.worker_id==user.id,
            CareDecision.reviewed_at>=datetime.now(timezone.utc)-timedelta(days=30))).all()
        return {'days':30,'reviewed':len(rows),'ai_prepared':sum(r.ai_prepared for r in rows),
                'unchanged':sum(r.ai_prepared and not r.edited for r in rows),
                'edited':sum(r.ai_prepared and r.edited for r in rows),'batch':sum(r.method=='batch' for r in rows)}

    @app.get('/api/caregiver/visits/{bid}/handoff')
    def handoff(bid:str,user=Depends(role('caregiver')),session=Depends(db)):
        b=session.get(Booking,bid);slot=session.get(Availability,b.slot_id) if b else None
        if not b or slot.caregiver_id!=user.id or b.status not in ('offered','accepted','in_progress','completed','attention'):
            raise HTTPException(404,'연결된 일정을 확인하세요.')
        lock_users(session,b.elder_id,user.id);session.refresh(b)
        if b.slot_id!=slot.id or b.status not in ('offered','accepted','in_progress','completed','attention'): raise HTTPException(409,'일정이 변경됐습니다.')
        coord=session.get(Coordination,bid);d=session.get(CareDecision,coord.care_id) if coord and coord.care_id else None
        audit(session,user,'handoff_read',bid);session.commit()
        return {'handoff':cipher.decrypt(d.encrypted_handoff.encode()).decode() if d and d.encrypted_handoff else None}
