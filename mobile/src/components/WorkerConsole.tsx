import React, { useEffect, useState } from 'react';
import { Alert, Switch, Text, View } from 'react-native';
import { ApiClient } from '../api';
import { Category, categories, urgencies } from '../types';
import { Button, Card, Chips, Field, Notice, s, useTask } from '../ui';

type Slot={slot_id:string;caregiver_id:string;day:string;start:string;end:string;province:string;district:string};
type Schedule=Slot&{id:string;elder_id:string;category:Category;status:string;worker_id:string|null;care_id:string|null;outcome:string|null;stage?:string;reason?:string};
export const states:Record<string,string>={offered:'요양보호사 수락 대기',withdrawn:'이전 제안 철회',pending:'조율 대기',accepted:'배정 확정',in_progress:'돌봄 진행',completed:'완료',attention:'특이사항 확인 필요',cancelled:'취소',declined:'거절 · 재조율 필요'};
export const stages:Record<string,string>={initial:'1차 · 자동 일정 제안',remaining:'2차 · 빈 시간 조율',urgent:'3차 · 긴급 일정 제안'};
function SlotLabel(slot:Slot){return `${slot.day} ${slot.start}–${slot.end} · ${slot.caregiver_id} · ${slot.province} ${slot.district}`;}
function ContactCheck({value,onChange}:{value:boolean;onChange:(v:boolean)=>void}){return <View style={s.switchRow}><Switch accessibilityLabel="당사자와 일정 확인 완료" value={value} onValueChange={onChange}/><Text style={[s.body,{flex:1}]}>이용자에게 필요한 돌봄 시간과 내용을 확인했습니다. 요양보호사는 제안을 받은 후 수락합니다.</Text></View>;}

export function RequestScheduler({api,careId,reviewRequired}:{api:ApiClient;careId:string;reviewRequired:boolean}){
  const [slots,setSlots]=useState<Slot[]>([]),[selected,setSelected]=useState(''),[confirmed,setConfirmed]=useState(false),[loaded,setLoaded]=useState(false);const task=useTask();
  return <View style={{gap:12}}><Text style={s.heading}>2·3차 일정 제안</Text><Text style={s.body}>일반 요청은 2차 빈 시간 조율, 긴급 분류 요청은 3차 긴급 제안으로 전달됩니다. 모든 일정은 요양보호사가 수락해야 확정됩니다.</Text>
    <Button secondary disabled={task.busy||reviewRequired} title="가능한 요양보호사 일정 찾기" onPress={()=>task.run(async()=>{setSlots(await api.request(`/api/worker/care/${careId}/slots`));setLoaded(true);})}/>
    {loaded&&!slots.length&&<Text style={s.body}>등록된 이용자 지역과 일치하는 일정이 없습니다. 이용자 지역과 요양보호사 근무 일정을 먼저 등록해 주세요.</Text>}
    {slots.map(slot=><Button key={slot.slot_id} secondary={selected!==slot.slot_id} title={SlotLabel(slot)} onPress={()=>{setSelected(slot.slot_id);setConfirmed(false);}}/>)}
    {selected&&<><ContactCheck value={confirmed} onChange={setConfirmed}/><Button disabled={task.busy||!confirmed||reviewRequired} title="요양보호사에게 일정 제안" onPress={()=>task.run(async()=>{await api.request('/api/worker/assign',{care_id:careId,slot_id:selected,contact_confirmed:confirmed});setSlots([]);setSelected('');task.setMessage('제안했습니다. 요양보호사 수락 후 확정됩니다.');})}/></>}
    <Notice text={task.message}/>
  </View>;
}

