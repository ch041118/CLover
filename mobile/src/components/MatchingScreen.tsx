import React, { useEffect, useState } from 'react';
import { Alert, Text, View } from 'react-native';
import { ApiClient } from '../api';
import { Category, categories } from '../types';
import { Button, Card, Chips, Field, Notice, s, useTask } from '../ui';

type Region = { province: string; district: string };
type Slot = Region & { id: string; caregiver_id: string; day: string; start: string; end: string; state: string };
type Booking = Slot & { elder_id: string; category: Category; status: string; slot_id: string };
const labels: Record<string,string> = { pending:'수락 대기', accepted:'일정 확정', declined:'수락하지 않음', cancelled:'취소됨', open:'신청 가능', reserved:'신청 있음', closed:'마감' };
const hours = Object.fromEntries(Array.from({ length: 18 }, (_, i) => { const h = `${String(i + 6).padStart(2,'0')}:00`; return [h,h]; }));
function nextDay(i: number) { return new Date(Date.now()+i*86400000+9*3600000).toISOString().slice(0,10); }
export function MatchingScreen({ api, caregiver }: { api: ApiClient; caregiver: boolean }) {
  const [regions, setRegions] = useState<Region[]>([]), [provinces, setProvinces] = useState<Record<string,string>>({});
  const [province,setProvince] = useState('서울특별시'), [district,setDistrict] = useState(''), [selected,setSelected] = useState(0), [editRegion,setEditRegion] = useState(false);
  const [day,setDay] = useState(nextDay(1)), [start,setStart] = useState('09:00'), [end,setEnd] = useState(caregiver ? '10:00' : '18:00');
  const [category,setCategory] = useState<Category>('companionship'), [slots,setSlots] = useState<Slot[]>([]), [bookings,setBookings] = useState<Booking[]>([]), [searched,setSearched] = useState(false);
  const task=useTask();
  const refresh = async () => { setBookings(await api.request('/api/bookings')); if (caregiver) setSlots(await api.request('/api/availability')); };
  useEffect(() => { task.run(async () => {
    const data=await api.request<{ provinces:string[];regions:Region[] }>('/api/regions');setRegions(data.regions);setEditRegion(!data.regions.length);
    setProvinces(Object.fromEntries(data.provinces.map(p=>[p,p]))); await refresh();
  }); }, [api]);
  const saveRegions = async (rows:Region[]) => { await api.request('/api/regions',{regions:rows}); setRegions(rows);setSelected(0);setSlots([]);setSearched(false);await refresh(); };
  const chooseDay = (v:string) => { setDay(v); if (!caregiver) {setSlots([]);setSearched(false);} };
  const decide = (id:string,action:string) => task.run(async () => { await api.request(`/api/bookings/${id}/decision`,{action});await refresh();if(!caregiver){setSlots([]);setSearched(false);}task.setMessage('일정 상태를 변경했습니다.'); });
  return <><Card><Text style={s.heading}>{caregiver ? '활동 지역과 근무 일정' : '지역과 시간으로 돌봄 찾기'}</Text>
    <Text style={s.body}>{caregiver ? '일할 수 있는 지역을 등록한 뒤 가능한 날짜와 시간을 올려 주세요.' : '도움받을 지역을 직접 정해 주세요. 원하는 시간 안에 들어오는 일정을 찾아드립니다.'} 위치 추적은 하지 않습니다.</Text>
    {regions.map((r,i)=><View key={`${r.province}:${r.district}`} style={{gap:6}}><Button secondary={selected!==i} title={`${r.province} ${r.district}`} onPress={()=>{setSelected(i);if(!caregiver){setSlots([]);setSearched(false);}}}/><Button secondary disabled={task.busy} title="이 지역 삭제" onPress={()=>task.run(()=>saveRegions(regions.filter((_,j)=>j!==i)))}/></View>)}
    <Button secondary title={editRegion ? '지역 입력 접기' : '지역 추가'} onPress={()=>setEditRegion(!editRegion)}/>
    {editRegion && <><Chips options={provinces} value={province} select={setProvince}/><Field label="시·군·구 (예: 수원시 영통구, 강남구 / 세종은 세종시)" value={district} onChange={setDistrict} maxLength={30}/><Text style={s.caption}>도로명·상세 주소 대신 같은 시·군·구 명칭을 입력해 주세요. 등록한 지역이 정확히 일치하는 일정을 찾습니다.</Text><Button disabled={task.busy || !district.trim() || regions.length>=10} title="지역 저장" onPress={()=>task.run(async()=>{await saveRegions([...regions,{province,district:district.trim()}]);setDistrict('');setEditRegion(false);})}/></>}
    <Notice text={task.message}/>
  </Card><Card><Text style={s.heading}>{caregiver ? '가능한 시간 등록' : '원하는 날짜와 시간'}</Text>
    <Text style={s.label}>날짜 · 한국 시간 기준</Text><Chips options={Object.fromEntries(Array.from({length:7},(_,i)=>[nextDay(i+1),nextDay(i+1).slice(5)]))} value={day} select={chooseDay}/>
    <Field label="다른 날짜 (YYYY-MM-DD, 90일 이내)" value={day} onChange={chooseDay} maxLength={10}/>
    <Text style={s.label}>시작 시간</Text><Chips options={hours} value={start} select={v=>{setStart(v);if(!caregiver){setSlots([]);setSearched(false);}}}/>
    <Text style={s.label}>종료 시간</Text><Chips options={hours} value={end} select={v=>{setEnd(v);if(!caregiver){setSlots([]);setSearched(false);}}}/>
    {!caregiver && <><Text style={s.label}>필요한 도움</Text><Chips options={categories} value={category} select={setCategory}/></>}
    <Button disabled={task.busy || !regions[selected] || start>=end} title={caregiver ? '근무 가능 일정 올리기' : '맞는 일정 찾기'} onPress={()=>task.run(async()=>{
      const body={region:regions[selected],day,start,end};
      if(caregiver){await api.request('/api/availability',body);await refresh();task.setMessage('가능한 일정을 등록했습니다.');}
      else {setSlots(await api.request('/api/matches',body));setSearched(true);}
    })}/>
    <Text style={s.caption}>신청 후 요양보호사가 수락해야 확정됩니다. 시간은 한국 시간이며 이동 시간은 별도로 고려해 주세요.</Text>
  </Card>
  {searched && !slots.length && <Card><Text style={s.body}>맞는 일정이 아직 없습니다. 시간 범위를 넓히거나 다른 날짜를 선택해 주세요.</Text></Card>}
  {slots.map(row=><Card key={row.id}><Text style={s.label}>{row.day} · {row.start}–{row.end}</Text><Text style={s.body}>{row.province} {row.district} · {caregiver ? labels[row.state] : `요양보호사 ${row.caregiver_id}`}</Text>
    {row.state==='open' && <Button disabled={task.busy} title={caregiver?'일정 내리기':'이 일정 신청'} onPress={()=>task.run(async()=>{
      if(caregiver) await api.request(`/api/availability/${row.id}/close`,{});
      else {await api.request('/api/bookings',{slot_id:row.id,category});setSlots([]);setSearched(false);task.setMessage('신청했습니다. 수락되면 아래 목록에 일정 확정으로 표시됩니다.');}
      await refresh();
    })}/>}</Card>)}
  <Card><Text style={s.heading}>{caregiver?'받은 신청':'내 신청 일정'}</Text><Button secondary disabled={task.busy} title="일정 상태 새로고침" onPress={()=>task.run(refresh)}/>{!bookings.length && <Text style={s.body}>아직 신청한 일정이 없습니다.</Text>}</Card>
  {bookings.map(b=><Card key={b.id}><Text style={s.label}>{labels[b.status]} · {categories[b.category]}</Text><Text style={s.body}>{b.day} {b.start}–{b.end}{'\n'}{b.province} {b.district}{'\n'}{caregiver ? `이용자 ${b.elder_id}` : `요양보호사 ${b.caregiver_id}`}</Text>
    {caregiver && b.status==='pending' && <><Button disabled={task.busy} title="수락하고 일정 확정" onPress={()=>decide(b.id,'accept')}/><Button secondary disabled={task.busy} title="이번 일정은 어렵습니다" onPress={()=>decide(b.id,'decline')}/></>}
    {['pending','accepted'].includes(b.status) && <Button secondary disabled={task.busy} title="신청 취소" onPress={()=>Alert.alert('일정을 취소할까요?','상대방의 일정 목록에도 취소로 표시됩니다.',[{text:'유지',style:'cancel'},{text:'취소 확정',style:'destructive',onPress:()=>decide(b.id,'cancel')}])}/>}
  </Card>)}</>;
}
