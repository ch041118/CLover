import React,{useEffect,useState} from 'react';
import {Switch,Text,View} from 'react-native';
import {ApiClient} from '../api';
import {Category,Urgency} from '../types';
import {categories,urgencies} from '../types';
import {Button,Card,Chips,Field,Notice,s,useTask} from '../ui';
type Packet={id:string;elder_id:string;category:Category;urgency:Urgency;source:string;summary:string;evidence:string[];handoff:string;note:string;blockers:string[];lane:string;repeat_count:number;token:string;checks:string[]};
type Metrics={reviewed:number;ai_prepared:number;unchanged:number;edited:number;batch:number};
function PreparedCard({api,row,onChanged,onSelect,selected}:{api:ApiClient;row:Packet;onChanged:()=>Promise<void>;onSelect:(v:boolean)=>void;selected:boolean}){
 const [open,setOpen]=useState(false),[checked,setChecked]=useState(false),[handoff,setHandoff]=useState(row.handoff),[urgency,setUrgency]=useState(row.urgency==='uncertain'?'need':row.urgency);const task=useTask();
 const unchanged=handoff===row.handoff&&urgency===row.urgency;
 return <Card><Text style={s.label}>{row.lane==='ready'?'확인 후 묶음 승인 가능':'직접 개입 필요'} · {urgencies[row.urgency]}</Text>
 <Text style={s.body}>{row.elder_id} · {categories[row.category]} · 최근 7일 {row.repeat_count}건</Text>
 <Text style={s.caption}>{row.source==='local_model'?'로컬 AI 요약 · 원문과 대조하세요':'선택 항목 기반 정리 · AI 요약 아님'}</Text><Text style={s.body}>{row.summary}</Text>
 {row.blockers.map(x=><Text key={x} style={s.label}>{x}</Text>)}
 <Button secondary title={open?'접기':'원문·근거·전달문 한 번에 확인'} onPress={()=>setOpen(!open)}/>
 {open&&<><Text style={s.label}>접수 원문</Text><Text style={s.body}>{row.note}</Text><Text style={s.label}>원문 근거 발췌</Text>{row.evidence.map((x,i)=><Text key={i} style={s.body}>{x}</Text>)}
 <Chips options={{danger:'긴급 확인',need:'도움 필요',self_care:'일반 확인'}} value={urgency} select={v=>{setUrgency(v);setChecked(false);onSelect(false);}}/>
 <Field label="요양보호사 전달문 · 승인 후 연결된 요양보호사에게 공개" value={handoff} onChange={v=>{setHandoff(v);setChecked(false);onSelect(false);}} multiline maxLength={1200}/>
 <Text style={s.caption}>일정 제안 전 확인: {row.checks.join(' · ')}</Text>
 <View style={s.switchRow}><Switch accessibilityLabel="원문과 전달문 검토 완료" value={checked} onValueChange={v=>{setChecked(v);if(!v)onSelect(false);}}/><Text style={[s.body,{flex:1}]}>원문·분류와 전달할 내용을 확인했습니다.</Text></View>
 {row.lane==='ready'&&unchanged&&<Button secondary disabled={!checked||task.busy} title={selected?'묶음 승인 선택 해제':'이 건을 묶음 승인에 선택'} onPress={()=>onSelect(!selected)}/>}
 <Button disabled={!checked||!handoff.trim()||task.busy} title="검토 결과와 전달문 승인" onPress={()=>task.run(async()=>{await api.request(`/api/worker/desk/${row.id}/approve`,{token:row.token,urgency,handoff,reviewed:checked});await onChanged();})}/>
 </>}<Notice text={task.message}/></Card>;
}
export function WorkerDesk({api,navigate}:{api:ApiClient;navigate:(tab:string)=>void}){
 const [rows,setRows]=useState<Packet[]>([]),[metrics,setMetrics]=useState<Metrics|null>(null),[lane,setLane]=useState('all'),[offset,setOffset]=useState(0),[selected,setSelected]=useState<string[]>([]);const task=useTask();
 const load=async()=>{setSelected([]);const [items,m]=await Promise.all([api.request<Packet[]>(`/api/worker/desk?offset=${offset}`),api.request<Metrics>('/api/worker/desk/metrics')]);setRows(items);setMetrics(m);};
 useEffect(()=>{task.run(load);},[api,offset]);
 return <><Card><Text style={s.heading}>AI가 준비한 업무함</Text><Text style={s.body}>요약·원문 근거·전달문을 함께 확인하세요. 일반 요청은 확인한 건만 묶어 승인하고, 긴급·반복·불확실한 건은 직접 판단합니다.</Text>
 <Button disabled={task.busy} title="미배정 요청 최대 20건 가져와 검토" onPress={()=>task.run(async()=>{const r=await api.request<{claimed:number}>('/api/worker/desk/claim',{});setOffset(0);await load();task.setMessage(`${r.claimed}건을 맡았습니다.`);})}/>
 <Button secondary disabled={task.busy} title="업무함 새로고침" onPress={()=>task.run(load)}/>
 {metrics&&<Text style={s.body}>최근 30일 내 검토 {metrics.reviewed}건 · AI 정리 {metrics.ai_prepared}건{'\n'}AI안 그대로 승인 {metrics.unchanged}건 · 수정 승인 {metrics.edited}건 · 묶음 승인 {metrics.batch}건</Text>}
 <Text style={s.caption}>내가 검토한 요청의 최신 결과 기준입니다. 처리 시간 절감률을 뜻하지 않습니다.</Text>
 <Chips options={{all:'전체',intervention:'직접 개입',ready:'묶음 승인 가능'}} value={lane} select={setLane}/>
 <Text style={s.caption}>묶음 승인은 최대 20건입니다. 현재 {offset+1}번부터 최대 50건 중 직접 개입 {rows.filter(x=>x.lane==='intervention').length}건 · 묶음 승인 가능 {rows.filter(x=>x.lane==='ready').length}건</Text>
 <Button disabled={task.busy||!selected.length} title={`확인한 ${selected.length}건 분류·전달문 승인`} onPress={()=>task.run(async()=>{const items=rows.filter(r=>selected.includes(r.id)).map(r=>({care_id:r.id,token:r.token}));const r=await api.request<{approved:number}>('/api/worker/desk/approve-batch',{items});await load();task.setMessage(`${r.approved}건 승인했습니다. 일정 관리에서 1차 자동 제안을 실행하거나 요청 검토에서 직접 연결하세요.`);})}/>
 <Button secondary title="승인한 요청의 일정 제안하기" onPress={()=>navigate('schedules')}/>
 <Button secondary title="반복 요청 상담·후속 조치" onPress={()=>navigate('repeats')}/>
 <Button secondary disabled={!offset||task.busy} title="이전 50건" onPress={()=>setOffset(Math.max(0,offset-50))}/><Button secondary disabled={rows.length<50||task.busy} title="다음 50건" onPress={()=>setOffset(offset+50)}/>
 <Notice text={task.message}/>{!rows.length&&<Text style={s.body}>검토할 담당 요청이 없습니다. 새 요청을 가져오거나 일정 관리를 진행하세요.</Text>}</Card>
 {rows.filter(r=>lane==='all'||r.lane===lane).map(row=><PreparedCard key={`${row.id}:${row.token}`} api={api} row={row} onChanged={load} selected={selected.includes(row.id)} onSelect={v=>setSelected(old=>v?old.includes(row.id)?old:old.length<20?[...old,row.id]:old:old.filter(x=>x!==row.id))}/>)}</>;
}
