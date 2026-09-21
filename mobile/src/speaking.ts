import * as Speech from 'expo-speech';
import {setAudioModeAsync} from 'expo-audio';
let generation=0;
let settle:((done:boolean)=>void)|null=null;
export async function stopSpeaking(){generation++;settle?.(false);settle=null;await Speech.stop().catch(()=>{});}
export async function say(text:string):Promise<boolean>{
 const stopping=stopSpeaking();const id=generation;await stopping;
 if(id!==generation)return false;
 try{await setAudioModeAsync({allowsRecording:false,playsInSilentMode:true,shouldRouteThroughEarpiece:false,shouldPlayInBackground:false});}
 catch{return false;}
 if(id!==generation)return false;
 return new Promise(resolve=>{
  let ended=false;const finish=(done:boolean)=>{if(ended)return;ended=true;clearTimeout(timer);if(settle===finish)settle=null;resolve(done);};
  const timer=setTimeout(()=>{finish(false);void Speech.stop().catch(()=>{});},30000);settle=finish;
  try{Speech.speak(text,{language:'ko-KR',rate:0.85,onDone:()=>finish(true),onStopped:()=>finish(false),onError:()=>finish(false)});}catch{finish(false);}
 });
}
export function receiptText(emergency?:string|null){return '요청이 정상적으로 접수되었습니다. 담당자가 확인할 예정입니다.'+(emergency?' '+emergency:'');}
