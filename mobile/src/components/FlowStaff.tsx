import React,{useEffect,useState} from 'react';
import {Switch,Text,View} from 'react-native';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';
import {AudioModule} from 'expo-audio';
import {ApiClient} from '../api';
import {Button,Card,Chips,Field,Notice,s,useTask} from '../ui';
import {categories,Category,User} from '../types';
import {FlowJob} from './ElderMic';
import {saveDevice} from '../device';

export function PairDevice({api,onLogin}:{api:ApiClient;onLogin:(u:User,toggle:boolean)=>void}){
 const [code,setCode]=useState(''),[toggle,setToggle]=useState(false);const task=useTask();
 return <Card><Text style={s.heading}>어르신 기기 연결 · 직원 설정</Text><Text style={s.body}>직원 화면에서 발급한 연결 코드를 입력하면 다음부터 마이크 화면으로 열립니다.</Text><Field label="일회용 연결 코드" value={code} onChange={setCode}/><View style={s.switchRow}><Switch value={toggle} onValueChange={setToggle}/><Text style={s.body}>꾹 누르기 대신 한 번 눌러 시작·종료</Text></View>
 <Button disabled={task.busy||!code.trim()} title="이 기기를 어르신 모드로 연결" onPress={()=>task.run(async()=>{const permission=await AudioModule.requestRecordingPermissionsAsync();if(!permission.granted)throw Error('마이크 권한을 허용해 주세요.');const r=await api.request<{access_token:string;secret:string;user:User}>('/api/device/pair',{code:code.trim()});await saveDevice(api,r.secret,toggle);api.token=r.access_token;onLogin(r.user,toggle);})}/><Notice text={task.message}/></Card>;
}
export function Enrollment({api}:{api:ApiClient}){
 const [name,setName]=useState(''),[province,setProvince]=useState('부산광역시'),[district,setDistrict]=useState(''),[address,setAddress]=useState(''),[consent,setConsent]=useState(false),[ai,setAi]=useState(false);
 const [results,setResults]=useState<{label:string;longitude:number;latitude:number}[]>([]),[chosen,setChosen]=useState<typeof results[number]|null>(null),[elders,setElders]=useState<{elder_id:string;name:string;worker_id:string}[]>([]),[pair,setPair]=useState(''),[legacy,setLegacy]=useState('');const task=useTask();
 const load=async()=>setElders(await api.request('/api/staff/elders'));useEffect(()=>{void task.run(load);},[api]);
 return <><Card><Text style={s.heading}>어르신 등록 돕기</Text><Field label="이름·호칭" value={name} onChange={setName}/><Field label="시·도 (예: 부산광역시)" value={province} onChange={setProvince}/><Field label="시·군·구 (예: 연제구)" value={district} onChange={setDistrict}/>
 <Text style={s.caption}>이용자에게 음성·AI 분석 및 지도 전송을 설명하고 본인의 의사를 확인하세요.</Text>
 <View style={s.switchRow}><Switch value={consent} onValueChange={setConsent}/><Text style={s.body}>주소·위치 전송 동의 확인</Text></View><View style={s.switchRow}><Switch value={ai} onValueChange={setAi}/><Text style={s.body}>음성·로컬 AI 이용 동의 확인</Text></View>
 <Field label="도로명 주소" value={address} onChange={x=>{setAddress(x);setChosen(null);setResults([]);}}/>
 <Button title="주소 검색" disabled={task.busy||!consent||!address.trim()} onPress={()=>task.run(async()=>{const rows=await api.request<typeof results>('/api/location/search',{query:address,consent});setResults(rows);if(!rows.length)task.setMessage('검색된 주소가 없습니다.');})}/>
 {results.map((x,i)=><Button key={i} secondary title={x.label} onPress={()=>{setChosen(x);setResults([]);}}/>)}{chosen&&<Text style={s.body}>{chosen.label}</Text>}
 <Button title="등록하고 담당 사회복지사 연결" disabled={task.busy||!name.trim()||!chosen||!ai||!consent||!district.trim()} onPress={()=>task.run(async()=>{await api.request('/api/caregiver/elders',{name,region:{province,district},location:{...chosen,consent},local_ai:ai,consent_confirmed:true});await load();setName('');setChosen(null);task.setMessage('등록했습니다. 아래에서 기기 연결 코드를 발급하세요.');})}/><Notice text={task.message}/></Card>
 <Card><Text style={s.heading}>기존 이용자 연결</Text><Text style={s.caption}>담당 사회복지사가 기존 요청을 맡은 이용자를 새 기기 모드로 연결합니다.</Text><Field label="기존 어르신 아이디" value={legacy} onChange={setLegacy}/><Button disabled={task.busy||!legacy.trim()} title="기존 이용자 담당 관계 연결" onPress={()=>task.run(async()=>{await api.request('/api/caregiver/elders/'+encodeURIComponent(legacy)+'/attach',{});await load();setLegacy('');})}/></Card>
 {elders.map(x=><Card key={x.elder_id}><Text style={s.label}>{x.name}</Text><Text style={s.body}>담당 사회복지사: {x.worker_id}</Text><Button title="새 기기 연결 코드 발급" disabled={task.busy} onPress={()=>task.run(async()=>{const r=await api.request<{code:string}>('/api/staff/elders/'+x.elder_id+'/pair',{});setPair(r.code);})}/><Text style={s.caption}>새 코드 발급 시 이전 기기 연결은 해제됩니다. 코드는 10분 동안 한 번만 사용할 수 있습니다.</Text><Button secondary disabled={task.busy} title="분실 기기 연결 해제" onPress={()=>task.run(async()=>{await api.request('/api/staff/elders/'+x.elder_id+'/revoke',{});setPair('');task.setMessage('기기 연결을 해제했습니다.');})}/></Card>)}
 {pair&&<Card><Text style={s.label}>어르신 기기에 입력할 코드</Text><Text selectable style={s.body}>{pair}</Text></Card>}</>;
}
export function AutoSettings({api}:{api:ApiClient}){
 const [enabled,setEnabled]=useState(false),[selected,setSelected]=useState<string[]>([]);const task=useTask();
 useEffect(()=>{void task.run(async()=>{const p=await api.request<{enabled:boolean;categories:string[]}>('/api/caregiver/auto-policy');setEnabled(p.enabled);setSelected(p.categories);});},[api]);
 return <Card><Text style={s.heading}>등록한 근무 시간에 자동 배정</Text><Text style={s.body}>활동 지역과 등록한 빈 근무 시간 안에서 선택한 업무를 자동 확정합니다. 일정마다 수락할 필요는 없으며, 불가능해지면 이유를 남겨 조율을 요청할 수 있습니다.</Text><Switch value={enabled} onValueChange={setEnabled} accessibilityLabel="자동 배정 동의"/>
 {(['meal','housekeeping','companionship','mobility'] as Category[]).map(x=><Button key={x} secondary={!selected.includes(x)} title={categories[x]+(selected.includes(x)?' · 선택됨':'')} onPress={()=>setSelected(selected.includes(x)?selected.filter(y=>y!==x):[...selected,x])}/>)}
 <Button disabled={task.busy} title="자동 배정 범위 저장" onPress={()=>task.run(async()=>{await api.request('/api/caregiver/auto-policy',{enabled,categories:selected});task.setMessage('저장했습니다. 근무 가능 시간과 출발지 설정도 확인하세요.');})}/><Notice text={task.message}/></Card>;
}
export function FlowInbox({api,readOnly=false}:{api:ApiClient;readOnly?:boolean}){
 const [stats,setStats]=useState<{total:number;automatic_completed:number;categories:{category:string;state:string;count:number}[]}|null>(null);
 const [rows,setRows]=useState<FlowJob[]>([]),[all,setAll]=useState(readOnly),[selected,setSelected]=useState<FlowJob|null>(null),[note,setNote]=useState(''),[category,setCategory]=useState<Category>('other'),[confirmed,setConfirmed]=useState(false),[slots,setSlots]=useState<{slot_id:string;caregiver_id:string;day:string;start:string;end:string}[]>([]),[slot,setSlot]=useState('');const task=useTask();
 const load=async()=>{const [rows,summary]=await Promise.all([api.request<FlowJob[]>('/api/flow/jobs'),api.request<NonNullable<typeof stats>>('/api/flow/statistics')]);setRows(rows);setStats(summary);};useEffect(()=>{void task.run(load);const id=setInterval(()=>void task.run(load),15000);return()=>clearInterval(id);},[api]);
 const resolve=(action:string)=>task.run(async()=>{if(!selected)return;await api.request('/api/worker/flow/'+selected.id+'/resolve',{action,slot_id:slot||null,category,note,confirmed});setSelected(null);setNote('');setSlot('');setConfirmed(false);await load();});
 if(selected)return <><Card><Text style={s.heading}>예외 조율 · {selected.elder_id}</Text><Text style={s.body}>{selected.reason_label}{'\n'}{selected.text||'음성 내용을 확인하지 못했습니다. 이용자에게 확인해 주세요.'}</Text>
 {selected.events?.map((x,i)=><Text key={i} style={s.caption}>{x.at} · {x.kind} · {x.note}</Text>)}
 {!readOnly&&['exception','clarify','rescheduling'].includes(selected.state)&&<><Chips options={categories} value={category} select={setCategory}/><Field label="확인한 내용과 조율 이유" value={note} onChange={setNote} multiline/>
 <View style={s.switchRow}><Switch value={confirmed} onValueChange={setConfirmed}/><Text style={s.body}>이용자와 업무·일정을 확인했습니다.</Text></View>
 <Button secondary title="담당 팀의 빈 일정 조회" disabled={task.busy} onPress={()=>task.run(async()=>setSlots(await api.request('/api/worker/open-slots')))}/>
 {slots.map(x=><Button key={x.slot_id} secondary={slot!==x.slot_id} title={`${x.day} ${x.start}–${x.end} · ${x.caregiver_id}`} onPress={()=>setSlot(x.slot_id)}/>)}
 <Button disabled={task.busy||!slot||!note.trim()||!confirmed} title="선택한 일정으로 조율 제안" onPress={()=>resolve('assign')}/>
 <Button secondary disabled={task.busy||!note.trim()||!confirmed} title="요청 취소 처리" onPress={()=>resolve('cancel')}/><Button secondary disabled={task.busy||!note.trim()||!confirmed} title="별도 조치 완료 기록" onPress={()=>resolve('close')}/></>}
 <Button secondary title="목록으로" onPress={()=>setSelected(null)}/><Notice text={task.message}/></Card></>;
 return <><Card><Text style={s.heading}>개입이 필요한 요청</Text>{stats&&<><Text style={s.body}>전체 접수 {stats.total}건 · 사람 개입 없이 완료 {stats.automatic_completed}건</Text>{all&&stats.categories.map((x,i)=><Text key={i} style={s.caption}>{categories[x.category as Category]||x.category} · {x.state}: {x.count}건</Text>)}</>}<Text style={s.body}>일반 요청은 자동 처리됩니다. 수행 불가·배정 실패·내용 확인이 필요한 건을 조율하세요.</Text><Button secondary title={all?'개입 필요만 보기':'전체 처리 내역 보기'} onPress={()=>setAll(!all)}/><Button secondary disabled={task.busy} title="새로고침" onPress={()=>task.run(load)}/><Notice text={task.message}/></Card>
 {rows.filter(x=>all||['exception','clarify','rescheduling'].includes(x.state)).map(x=><Card key={x.id}><Text style={s.label}>{x.elder_id} · {x.state}</Text><Text style={s.body}>{x.reason_label||x.message}{'\n'}{x.text}</Text><Button secondary title={readOnly?"처리 이력 확인":"이력 확인·조율"} onPress={()=>{setSelected(x);setNote('');setSlot('');setConfirmed(false);}}/></Card>)}</>;
}
export function FlowAlerts({api}:{api:ApiClient}){
 const [rows,setRows]=useState<{id:string;kind:string;read:boolean}[]>([]);const task=useTask();
 const load=async()=>setRows(await api.request('/api/flow/notices'));useEffect(()=>{void load().catch(()=>{});const id=setInterval(()=>void load().catch(()=>{}),15000);return()=>clearInterval(id);},[api]);
 return <Card><Text style={s.heading}>새 일정·확인 알림</Text><Button secondary title="휴대폰 알림 연결" disabled={task.busy} onPress={()=>task.run(async()=>{const projectId=Constants.expoConfig?.extra?.eas?.projectId;if(!projectId)throw Error('알림은 EAS 프로젝트가 설정된 개발 빌드에서 연결해 주세요.');const p=await Notifications.requestPermissionsAsync();if(p.status!=='granted')throw Error('알림 권한을 허용해 주세요.');const token=await Notifications.getExpoPushTokenAsync({projectId});await api.request('/api/flow/push-device',{token:token.data});task.setMessage('휴대폰 알림을 연결했습니다. 서버에서도 푸시 기능을 켜야 합니다.');})}/>
 {rows.filter(x=>!x.read).map(x=><Button secondary key={x.id} title={(x.kind==='assigned'?'새 일정이 배정됐습니다':x.kind==='exception'?'조율이 필요한 요청이 있습니다':'일정 상태가 변경됐습니다')+' · 확인'} onPress={()=>task.run(async()=>{await api.request('/api/flow/notices/'+x.id+'/read',{});await load();})}/>)}<Notice text={task.message}/></Card>;
}
