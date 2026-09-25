import * as SecureStore from 'expo-secure-store';
import {digestStringAsync,CryptoDigestAlgorithm} from 'expo-crypto';
import {ApiClient} from './api';
import {User} from './types';
async function key(api:ApiClient){return 'clover.device.'+await digestStringAsync(CryptoDigestAlgorithm.SHA256,api.baseUrl);}
export async function saveDevice(api:ApiClient,secret:string,toggleMode:boolean){await SecureStore.setItemAsync(await key(api),JSON.stringify({secret,toggleMode}));}
export async function restoreDevice(api:ApiClient):Promise<{user:User;toggleMode:boolean}|null>{
 const value=await SecureStore.getItemAsync(await key(api));if(!value)return null;
 const saved=JSON.parse(value);const r=await api.request<{access_token:string;user:User}>('/api/device/refresh',{secret:saved.secret});api.token=r.access_token;return {user:r.user,toggleMode:Boolean(saved.toggleMode)};
}
export async function forgetDevice(api:ApiClient){await SecureStore.deleteItemAsync(await key(api));}
