import React, { useEffect, useState, useRef } from 'react';
import { AppState, KeyboardAvoidingView, Platform, Pressable, ScrollView, StatusBar, Text, View } from 'react-native';
import { ApiClient, resolveBaseUrl } from './src/api';
import { Care, Category, Role, User, Urgency, categories, roles, urgencies } from './src/types';

import { Button, Card, Field, Chips, useTask, Notice, colors, s } from './src/ui';
import { SettingsScreen, ConsentGate } from './src/components/SettingsScreen';
import { MatchingScreen } from './src/components/MatchingScreen';
import { WorkerStatistics, WorkerSchedules, RepeatInbox, RequestScheduler } from './src/components/WorkerConsole';
import {Teams,LocationSettings,OperationHistory,MapUsagePanel} from './src/components/Operations';
import { WorkerDesk } from './src/components/WorkerDesk';
import { CaregiverVisits } from './src/components/CaregiverVisits';
import {say,stopSpeaking,receiptText} from './src/speaking';
import {VoiceCheckin} from './src/components/VoiceCheckin';
import { VoiceRequest } from './src/components/VoiceRequest';

function Auth({ api, onLogin }: { api: ApiClient; onLogin: (user: User) => void }) {
  const [signup, setSignup] = useState(false), [id, setId] = useState(''), [password, setPassword] = useState(''), [role, setRole] = useState<'elder' | 'social_worker' | 'caregiver'>('elder');
  const task = useTask();
  return <Card><Text style={s.heading}>{signup ? '함께 돌봄을 시작해요' : '다시 만나 반가워요'}</Text><Text style={s.body}>가입 후 기관 관리자의 승인이 필요합니다.</Text>
    <Field label="아이디 (영문·숫자·_·-)" value={id} onChange={setId} maxLength={40} />
    <Field label="비밀번호 (가입 시 12자 이상)" value={password} onChange={setPassword} password />
    {signup && <Chips options={{ elder: '어르신', social_worker: '사회복지사', caregiver: '요양보호사' }} value={role} select={setRole} />}
    <Button disabled={task.busy || !id || !password} title={task.busy ? '처리 중…' : signup ? '가입 신청' : '로그인'} onPress={() => task.run(async () => {
      if (signup) { await api.request('/api/signup', { id, password, role }); setSignup(false); setPassword(''); task.setMessage('가입 신청을 보냈습니다. 관리자 승인 후 로그인해 주세요.'); }
      else { const result = await api.request<{ access_token: string }>('/api/login', { id, password }); api.token = result.access_token;
        try { const user = await api.request<User>('/api/me'); setPassword(''); onLogin(user); } catch (error) { api.token = ''; throw error; }
      }
    })} />
    <Button secondary disabled={task.busy} title={signup ? '로그인으로 돌아가기' : '처음 이용하시나요? 가입하기'} onPress={() => { setSignup(!signup); task.setMessage(''); }} />
    <Button secondary disabled={task.busy} title="기관 서버 연결 확인" onPress={() => task.run(async () => { await api.request('/health'); task.setMessage('기관 서버에 연결되었습니다.'); })} /><Notice text={task.message} />
  </Card>;
}
function NewRequest({ api, onDone }: { api: ApiClient; onDone: () => void }) {
  const [category, setCategory] = useState<Category>('meal'), [note, setNote] = useState(''), [signals, setSignals] = useState<string[]>([]), [urgent, setUrgent] = useState(false), [voiceBusy, setVoiceBusy] = useState(false);
  const task = useTask();const activeRequest=useRef(true);
  useEffect(()=>{activeRequest.current=true;const listener=AppState.addEventListener('change',state=>{if(state!=='active')void stopSpeaking();});return()=>{activeRequest.current=false;listener.remove();void stopSpeaking();};},[]);
  const choices: Record<string, string> = { meal_preparation: '식사 준비', walk_companion: '산책·외출 동행', light_housework: '가벼운 집안일', shopping_help: '장보기 도움', conversation: '이야기 나누기', medication_reminder: '약 시간 챙기기', ...(urgent ? { breathing_difficulty: '숨쉬기 어려움', unconscious: '의식 없음', severe_bleeding: '심한 출혈', fall: '넘어짐', missed_meal: '식사를 못함', missed_medication: '약을 못 먹음' } : {}) };
  return <><VoiceRequest api={api} onDone={onDone} onBusy={setVoiceBusy} /><Card><Text style={s.heading}>어떤 도움이 필요한가요?</Text><Chips options={categories} value={category} select={setCategory} />
    <Text style={s.label}>오늘 필요한 도움 (편하게 골라 주세요)</Text><View style={s.wrap}>{Object.entries(choices).map(([key, label]) => <Pressable key={key} accessibilityRole="checkbox" accessibilityState={{ checked: signals.includes(key) }} onPress={() => setSignals(signals.includes(key) ? signals.filter(x => x !== key) : [...signals, key])} style={[s.chip, signals.includes(key) && s.chipOn]}><Text style={[s.chipText, signals.includes(key) && { color: '#fff' }]}>{label}</Text></Pressable>)}</View>
    <Button secondary title={urgent ? "긴급 항목 접기" : "다치거나 급한 상황인가요?"} onPress={() => setUrgent(!urgent)} />
    <Field label="담당자에게 전할 내용" value={note} onChange={setNote} multiline maxLength={4000} />
    <Text style={s.caption}>AI 분석은 처음 정한 설정을 자동 적용합니다. 설정에서 언제든 변경할 수 있습니다.</Text>
    <Button disabled={task.busy || voiceBusy || !note.trim()} title={task.busy ? '접수 중…' : '도움 요청 보내기'} onPress={() => task.run(async () => {
      const row = await api.request<Care>('/api/care-requests', { note, features: { category, signals, duration: 'unknown', can_self_manage: false } });
      setNote(''); setSignals([]); task.setMessage(row.emergency_notice || '접수되었습니다. 담당자가 확인합니다.');
      if(activeRequest.current&&!api.closed&&AppState.currentState==='active'){const played=await say(receiptText(row.emergency_notice));if(!played)task.setMessage('접수는 완료됐습니다. 음성 안내는 재생하지 못했습니다.');}
    })} /><Button secondary title="내 요청 보기" onPress={onDone} /><Notice text={task.message} />
  </Card></>;
}
function Home({ api, navigate }: { api: ApiClient; navigate: (tab: string) => void }) {
  const task = useTask(); const [patterns, setPatterns] = useState<{ category: Category; count: number; suggestion: string }[]>([]);
  return <><VoiceCheckin api={api} onHelp={()=>navigate('request')}/><Card><Text style={s.kicker}>나의 생활 돌봄</Text><Text style={s.heading}>어떤 도움이 필요하세요?</Text><Text style={s.body}>필요한 도움을 요청하거나 내 지역의 돌봄 일정을 찾아보세요.</Text>
    <Button title="말로 또는 글로 도움 요청" onPress={() => navigate('request')} />
    <Button secondary title="내 지역에서 돌봄 일정 찾기" onPress={() => navigate('match')} />
    <Button secondary disabled={task.busy} title="반복 요청 안내 확인" onPress={() => task.run(async () => { const rows = await api.request<typeof patterns>('/api/patterns'); setPatterns(rows); if (!rows.length) task.setMessage('최근 반복 요청 안내가 없습니다.'); })} /><Notice text={task.message} />
  </Card>{patterns.map(p => <Card key={p.category}><Text style={s.label}>{categories[p.category]} · 최근 7일 {p.count}회</Text><Text style={s.body}>{p.suggestion}</Text></Card>)}</>;
}
function Requests({ api, worker, unassigned = false }: { api: ApiClient; worker: boolean; unassigned?: boolean }) {
  const [rows, setRows] = useState<Care[]>([]), [detail, setDetail] = useState<Care | null>(null), [loaded, setLoaded] = useState(false); const task = useTask();
  const load = async () => { setRows(await api.request<Care[]>(unassigned ? '/api/worker/unassigned' : '/api/care-requests')); setLoaded(true); };
  useEffect(() => { task.run(load); }, []);
  if (detail) return <Card><Text style={s.heading}>요청 내용</Text><Text style={s.body}>{detail.content?.note}</Text><Text style={s.label}>{urgencies[detail.urgency]} · {detail.review_required ? '담당자 확인 필요' : '검토 완료'}</Text>
    {detail.emergency_notice && <Text style={s.emergency}>{detail.emergency_notice}</Text>}
    {worker && <><Text style={s.body}>내용을 확인한 뒤 상태를 확정하세요.</Text>{(['danger', 'need', 'self_care'] as Urgency[]).map(u => <Button key={u} secondary disabled={task.busy} title={`${urgencies[u]}로 확정`} onPress={() => task.run(async () => { const updated = await api.request<Care>(`/api/worker/review/${encodeURIComponent(detail.id)}`, { urgency: u }); setDetail({ ...detail, ...updated }); await load(); task.setMessage('검토 결과를 저장했습니다.'); })} />)}</>}
    {worker && <RequestScheduler api={api} careId={detail.id} reviewRequired={detail.review_required !== false} />}
    <Button secondary title="목록으로" onPress={() => setDetail(null)} /><Notice text={task.message} />
  </Card>;
  return <><Card><Text style={s.heading}>{unassigned ? '미배정 접수함' : worker ? '내 담당 요청' : '내 요청'}</Text><Button secondary disabled={task.busy} title={task.busy ? '불러오는 중…' : '새로고침'} onPress={() => task.run(load)} /><Notice text={task.message} />{loaded && !rows.length && <Text style={s.body}>현재 표시할 요청이 없습니다.</Text>}</Card>
    {rows.map(row => <Card key={row.id}><Text style={[s.label, row.urgency === 'danger' && { color: colors.danger }]}>{urgencies[row.urgency]}{row.category ? ` · ${categories[row.category]}` : ''}</Text><Text style={s.caption}>{new Date(row.created_at).toLocaleString('ko-KR')}</Text>
      {!unassigned && <Text style={s.body}>{row.review_required ? '담당자 확인 대기' : '검토 완료'}</Text>}
      <Button disabled={task.busy} title={unassigned ? '담당 접수하기' : '내용 보기'} onPress={() => task.run(async () => {
        if (unassigned) { await api.request(`/api/worker/claim/${encodeURIComponent(row.id)}`, {}); await load(); task.setMessage('배정되었습니다. 내 담당 메뉴에서 내용을 확인하세요.'); }
        else setDetail(await api.request<Care>(`/api/care-requests/${encodeURIComponent(row.id)}`));
      })} />
    </Card>)}</>;
}
function Approvals({ api }: { api: ApiClient }) {
  const [users, setUsers] = useState<User[]>([]), [loaded, setLoaded] = useState(false); const task = useTask();
  const load = async () => { setUsers(await api.request<User[]>('/api/admin/pending-users')); setLoaded(true); };
  useEffect(() => { task.run(load); }, []);
  return <><Card><Text style={s.heading}>가입 승인</Text><Button secondary disabled={task.busy} title="새로고침" onPress={() => task.run(load)} /><Notice text={task.message} />{loaded && !users.length && <Text style={s.body}>승인을 기다리는 계정이 없습니다.</Text>}</Card>
    {users.map(user => <Card key={user.id}><Text style={s.label}>{user.id} · {roles[user.role]}</Text><Button disabled={task.busy} title="가입 승인" onPress={() => task.run(async () => { await api.request(`/api/admin/approve/${encodeURIComponent(user.id)}`, {}); await load(); task.setMessage('승인했습니다.'); })} /></Card>)}</>;
}
function Drafts({ api }: { api: ApiClient }) {
  const [topic, setTopic] = useState('welcome_notice'), [draft, setDraft] = useState(''), [source, setSource] = useState(''); const task = useTask();
  return <Card><Text style={s.heading}>안내문 초안</Text><Chips options={{ welcome_notice: '환영문', volunteer_etiquette: '봉사 예절', service_introduction: '서비스 소개' }} value={topic} select={setTopic} /><Text style={s.body}>기관 내부 AI로 안내문을 작성합니다. AI를 사용할 수 없으면 기본 문구를 제공하며, 내용을 직접 고칠 수 있습니다.</Text>
    <Button disabled={task.busy} title={task.busy ? '작성 중…' : '내부 AI로 초안 만들기'} onPress={() => task.run(async () => { const r = await api.request<{ draft: string; source: string; reason?: string }>('/api/general-drafts', { topic, allow_local_ai: true }); setDraft(r.draft); setSource(r.source === 'template' ? (r.reason === 'local_disabled' ? '기본 문구 · 서버 AI가 꺼져 있습니다.' : '기본 문구 · AI가 응답하지 않아 준비된 문구를 불러왔습니다.') : '로컬 AI 작성 · 사용 전 검토해 주세요.'); })} />{draft ? <><Text style={s.caption}>{source}</Text><Field label="안내문 편집" value={draft} onChange={setDraft} multiline maxLength={2000} /></> : null}<Notice text={task.message} />
  </Card>;
}
function Session({ baseUrl }: { baseUrl: string }) {
  const [user, setUser] = useState<User | null>(null), [tab, setTab] = useState('home'), [sessionId, setSessionId] = useState(0);
  const api = React.useMemo(() => new ApiClient(baseUrl, () => { setUser(null); setSessionId(x => x + 1); }), [baseUrl, sessionId]);
  useEffect(() => () => api.close(), [api]);
  const logout = () => { api.close(); setUser(null); setTab('home'); setSessionId(x => x + 1); };
  const menu: Record<string, string> = !user ? {} : user.role === 'elder' ? { home: '홈', request: '도움 요청', match: '돌봄 연결', list: '내 요청', settings: '설정' } : user.role === 'social_worker' ? { desk: 'AI 업무함', team: '담당 팀', history: '처리 이력', stats: '현황', queue: '새 요청', list: '요청 검토', schedules: '일정 관리', repeats: '반복 요청', draft: '안내문', settings: '설정' } : user.role === 'admin' ? { approvals: '가입 승인', team: '담당 연결', history: '처리 이력', draft: '안내문', settings: '설정' } : { home: '돌봄 수행', team: '담당 사회복지사', availability: '근무 가능 시간', settings: '설정' };
  return <><View style={s.brand}><Text style={s.logo}>CLover</Text><Text style={s.body}>생활 속 도움을 연결해요</Text></View>
    {!user ? <Auth key={sessionId} api={api} onLogin={u => { setUser(u); setTab(u.role === 'social_worker' ? 'desk' : u.role === 'admin' ? 'approvals' : 'home'); }} /> : <>
      <View style={s.account}><Text style={s.label}>{user.id} · {roles[user.role]}</Text><Pressable accessibilityRole="button" onPress={logout} style={{ padding: 12 }}><Text style={s.link}>로그아웃</Text></Pressable></View>
      {user.role === 'elder' && <ConsentGate api={api} />}
      <Chips options={menu} value={tab} select={setTab} />
      <View key={`${user.id}:${tab}`} style={{ gap: 14 }}>
        {user.role === 'elder' && tab === 'home' && <Home api={api} navigate={setTab} />}
        {user.role === 'elder' && tab === 'request' && <NewRequest api={api} onDone={() => setTab('list')} />}
        {(user.role === 'elder' || user.role === 'social_worker') && tab === 'list' && <Requests api={api} worker={user.role === 'social_worker'} />}
        {user.role === 'social_worker' && tab === 'queue' && <Requests api={api} worker unassigned />}
        {user.role === 'admin' && tab === 'approvals' && <Approvals api={api} />}
        {(user.role === 'admin' || user.role === 'social_worker') && tab === 'draft' && <Drafts api={api} />}
        {user.role === 'social_worker' && tab === 'desk' && <WorkerDesk api={api} navigate={setTab} />}
        {user.role === 'social_worker' && tab === 'stats' && <WorkerStatistics api={api} />}
        {user.role === 'social_worker' && tab === 'schedules' && <WorkerSchedules api={api} userId={user.id} />}
        {user.role === 'social_worker' && tab === 'repeats' && <RepeatInbox api={api} userId={user.id} />}
        {user.role === 'caregiver' && tab === 'home' && <CaregiverVisits api={api} />}
        {tab === 'settings' && <><SettingsScreen api={api}/>{user.role==='admin'&&<MapUsagePanel api={api}/>}{['elder','caregiver'].includes(user.role)&&<LocationSettings api={api} caregiver={user.role==='caregiver'}/>}</>}
        {tab==='team'&&['admin','social_worker','caregiver'].includes(user.role)&&<Teams api={api} admin={user.role==='admin'}/>}
        {tab==='history'&&['admin','social_worker'].includes(user.role)&&<OperationHistory api={api}/>} 
        {((user.role === 'elder' && tab === 'match') || (user.role === 'caregiver' && tab === 'availability')) && <MatchingScreen api={api} caregiver={user.role === 'caregiver'} />}
      </View></>}
    <Text style={s.emergency}>즉시 위험한 상황이면 119에 연락하세요. 이 앱은 자동 신고하지 않습니다.</Text>
  </>;
}
export default function App() {
  const [active, setActive] = useState(AppState.currentState === 'active');
  useEffect(() => { const listener = AppState.addEventListener('change', x => setActive(x === 'active')); return () => listener.remove(); }, []);
  let url = '', error = '';
  try { url = resolveBaseUrl(process.env.EXPO_PUBLIC_API_URL, __DEV__, process.env.EXPO_PUBLIC_ALLOW_INSECURE_DEV === 'true'); }
  catch (e) { error = e instanceof Error ? e.message : '서버 설정을 확인하세요.'; }
  return <View style={s.root}><StatusBar barStyle="dark-content" backgroundColor={colors.bg} /><KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.page}>
    {error ? <Card><Text style={s.heading}>기관 서버 연결 설정</Text><Text style={s.body}>{error}</Text><Text style={s.caption}>설정 방법: 저장소 docs/MOBILE.md</Text></Card> : <Session baseUrl={url} />}
  </ScrollView></KeyboardAvoidingView>{!active && <View style={s.cover}><Text style={s.logo}>CLover</Text><Text style={s.body}>개인정보 보호를 위해 화면을 가렸습니다.</Text></View>}</View>;
}
