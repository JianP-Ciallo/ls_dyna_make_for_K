import {demoController as demo} from './blast_demo.js';
import {SCENE_PRESETS,responseMethod} from './blast_demo_model.js';
import {resultCache} from './blast_demo_cache.js';
import {PANEL_FRACTURE_METHOD} from './blast_panel_fracture.js';

const $=id=>document.getElementById(id),navigation=window.WorkbenchNavigation,select=$('buildingSelect'),status=$('cacheStatus');
demo.setLoading(true);select.disabled=true;
const originalUrl=new URL(location.href),legacy=new URL('/cpu-blast',location.origin);legacy.search=originalUrl.search;legacy.searchParams.set('legacy','1');legacy.searchParams.delete('building');
if(!legacy.searchParams.has('source'))legacy.searchParams.set('source',demo.preset.id==='residence-3'?'fixed_three_storey':demo.preset.id);
$('legacyCpu').href=legacy.pathname+legacy.search;
select.replaceChildren(...SCENE_PRESETS.map(p=>new Option(p.id==='residence-3'?'我的三层建筑':p.name,p.id)));select.value=demo.preset.id;
const identity='demo:'+demo.preset.id,revision='simple-components-draft@1';let cacheWrite=Promise.resolve(),cacheVersion=0;
const currentUrl=new URL(originalUrl);currentUrl.pathname='/cpu-blast';currentUrl.searchParams.delete('legacy');currentUrl.searchParams.set('building',demo.preset.id);
const url=()=>currentUrl.pathname+currentUrl.search;
function cacheMessage(text,error=false){status.textContent=text;status.dataset.error=String(error);}
demo.onResult(result=>{
 const version=++cacheVersion;status.dataset.saved='false';cacheMessage('正在保留本场景最近一次结果…');
 cacheWrite=cacheWrite.catch(()=>{}).then(()=>resultCache(demo.preset.id,result)).then(()=>{
  if(version!==cacheVersion)return;status.dataset.saved='true';cacheMessage('本场景最近一次结果已保留，刷新后可继续回放。');
 },()=>{if(version===cacheVersion)cacheMessage('结果缓存不可用，请下载结果保留；当前回放仍可使用。',true);});
});
let restoredFrame=0;
async function beforeLeave(){demo.beforeLeave();let pending;do{pending=cacheWrite;await pending;demo.beforeLeave();}while(pending!==cacheWrite);}
await navigation.register('blast',{
 context:()=>({identity,revision,label:demo.preset.name+' · CPU 模拟',url:url()}),restoreIdentity:()=>identity,
 capture:()=>({schema:revision,fields:navigation.captureFields(document),playback:demo.playback()}),
 restore:saved=>{
  if(saved.schema!==revision)throw Error('演示草稿版本不支持');
  navigation.restoreFields(document,saved.fields);demo.changed();demo.refreshView();
  if(saved.playback?.damage)$('damage').click();restoredFrame=saved.playback?.frame||0;
 },
 beforeLeave,
});
try{
 const saved=await resultCache(demo.preset.id,undefined,responseMethod(demo.config()));
 if(saved){demo.installResult(saved,false,restoredFrame);cacheMessage('已恢复本场景最近一次结果，点击播放或拖动时间轴。');status.dataset.saved='true';}
}catch(error){cacheMessage(error.message.includes('不匹配')?'已保留旧缓存；当前参数等待重新计算。':'结果缓存暂不可用；可正常计算并下载结果。',!error.message.includes('不匹配'));}
finally{demo.setLoading(false);select.disabled=false;}
select.addEventListener('change',async()=>{
 const next=select.value;
 try{await beforeLeave();navigation.checkpoint();location.assign('/cpu-blast?building='+encodeURIComponent(next));}
 catch(error){select.value=demo.preset.id;cacheMessage(error.message,true);}
});
document.querySelector('.cpu-heading-actions a').addEventListener('click',async event=>{
 if(event.ctrlKey||event.metaKey||event.shiftKey)return;
 const href=event.currentTarget.href;event.preventDefault();try{await beforeLeave();navigation.checkpoint();location.assign(href);}catch(error){cacheMessage(error.message,true);}
});
document.title=demo.preset.name+' · CPU 爆炸模拟';document.body.dataset.cpuReady='true';
