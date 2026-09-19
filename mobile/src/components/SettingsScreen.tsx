import React, { useEffect, useState } from 'react';
import { Text } from 'react-native';
import { ApiClient } from '../api';
import { Button, Card, Notice, s, useTask } from '../ui';

type Preference = { local_ai: boolean; reviewed: boolean };
export function ConsentGate({ api }: { api: ApiClient }) {
  const [pref, setPref] = useState<Preference | null>(null); const task = useTask();
  useEffect(() => { task.run(async () => setPref(await api.request('/api/preferences'))); }, [api]);
  if (pref?.reviewed) return null;
  return <Card><Text style={s.heading}>처음 한 번, 요청 분석 방식을 정해 주세요</Text>
    <Text style={s.body}>기관 PC의 AI가 도움 요청을 정리하고 담당자가 최종 확인합니다. 외부 AI에는 보내지 않습니다. 한 번 정하면 다음 요청부터 자동 적용되고, 설정에서 바꿀 수 있습니다.</Text>
    <Button disabled={task.busy || !pref} title="설명을 확인했어요 · AI 분석 사용" onPress={() => task.run(async () => setPref(await api.request('/api/preferences', { local_ai: true })))} />
    <Button secondary disabled={task.busy || !pref} title="담당자에게 바로 접수할게요" onPress={() => task.run(async () => setPref(await api.request('/api/preferences', { local_ai: false })))} />
    <Notice text={task.message} />
  </Card>;
}
export function SettingsScreen({ api }: { api: ApiClient }) {
  const [pref, setPref] = useState<Preference | null>(null);
  const [status, setStatus] = useState<{ text_enabled: boolean; speech_enabled: boolean; speech_model_installed: boolean } | null>(null); const task = useTask();
  useEffect(() => { task.run(async () => { setPref(await api.request('/api/preferences')); setStatus(await api.request('/api/ai-status')); }); }, [api]);
  return <Card><Text style={s.heading}>AI와 음성 설정</Text><Text style={s.body}>요청 자동 분석: {pref ? pref.local_ai ? '사용 중' : '사용 안 함' : '확인 중'}</Text>
    <Text style={s.body}>동의한 요청만 기관 PC에서 분석합니다. 분석을 꺼도 담당자에게 접수할 수 있습니다. 음성은 녹음할 때 별도로 안내합니다.</Text>
    <Button disabled={task.busy || !pref} title={pref?.local_ai ? '요청 자동 분석 끄기' : '안내에 동의하고 자동 분석 켜기'} onPress={() => task.run(async () => { setPref(await api.request('/api/preferences', { local_ai: !pref?.local_ai })); task.setMessage('다음 요청부터 적용됩니다.'); })} />
    {status && <><Text style={s.caption}>서버 AI 설정: {status.text_enabled ? '켜짐 (실제 응답 여부는 요청 시 확인)' : '꺼짐 · 서버 담당자에게 설정을 요청하세요.'}</Text>
      <Text style={s.caption}>음성 설정: {status.speech_enabled && status.speech_model_installed ? '모델 준비됨' : '서버에 음성 모델 설치·설정이 필요합니다.'}</Text></>}
    <Notice text={task.message} />
  </Card>;
}