export function WorkerStatistics({api}:{api:ApiClient}){
  const [days,setDays]=useState('7'),[data,setData]=useState<any>(null);const task=useTask();
  useEffect(()=>{task.run(async()=>setData(await api.request(`/api/worker/statistics?days=${days}`)));},[api,days]);
  return <Card><Text style={s.heading}>요청 현황</Text><Text style={s.body}>기관 전체 접수 건수입니다. 선택한 종류와 현재 위험도 분류를 함께 보여줍니다.</Text><Chips options={{'7':'최근 7일','30':'최근 30일','90':'최근 90일'}} value={days} select={setDays}/>
    <Button secondary disabled={task.busy} title="현황 새로고침" onPress={()=>task.run(async()=>setData(await api.request(`/api/worker/statistics?days=${days}`)))}/>
    {data&&<><Text style={s.heading}>최근 {data.days}일 · 총 {data.total}건</Text><Text style={s.body}>검토 대기 {data.review_pending} · 검토 완료 {data.reviewed}{'\n'}담당 미배정 {data.unassigned} · 담당 배정 {data.assigned}</Text>
      {(Object.keys(categories) as Category[]).map(category=>{const rows=data.matrix.filter((r:any)=>r.category===category);return <View key={category} style={{gap:4}}><Text style={s.label}>{categories[category]} · {rows.reduce((n:number,r:any)=>n+r.count,0)}건</Text><Text style={s.body}>{Object.entries(urgencies).map(([key,label])=>`${label} ${rows.find((r:any)=>r.urgency===key)?.count||0}`).join(' / ')}</Text></View>;})}
      <Text style={s.label}>같은 기간 신청된 돌봄 일정</Text>{data.bookings.map((b:any)=><Text key={b.status} style={s.body}>{states[b.status]||b.status} · {b.count}건</Text>)}
      <Text style={s.caption}>요청 검토 완료와 실제 돌봄 완료는 다릅니다. 건수는 접수 시각 기준이며, 위험도는 현재 분류입니다.</Text></>}
    <Notice text={task.message}/>
  </Card>;
}
function ScheduleCard({api,row,userId,onChanged}:{api:ApiClient;row:Schedule;userId:string;onChanged:()=>Promise<void>}){
  const [confirmed,setConfirmed]=useState(false),[slots,setSlots]=useState<Slot[]>([]),[target,setTarget]=useState(''),[report,setReport]=useState('');const task=useTask();
  return <Card><Text style={s.label}>{states[row.status]||row.status} · {categories[row.category]}</Text><Text style={s.body}>{row.elder_id} → {row.caregiver_id}{'\n'}{row.day} {row.start}–{row.end}{'\n'}{row.province} {row.district}{'\n'}관리 담당: {row.worker_id||'미배정'}</Text>{row.stage&&<Text style={s.label}>{stages[row.stage]}</Text>}{row.reason&&<Text style={s.body}>거절 사유: {row.reason}</Text>}
    {!row.worker_id&&<Button disabled={task.busy} title="이 일정 관리 맡기" onPress={()=>task.run(async()=>{await api.request(`/api/worker/schedules/${row.id}/claim`,{});await onChanged();})}/>}
    {row.worker_id===userId&&<>
      {row.status==='pending'&&<><ContactCheck value={confirmed} onChange={setConfirmed}/><Button disabled={task.busy||!confirmed} title="조율 완료 · 수락 요청" onPress={()=>task.run(async()=>{await api.request(`/api/worker/schedules/${row.id}/confirm`,{contact_confirmed:confirmed});await onChanged();})}/></>}
      {['pending','offered','accepted','declined'].includes(row.status)&&<><Button secondary disabled={task.busy} title="변경 가능한 일정 보기" onPress={()=>task.run(async()=>{const all=await api.request<Slot[]>('/api/worker/open-slots');setSlots(all.filter(x=>x.province===row.province&&x.district===row.district));setTarget('');setConfirmed(false);if(!all.length)task.setMessage('근무 가능 일정이 없습니다.');})}/>
      {slots.map(slot=><Button key={slot.slot_id} secondary={target!==slot.slot_id} title={SlotLabel(slot)} onPress={()=>{setTarget(slot.slot_id);setConfirmed(false);}}/>)}
      {target&&<><ContactCheck value={confirmed} onChange={setConfirmed}/><Button disabled={task.busy||!confirmed} title="변경 일정 다시 제안" onPress={()=>task.run(async()=>{await api.request(`/api/worker/schedules/${row.id}/reschedule`,{slot_id:target,contact_confirmed:confirmed});setSlots([]);setTarget('');await onChanged();})}/></>}
      <Button secondary disabled={task.busy} title="이 일정 취소" onPress={()=>Alert.alert('일정을 취소할까요?','이용자와 요양보호사의 일정에도 취소로 표시됩니다.',[{text:'유지',style:'cancel'},{text:'취소 확정',style:'destructive',onPress:()=>task.run(async()=>{await api.request(`/api/worker/schedules/${row.id}/cancel`,{});await onChanged();})}])}/></>}
      {['completed','attention'].includes(row.status)&&<Button secondary disabled={task.busy} title="요양보호사 수행 기록 확인" onPress={()=>task.run(async()=>{const r=await api.request<{note:string}>(`/api/visits/${row.id}/report`);setReport(r.note);})}/>}
      {report&&<Text style={s.body}>{report}</Text>}
    </>}
    <Notice text={task.message}/>
  </Card>;
}
export function WorkerSchedules({api,userId}:{api:ApiClient;userId:string}){
  const [rows,setRows]=useState<Schedule[]>([]),[offset,setOffset]=useState(0);const task=useTask();
  const load=async()=>setRows(await api.request(`/api/worker/schedules?offset=${offset}`));
  useEffect(()=>{task.run(load);},[api,offset]);
  return <><Card><Text style={s.heading}>돌봄 일정 조율·관리</Text><Text style={s.body}>1차: 스케줄러 자동 제안 → 2차: 사회복지사가 남은 시간 조율 → 3차: 긴급 일정 제안. ‘요청 검토’에서 일반·긴급 요청을 연결하세요. 거절된 건은 사유를 확인하고 다른 일정을 다시 제안합니다.</Text><Button disabled={task.busy} title="1차 · 향후 7일 자동 제안 실행" onPress={()=>task.run(async()=>{const r=await api.request<{offered:string[];skipped:{care_id:string;reason:string}[]}>('/api/worker/scheduler/run',{});await load();task.setMessage(`제안 ${r.offered.length}건 / 미연결 ${r.skipped.length}건`+r.skipped.map(x=>`\n${x.care_id}: ${x.reason}`).join(''));})}/><Text style={s.caption}>내가 검토한 미연결 일반 요청을 접수순으로 최대 100건 처리합니다. 지역이 같은 가장 이른 빈 시간에 제안하며, 거절된 건은 자동 재제안하지 않습니다.</Text><Button secondary disabled={task.busy} title="새로고침" onPress={()=>task.run(load)}/><Text style={s.caption}>{offset+1}번부터 최대 100건 · 특이사항 확인 필요 건은 수행 기록을 확인하고 후속 조치를 조율하세요.</Text><Button secondary disabled={!offset||task.busy} title="이전 목록" onPress={()=>setOffset(Math.max(0,offset-100))}/><Button secondary disabled={rows.length<100||task.busy} title="다음 목록" onPress={()=>setOffset(offset+100)}/><Notice text={task.message}/></Card>{rows.map(row=><ScheduleCard key={`${row.id}:${row.status}:${row.slot_id}:${row.worker_id}`} api={api} row={row} userId={userId} onChanged={load}/>)}</>;
}

