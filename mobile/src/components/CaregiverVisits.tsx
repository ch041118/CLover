import React, { useEffect, useState } from 'react';
import { Text } from 'react-native';
import { ApiClient } from '../api';
import { Category, categories } from '../types';
import { Button, Card, Chips, Field, Notice, s, useTask } from '../ui';
import { states } from './WorkerConsole';
type Visit={id:string;day:string;start:string;end:string;elder_id:string;category:Category;province:string;district:string;status:string};
function VisitCard({api,row,reload}:{api:ApiClient;row:Visit;reload:()=>Promise<void>}){
  const [outcome,setOutcome]=useState(row.status==='in_progress'?'completed':'unable'),[note,setNote]=useState(''),[record,setRecord]=useState('');const task=useTask();
  return <Card><Text style={s.label}>{states[row.status]||row.status} · {categories[row.category]}</Text><Text style={s.body}>{row.day} {row.start}–{row.end}{'\n'}{row.elder_id} · {row.province} {row.district}</Text>
    {row.status==='pending'&&<Text style={s.body}>사회복지사가 일정을 조율 중입니다. 확정 후 직접 돌봄을 수행해 주세요.</Text>}
    {row.status==='accepted'&&<Button disabled={task.busy} title="방문 당일 · 돌봄 시작" onPress={()=>task.run(async()=>{await api.request(`/api/caregiver/visits/${row.id}/start`,{});await reload();})}/>}
    {['accepted','in_progress'].includes(row.status)&&<><Chips options={row.status==='in_progress'?{completed:'돌봄 완료',unable:'수행 어려움',concern:'특이사항 보고'}:{unable:'수행 어려움',concern:'특이사항 보고'}} value={outcome} select={setOutcome}/><Field label="수행 내용·담당자에게 전할 내용" value={note} onChange={setNote} multiline maxLength={1500}/><Button disabled={task.busy||!note.trim()||(outcome==='completed'&&row.status!=='in_progress')} title="사회복지사에게 수행 결과 남기기" onPress={()=>task.run(async()=>{await api.request(`/api/caregiver/visits/${row.id}/report`,{outcome,note});await reload();})}/></>}
    {['completed','attention'].includes(row.status)&&<Button secondary disabled={task.busy} title="내 수행 기록 보기" onPress={()=>task.run(async()=>{const r=await api.request<{note:string}>(`/api/visits/${row.id}/report`);setRecord(r.note);})}/>}
    {record&&<Text style={s.body}>{record}</Text>}<Notice text={task.message}/>
  </Card>;
}
export function CaregiverVisits({api}:{api:ApiClient}){
  const [rows,setRows]=useState<Visit[]>([]);const task=useTask();const load=async()=>setRows(await api.request('/api/bookings'));
  useEffect(()=>{task.run(load);},[api]);
  return <><Card><Text style={s.heading}>내가 수행할 돌봄</Text><Text style={s.body}>사회복지사가 배정·조율한 일정을 확인하고, 현장에서 수행한 내용과 특이사항을 기록하세요. 일정 변경은 사회복지사가 담당합니다.</Text><Button secondary disabled={task.busy} title="배정·수행 상태 새로고침" onPress={()=>task.run(load)}/><Notice text={task.message}/>{!rows.length&&<Text style={s.body}>아직 배정된 일정이 없습니다.</Text>}</Card>{rows.map(row=><VisitCard key={`${row.id}:${row.status}`} api={api} row={row} reload={load}/>)}</>;
}
