import {buildBuilding,validateConfig,responseMethod,ALL_PRESETS,SCENE_PRESETS,DEFAULT_BUILDING_ID,COMPONENT_RESPONSE_METHOD} from './blast_demo_model.js';
import {createDemoView} from './blast_demo_view.js';
import {validFractureFrame,PANEL_FRACTURE_METHOD} from './blast_panel_fracture.js';
import {validDebrisFrame} from './blast_debris_contact.js';
import {scenePresentation,chooseFocusTarget} from './blast_demo_presentation.js';
import {REBAR_RESPONSE,validRebarFrame} from './blast_rebar_bundles.js';
import {LOCAL_REBAR_RESPONSE,validLocalRebarFrame} from './blast_local_rebar.js';
import {POWDER_RESPONSE,POWDER_SCHEMA,validPowderHistory} from './blast_powder.js';

const $=id=>document.getElementById(id),cpuWorkbench=document.body.hasAttribute('data-cpu-workbench'),query=new URL(location.href).searchParams;
const requestedId=query.get('building')||(cpuWorkbench?(query.get('source')==='fixed_three_storey'?DEFAULT_BUILDING_ID:query.get('source')):null)||DEFAULT_BUILDING_ID;
const preset=(cpuWorkbench?SCENE_PRESETS:ALL_PRESETS).find(p=>p.id===requestedId);
if(!preset){location.replace('./blast_buildings.html');throw Error('未知建筑，返回建筑列表');}
const model=buildBuilding({building:preset.id}),presentation=scenePresentation(model,preset.source),previousStorageKey=preset.id===DEFAULT_BUILDING_ID?'simple-blast-demo-config-v1':`simple-blast-demo-config-v1:${preset.id}`,panelStorageKey=previousStorageKey+':panel-fracture@2',storageKey=preset.id===DEFAULT_BUILDING_ID?panelStorageKey+':'+LOCAL_REBAR_RESPONSE+':'+POWDER_RESPONSE:panelStorageKey;
const exportName=preset.id===DEFAULT_BUILDING_ID?'three-storey':preset.id;
document.title=preset.name+' · 爆炸演示';
if($('demoTitle'))$('demoTitle').innerHTML=`${preset.name}<br>爆炸演示<span>每个入口独立运行当前场景。</span>`;
if($('buildingName'))$('buildingName').textContent=preset.name;
if($('buildingSize'))$('buildingSize').textContent=`${model.width.toFixed(1)} × ${model.depth.toFixed(1)} m`;
if($('buildingHeader'))$('buildingHeader').textContent=preset.name;
if($('buildingLinks'))$('buildingLinks').innerHTML=SCENE_PRESETS.map(p=>`<a href="/cpu-blast?building=${p.id}" target="_blank" rel="noopener" ${p.id===preset.id?'aria-current="page"':''}>${p.name} ↗</a>`).join('');
$('sourceZ').max=Math.max(15,Math.ceil(model.height+5));
const rebarControls=document.createElement('div');rebarControls.className='demo-target-controls';rebarControls.hidden=preset.id!==DEFAULT_BUILDING_ID;rebarControls.innerHTML='<label style="display:flex;align-items:center;gap:7px"><input id="useRebar" type="checkbox" checked> K 配筋参与受力</label><label style="display:flex;align-items:center;gap:7px"><input id="usePowder" type="checkbox" checked> 近爆区粉碎成尘</label><p class="hint">强冲击下近处混凝土可粉化，粉尘散去后保留破坏缺口。</p><button id="inspectRebar" class="secondary" aria-pressed="false">查看完整配筋</button><p id="rebarFacts" class="hint" aria-live="polite"></p><p class="hint">按 K 配筋规则映射，保持当前建筑尺寸；混凝土剥落后露筋，钢筋继续拉结并可屈服、断裂。</p>';
$('downloadModel').insertAdjacentElement('afterend',rebarControls);let inspectSteel=false;
const inputs=['sourceX','sourceY','sourceZ','charge','duration',...($('responseModel')?['responseModel']:[]),'useRebar','usePowder'];
let worker=null,token=0,result=null,frames=[],events=[],frameIndex=0,playing=false,playTime=0,lastTick=0,loading=false;
const resultListeners=new Set();
function message(text,error=false){$('inputMessage').textContent=text;$('inputMessage').dataset.error=String(error);}
function config(){if(['sourceX','sourceY','sourceZ','charge','duration'].some(id=>$(id).value.trim()===''))throw Error('请填写完整的爆源坐标和模拟参数。');return validateConfig({building:preset.id,mass:$('charge').value,source:['sourceX','sourceY','sourceZ'].map(id=>$(id).value),duration:$('duration').value,response:$('responseModel')?.value||'components',...(preset.id===DEFAULT_BUILDING_ID&&$('useRebar').checked?{reinforcement:LOCAL_REBAR_RESPONSE}:{}),...(preset.id===DEFAULT_BUILDING_ID&&$('usePowder').checked&&$('responseModel')?.value==='fracture'?{pulverization:POWDER_RESPONSE}:{})});}
function fill(c){$('charge').value=c.mass;['sourceX','sourceY','sourceZ'].forEach((id,i)=>$(id).value=c.source[i]);const duration=$('duration'),value=String(c.duration);if(!Array.from(duration.options).some(o=>o.value===value))duration.add(new Option(value+' s',value));duration.value=value;if($('responseModel')&&c.response)$('responseModel').value=c.response;$('useRebar').checked=!!c.reinforcement;$('usePowder').checked=c.pulverization===POWDER_RESPONSE;}
if(preset.id!==DEFAULT_BUILDING_ID)fill({mass:600,source:chooseFocusTarget(presentation,null).source,duration:6,response:'fracture'});
try{let saved=JSON.parse(localStorage.getItem(storageKey));if(!saved){const previous=JSON.parse((preset.id===DEFAULT_BUILDING_ID?(localStorage.getItem(panelStorageKey+':'+LOCAL_REBAR_RESPONSE)||localStorage.getItem(panelStorageKey+':'+REBAR_RESPONSE)):null)||localStorage.getItem(panelStorageKey)||localStorage.getItem(previousStorageKey));if(previous)saved={...previous,response:'fracture',...(preset.id===DEFAULT_BUILDING_ID?{reinforcement:LOCAL_REBAR_RESPONSE}:{})};}if(saved)fill(validateConfig({...saved,building:preset.id}));}catch{}
const view=createDemoView($('viewport'),model,point=>{
 ['sourceX','sourceY','sourceZ'].forEach((id,i)=>$(id).value=point[i].toFixed(2));changed(true);
});
function refreshRebar(){const enabled=preset.id===DEFAULT_BUILDING_ID&&$('useRebar').checked&&$('responseModel')?.value==='fracture';view.reinforcement(enabled,inspectSteel,LOCAL_REBAR_RESPONSE);$('inspectRebar').disabled=!enabled;$('inspectRebar').textContent=inspectSteel&&enabled?'退出配筋透视':'查看完整配筋';$('inspectRebar').setAttribute('aria-pressed',String(inspectSteel&&enabled));}
$('inspectRebar').onclick=()=>{inspectSteel=!inspectSteel;refreshRebar();};
$('modelCount').textContent=`${model.floorLabel||model.storeys+'层'} · ${model.bodies.length} 个实体构件`;
document.body.dataset.bodyCount=model.bodies.length;
document.body.dataset.buildingId=preset.id;document.body.dataset.buildingCount=model.buildingCount||1;document.body.dataset.sceneCount='1';
if($('cutawayControl'))$('cutawayControl').hidden=!model.cutaway;
if($('showCutaway'))$('showCutaway').onchange=()=>view.cutaway($('showCutaway').checked);
if($('designBasis'))$('designBasis').textContent=preset.detail||'原三层住宅与简化构件演示。';
const observation=document.createElement('div');observation.className='demo-target-controls';observation.innerHTML='<label for="demoTarget">演示目标<select id="demoTarget" data-workbench-ephemeral aria-label="选择演示目标"></select></label><div class="demo-target-actions"><button id="applyDemoTarget" class="secondary">应用目标演示</button><button id="focusDemo" class="secondary">聚焦破坏</button><button id="inspectFragments" class="secondary">观察碎片</button></div><p id="demoTargetNote" class="hint"></p>';
$('downloadModel').insertAdjacentElement('afterend',observation);$('demoTarget').replaceChildren(new Option('自动：破坏最明显的建筑','auto'),...presentation.targets.map(t=>new Option(t.label,t.id)));
function currentTarget(frame=result?.frames.at(-1)){return chooseFocusTarget(presentation,frame,$('demoTarget').value);}
function targetNote(){const target=currentTarget();$('demoTargetNote').textContent=`${target.label} · 应用示例会设置正面空地爆源；聚焦和观察仅改变视图。`;}
function focusTarget(frame){const target=currentTarget(frame);view.focus(target.bounds,target.id);targetNote();}
$('demoTarget').onchange=()=>focusTarget();$('focusDemo').onclick=()=>focusTarget();
$('inspectFragments').onclick=()=>{ $('showRoof').checked=false;$('showDust').checked=false;view.roof(false);view.dust(false);if(model.cutaway&&$('showCutaway')){$('showCutaway').checked=true;view.cutaway(true);}focusTarget();};
$('applyDemoTarget').onclick=()=>{const target=currentTarget();$('demoTarget').value=target.id;fill(validateConfig({building:preset.id,source:target.source,mass:preset.id===DEFAULT_BUILDING_ID?160:600,duration:6,response:'fracture',...(preset.id===DEFAULT_BUILDING_ID?{reinforcement:LOCAL_REBAR_RESPONSE,pulverization:POWDER_RESPONSE}:{})}));changed();focusTarget();message(`已应用${target.label}的增强演示参数，点击开始计算。已保存结果保留。`);};
function pause(){playing=false;$('playDemo').textContent='▶';}
function terminate(){token++;worker?.terminate();worker=null;document.body.dataset.running='false';$('startDemo').disabled=loading;$('applyDemoTarget').disabled=loading;$('cancelDemo').hidden=true;$('computeProgress').hidden=true;view.editable(true);}
function drawChart(id,values,color){
 const svg=$(id);if(!values.length){svg.innerHTML='<text x="15" y="70">模拟后显示响应曲线</text>';return;}
 const max=Math.max(1e-6,...values),path=values.map((v,i)=>`${i?'L':'M'}${20+i/Math.max(1,values.length-1)*420},${90-v/max*65}`).join(' ');
 svg.innerHTML=`<line x1="20" y1="90" x2="440" y2="90"/><line x1="20" y1="20" x2="20" y2="90"/><text x="25" y="15">${max<1?max.toFixed(3):max.toFixed(1)}</text><path d="${path}" stroke="${color}"/>`;
}
function show(index){
 frameIndex=Math.max(0,Math.min(frames.length-1,index));const frame=frames[frameIndex];
 view.frame(frame,events);$('timeline').value=Math.max(0,frameIndex);
 $('timeDisplay').textContent=`${(frame?.time||0).toFixed(2)} / ${Number($('duration').value).toFixed(2)} s`;
 $('brokenCount').innerHTML=`${frame?.broken||0} <em>/ ${model.bodies.length}</em>`;
 $('failureRatio').textContent=((frame?.broken||0)/model.bodies.length*100).toFixed(1)+'% 构件脱落';
 if($('fractureFacts'))$('fractureFacts').textContent=frame?.fracture?`${frame.fracture.cracked} 处裂缝 · ${frame.fracture.detached} 个三角片脱离连接${frame.fracture.limited?' · 已达到细分上限':''}`:($('responseModel')?.value==='fracture'?'板片先弯曲，连接逐步断裂后形成碎片。':'原整块脱落模式，用于对比。');
 if($('fractureFacts')&&frame?.debris)$('fractureFacts').textContent+=` · ${frame.debris.settled} 个静止碎片 · 近地堆积 ${frame.debris.pileHeight.toFixed(2)} m`;
 if(frame?.fracture?.compression)$('fractureFacts').textContent+=` · ${frame.fracture.compression.filter(d=>d>.5).length} 处局部压碎`;
 if(frame?.fracture?.powderSchema)$('fractureFacts').textContent+=` · ${frame.fracture.powdered} 片已粉化成尘`;
 if(preset.id===DEFAULT_BUILDING_ID){const steel=frame?.rebar;$('rebarFacts').textContent=$('useRebar').checked?(steel?`${steel.bars} 条筋线 · ${steel.bent} 组弯曲 · ${steel.held} 处拉结 · ${steel.yielded} 段屈服 · ${steel.broken} 段断裂`:`${view.reinforcementPlan().barCount} 条筋线已布置，计算后查看钢筋拉结与断裂。`):'当前为无筋对比；已保存的旧结果仍保留。';}
}
function changed(fromDrag=false){
 if($('responseModel')?.value!=='fracture')$('useRebar').checked=false;
 terminate();pause();result=null;frames=[];events=[];playTime=0;document.body.dataset.result='empty';
 $('playDemo').disabled=true;$('timeline').disabled=true;$('timeline').max=0;$('downloadDemo').disabled=true;
 $('wallTime').textContent='—';$('resultType').textContent='等待开始';$('stageStatus').textContent='模型就绪';$('viewLabel').textContent=preset.name+' / 初始模型';
 $('massLabel').textContent=$('charge').value+' kg';document.querySelectorAll('[data-mass]').forEach(b=>b.classList.toggle('active',b.dataset.mass===$('charge').value));
 $('usePowder').disabled=$('responseModel')?.value!=='fracture';
 if($('responseBadge'))$('responseBadge').textContent=$('responseModel')?.value==='fracture'?($('usePowder').checked&&preset.id===DEFAULT_BUILDING_ID?'近爆粉化 · 钢筋与碎片响应':$('useRebar').checked&&preset.id===DEFAULT_BUILDING_ID?'K 配筋拉结 · 渐进碎裂':'渐进碎裂 · 碎片互撞'):'整块脱落（对比）';targetNote();refreshRebar();
 show(0);drawChart('motionChart',[]);drawChart('failureChart',[]);
 try{const c=config();view.charge(c.mass);if(!fromDrag)view.source(c.source);localStorage.setItem(storageKey,JSON.stringify(c));message('参数已就绪，点击开始运行这一场景。');}
 catch(error){$('startDemo').disabled=true;message(error.message,true);if(!fromDrag){const s=['sourceX','sourceY','sourceZ'].map(id=>Number($(id).value));if(s.every(Number.isFinite))view.source(s);}}
}
function installResult(value,autoplay=false,index=0){
 const current=config(),expected=responseMethod(current);
 if(value?.schema!=='simple-blast-demo@1'||value.method!==expected||JSON.stringify(validateConfig(value.config))!==JSON.stringify(config())||value.model?.buildingId!==preset.id||value.model?.bodies?.length!==model.bodies.length||!value.frames?.length)throw Error('缓存结果与当前场景或参数不匹配');
 if(!Array.isArray(value.frames)||!Array.isArray(value.events)||!Number.isFinite(value.metrics?.wallMs)||!Number.isFinite(value.metrics?.broken)||value.model.bodies.some((b,i)=>JSON.stringify([b.center,b.size,b.rotation,!!b.fixed,b.supports])!==JSON.stringify([model.bodies[i].center,model.bodies[i].size,model.bodies[i].rotation,!!model.bodies[i].fixed,model.bodies[i].supports]))||value.frames.some(f=>f.poses?.length!==model.bodies.length*7||f.damage?.length!==model.bodies.length||!f.poses.every(Number.isFinite)||!f.damage.every(Number.isFinite)||![f.time,f.maxDisplacement,f.broken].every(Number.isFinite)))throw Error('缓存几何或响应帧版本不匹配');
 if(current.response==='fracture'&&value.frames.some(f=>!validFractureFrame(f.fracture,model)))throw Error('缓存柔性板片帧版本不匹配');
 if(current.response==='fracture'&&value.frames.some(f=>!validDebrisFrame(f.debris)))throw Error('缓存碎片接触帧版本不匹配');
 if(current.pulverization&&(value.frames.some(f=>f.fracture.powderSchema!==POWDER_SCHEMA)||!validPowderHistory(value.frames,value.events,model,current.duration)))throw Error('缓存粉化状态或粉尘事件版本不匹配');
 if(current.reinforcement&&(JSON.stringify(value.reinforcement?.source)!==JSON.stringify(view.reinforcementPlan().source)||value.frames.some(f=>current.reinforcement===LOCAL_REBAR_RESPONSE?!validLocalRebarFrame(f.rebar,view.reinforcementLayout()):!validRebarFrame(f.rebar,view.reinforcementPlan()))))throw Error('缓存钢筋来源或受力帧版本不匹配');
 result=value;frames=result.frames;events=result.events;document.body.dataset.result='completed';
 if(view.framing().mode==='focus')focusTarget(frames.at(-1));
 $('timeline').max=frames.length-1;$('timeline').disabled=false;$('playDemo').disabled=false;$('downloadDemo').disabled=false;
 $('wallTime').textContent=(result.metrics.wallMs/1000).toFixed(2)+' s';$('resultType').textContent='计算完成 · 简化动力学';$('stageStatus').textContent=autoplay?'计算完成':'已恢复结果';$('viewLabel').textContent=preset.name+' / 爆炸响应';
 drawChart('motionChart',frames.map(f=>f.maxDisplacement));drawChart('failureChart',frames.map(f=>f.broken));
 message(`已完成 ${result.config.duration} 秒过程，共 ${result.metrics.broken} 个构件脱落。拖动时间轴可查看任意时刻。`);
 pause();show(index);playTime=frames[frameIndex]?.time||0;playing=autoplay;$('playDemo').textContent=autoplay?'Ⅱ':'▶';lastTick=performance.now();
}
function start(){
 if(loading)return;
 let c;try{c=config();}catch(error){message(error.message,true);return;}
 terminate();pause();frames=[];events=[];result=null;playTime=0;show(0);const run=++token;
 document.body.dataset.running='true';document.body.dataset.result='running';$('startDemo').disabled=true;$('playDemo').disabled=true;$('downloadDemo').disabled=true;$('timeline').disabled=true;
 $('applyDemoTarget').disabled=true;
 $('computeProgress').hidden=false;$('cancelDemo').hidden=false;$('computeBar').value=0;$('computeLabel').textContent='计算开始';$('stageStatus').textContent='正在计算';$('viewLabel').textContent=preset.name+' / 爆炸响应';view.editable(false);message('正在计算冲击、构件破坏和运动，可随时停止。');
 const active=new Worker(new URL('./blast_demo_worker.js',import.meta.url),{type:'module'});worker=active;
 function fail(text){if(run!==token)return;terminate();pause();result=null;frames=[];events=[];show(0);document.body.dataset.result='error';message(text,true);$('stageStatus').textContent='已停止';}
 active.onerror=e=>fail(e.message||'计算进程未能启动');
 active.onmessage=({data})=>{
  if(run!==token)return;
  if(data.kind==='error'){fail(data.message);return;}
  if(data.kind==='progress'){
   frames.push(data.frame);events=data.events;show(frames.length-1);$('computeBar').value=data.fraction;
   $('computeLabel').textContent=`${Math.round(data.fraction*100)}% · 已计算 ${data.frame.time.toFixed(1)} / ${c.duration.toFixed(1)} s`;
  } else if(data.kind==='result') {
   try{installResult(data.result,true);}catch(error){fail(error.message);return;}terminate();for(const listener of resultListeners){try{listener(result);}catch(error){message('结果已完成，保留失败：'+error.message,true);}}
  }
 };
 active.postMessage(c);
}
function cancel(){
 if(!worker)return;terminate();pause();document.body.dataset.result='cancelled';$('stageStatus').textContent='已停止';message('计算已停止，已算帧保留，可调整参数重新开始。');
 $('playDemo').disabled=!frames.length;$('timeline').disabled=!frames.length;$('timeline').max=Math.max(0,frames.length-1);$('resultType').textContent='计算已停止';
}
for(const id of inputs)$(id).addEventListener('input',()=>{if((id==='useRebar'&&$('useRebar').checked)||(id==='usePowder'&&$('usePowder').checked))$('responseModel').value='fracture';changed();});
document.querySelectorAll('[data-mass]').forEach(b=>b.onclick=()=>{$('charge').value=b.dataset.mass;changed();});
$('startDemo').onclick=start;$('cancelDemo').onclick=cancel;$('closeProgress').onclick=cancel;
$('timeline').oninput=()=>{pause();show(Number($('timeline').value));playTime=frames[frameIndex]?.time||0;};
$('playDemo').onclick=()=>{if(playing){pause();return;}if(!frames.length)return;if(playTime>=frames.at(-1).time)playTime=0;playing=true;$('playDemo').textContent='Ⅱ';lastTick=performance.now();};
$('speed').onchange=()=>{lastTick=performance.now();};
$('resetDemo').onclick=()=>{pause();playTime=0;show(0);view.fit();};
$('fitDemo').onclick=()=>view.fit();$('showRoof').onchange=()=>view.roof($('showRoof').checked);$('showDust').onchange=()=>view.dust($('showDust').checked);
const damageLegend=document.createElement('div');damageLegend.id='damageLegend';damageLegend.hidden=true;damageLegend.textContent='材料损伤：蓝低 → 黄 → 红高；开裂与压碎，脱落另计';Object.assign(damageLegend.style,{position:'absolute',left:'20px',top:'64px',padding:'7px 10px',borderRadius:'5px',background:'rgba(255,255,255,.88)',color:'#37515c',fontSize:'11px',pointerEvents:'none'});$('viewport').append(damageLegend);
for(const id of ['appearance','damage'])$(id).onclick=()=>{view.mode(id==='damage');damageLegend.hidden=id!=='damage';for(const key of ['appearance','damage']){$(key).classList.toggle('selected',id===key);$(key).setAttribute('aria-pressed',String(id===key));}};
$('fullscreenDemo').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else $('viewport').requestFullscreen?.();};
function download(name,href){const a=document.createElement('a');a.download=name;a.href=href;document.body.append(a);a.click();a.remove();}
function jsonDownload(name,value){const url=URL.createObjectURL(new Blob([JSON.stringify(value,(_k,v)=>ArrayBuffer.isView(v)?Array.from(v):v)],{type:'application/json'}));download(name,url);setTimeout(()=>URL.revokeObjectURL(url),10000);}
$('captureDemo').onclick=()=>download(exportName+'-blast.png',view.capture());
$('downloadModel').onclick=()=>jsonDownload(exportName+'-solid-geometry.json',preset.id===DEFAULT_BUILDING_ID&&$('useRebar').checked?{...model,reinforcement:view.reinforcementLayout()}:model);
$('downloadDemo').onclick=()=>{if(result)jsonDownload(exportName+'-blast-result.json',result);};
function tick(now){
 if(playing&&frames.length){playTime=Math.min(frames.at(-1).time,playTime+(now-lastTick)/1000*Number($('speed').value));let i=frameIndex;if(!frames[i]||frames[i].time>playTime)i=0;while(i<frames.length-1&&frames[i+1].time<=playTime)i++;if(i!==frameIndex)show(i);if(playTime>=frames.at(-1).time)pause();}
 lastTick=now;requestAnimationFrame(tick);
}
changed();if(preset.id!==DEFAULT_BUILDING_ID)focusTarget();document.body.dataset.demoReady='true';requestAnimationFrame(tick);
export const demoController={preset,model,config,changed,pause,installResult,
 onResult(listener){resultListeners.add(listener);return()=>resultListeners.delete(listener);},
 playback:()=>({frame:frameIndex,damage:$('damage').classList.contains('selected')}),
 refreshView(){view.roof($('showRoof').checked);view.dust($('showDust').checked);view.cutaway($('showCutaway')?.checked??!!model.cutaway);refreshRebar();},
 setLoading(value){loading=value;$('applyDemoTarget').disabled=loading||!!worker;try{config();$('startDemo').disabled=loading||!!worker;}catch{$('startDemo').disabled=true;}},
 viewState:()=>view.framing(),
 beforeLeave(){if(worker)throw Error('正在计算，请先停止当前计算再切换。');pause();},
};
