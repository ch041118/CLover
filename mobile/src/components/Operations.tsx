import React,{useEffect,useState} from 'react';
import {Switch,Text,View} from 'react-native';
import {ApiClient} from '../api';
import {Button,Card,Chips,Field,Notice,s,useTask} from '../ui';
import {states,stages} from './WorkerConsole';
import {categories,Category} from '../types';
type Team={caregivers:{caregiver_id:string;worker_id:string|null;status:string}[];workers:{id:string}[]};
export function Teams({api,admin=false}:{api:ApiClient;admin?:boolean}){
 const [data,setData]=useState<Team>({caregivers:[],workers:[]}),[cg,setCg]=useState(''),[worker,setWorker]=useState('');const task=useTask();
 const load=async()=>setData(await api.request('/api/teams'));useEffect(()=>{task.run(load);},[api]);
 return <Card><Text style={s.heading}>{admin?'요양보호사 담당 연결':'담당 사회복지사와 요양보호사'}</Text><Text style={s.body}>사회복지사 한 명이 여러 요양보호사를 관리합니다. 요양보호사의 담당 사회복지사는 한 명입니다.</Text>
 <Button secondary title="연결 상태 새로고침" disabled={task.busy} onPress={()=>task.run(load)}/>
 {data.caregivers.map(x=><Text key={x.caregiver_id} style={s.body}>{x.caregiver_id} → {x.worker_id||'미연결'} · {x.status}</Text>)}
 {admin&&<><Text style={s.label}>요양보호사 선택</Text>{data.caregivers.map(x=><Button key={x.caregiver_id} secondary={cg!==x.caregiver_id} title={x.caregiver_id} onPress={()=>{setCg(x.caregiver_id);setWorker(x.worker_id||'');}}/>)}
 <Text style={s.label}>사회복지사 선택</Text>{data.workers.map(x=><Button key={x.id} secondary={worker!==x.id} title={x.id} onPress={()=>setWorker(x.id)}/>)}
 <Button disabled={!cg||!worker||task.busy} title="담당 연결 저장" onPress={()=>task.run(async()=>{await api.request('/api/admin/teams',{caregiver_id:cg,worker_id:worker});await load();task.setMessage('저장했습니다.');})}/>
 <Button secondary disabled={!cg||task.busy} title="선택한 요양보호사 연결 해제" onPress={()=>task.run(async()=>{await api.request('/api/admin/teams',{caregiver_id:cg,worker_id:null});await load();})}/><Text style={s.caption}>진행 중인 일정이 있으면 먼저 완료·취소한 뒤 담당자를 변경하세요.</Text></>}
 <Notice text={task.message}/></Card>;
}
type Point={longitude:number;latitude:number;consent:boolean;departure:string};
export function LocationSettings({api,caregiver}:{api:ApiClient;caregiver:boolean}){
 const [query,setQuery]=useState(''),[consent,setConsent]=useState(false),[lng,setLng]=useState(''),[lat,setLat]=useState(''),[departure,setDeparture]=useState('08:00'),[results,setResults]=useState<(Point&{label:string})[]>([]);const task=useTask();
 useEffect(()=>{task.run(async()=>{const p=await api.request<Point|null>('/api/location');if(p){setLng(String(p.longitude));setLat(String(p.latitude));setConsent(p.consent);setDeparture(p.departure);}});},[api]);
 return <Card><Text style={s.heading}>{caregiver?'이동 출발지 설정':'돌봄 방문지 설정'}</Text><Text style={s.body}>주소 검색은 네이버 지도에 주소를, 이동 시간 계산은 관련 출발·도착 좌표를 전송합니다. 상담·건강 기록은 보내지 않습니다. 현재 자동차 이동만 지원합니다.</Text>
 <View style={s.switchRow}><Switch value={consent} onValueChange={setConsent} accessibilityLabel="네이버 지도 위치 전송 동의"/><Text style={[s.body,{flex:1}]}>주소·좌표를 지도 서비스로 전송하는 데 동의합니다.</Text></View>
 <Field label="도로명 주소 · 동호수 제외" value={query} onChange={setQuery} maxLength={200}/><Button disabled={!consent||query.trim().length<2||task.busy} title="주소로 위치 찾기" onPress={()=>task.run(async()=>{const r=await api.request<typeof results>('/api/location/search',{query,consent});setResults(r);if(!r.length)task.setMessage('검색된 주소가 없습니다.');})}/>
 {results.map((x,i)=><Button secondary key={i} title={x.label} onPress={()=>{setLng(String(x.longitude));setLat(String(x.latitude));setResults([]);}}/>)}
 <Field label="경도" value={lng} onChange={setLng} maxLength={20}/><Field label="위도" value={lat} onChange={setLat} maxLength={20}/>
 {caregiver&&<Field label="매일 출발 가능한 시각 (HH:MM)" value={departure} onChange={setDeparture} maxLength={5}/>}
 <Button disabled={!lng.trim()||!lat.trim()||!Number.isFinite(Number(lng))||!Number.isFinite(Number(lat))||task.busy} title="위치·동의 설정 저장" onPress={()=>task.run(async()=>{await api.request('/api/location',{longitude:Number(lng),latitude:Number(lat),departure,consent});task.setMessage('저장했습니다. 지역 등록과 근무 가능 시간도 확인해 주세요.');})}/>
 <Notice text={task.message}/></Card>;
}
type RecordRow={id:string;elder_id:string;caregiver_id:string;worker_id:string|null;day:string;start:string;end:string;category:Category;status:string};
type Detail={handoff:string|null;outcome:string|null;report:string|null;recorded_at:string|null;proposals:{stage:string;status:string;caregiver_id:string;created_at:string;reason:string|null}[]};
export function OperationHistory({api}:{api:ApiClient}){
 const [data,setData]=useState<{rows:RecordRow[];counts:{status:string;count:number}[];total:number}>({rows:[],counts:[],total:0}),[from,setFrom]=useState(''),[to,setTo]=useState(''),[cg,setCg]=useState(''),[status,setStatus]=useState(''),[offset,setOffset]=useState(0),[detail,setDetail]=useState<Detail|null>(null),[selected,setSelected]=useState('');const task=useTask();
 const load=async(page=offset)=>{const q=`day_from=${encodeURIComponent(from)}&day_to=${encodeURIComponent(to)}&caregiver_id=${encodeURIComponent(cg)}&status=${encodeURIComponent(status)}&offset=${page}`;setData(await api.request('/api/operations/history?'+q));setOffset(page);setDetail(null);};
 useEffect(()=>{task.run(()=>load(0));},[api]);
 return <><Card><Text style={s.heading}>돌봄 처리 이력</Text><Text style={s.body}>관리자는 기관 전체, 사회복지사는 담당 팀 또는 자신이 조율한 일정을 조회합니다. 건수는 방문일 기준이며 목록 밖의 기록도 집계합니다.</Text>
 <Field label="방문 시작일 (선택 · YYYY-MM-DD)" value={from} onChange={setFrom}/><Field label="방문 종료일 (선택 · YYYY-MM-DD)" value={to} onChange={setTo}/><Field label="요양보호사 아이디 (선택)" value={cg} onChange={setCg}/>
 <Chips options={{'':'모든 상태',completed:'완료',attention:'특이사항',declined:'거절',accepted:'확정',cancelled:'취소'}} value={status} select={setStatus}/>
 <Button disabled={task.busy} title="조건으로 조회" onPress={()=>task.run(()=>load(0))}/><Text style={s.label}>총 {data.total}건</Text>{data.counts.map(x=><Text key={x.status} style={s.body}>{states[x.status]||x.status} {x.count}건</Text>)}<Button secondary disabled={!offset||task.busy} title="이전 50건" onPress={()=>task.run(()=>load(Math.max(0,offset-50)))}/><Button secondary disabled={offset+50>=data.total||task.busy} title="다음 50건" onPress={()=>task.run(()=>load(offset+50))}/><Notice text={task.message}/></Card>
 {data.rows.map(row=><Card key={row.id}><Text style={s.label}>{row.day} {row.start}–{row.end} · {states[row.status]}</Text><Text style={s.body}>{row.elder_id} ↔ {row.caregiver_id} · {categories[row.category]}{'\n'}조율 담당 {row.worker_id||'미지정'}</Text><Button secondary disabled={task.busy} title="전달문·수행 기록·제안 이력" onPress={()=>task.run(async()=>{setDetail(null);setSelected(row.id);setDetail(await api.request('/api/operations/history/'+row.id));})}/>
 {selected===row.id&&detail&&<><Text style={s.label}>승인 전달문</Text><Text style={s.body}>{detail.handoff||'기록 없음'}</Text><Text style={s.label}>수행 결과</Text><Text style={s.body}>{detail.outcome||'아직 보고 없음'} · {detail.recorded_at||''}{'\n'}{detail.report}</Text>{detail.proposals.map((p,i)=><Text key={i} style={s.body}>{stages[p.stage]} · {states[p.status]||p.status} · {p.caregiver_id}{'\n'}{p.created_at}{p.reason?' · '+p.reason:''}</Text>)}</>}</Card>)}</>;
}
