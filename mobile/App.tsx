import React, { useEffect, useRef, useState } from 'react';
import { AppState, KeyboardAvoidingView, Platform, Pressable, ScrollView, StatusBar, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { ApiClient, resolveBaseUrl } from './src/api';
import { Care, Category, Role, User, Urgency, categories, roles, urgencies } from './src/types';

const colors = { bg: '#F1F6F2', card: '#FFFFFF', green: '#176347', dark: '#153629', muted: '#526B5E', line: '#D6E2D9', danger: '#A32627' };
function Button({ title, onPress, secondary = false, disabled = false }: { title: string; onPress: () => void; secondary?: boolean; disabled?: boolean }) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={[s.button, secondary && s.secondary, disabled && { opacity: .45 }]}><Text style={[s.buttonText, secondary && { color: colors.green }]}>{title}</Text></Pressable>;
}
function Card({ children }: { children: React.ReactNode }) { return <View style={s.card}>{children}</View>; }
function Field({ label, value, onChange, password = false, multiline = false, maxLength = 128 }: { label: string; value: string; onChange: (x: string) => void; password?: boolean; multiline?: boolean; maxLength?: number }) {
  return <View style={{ gap: 6 }}><Text style={s.label}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={onChange} secureTextEntry={password} autoCorrect={false} autoCapitalize="none" multiline={multiline} maxLength={maxLength} style={[s.input, multiline && { minHeight: 130, textAlignVertical: 'top' }]} /></View>;
}
function Chips<T extends string>({ options, value, select }: { options: Record<T, string>; value: T; select: (v: T) => void }) {
  return <View style={s.wrap}>{(Object.keys(options) as T[]).map(v => <Pressable key={v} accessibilityRole="button" accessibilityState={{ selected: v === value }} onPress={() => select(v)} style={[s.chip, v === value && s.chipOn]}><Text style={[s.chipText, v === value && { color: '#fff' }]}>{options[v]}</Text></Pressable>)}</View>;
}
function useTask() {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''); const lock = useRef(false);
  async function run(fn: () => Promise<void>) {
    if (lock.current) return; lock.current = true; setBusy(true); setMessage('');
    try { await fn(); } catch (error) { setMessage(error instanceof Error ? error.message : '처리에 실패했습니다.'); }
    finally { lock.current = false; setBusy(false); }
  }
  return { busy, message, setMessage, run };
}
function Notice({ text }: { text: string }) { return text ? <Text accessibilityLiveRegion="polite" style={s.notice}>{text}</Text> : null; }

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
  const [category, setCategory] = useState<Category>('meal'), [note, setNote] = useState(''), [signals, setSignals] = useState<string[]>([]), [consent, setConsent] = useState(false);
  const task = useTask();
  const choices: Record<string, string> = { breathing_difficulty: '숨쉬기 어려움', unconscious: '의식 없음', severe_bleeding: '심한 출혈', fall: '넘어짐', missed_meal: '식사를 못함', missed_medication: '약을 못 먹음', loneliness: '외로움' };
  return <Card><Text style={s.heading}>어떤 도움이 필요한가요?</Text><Chips options={categories} value={category} select={setCategory} />
    <Text style={s.label}>현재 상황 (해당하는 항목 선택)</Text><View style={s.wrap}>{Object.entries(choices).map(([key, label]) => <Pressable key={key} accessibilityRole="checkbox" accessibilityState={{ checked: signals.includes(key) }} onPress={() => setSignals(signals.includes(key) ? signals.filter(x => x !== key) : [...signals, key])} style={[s.chip, signals.includes(key) && s.chipOn]}><Text style={[s.chipText, signals.includes(key) && { color: '#fff' }]}>{label}</Text></Pressable>)}</View>
    <Field label="담당자에게 전할 내용" value={note} onChange={setNote} multiline maxLength={4000} />
    <View style={s.switchRow}><Switch accessibilityLabel="기관 내부 AI 분석 동의" value={consent} onValueChange={setConsent} /><Text style={[s.body, { flex: 1 }]}>선택: 기관 내부 AI로 내용을 분석합니다. 동의하지 않아도 접수됩니다.</Text></View>
    <Text style={s.caption}>내용은 기관 서버로 전송됩니다. 외부 AI 서비스는 사용하지 않습니다.</Text>
    <Button disabled={task.busy || !note.trim()} title={task.busy ? '접수 중…' : '도움 요청 보내기'} onPress={() => task.run(async () => {
      const row = await api.request<Care>('/api/care-requests', { note, features: { category, signals, duration: 'unknown', can_self_manage: false }, allow_local_ai: consent });
      setNote(''); setSignals([]); task.setMessage(row.emergency_notice || '접수되었습니다. 담당자가 확인합니다.');
    })} /><Button secondary title="내 요청 보기" onPress={onDone} /><Notice text={task.message} />
  </Card>;
}
function Home({ api }: { api: ApiClient }) {
  const task = useTask(); const [patterns, setPatterns] = useState<{ category: Category; count: number; suggestion: string }[]>([]);
  return <><Card><Text style={s.kicker}>오늘의 안부</Text><Text style={s.heading}>오늘도 잘 지내고 계신가요?</Text><Text style={s.body}>버튼을 눌러 오늘의 안부를 남겨 주세요.</Text>
    <Button disabled={task.busy} title="오늘 안부 남기기" onPress={() => task.run(async () => { const r = await api.request<{ day: string }>('/api/attendance', {}); task.setMessage(`${r.day} 안부를 남겼습니다.`); })} />
    <Button secondary disabled={task.busy} title="반복 요청 안내 확인" onPress={() => task.run(async () => { const rows = await api.request<typeof patterns>('/api/patterns'); setPatterns(rows); if (!rows.length) task.setMessage('최근 반복 요청 안내가 없습니다.'); })} /><Notice text={task.message} />
  </Card>{patterns.map(p => <Card key={p.category}><Text style={s.label}>{categories[p.category]} · 최근 7일 {p.count}회</Text><Text style={s.body}>{p.suggestion}</Text></Card>)}</>;
}
function Requests({ api, worker, unassigned = false }: { api: ApiClient; worker: boolean; unassigned?: boolean }) {
  const [rows, setRows] = useState<Care[]>([]), [detail, setDetail] = useState<Care | null>(null), [loaded, setLoaded] = useState(false); const task = useTask();
  const load = async () => { setRows(await api.request<Care[]>(unassigned ? '/api/worker/unassigned' : '/api/care-requests')); setLoaded(true); };
  useEffect(() => { task.run(load); }, []);
  if (detail) return <Card><Text style={s.heading}>요청 내용</Text><Text style={s.body}>{detail.content?.note}</Text><Text style={s.label}>{urgencies[detail.urgency]} · {detail.review_required ? '담당자 확인 필요' : '검토 완료'}</Text>
    {detail.emergency_notice && <Text style={s.emergency}>{detail.emergency_notice}</Text>}
    {worker && <><Text style={s.body}>내용을 확인한 뒤 상태를 확정하세요.</Text>{(['danger', 'need', 'self_care'] as Urgency[]).map(u => <Button key={u} secondary disabled={task.busy} title={`${urgencies[u]}로 확정`} onPress={() => task.run(async () => { await api.request(`/api/worker/review/${encodeURIComponent(detail.id)}`, { urgency: u }); setDetail(null); await load(); task.setMessage('검토 결과를 저장했습니다.'); })} />)}</>}
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
  const [topic, setTopic] = useState('welcome_notice'), [draft, setDraft] = useState(''); const task = useTask();
  return <Card><Text style={s.heading}>안내문 초안</Text><Chips options={{ welcome_notice: '환영문', volunteer_etiquette: '봉사 예절', service_introduction: '서비스 소개' }} value={topic} select={setTopic} /><Text style={s.body}>기관 내부 AI로 초안을 만듭니다. 사용 전 담당자가 확인해 주세요.</Text>
    <Button disabled={task.busy} title={task.busy ? '작성 중…' : '내부 AI로 초안 만들기'} onPress={() => task.run(async () => { const r = await api.request<{ draft: string }>('/api/general-drafts', { topic, allow_local_ai: true }); setDraft(r.draft); })} />{draft ? <Text selectable style={s.body}>{draft}</Text> : null}<Notice text={task.message} />
  </Card>;
}
function Session({ baseUrl }: { baseUrl: string }) {
  const [user, setUser] = useState<User | null>(null), [tab, setTab] = useState('home'), [sessionId, setSessionId] = useState(0);
  const api = React.useMemo(() => new ApiClient(baseUrl, () => { setUser(null); setSessionId(x => x + 1); }), [baseUrl, sessionId]);
  useEffect(() => () => api.close(), [api]);
  const logout = () => { api.close(); setUser(null); setTab('home'); setSessionId(x => x + 1); };
  const menu: Record<string, string> = !user ? {} : user.role === 'elder' ? { home: '안부', request: '도움 요청', list: '내 요청' } : user.role === 'social_worker' ? { queue: '접수함', list: '내 담당', draft: '안내문' } : user.role === 'admin' ? { approvals: '가입 승인', draft: '안내문' } : { home: '내 정보' };
  return <><View style={s.brand}><Text style={s.logo}>CLover</Text><Text style={s.body}>가까이에서 전하는 안부</Text></View>
    {!user ? <Auth key={sessionId} api={api} onLogin={u => { setUser(u); setTab(u.role === 'social_worker' ? 'queue' : u.role === 'admin' ? 'approvals' : 'home'); }} /> : <>
      <View style={s.account}><Text style={s.label}>{user.id} · {roles[user.role]}</Text><Pressable accessibilityRole="button" onPress={logout} style={{ padding: 12 }}><Text style={s.link}>로그아웃</Text></Pressable></View>
      <Chips options={menu} value={tab} select={setTab} />
      <View key={`${user.id}:${tab}`} style={{ gap: 14 }}>
        {user.role === 'elder' && tab === 'home' && <Home api={api} />}
        {user.role === 'elder' && tab === 'request' && <NewRequest api={api} onDone={() => setTab('list')} />}
        {(user.role === 'elder' || user.role === 'social_worker') && tab === 'list' && <Requests api={api} worker={user.role === 'social_worker'} />}
        {user.role === 'social_worker' && tab === 'queue' && <Requests api={api} worker unassigned />}
        {user.role === 'admin' && tab === 'approvals' && <Approvals api={api} />}
        {(user.role === 'admin' || user.role === 'social_worker') && tab === 'draft' && <Drafts api={api} />}
        {user.role === 'caregiver' && <Card><Text style={s.heading}>요양보호사 계정</Text><Text style={s.body}>가입·로그인은 사용할 수 있습니다. 일정 배정과 수락 기능은 아직 준비 중입니다.</Text></Card>}
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
const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg }, page: { padding: 20, paddingTop: 60, paddingBottom: 50, gap: 16, maxWidth: 720, width: '100%', alignSelf: 'center' },
  brand: { paddingVertical: 14, gap: 6 }, logo: { fontSize: 36, fontWeight: '800', color: colors.green, letterSpacing: -1 },
  card: { backgroundColor: colors.card, borderRadius: 22, padding: 22, gap: 16, borderWidth: 1, borderColor: colors.line }, heading: { fontSize: 25, fontWeight: '700', color: colors.dark },
  kicker: { color: colors.green, fontSize: 15, fontWeight: '700' }, body: { color: colors.muted, fontSize: 17, lineHeight: 26 }, caption: { color: colors.muted, fontSize: 14, lineHeight: 22 }, label: { color: colors.dark, fontSize: 18, fontWeight: '600' },
  input: { borderWidth: 1, borderColor: colors.line, borderRadius: 12, padding: 14, color: colors.dark, backgroundColor: '#FAFCFA', fontSize: 18, minHeight: 54 },
  button: { minHeight: 54, borderRadius: 14, backgroundColor: colors.green, padding: 15, alignItems: 'center', justifyContent: 'center' }, secondary: { backgroundColor: '#E8F2EC' }, buttonText: { color: '#fff', fontSize: 18, fontWeight: '700', textAlign: 'center' },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 }, chip: { paddingHorizontal: 16, paddingVertical: 13, borderWidth: 1, borderColor: colors.line, borderRadius: 24, backgroundColor: '#fff', minHeight: 48 }, chipOn: { backgroundColor: colors.green, borderColor: colors.green }, chipText: { color: colors.green, fontSize: 16, fontWeight: '600' },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: 12 }, notice: { padding: 14, borderRadius: 12, backgroundColor: '#EAF3ED', color: colors.dark, fontSize: 16, lineHeight: 25 }, emergency: { fontSize: 16, lineHeight: 25, color: colors.danger, paddingVertical: 10 }, account: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }, link: { color: colors.green, fontSize: 16, textDecorationLine: 'underline' }, cover: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: colors.bg, alignItems: 'center', justifyContent: 'center', gap: 18 },
});
