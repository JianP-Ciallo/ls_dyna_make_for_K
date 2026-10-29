// One recent result per demonstration scene. No existing engineering stores touched.
import {COMPONENT_RESPONSE_METHOD} from './blast_demo_model.js';
const DATABASE='lsprepost-simple-blast-results',STORE='recent',VERSION=COMPONENT_RESPONSE_METHOD;
export async function resultCache(building,value,method=VERSION){
 const db=await new Promise((resolve,reject)=>{
  const request=indexedDB.open(DATABASE,1);
  request.onupgradeneeded=()=>request.result.createObjectStore(STORE);
  request.onsuccess=()=>resolve(request.result);
  request.onerror=()=>reject(request.error);request.onblocked=()=>reject(Error('结果缓存暂时被其他页面占用'));
 });
 try{return await new Promise((resolve,reject)=>{
  const tx=db.transaction(STORE,value===undefined?'readonly':'readwrite'),store=tx.objectStore(STORE);
  const versionedKey=(value?.method||method)+':'+building,request=value===undefined?store.get(versionedKey):store.put(value,versionedKey);let saved;
  request.onsuccess=()=>{saved=request.result;};
  tx.oncomplete=()=>resolve(saved);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('缓存已中止'));
 });}finally{db.close();}
}