type Repeat={id:string;elder_id:string;category:Category;worker_id:string|null;state:string;count_7d:number;new_count:number;danger_count:number;followup_day:string|null;due:boolean;auto_route:boolean;decision_note:string|null};
function RepeatCard({api,row,userId,onChanged}:{api:ApiClient;row:Repeat;userId:string;onChanged:()=>Promise<void>}){
  const [decision,setDecision]=useState('monitor'),[note,setNote]=useState(''),[date,setDate]=useState(new Date(Date.now()+86400000+9*3600000).toISOString().slice(0,10)),[route,setRoute]=useState(row.auto_route);const task=useTask();
  const names:Record<string,string>={open:'개입 검토 필요',monitoring:'경과 확인',planning:'정기 돌봄 계획 검토',closed:'검토 종료'};
  return <Card><Text style={s.label}>{row.due?'오늘 확인 필요 · ':''}{names[row.state]}</Text><Text style={s.body}>{row.elder_id} · {categories[row.category]}{'\n'}최근 7일 {row.count_7d}건 / 지난 검토 이후 7일 내 {row.new_count}건{'\n'}긴급 분류 {row.danger_count}건{row.followup_day?` / 다음 확인 ${row.followup_day}`:''}</Text>
    {row.decision_note&&<Text style={s.caption}>이전 조치: {row.decision_note}</Text>}
    {!row.worker_id&&<Button disabled={task.busy} title="반복 요청 묶음 담당하기" onPress={()=>task.run(async()=>{await api.request(`/api/worker/repeats/${row.id}/claim`,{});await onChanged();})}/>}
    {row.worker_id===userId&&<><Text style={s.body}>개별 원문은 ‘요청 검토’에서 확인하세요. 상담 결과와 다음 조치를 남기면 새 요청을 구분해 모아드립니다.</Text><Chips options={{monitor:'경과 확인',plan:'정기 돌봄 검토',close:'검토 종료'}} value={decision} select={setDecision}/><Field label="상담·조치 내용" value={note} onChange={setNote} multiline maxLength={1500}/>{decision!=='close'&&<><Field label="다음 확인 날짜 (YYYY-MM-DD)" value={date} onChange={setDate} maxLength={10}/><View style={s.switchRow}><Switch accessibilityLabel="동일 종류 요청을 나에게 자동 배정" value={route} onValueChange={setRoute}/><Text style={[s.body,{flex:1}]}>이 어르신의 같은 종류 새 요청을 나에게 자동 배정</Text></View></>}
      <Button disabled={task.busy||!note.trim()} title="사람의 검토 결과 저장" onPress={()=>task.run(async()=>{await api.request(`/api/worker/repeats/${row.id}/decision`,{decision,note,followup_day:decision==='close'?null:date,auto_route:route});await onChanged();setNote('');task.setMessage('저장했습니다. 일정은 자동 확정되지 않습니다.');})}/></>}
    <Notice text={task.message}/>
  </Card>;
}
export function RepeatInbox({api,userId}:{api:ApiClient;userId:string}){
  const [rows,setRows]=useState<Repeat[]>([]);const task=useTask();const load=async()=>setRows(await api.request('/api/worker/repeats'));
  useEffect(()=>{task.run(load);},[api]);
  return <><Card><Text style={s.heading}>반복 요청 · 사람이 개입할 지점</Text><Text style={s.body}>같은 어르신·같은 종류 요청이 7일 안에 3회 이상이면 자동으로 묶습니다. 같은 문장이라는 뜻은 아니므로 개별 내용을 확인하세요.</Text><Text style={s.caption}>자동: 묶음 생성, 승인한 담당자 배정, 확인일 표시. 사람: 상담·위험도 확인·정기 돌봄 계획·일정 확정.</Text><Button disabled={task.busy} title="1차 · 향후 7일 자동 제안 실행" onPress={()=>task.run(async()=>{const r=await api.request<{offered:string[];skipped:{care_id:string;reason:string}[]}>('/api/worker/scheduler/run',{});await load();task.setMessage(`제안 ${r.offered.length}건 / 미연결 ${r.skipped.length}건`+r.skipped.map(x=>`\n${x.care_id}: ${x.reason}`).join(''));})}/><Text style={s.caption}>내가 검토한 미연결 일반 요청을 접수순으로 최대 100건 처리합니다. 지역이 같은 가장 이른 빈 시간에 제안하며, 거절된 건은 자동 재제안하지 않습니다.</Text><Button secondary disabled={task.busy} title="새로고침" onPress={()=>task.run(load)}/><Button secondary disabled={task.busy} title="업데이트 전 요청도 찾아 묶기" onPress={()=>task.run(async()=>{await api.request('/api/worker/repeats/scan',{});await load();})}/><Notice text={task.message}/>{!rows.length&&<Text style={s.body}>현재 검토할 반복 요청 묶음이 없습니다.</Text>}</Card>{rows.map(row=><RepeatCard key={`${row.id}:${row.state}:${row.worker_id}`} api={api} row={row} userId={userId} onChanged={load}/>)}</>;
}
