import React,{useEffect,useRef,useState} from 'react';
import {AppState,Text} from 'react-native';
import {AudioModule,RecordingPresets,setAudioModeAsync,useAudioRecorder} from 'expo-audio';
import {File} from 'expo-file-system';
import {ApiClient} from '../api';
import {Button,Card,Notice,s} from '../ui';
import {say,stopSpeaking} from '../speaking';
type Status={enabled:boolean;due:boolean;state:string;attempts:number;max_attempts:number;next_at:string|null;day:string};
export function VoiceCheckin({api,onHelp}:{api:ApiClient;onHelp:()=>void}){
 const recorder=useAudioRecorder({...RecordingPresets.HIGH_QUALITY,numberOfChannels:1,sampleRate:16000,bitRate:32000});
 const [status,setStatus]=useState<Status|null>(null),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
 const alive=useRef(true),epoch=useRef(0),locked=useRef(false),blockedUntil=useRef(0),token=useRef('');
 const timer=useRef<ReturnType<typeof setTimeout>|null>(null),wake=useRef<(()=>void)|null>(null);
 const clean=(uri:string|null)=>{if(uri)try{const f=new File(uri);if(f.exists)f.delete();}catch{}};
 const cancel=()=>{epoch.current++;const pending=token.current;if(pending&&!api.closed)void api.request('/api/checkin/abort',{token:pending}).catch(()=>{});if(timer.current)clearTimeout(timer.current);wake.current?.();wake.current=null;void stopSpeaking();void recorder.stop().catch(()=>{}).finally(()=>clean(recorder.uri));};
 async function cycle(){
  if(locked.current||!alive.current||api.closed||AppState.currentState!=='active'||Date.now()<blockedUntil.current)return;
  locked.current=true;const id=epoch.current;const current=()=>alive.current&&epoch.current===id&&!api.closed&&AppState.currentState==='active';
  try{
   const st=await api.request<Status>('/api/checkin');if(!current())return;setStatus(st);if(!st.due)return;
   const permission=await AudioModule.getRecordingPermissionsAsync();if(!current())return;
   if(!permission.granted){setMessage('휴대폰 설정에서 마이크 권한을 허용해 주세요. 자동 확인을 잠시 쉬고 있습니다.');blockedUntil.current=Date.now()+300000;return;}
   setBusy(true);const attempt=await api.request<{token:string;question:string}>('/api/checkin/start',{});token.current=attempt.token;if(!current()){if(!api.closed)await api.request('/api/checkin/abort',{token:attempt.token}).catch(()=>{});return;}
   setMessage('안부를 묻고 있습니다. 안내가 끝나면 말씀해 주세요.');
   if(!await say(attempt.question)){if(current())throw new Error('음성 안내를 재생하지 못했습니다. 휴대폰 소리 설정을 확인해 주세요.');return;}
   if(!current())return;
   await setAudioModeAsync({allowsRecording:true,playsInSilentMode:true,allowsBackgroundRecording:false,shouldRouteThroughEarpiece:false});
   await recorder.prepareToRecordAsync();if(!current()){await recorder.stop().catch(()=>{});clean(recorder.uri);return;}
   recorder.record();setMessage('듣고 있어요. “네”, “잘 지내요” 또는 “도와주세요”라고 말씀해 주세요.');
   await new Promise<void>(resolve=>{wake.current=resolve;timer.current=setTimeout(resolve,8000);});wake.current=null;timer.current=null;
   await recorder.stop();const uri=recorder.uri;if(!current()){clean(uri);return;}
   if(!uri)throw new Error('녹음을 확인할 수 없습니다.');
   let audio_base64:string;try{const f=new File(uri);if(f.size>2_000_000)throw new Error('녹음이 너무 깁니다.');audio_base64=await f.base64();}finally{clean(uri);}
   if(!current())return;setMessage('말씀을 확인하고 있습니다…');
   const result=await api.request<Status>('/api/checkin/respond',{token:attempt.token,audio_base64});token.current='';if(!current())return;setStatus(result);
   const text=result.state==='answered'?'답변을 확인했습니다. 오늘 음성 확인을 마쳤습니다.':result.state==='help'?'답변을 확인했습니다. 도움이 필요하시면 도움 요청에서 말씀해 주세요. 급한 위험 상황이면 119에 연락해 주세요.':result.state==='technical'?(result.attempts>=3?'음성을 처리하지 못했습니다. 오늘 자동 확인을 마칩니다. 기관 담당자에게 음성 설정 확인을 요청해 주세요.':'음성을 처리하지 못했습니다. 5분 뒤 다시 확인하겠습니다.'):result.attempts>=3?'아직 답변을 확인하지 못했습니다. 오늘 자동 질문은 여기서 마칩니다.':'답변을 확인하지 못했습니다. 5분 뒤에 다시 여쭤볼게요.';
   setMessage(text);await say(text);
  }catch(error){
   if(current()){setMessage(error instanceof Error?error.message:'음성 확인을 진행하지 못했습니다.');blockedUntil.current=Date.now()+300000;
    if(token.current)await api.request('/api/checkin/abort',{token:token.current}).catch(()=>{});
   }
  }finally{locked.current=false;token.current='';if(alive.current)setBusy(false);}
 }
 useEffect(()=>{alive.current=true;void cycle();const poll=setInterval(()=>{void cycle();},15000);const listener=AppState.addEventListener('change',state=>{if(state!=='active')cancel();else void cycle();});return()=>{alive.current=false;clearInterval(poll);listener.remove();cancel();};},[api,recorder]);
 async function toggle(){if(locked.current)return;locked.current=true;setBusy(true);try{
  const enable=!status?.enabled;if(enable){const p=await AudioModule.requestRecordingPermissionsAsync();if(!p.granted)throw new Error('자동 음성 확인에는 마이크 권한이 필요합니다.');}
  const st=await api.request<Status>('/api/checkin/settings',{enabled:enable});if(alive.current){setStatus(st);setMessage(enable?'자동 음성 확인을 켰습니다. 오전 9시부터 오후 8시 사이 홈 화면에서 질문합니다.':'자동 음성 확인을 껐습니다.');blockedUntil.current=0;}
 }catch(e){if(alive.current)setMessage(e instanceof Error?e.message:'설정하지 못했습니다.');}finally{locked.current=false;if(alive.current)setBusy(false);}void cycle();}
 return <Card><Text style={s.heading}>말로 하는 하루 확인</Text><Text style={s.body}>한 번 켜 두면 홈 화면에서 먼저 안부를 묻고 답변을 듣습니다. 답변이 확인되지 않으면 5분 간격으로 하루 최대 3회 질문합니다.</Text>
 <Text style={s.caption}>마이크 음성은 기관 서버에서 처리하고 녹음은 처리 후 삭제합니다. 자동 확인에 동의하면 아래에서 켜 주세요. 오전 9시~오후 8시, 홈 화면이 켜져 있을 때만 동작합니다. 잠금·다른 화면에서는 중단됩니다.</Text>
 <Text style={s.label}>{status?.state==='help'?'답변 확인 · 도움 요청 필요':status?.state==='answered'?'오늘 답변 확인 완료':status?.enabled?`자동 확인 켜짐 · 오늘 ${status.attempts}/3회`:'자동 확인 꺼짐'}</Text>
 <Button disabled={busy||!status} title={status?.enabled?'자동 음성 확인 끄기':'동의하고 자동 음성 확인 켜기'} onPress={toggle}/>
 {busy&&<Button secondary title="지금 질문·녹음 멈추기" onPress={()=>{cancel();blockedUntil.current=Date.now()+300000;setMessage('중단했습니다. 5분 동안 다시 묻지 않습니다.');}}/>}
 <Button secondary title="도움 요청하기" onPress={onHelp}/><Notice text={message}/></Card>;
}
