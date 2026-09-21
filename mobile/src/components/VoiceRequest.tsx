import React, { useEffect, useRef, useState } from 'react';
import { AppState, Text } from 'react-native';
import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder } from 'expo-audio';
import { File } from 'expo-file-system';
import { ApiClient } from '../api';
import { Care, Category } from '../types';
import { Button, Card, Notice, s } from '../ui';
import {say,stopSpeaking,receiptText} from '../speaking';
import { voiceDecision } from '../voice';

type Transcript = { text: string; category: Category };
export function VoiceRequest({ api, onDone, onBusy }: { api: ApiClient; onDone: () => void; onBusy: (busy:boolean)=>void }) {
  const recorder=useAudioRecorder({...RecordingPresets.HIGH_QUALITY,numberOfChannels:1,sampleRate:16000,bitRate:32000});
  const [recording,setRecording]=useState(false),[busy,setBusy]=useState(false),[draft,setDraft]=useState<Transcript|null>(null),[message,setMessage]=useState('');
  const timer=useRef<ReturnType<typeof setTimeout>|null>(null), epoch=useRef(0), alive=useRef(true), locked=useRef(false);
  const cleanFile=(uri:string|null)=>{if(uri){try {const f=new File(uri);if(f.exists)f.delete();}catch{ /* OS may have already removed cache */ }}};
  useEffect(()=>{
    alive.current=true;
    const cancel=()=>{epoch.current++;void stopSpeaking();if(timer.current)clearTimeout(timer.current);timer.current=null;
      void recorder.stop().catch(()=>{}).finally(()=>{cleanFile(recorder.uri);locked.current=false;if(alive.current){setBusy(false);setRecording(false);onBusy(false);}});
    };
    const listener=AppState.addEventListener('change',state=>{if(state!=='active'){cancel();setMessage('녹음이 중단되었습니다. 다시 시작해 주세요.');}});
    return()=>{alive.current=false;listener.remove();cancel();};
  },[recorder]);
  async function start(confirm:boolean){
    if(locked.current)return;if(!confirm)setDraft(null);locked.current=true;setBusy(true);onBusy(true);setMessage('');const id=++epoch.current;
    const current=()=>alive.current&&epoch.current===id&&!api.closed;
    try{
      const permission=await AudioModule.requestRecordingPermissionsAsync();
      if(!permission.granted)throw new Error('휴대폰 설정에서 마이크 사용을 허용해 주세요. 글로도 접수할 수 있습니다.');
      if(!current())return;
      await setAudioModeAsync({allowsRecording:true,playsInSilentMode:true,allowsBackgroundRecording:false});
      await recorder.prepareToRecordAsync();if(!current()){await recorder.stop().catch(()=>{});cleanFile(recorder.uri);return;}
      recorder.record();setRecording(true);
      const seconds=confirm?7:25;
      setMessage(confirm?'지금 “접수해 주세요” 또는 “취소해 주세요”라고 말씀해 주세요. 7초 후 확인합니다.':'필요한 도움을 편하게 말씀해 주세요. 25초 후 자동으로 녹음을 마칩니다.');
      timer.current=setTimeout(()=>{void finish(confirm,id);},seconds*1000);
    }catch(error){await recorder.stop().catch(()=>{});cleanFile(recorder.uri);if(current()){setMessage(error instanceof Error?error.message:'녹음을 시작하지 못했습니다.');setBusy(false);setRecording(false);onBusy(false);locked.current=false;}}
  }
  async function finish(confirm:boolean,id:number){
    timer.current=null;let uri:string|null=null;
    const current=()=>alive.current&&epoch.current===id&&!api.closed;
    try{
      await recorder.stop();uri=recorder.uri;if(!current())return;setRecording(false);setMessage('기관 PC에서 음성을 글로 바꾸고 있습니다…');
      if(!uri)throw new Error('녹음 파일을 확인할 수 없습니다. 다시 녹음해 주세요.');
      const file=new File(uri);if(file.size>2_000_000)throw new Error('녹음이 너무 깁니다. 짧게 다시 말씀해 주세요.');
      const audio_base64=await file.base64();cleanFile(uri);uri=null;
      if(!current())return;
      const result=await api.request<Transcript>('/api/speech/transcribe',{audio_base64,consent:true});
      if(!current())return;
      if(!confirm){setDraft(result);setMessage('아래 내용이 맞으면 “말로 확인·접수”를 누르고 “접수해 주세요”라고 말씀하세요.');return;}
      const decision=voiceDecision(result.text);
      if(decision==='cancel'){setDraft(null);setMessage('접수하지 않고 취소했습니다.');return;}
      if(decision!=='submit'||!draft){setMessage('접수하지 않았습니다. “접수해 주세요” 또는 “취소해 주세요”로 다시 확인해 주세요.');return;}
      const row=await api.request<Care>('/api/care-requests',{note:draft.text,features:{category:draft.category,signals:[],duration:'unknown',can_self_manage:false}});
      if(current()){setDraft(null);setMessage(row.emergency_notice||'말씀하신 내용을 접수했습니다. 담당자가 확인합니다.');const played=await say(receiptText(row.emergency_notice));if(current()&&!played)setMessage('접수는 완료됐습니다. 음성 안내는 재생하지 못했습니다.');}
    }catch(error){if(current())setMessage(error instanceof Error?error.message:'음성을 처리하지 못했습니다. 글로 접수하거나 다시 녹음해 주세요.');}
    finally{cleanFile(uri);if(current()){setBusy(false);setRecording(false);onBusy(false);locked.current=false;}}
  }
  return <Card><Text style={s.heading}>말로 도움 요청하기</Text><Text style={s.body}>타이핑 없이 내용을 말하고, 한 번 더 말로 확인해 접수할 수 있어요. 각 녹음은 버튼을 누르면 시작하고 자동으로 끝납니다.</Text>
    <Text style={s.caption}>녹음을 시작하면 음성을 기관 PC로 보내 글로 바꾸는 데 동의합니다. 외부 음성 서비스는 사용하지 않으며, 녹음 파일은 처리 후 삭제합니다. 접수 전 인식된 내용을 확인해 주세요.</Text>
    <Button disabled={busy} title={recording?'듣고 있어요…':draft?'내용 다시 말하기':'안내에 동의하고 말하기'} onPress={()=>start(false)}/>
    {draft&&<><Text style={s.label}>이렇게 들었어요</Text><Text style={s.body}>{draft.text}</Text><Button disabled={busy} title="말로 확인·접수" onPress={()=>start(true)}/><Button secondary disabled={busy} title="내용 지우기" onPress={()=>setDraft(null)}/></>}
    {recording && <Text accessibilityLiveRegion="polite" style={s.label}>녹음 중 · 앱을 다른 화면으로 전환하면 중단됩니다.</Text>}
    <Notice text={message}/><Button secondary disabled={busy} title="내 요청에서 접수 확인" onPress={onDone}/>
  </Card>;
}
