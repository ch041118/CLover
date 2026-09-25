import React,{useEffect,useRef,useState} from 'react';
import {AppState,Pressable,StyleSheet,Text,View,Vibration} from 'react-native';
import {AudioModule,RecordingPresets,setAudioModeAsync,useAudioRecorder} from 'expo-audio';
import {File} from 'expo-file-system';
import {randomUUID} from 'expo-crypto';
import {ApiClient} from '../api';
import {say,stopSpeaking} from '../speaking';
import {stopAndCleanRecorder} from '../recorderCleanup';
export type FlowJob={id:string;state:string;message:string;reason:string;updated_at:string;care_id:string|null;booking_id:string|null;elder_id?:string;reason_label?:string;text?:string;events?:{kind:string;actor:string;note:string;at:string}[];schedule?:{day:string;start:string;end:string;caregiver_id:string;status:string}|null};
export function ElderMic({api,toggleMode=false,onStaff}:{api:ApiClient;toggleMode?:boolean;onStaff:()=>void}){
 const recorder=useAudioRecorder({...RecordingPresets.HIGH_QUALITY,numberOfChannels:1,sampleRate:16000,bitRate:32000});
 const [phase,setPhase]=useState('idle'),[message,setMessage]=useState(toggleMode?'누르면 녹음이 시작돼요':'누른 채 말씀하세요');
 const job=useRef<FlowJob|null>(null),alive=useRef(true),epoch=useRef(0),busy=useRef(false),pressed=useRef(false),recording=useRef(false),started=useRef(0),last=useRef('');
 const stopping=useRef<Promise<void>>(Promise.resolve());
 const timer=useRef<ReturnType<typeof setTimeout>|null>(null),pending=useRef<{request_key:string;audio_base64:string;reply_to?:string}|null>(null);
 const clean=(uri:string|null)=>{if(uri)try{const f=new File(uri);if(f.exists)f.delete();}catch{}};
 const cancel=()=>{epoch.current++;pressed.current=false;recording.current=false;if(timer.current)clearTimeout(timer.current);void stopSpeaking();stopping.current=stopAndCleanRecorder(recorder,clean);busy.current=false;if(alive.current)setPhase('idle');};
 useEffect(()=>{alive.current=true;const sub=AppState.addEventListener('change',state=>{if(state!=='active')cancel();});
  let fetching=false;const poll=async()=>{if(fetching||busy.current||AppState.currentState!=='active')return;fetching=true;try{
   const rows=await api.request<FlowJob[]>('/api/flow/jobs');if(!alive.current||busy.current||AppState.currentState!=='active')return;
   const latest=rows.find(x=>x.state!=='superseded');if(!latest)return;job.current=latest;
   const stamp=latest.id+latest.state+latest.updated_at;if(stamp!==last.current){last.current=stamp;setMessage(latest.message);if(!['processing','queued'].includes(latest.state))await say(latest.message);}
  }catch{}finally{fetching=false;}};void poll();const interval=setInterval(()=>void poll(),3000);
  return()=>{alive.current=false;clearInterval(interval);sub.remove();cancel();};},[api,recorder]);
 async function upload(){
  const body=pending.current;if(!body)return;
  try{
   // A lost response is resolved using the same request key, never a new booking request.
   const existing=await api.request<FlowJob|null>('/api/flow/request/'+body.request_key);
   const result=existing||await api.request<FlowJob>('/api/flow/voice',body);pending.current=null;job.current=result;last.current=result.id+result.state+result.updated_at;
   if(alive.current&&AppState.currentState==='active'){setMessage(result.message);await say(result.message);}
  }catch{if(alive.current){setMessage('접수 여부를 확인하지 못했어요. 마이크를 누르면 같은 요청을 다시 확인합니다.');await say('접수 여부를 확인하지 못했습니다. 마이크를 눌러 다시 확인해 주세요.');}}
  finally{busy.current=false;if(alive.current)setPhase('idle');}
 }
 async function finish(id:number){
  if(!recording.current)return;recording.current=false;if(timer.current)clearTimeout(timer.current);setPhase('sending');
  let uri:string|null=null;
  try{
   await recorder.stop();if(!alive.current||epoch.current!==id)return;uri=recorder.uri;
   if(Date.now()-started.current<400){setMessage('누른 채 조금 더 길게 말씀해 주세요.');return;}
   if(!uri)throw Error();const f=new File(uri);if(f.size>2_000_000)throw Error();
   const audio_base64=await f.base64();if(!alive.current||epoch.current!==id)return;
   pending.current={request_key:randomUUID(),audio_base64,...(job.current?.state==='clarify'?{reply_to:job.current.id}:{})};
   clean(uri);uri=null;setMessage('말씀을 접수하고 있어요');await upload();
  }catch{if(alive.current&&epoch.current===id)setMessage('녹음을 확인하지 못했어요. 다시 말씀해 주세요.');}
  finally{clean(uri);if(epoch.current===id){busy.current=false;if(alive.current)setPhase('idle');}}
 }
 async function start(){
  if(busy.current)return;busy.current=true;pressed.current=true;const id=++epoch.current;const current=()=>alive.current&&epoch.current===id&&AppState.currentState==='active';
  if(pending.current){setPhase('sending');await upload();return;}
  try{
   await stopping.current;if(!current())return;await stopSpeaking();setPhase('preparing');const p=await AudioModule.requestRecordingPermissionsAsync();if(!current())return;
   if(!p.granted)throw Error('직원에게 마이크 권한 설정을 요청해 주세요.');
   await setAudioModeAsync({allowsRecording:true,playsInSilentMode:true,allowsBackgroundRecording:false});if(!current())return;
   await recorder.prepareToRecordAsync();if(!current()){await stopAndCleanRecorder(recorder,clean);return;}
   if(!pressed.current){await stopAndCleanRecorder(recorder,clean);busy.current=false;setPhase('idle');setMessage('마이크를 누른 채 말씀해 주세요.');return;}
   recorder.record();started.current=Date.now();recording.current=true;setPhase('recording');setMessage(toggleMode?'말씀 후 마이크를 다시 누르세요':'듣고 있어요. 다 말씀하시면 손을 떼세요');Vibration.vibrate(30);
   timer.current=setTimeout(()=>void finish(id),30000);
  }catch(e){await stopAndCleanRecorder(recorder,clean);if(current()){busy.current=false;setPhase('idle');setMessage(e instanceof Error&&e.message?e.message:'녹음을 시작하지 못했어요.');}}
 }
 const release=()=>{pressed.current=false;if(recording.current)void finish(epoch.current);};
 return <View style={styles.page}><Text accessibilityRole="header" onLongPress={onStaff} style={styles.brand}>CLover</Text>
 <Pressable accessibilityRole="button" accessibilityLabel={phase==='recording'?'녹음 중':pending.current?'접수 여부 다시 확인':'말로 도움 요청'}
  onPressIn={()=>{if(!toggleMode)void start();}} onPressOut={()=>{if(!toggleMode)release();}}
  onPress={()=>{if(toggleMode){if(recording.current)release();else void start();}}}
  style={[styles.mic,phase==='recording'&&styles.recording]}><Text style={styles.icon}>🎙</Text></Pressable>
 <Text accessibilityLiveRegion="polite" style={styles.message}>{message}</Text>
 </View>;
}
const styles=StyleSheet.create({page:{flex:1,backgroundColor:'#F1F6F2',alignItems:'center',justifyContent:'center',padding:28,gap:45},brand:{fontSize:25,color:'#176347',position:'absolute',top:65},mic:{width:240,height:240,borderRadius:120,backgroundColor:'#176347',alignItems:'center',justifyContent:'center'},recording:{backgroundColor:'#A32627'},icon:{fontSize:110,color:'white'},message:{fontSize:26,lineHeight:38,textAlign:'center',color:'#153629'}});
