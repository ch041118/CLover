import React, { useEffect, useState } from 'react';
import { Text } from 'react-native';
import { ApiClient } from '../api';
import { Category, categories } from '../types';
import { Button, Card, Chips, Field, Notice, s, useTask } from '../ui';
import { states, stages } from './WorkerConsole';
type Visit={id:string;day:string;start:string;end:string;elder_id:string;category:Category;province:string;district:string;status:string;proposal_id?:string;stage?:string;reason?:string};
function VisitCard({api,row,reload}:{api:ApiClient;row:Visit;reload:()=>Promise<void>}){
  const [reason,setReason]=useState('');
  const [outcome,setOutcome]=useState(row.status==='in_progress'?'completed':'unable'),[note,setNote]=useState(''),[record,setRecord]=useState(''),[handoff,setHandoff]=useState('');const task=useTask();
  return <Card><Text style={s.label}>{states[row.status]||row.status} · {categories[row.category]}</Text><Text style={s.body}>{row.day} {row.start}–{row.end}{'\n'}{row.elder_id} · {row.province} {row.district}</Text>
    {row.stage&&<Text style={s.label}>{stages[row.stage]||'자동 배정'}</Text>}
    {row.reason&&<Text style={s.body}>거절 사유: {row.reason}</Text>}
    {row.proposal_id&&['offered','accepted'].includes(row.status)&&<>
      {row.status==='offered'&&<Button disabled={task.busy} title="이 일정 수락" onPress={()=>task.run(async()=>{await api.request(`/api/caregiver/proposals/${row.proposal_id}/decision`,{action:'accept'});await reload();})}/>}
      <Field label="일정이 어려운 이유" value={reason} onChange={setReason} multiline maxLength={1500}/>
      <Button secondary disabled={task.busy||!reason.trim()} title={row.status==='accepted'?'수락 철회 · 재조율 요청':'일정 거절 · 재조율 요청'} onPress={()=>task.run(async()=>{await api.request(`/api/caregiver/proposals/${row.proposal_id}/decision`,{action:'decline',reason});await reload();})}/>
    </>}
    {['offered','accepted','in_progress','completed','attention'].includes(row.status)&&<Button secondary disabled={task.busy} title="방문 주소·돌봄 내용 확인" onPress={()=>task.run(async()=>{const r=await api.request<{name:string;address:string;note:string;prepared_by:string}>(`/api/flow/visits/${row.id}`);setHandoff(`${r.name} · ${r.address}\n${r.prepared_by}\n${r.note}`);})}/>}
    {handoff&&<Text style={s.body}>{handoff}</Text>}
    {row.status==='pending' &&<Text style={s.body}>사회복지사가 일정을 조율 중입니다. 확정 후 직접 돌봄을 수행해 주세요.</Text>}
    {row.status==='accepted'&&<Button disabled={task.busy} title="방문 당일 · 돌봄 시작" onPress={()=>task.run(async()=>{await api.request(`/api/caregiver/visits/${row.id}/start`,{});await reload();})}/>}
    {['accepted','in_progress'].includes(row.status)&&<><Chips options={row.status==='in_progress'?{completed:'돌봄 완료',unable:'수행 어려움',concern:'특이사항 보고'}:{unable:'수행 어려움',concern:'특이사항 보고'}} value={outcome} select={setOutcome}/><Field label="수행 내용·담당자에게 전할 내용" value={note} onChange={setNote} multiline maxLength={1500}/><Button disabled={task.busy||!note.trim()||(outcome==='completed'&&row.status!=='in_progress')} title="사회복지사에게 수행 결과 남기기" onPress={()=>task.run(async()=>{await api.request(`/api/caregiver/visits/${row.id}/report`,{outcome,note});await reload();})}/></>}
    {['completed','attention'].includes(row.status)&&<Button secondary disabled={task.busy} title="내 수행 기록 보기" onPress={()=>task.run(async()=>{const r=await api.request<{note:string}>(`/api/visits/${row.id}/report`);setRecord(r.note);})}/>}
    {record&&<Text style={s.body}>{record}</Text>}<Notice text={task.message}/>
  </Card>;
}
export function CaregiverVisits({api}:{api:ApiClient}){
  const [rows,setRows]=useState<Visit[]>([]);const task=useTask();const load=async()=>{const [bookings,proposals]=await Promise.all([api.request<Visit[]>('/api/bookings'),api.request<Visit[]>('/api/caregiver/proposals')]);const latest=new Map<string,Visit>();for(const p of proposals){if(!latest.has(p.id))latest.set(p.id,p);}setRows([...bookings.map(b=>({...b,...latest.get(b.id)})),...Array.from(latest.values()).filter(p=>!bookings.some(b=>b.id===p.id))]);};
  useEffect(()=>{task.run(load);},[api]);
  return <><Card><Text style={s.heading}>내가 수행할 돌봄</Text><Text style={s.body}>사전 동의한 일반 일정은 자동 확정됩니다. 사회복지사가 조율한 제안은 수락 후 확정됩니다. 수행이 어려우면 사유를 남겨 재조율을 요청하세요.</Text><Button secondary disabled={task.busy} title="배정·수행 상태 새로고침" onPress={()=>task.run(load)}/><Notice text={task.message}/>{!rows.length&&<Text style={s.body}>아직 배정된 일정이 없습니다.</Text>}</Card>{rows.map(row=><VisitCard key={`${row.id}:${row.status}`} api={api} row={row} reload={load}/>)}</>;
}
