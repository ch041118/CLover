"""Optional Naver driving estimates; only coordinates/addresses leave the server."""
import json,math,time
from datetime import datetime
import httpx
from fastapi import Depends,HTTPException
from pydantic import Field
from sqlalchemy import select
from .schemas import StrictModel
from .models import RouteLocation,Booking,Availability
from .matching import KST
from .map_usage import MapUsage

class Point(StrictModel):
    longitude:float=Field(ge=-180,le=180,allow_inf_nan=False)
    latitude:float=Field(ge=-90,le=90,allow_inf_nan=False)
    consent:bool=False
    label:str=Field(default='',max_length=300)
    departure:str=Field(default='08:00',pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')

class Address(StrictModel):
    query:str=Field(min_length=2,max_length=200)
    consent:bool=False

class Routing:
    def __init__(self,settings,cipher,transport=None):
        self.settings=settings;self.cipher=cipher;self.transport=transport
        self.usage=MapUsage(settings,cipher)
    def context(self):return {'cache':{},'calls':0,'deadline':time.monotonic()+12}
    def get(self,path,params,ctx):
        if not self.settings.routing_enabled or not self.settings.naver_maps_key_id.get_secret_value() or not self.settings.naver_maps_key.get_secret_value():raise HTTPException(409,'네이버 지도 API 설정이 필요합니다.')
        return self.usage.run(path,params,lambda:self.fetch(path,params,ctx))
    def fetch(self,path,params,ctx):
        if ctx['calls']>=12 or time.monotonic()>ctx['deadline']:raise HTTPException(409,'경로 조회 한도에 도달했습니다. 후보를 좁혀 다시 확인하세요.')
        ctx['calls']+=1
        try:
            with httpx.Client(base_url='https://naveropenapi.apigw.ntruss.com',trust_env=False,follow_redirects=False,timeout=httpx.Timeout(2,connect=1),transport=self.transport) as client:
                with client.stream('GET',path,params=params,headers={'Accept':'application/json','x-ncp-apigw-api-key-id':self.settings.naver_maps_key_id.get_secret_value(),'x-ncp-apigw-api-key':self.settings.naver_maps_key.get_secret_value()}) as resp:
                    resp.raise_for_status();raw=bytearray()
                    for part in resp.iter_bytes():
                        raw.extend(part)
                        if len(raw)>1_000_000:raise ValueError()
            data=json.loads(raw)
            # Keep only validated data needed by this app, never route geometry or raw provider errors.
            if path=='/map-geocode/v2/geocode':
                if data.get('status','OK')!='OK':raise ValueError()
                rows=[]
                for x in data['addresses'][:5]:
                    point=Point(longitude=float(x['x']),latitude=float(x['y']),label=x.get('roadAddress') or x['jibunAddress'])
                    if not point.label.strip():raise ValueError()
                    rows.append({'roadAddress':point.label,'x':str(point.longitude),'y':str(point.latitude)})
                return {'addresses':rows}
            duration=data['route']['traoptimal'][0]['summary']['duration']
            if data['code']!=0 or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<0:raise ValueError()
            return {'code':0,'route':{'traoptimal':[{'summary':{'duration':duration}}]}}
        except (httpx.HTTPError,ValueError,TypeError,KeyError,IndexError,AttributeError):raise HTTPException(409,'지도 경로를 확인할 수 없습니다. 설정·응답을 확인하고 다시 시도하세요.') from None
    def point(self,session,uid):
        loc=session.get(RouteLocation,uid)
        if not loc or not loc.consent:raise HTTPException(409,'연결 당사자와 인접 방문 이용자의 위치·지도 전송 동의가 필요합니다.')
        return json.loads(self.cipher.decrypt(loc.encrypted_point.encode()))[:2],loc.departure
    def minutes(self,a,b,ctx):
        if a==b:return self.settings.travel_buffer_minutes
        key=(tuple(a),tuple(b))
        if key not in ctx['cache']:
            data=self.get('/map-direction/v1/driving',{'start':','.join(map(str,a)),'goal':','.join(map(str,b)),'option':'traoptimal'},ctx)
            try:
                if data['code']!=0:raise ValueError()
                seconds=data['route']['traoptimal'][0]['summary']['duration']/1000
                if not math.isfinite(seconds) or seconds<0:raise ValueError()
                ctx['cache'][key]=math.ceil(seconds/60)+self.settings.travel_buffer_minutes
            except (KeyError,IndexError,ValueError,TypeError):raise HTTPException(409,'이동 시간 응답을 확인할 수 없습니다.') from None
        return ctx['cache'][key]
    def check(self,session,slot,elder_id,exclude=None,ctx=None):
        if not self.settings.routing_enabled:return {'mode':'region_only','warning':'지도 연동 꺼짐 · 이동 시간 미검증'}
        if not self.settings.naver_maps_key_id.get_secret_value() or not self.settings.naver_maps_key.get_secret_value():raise HTTPException(409,'네이버 지도 API 설정이 필요합니다.')
        ctx=ctx or self.context();dest,_=self.point(session,elder_id)
        rows=session.execute(select(Booking,Availability).join(Availability).where(Availability.caregiver_id==slot.caregiver_id,
            Availability.day==slot.day,Booking.status.in_(('pending','offered','accepted','in_progress','completed','attention')))).all()
        rows=[(b,s) for b,s in rows if b.id!=exclude]
        if any(s.start<slot.end and s.end>slot.start for b,s in rows):raise HTTPException(409,'요양보호사의 다른 방문과 겹칩니다.')
        before=[(b,s) for b,s in rows if s.end<=slot.start];after=[(b,s) for b,s in rows if s.start>=slot.end]
        minutes=lambda value:int(value[:2])*60+int(value[3:])
        if before:
            b,prev=max(before,key=lambda r:r[1].end);origin,_=self.point(session,b.elder_id);depart=prev.end
        else:origin,depart=self.point(session,slot.caregiver_id)
        inbound=self.minutes(origin,dest,ctx)
        if minutes(depart)+inbound>minutes(slot.start):raise HTTPException(409,'이전 방문 또는 출발지에서 이동할 시간이 부족합니다.')
        outbound=0
        if after:
            b,nxt=min(after,key=lambda r:r[1].start);goal,_=self.point(session,b.elder_id);outbound=self.minutes(dest,goal,ctx)
            if minutes(slot.end)+outbound>minutes(nxt.start):raise HTTPException(409,'다음 방문까지 이동할 시간이 부족합니다.')
        return {'mode':'naver_driving','inbound_minutes':inbound,'outbound_minutes':outbound,
            'buffer_minutes':self.settings.travel_buffer_minutes,'warning':'조회 시점 자동차 예상값 · 미래 교통 예측 아님'}


def register_locations(app,db,role,audit,cipher):
    @app.get('/api/admin/maps-usage')
    def maps_usage(user=Depends(role('admin'))):
        return app.state.routing.usage.stats()

    @app.get('/api/location/status')
    def location_status(user=Depends(role('elder','caregiver'))):
        settings=app.state.routing.settings
        configured=bool(settings.routing_enabled and settings.naver_maps_key_id.get_secret_value() and settings.naver_maps_key.get_secret_value())
        return {'configured':configured}

    @app.get('/api/location')
    def get_location(user=Depends(role('elder','caregiver')),session=Depends(db)):
        loc=session.get(RouteLocation,user.id)
        if not loc:return None
        point=json.loads(cipher.decrypt(loc.encrypted_point.encode()))
        return {'longitude':point[0],'latitude':point[1],'consent':loc.consent,'departure':loc.departure,'label':point[2] if len(point)>2 else ''}
    @app.post('/api/location')
    def save(body:Point,user=Depends(role('elder','caregiver')),session=Depends(db)):
        from .coordination import lock_users
        lock_users(session,user.id);loc=session.get(RouteLocation,user.id);point=[body.longitude,body.latitude]
        if loc:
            old=json.loads(cipher.decrypt(loc.encrypted_point.encode()))
            q=select(Booking.id).join(Availability).where(Booking.status.in_(('pending','offered','accepted','in_progress','completed','attention')),Availability.day>=str(datetime.now(KST).date()))
            q=q.where(Booking.elder_id==user.id) if user.role=='elder' else q.where(Availability.caregiver_id==user.id)
            if (old[:2]!=point or loc.departure!=body.departure) and session.scalar(q):raise HTTPException(409,'진행할 일정이 있어 위치·출발 시간을 변경할 수 없습니다. 담당자에게 일정 재조율을 요청하세요.')
        else:loc=RouteLocation(owner_id=user.id);session.add(loc)
        loc.encrypted_point=cipher.encrypt(json.dumps(point+[body.label.strip()],ensure_ascii=False).encode()).decode();loc.consent=body.consent;loc.departure=body.departure
        audit(session,user,'location_save',user.id);session.commit();return {'status':'saved'}
    @app.post('/api/location/search')
    def search(body:Address,user=Depends(role('elder','caregiver')),session=Depends(db)):
        if not body.consent:raise HTTPException(422,'주소를 네이버 지도에 전송하는 데 동의해 주세요.')
        data=app.state.routing.get('/map-geocode/v2/geocode',{'query':' '.join(body.query.split())},app.state.routing.context())
        try:
            if data.get('status','OK')!='OK':raise ValueError()
            rows=[]
            for x in data['addresses'][:5]:
                point=Point(longitude=float(x['x']),latitude=float(x['y']),label=x.get('roadAddress') or x['jibunAddress'])
                if not point.label.strip():raise ValueError()
                rows.append({'label':point.label,'longitude':point.longitude,'latitude':point.latitude})
        except (KeyError,TypeError,ValueError):raise HTTPException(409,'주소 검색 응답을 확인할 수 없습니다.')
        audit(session,user,'location_search','naver');session.commit();return rows
