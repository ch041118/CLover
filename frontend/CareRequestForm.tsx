'use client';
import { useState } from 'react';

// Drop into the existing Next.js app. Keep access tokens in memory, never localStorage.
// The backend URL is public configuration; Keep all model requests on the backend.
export default function CareRequestForm({ accessToken, apiBase = 'http://localhost:8000' }: { accessToken: string; apiBase?: string }) {
  const [note, setNote] = useState('');
  const [category, setCategory] = useState('meal');
  const [signals, setSignals] = useState<string[]>([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const choices = [['breathing_difficulty','숨쉬기 어려움'],['unconscious','의식 없음'],['severe_bleeding','심한 출혈'],['fall','넘어짐'],['missed_meal','식사를 못함'],['missed_medication','약을 못 먹음'],['loneliness','외로움']];
  return <form onSubmit={async e => {
    e.preventDefault(); if (busy) return; setBusy(true); setMessage('');
    try {
      const response = await fetch(`${apiBase}/api/care-requests`, {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify({ note, features: { category, signals, duration: 'unknown', can_self_manage: false }, allow_local_ai: consent })
      });
      if (!response.ok) throw new Error(response.status === 422 ? '입력을 확인하고 인증키·비밀번호를 제거해 주세요.' : '요청을 저장하지 못했습니다. 로그인 상태를 확인해 주세요.');
      const result = await response.json();
      setMessage(result.urgency === 'danger' ? '긴급 확인 대상으로 접수했습니다. 즉시 위험한 상황이면 119에 연락하세요. 자동 신고되지는 않습니다.' : '접수했습니다. 담당 사회복지사가 확인합니다.');
      setNote('');
    } catch (error) { setMessage(error instanceof Error ? error.message : '연결에 실패했습니다.'); }
    finally { setBusy(false); }
  }} style={{ maxWidth: 560, display: 'grid', gap: 16, fontSize: 18 }}>
    <h1>돌봄 요청하기</h1>
    <p>즉시 위험한 상황이면 119에 연락하세요. 이 서비스는 자동 신고하지 않습니다.</p>
    <label>어떤 도움이 필요한가요?<select value={category} onChange={e => setCategory(e.target.value)}>
      {[['meal','식사'],['mobility','이동'],['housekeeping','집안일'],['companionship','말벗'],['medication','복약 도움'],['other','기타']].map(([v,l]) => <option value={v} key={v}>{l}</option>)}
    </select></label>
    <fieldset><legend>현재 상황</legend>{choices.map(([v,l]) => <label key={v} style={{ display: 'block' }}>
      <input type="checkbox" checked={signals.includes(v)} onChange={e => setSignals(e.target.checked ? [...signals,v] : signals.filter(x => x !== v))} />{l}
    </label>)}</fieldset>
    <label>담당자에게 전할 내용<textarea required maxLength={4000} value={note} onChange={e => setNote(e.target.value)} style={{ width:'100%', minHeight:140 }} /></label>
    <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />
      선택: 입력한 돌봄 내용을 기관 내부 AI로 분석하는 데 동의합니다. 외부 AI 서비스에는 보내지 않습니다. 동의하지 않아도 담당자에게 접수됩니다.
    </label>
    <button disabled={busy} type="submit">{busy ? '접수 중…' : '도움 요청'}</button>
    <p role="status">{message}</p>
  </form>;
}
