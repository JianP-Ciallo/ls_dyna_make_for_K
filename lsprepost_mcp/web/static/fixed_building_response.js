import {ResponseView} from './fixed_building_response_view.js';
import {ResponseCharts} from './fixed_building_response_charts.js';
const $=id=>document.getElementById(id),api='/api/architecture/pressure/cpu-response/';
let epoch=0,currentRun=null,result=null,frame=0,playing=false,playTime=0,lastTick=0,available=false;
let historyRequest=0,historyMutating=false,buildingTrial=null;const historyRecords=new Map();
const runLabels={queued:'等待计算',running:'正在计算',completed:'已完成',cancelled:'已停止',failed:'失败',interrupted:'已中断'};
const cancelledPreparations=new Set();let preparingToken=null;
const charts=new ResponseCharts($('responseChart'));
let view;
function status(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);}
try{view=new ResponseView($('responseViewport'),v=>{
  $('legendLabel').textContent=v.label;$('legendMin').textContent=v.min.toPrecision(3);$('legendMax').textContent=v.max.toPrecision(3);
  $('colorbar').style.background=v.signed?'linear-gradient(90deg,#207bc8,#f7f7f1,#d95b36)':'';
});}catch(error){status('三维显示不可用：'+error.message,true);}
async function request(path,payload){const response=await fetch(api+path,payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const value=await response.json();if(!response.ok)throw Error(typeof value.error==='string'?value.error:value.error?.message||`HTTP ${response.status}`);return value;}
function busy(value){$('startRun').disabled=value||!available||!view;$('cancelRun').hidden=!value;$('runProgress').hidden=!value;}
function controls(enabled){for(const id of ['play','previousFrame','nextFrame','timeline','savePng'])$(id).disabled=!enabled;}
function clear(){const url=new URL(location.href);url.searchParams.delete('run_id');window.history.replaceState(null,'',url);result=null;currentRun=null;playing=false;frame=0;view?.setResult(null);charts.setResult(null);$('emptyState').hidden=false;$('legend').hidden=true;controls(false);busy(false);$('runState').textContent='待计算';$('resultIdentity').textContent='尚未计算 · 不显示示例结果';$('timeValue').textContent='— ms';
  for(const id of ['peakDisplacement','peakSteel','wallTime','buildTime','solveTime','extractTime','loadTime','renderTime','memory'])$(id).textContent='—';
  for(const id of ['downloadCsv','downloadJson'])$(id).hidden=true;
  $('sampleDetails').textContent='计算后显示元素、积分点和钢筋位置。';$('modelSize').textContent='计算规模随结果记录。';
}
function configureCase(){epoch++;clear();const column=$('benchmark').value==='rc-column-v1';$('caseDescription').innerHTML=column?'3.0 m 悬臂柱 · 300 × 300 mm<br>4Φ16 纵筋 · 40 mm 保护层':'2.0 × 2.0 m 简支板 · 厚 150 mm<br>上下双向 Φ10@200 · 25 mm 保护层';$('viewTitle').textContent=column?'单柱动态响应':'单板动态响应';$('scale').value=column?300:1000;view?.setScale(Number($('scale').value));fillSteel();history();loadPreview();}
function fillSteel(){const column=$('benchmark').value==='rc-column-v1';$('steelFilter').replaceChildren();for(const [value,label]of column?[['all','全部纵筋'],['bar-1','纵筋 1'],['bar-2','纵筋 2'],['bar-3','纵筋 3'],['bar-4','纵筋 4']]:[['top-X','上层 X 向'],['top-Y','上层 Y 向'],['bottom-X','下层 X 向'],['bottom-Y','下层 Y 向']]){const o=document.createElement('option');o.value=value;o.textContent=label;$('steelFilter').append(o);}}
function loadPreview(){const scale=Number($('pressureScale').value)||0;$('loadPreview').innerHTML='<path d="M8 56 H212 M8 10 V56" fill="none" stroke="#ded5c5"/><path d="M8 56 L27 '+(56-Math.min(scale,2)*22)+' L190 56 H212" fill="none" stroke="#c49254" stroke-width="2"/><text x="34" y="15" font-size="10" fill="#a08861">'+(10*scale).toFixed(1)+' kPa</text>';}
function historyActions(){const r=historyRecords.get($('history').value),trash=!!$('showDeleted').checked;
 $('deleteHistory').hidden=trash;$('restoreHistory').hidden=!trash;
 $('deleteHistory').disabled=historyMutating||!r||['queued','running'].includes(r.status)||preparingToken!==null;
 $('restoreHistory').disabled=historyMutating||!r||!r.deleted_at;
 $('historyHint').textContent=r&&['queued','running'].includes(r.status)?'任务仍在进行，请先停止后再删除记录。':trash?'选择记录后可恢复，原输入与结果文件均保留。':'选择一条记录后可删除；原计算文件保留，可恢复。';
}
async function history(){const token=epoch,version=++historyRequest,id=$('benchmark').value,trash=!!$('showDeleted').checked,selected=$('history').value;try{
 const response=await request(`sources/benchmark/${id}/${trash?'deleted-runs':'runs'}`);if(token!==epoch||version!==historyRequest)return;
 historyRecords.clear();$('history').replaceChildren(new Option(trash?'选择已删除记录':'选择已保存记录',''));
 for(const r of response.runs){historyRecords.set(r.run_id,r);$('history').add(new Option(`${new Date(r.created_at).toLocaleString()} · ${runLabels[r.status]||r.status} · ${r.run_id.slice(0,8)}`,r.run_id));}
 $('history').value=historyRecords.has(selected)?selected:historyRecords.has(currentRun?.run_id)?currentRun.run_id:'';historyActions();
 }catch(error){if(token===epoch&&version===historyRequest)status(error.message,true);}}
async function changeHistory(action){
 const id=$('history').value,record=historyRecords.get(id);if(!record||historyMutating)return;
 if(action==='delete'&&!window.confirm(`删除这条${runLabels[record.status]||record.status}记录（${id.slice(0,8)}）？\n记录将移入“已删除记录”，原文件保留，可恢复。`))return;
 historyMutating=true;historyActions();
 try{await request('runs/'+id+'/'+action,{});if(action==='delete'&&currentRun?.run_id===id){epoch++;clear();}
  await history();window.WorkbenchNavigation?.checkpoint();status(action==='delete'?'记录已移入“已删除记录”，可随时恢复。':'记录已恢复，可从历史计算中重新查看。');
 }catch(error){status(error.message,true);}finally{historyMutating=false;historyActions();}
}
function showFrame(index){if(!result)return;frame=Math.max(0,Math.min(result.frames.length-1,index));view.setFrame(frame);$('timeline').value=frame;const t=result.frames[frame].time_s;charts.setCursor(t);$('timeValue').textContent=(t*1000).toFixed(2)+' ms';}
function field(){const steel=$('field').value==='steel';$('steelFilterLabel').hidden=!steel;view?.setField($('field').value,$('steelFilter').value);$('fieldNote').textContent=steel?(result?.mesh.kind==='panel'?'弹性配筋层恢复并经原生记录器核对；积分点均值着色，摘要取原始积分点峰值。':'钢筋纤维采样值沿柱插值着色；未模拟箍筋、滑移或断裂。'):$('field').value==='pressure'?'显示施加在受载面的给定压力，不是空气压力场求解。':'变形已放大；位移色标和曲线保持实际计算值。';}
async function display(run,token){const tick=performance.now(),value=await request('runs/'+run.run_id+'/results');const loaded=performance.now();if(token!==epoch)return;
  result=value;currentRun=run;const column=result.mesh.kind==='column';$('benchmark').value=column?'rc-column-v1':'rc-panel-v1';$('viewTitle').textContent=column?'单柱动态响应':'单板动态响应';$('meshN').value=result.provenance.case.mesh.n;$('dtMs').value=result.provenance.case.analysis.dt_s*1000;$('pressureScale').value=Math.max(...result.provenance.case.loads.curve_si.map(r=>r[1]))/10000;loadPreview();fillSteel();view.setScale(Number($('scale').value));view.setResult(value);charts.setResult(value);charts.setQuantity($('quantity').value);field();$('timeline').max=result.frames.length-1;controls(true);$('emptyState').hidden=true;$('legend').hidden=false;
  const nearest=result.frames.reduce((best,r,i)=>Math.abs(r.time_s-result.peaks.displacement_time_s)<Math.abs(result.frames[best].time_s-result.peaks.displacement_time_s)?i:best,0);showFrame(nearest);
  $('runState').textContent='计算完成';$('resultIdentity').textContent=`弹性参考 · ${run.run_id.slice(0,8)} · 输入 ${result.input_fingerprint.slice(0,8)}`;
  $('peakDisplacement').textContent=(result.peaks.displacement_m*1000).toFixed(4)+' mm';$('peakSteel').textContent=(result.peaks.steel_abs_pa/1e6).toFixed(3)+' MPa';
  const times=result.diagnostics.timings,format=v=>Number.isFinite(v)?v.toFixed(3)+' s':'—';$('wallTime').textContent=format(run.process?.wall_s);$('buildTime').textContent=format(times.build_s);$('solveTime').textContent=format(times.solve_s);$('extractTime').textContent=format(times.stress_read_s);$('loadTime').textContent=(loaded-tick).toFixed(1)+' ms';$('memory').textContent=run.process?.peak_rss_bytes?(run.process.peak_rss_bytes/1048576).toFixed(1)+' MiB':'—';
  $('modelSize').textContent=`完整模型 ${result.mesh.nodes.length} 节点 · ${result.mesh.elements.length} 单元 · ${result.mesh.steel_samples.length} 个钢筋采样位置${result.mesh.symmetry?`；对称域实际求解 ${result.diagnostics.native_element_count} 单元` : ''}${result.diagnostics.dynamic_modes?`，保留全部 ${result.diagnostics.dynamic_modes} 个动力自由度`:''} · ${result.diagnostics.accepted_steps} 步`;
  $('accuracyNote').textContent=result.provenance.case.mesh.n>=16?'此参考算例的 16→32 网格与 32 网格步长减半已通过收敛对照；不代表实际建筑精度。':'当前为基础预览网格；精细结果请选择 32 网格重新计算。';
  const peak=result.mesh.steel_samples.find(s=>s.id===result.peaks.steel_sample_id);$('sampleDetails').textContent=peak?`${peak.id}\nXYZ / m：${peak.position_m.map(v=>v.toFixed(4)).join(', ')}\n应力：${(result.peaks.steel_signed_pa/1e6).toFixed(4)} MPa\n时刻：${(result.peaks.steel_time_s*1000).toFixed(3)} ms\n${peak.scope}`:'零应力工况；无非零应力峰值。';
  for(const [id,name]of [['downloadCsv','curves.csv'],['downloadJson','result.json']]){$(id).href=api+'runs/'+run.run_id+'/artifacts/'+name;$(id).hidden=false;}
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));if(token!==epoch)return;$('renderTime').textContent=(performance.now()-loaded).toFixed(1)+' ms';status('计算结果已载入。位移与钢筋应力为弹性参考解。');
}
async function follow(run,token){if(token!==epoch)return;if(run.deleted_at){clear();status('这条记录已删除，可从“已删除记录”恢复后查看。');return;}currentRun=run;for(;;){if(token!==epoch)return;$('runState').textContent=runLabels[run.status]||run.status;
  if(run.status==='completed'){busy(false);await display(run,token);history();return;}
  if(['failed','cancelled','interrupted'].includes(run.status)){busy(false);status(run.error||'本次计算未完成',run.status!=='cancelled');history();return;}
  await new Promise(r=>setTimeout(r,300));if(token!==epoch)return;run=await request('runs/'+run.run_id);if(token!==epoch)return;currentRun=run;
}}
$('startRun').addEventListener('click',async()=>{const token=++epoch;preparingToken=token;clear();busy(true);status('正在检查参数与计算预算…');try{
  const profile=await request('profiles',{benchmark_id:$('benchmark').value,mesh_n:Number($('meshN').value),dt_s:Number($('dtMs').value)/1000,pressure_scale:Number($('pressureScale').value)});if(token!==epoch)return;
  const check=await request('preflight',{source:profile.source,profile_id:profile.profile_id});if(token!==epoch)return;
  const run=await request('runs',{source:profile.source,profile_id:profile.profile_id,input_fingerprint:check.input_fingerprint,client_request_id:crypto.randomUUID()});if(cancelledPreparations.has(token)){await request('runs/'+run.run_id+'/cancel',{});return;}if(token!==epoch)return;preparingToken=null;
  const url=new URL(location.href);url.searchParams.set('run_id',run.run_id);window.history.replaceState(null,'',url);status('CPU 正在计算；可停止本次任务。');await follow(run,token);
}catch(error){if(token===epoch){busy(false);$('runState').textContent='未完成';status(error.message,true);}}});
$('cancelRun').addEventListener('click',async()=>{if(!currentRun){if(preparingToken!==null)cancelledPreparations.add(preparingToken);epoch++;busy(false);$('runState').textContent='已取消';status('已取消计算准备。');return;}try{await request('runs/'+currentRun.run_id+'/cancel',{});}catch(e){status(e.message,true);}});
$('benchmark').addEventListener('change',configureCase);
for(const id of ['meshN','dtMs','pressureScale'])for(const type of ['input','change'])$(id).addEventListener(type,()=>{epoch++;clear();status('参数已修改，请重新计算。');loadPreview();});
$('field').addEventListener('change',field);$('steelFilter').addEventListener('change',field);$('scale').addEventListener('input',()=>view?.setScale(Number($('scale').value)));$('fitView').addEventListener('click',()=>view?.fit());$('quantity').addEventListener('change',()=>charts.setQuantity($('quantity').value));
$('timeline').addEventListener('input',()=>{playing=false;showFrame(Number($('timeline').value));});$('previousFrame').addEventListener('click',()=>{playing=false;showFrame(frame-1);});$('nextFrame').addEventListener('click',()=>{playing=false;showFrame(frame+1);});
$('play').addEventListener('click',()=>{if(!result)return;playing=!playing;playTime=result.frames[frame].time_s;if(frame===result.frames.length-1)playTime=0;lastTick=performance.now();});
function animate(tick){if(playing&&result){playTime+=(tick-lastTick)/1000*Number($('playSpeed').value);const end=result.frames.at(-1).time_s;if(playTime>=end){playTime=end;playing=false;}let i=result.frames.findIndex(f=>f.time_s>=playTime);showFrame(i<0?result.frames.length-1:i);}const label=playing?'Ⅱ':'▶';if($('play').textContent!==label)$('play').textContent=label;lastTick=tick;requestAnimationFrame(animate);}requestAnimationFrame(animate);
$('savePng').addEventListener('click',()=>{if(!result)return;const a=document.createElement('a');a.href=view.png();a.download='cpu-response.png';a.click();});
$('history').addEventListener('change',async()=>{historyActions();const id=$('history').value;if(!id||$('showDeleted').checked)return;const token=++epoch;clear();try{const run=await request('runs/'+id);if(token===epoch){const url=new URL(location.href);url.searchParams.set('run_id',run.run_id);window.history.replaceState(null,'',url);busy(['queued','running'].includes(run.status));await follow(run,token);}}catch(e){if(token===epoch)status(e.message,true);}});
$('showDeleted').addEventListener('change',()=>history());$('deleteHistory').addEventListener('click',()=>changeHistory('delete'));$('restoreHistory').addEventListener('click',()=>changeHistory('restore'));
const context=new URL(location.href).searchParams;if(/^[a-f0-9]{32}$/.test(context.get('scene_id')||''))$('backPressure').href='/structural-pressure?scene_id='+context.get('scene_id');
async function init(){
 const boot=epoch;let preserveInputs=false,activeRun=null,activeToken=null;
 try{
  const caps=await request('capabilities');available=!!(caps.available&&caps.verified);$('runtimeState').textContent=available?'CPU 内核已验证':'CPU 环境未就绪';
  if(boot!==epoch){preserveInputs=true;busy(false);return;}
  configureCase();busy(false);status(available?'选择单柱或单板，点击开始计算。':caps.reason||'请先配置 CPU 求解环境。',!available);
  const rid=context.get('run_id');
  if(/^[a-f0-9]{32}$/.test(rid||'')){
   const pending=epoch,run=await request('runs/'+rid);
   if(pending!==epoch){preserveInputs=true;return;}
   $('benchmark').value=run.source.id;configureCase();const token=epoch;
   const url=new URL(location.href);url.searchParams.set('run_id',run.run_id);window.history.replaceState(null,'',url);
   busy(['queued','running'].includes(run.status));
   if(['queued','running'].includes(run.status)){currentRun=run;activeRun=run;activeToken=token;}
   else{await follow(run,token);preserveInputs=token!==epoch;}
  }
 }catch(e){status(e.message,true);}
 finally{
  await registerResponseNavigation(preserveInputs);
  if(activeRun&&activeToken===epoch)follow(activeRun,activeToken).catch(e=>{if(activeToken===epoch)status(e.message,true);});
 }
}init();

function fieldsMatchResult(fields){
 if(!result)return false;
 const saved=new Map((fields||[]).map(f=>[f.key,f.value])),c=result.provenance.case;
 const close=(value,wanted)=>value!==undefined&&value.trim()!==''&&Number.isFinite(Number(value))&&Math.abs(Number(value)-wanted)<=1e-10*Math.max(1,Math.abs(wanted));
 return saved.get('id:benchmark')===(result.mesh.kind==='column'?'rc-column-v1':'rc-panel-v1')&&close(saved.get('id:meshN'),c.mesh.n)&&close(saved.get('id:dtMs'),c.analysis.dt_s*1000)&&close(saved.get('id:pressureScale'),Math.max(...c.loads.curve_si.map(r=>r[1]))/10000);
}
async function registerResponseNavigation(preserveInputs=false){
 const n=window.WorkbenchNavigation;if(!n)return;
 const key=()=>{const p=new URL(location.href).searchParams;return (p.get('scene_id')||'standalone')+':'+(p.get('run_id')||'new');};
 await n.register('response',{
  restoreIdentity:key,context:()=>({identity:key(),label:($('benchmark').value==='rc-panel-v1'?'单板':'单柱')+(result?' · 已保存结果':' · 参数草稿'),url:location.pathname+location.search}),
  beforeLeave:()=>{if(preparingToken!==null)throw Error('计算准备尚未结束，请先停止本次准备。');},
  capture:()=>({fields:n.captureFields(document.body),hasResult:!!result,runId:currentRun?.run_id||null,frame}),
  restore:s=>{
   if(preserveInputs)return;
   const source=s.fields?.find(f=>f.key==='id:benchmark');if(source)$('benchmark').value=source.value;
   const attached=s.runId&&s.runId===currentRun?.run_id;
   if(!attached||(result&&!fieldsMatchResult(s.fields)))configureCase();
   n.restoreFields(document.body,s.fields);fillSteel();n.restoreFields(document.body,s.fields);
   view?.setScale(Number($('scale').value));field();charts.setQuantity($('quantity').value);loadPreview();
   history();if(result)showFrame(s.frame||0);else status('已恢复本标签页参数；点击开始计算前不会运行。');
  },
 });
}

async function loadBuildingTrial(){
 try{
  const data=await request('building-trial');buildingTrial=data.trial;
  if(data.status!=='saved_trial'||!buildingTrial){$('buildingTrialState').textContent='已有首试资料暂不可用';$('buildingTrialBrief').textContent=data.reason||'当前环境未附带首试结果；整栋收敛仍待验证。';return;}
  const t=buildingTrial;$('buildingTrialState').textContent='整栋首试已完成 · 收敛待验证';
  $('buildingTrialBrief').textContent=`单墙 ${t.peak_pressure_kpa} kPa · ${t.duration_ms} ms · 历史耗时 ${Number(t.wall_s).toFixed(1)} s`;
  $('openBuildingTrial').disabled=false;
 }catch(error){$('buildingTrialState').textContent='已有首试资料暂不可用';$('buildingTrialBrief').textContent=error.message;}
}
$('openBuildingTrial').addEventListener('click',()=>{
 if(!buildingTrial)return;const t=buildingTrial,a=t.artifacts;
 $('buildingTrialFacts').textContent=`受载墙：${t.target}\n峰值压力：${t.peak_pressure_kpa} kPa；分析 ${t.duration_ms} ms，步长 ${t.dt_ms} ms\n${t.nodes} 个结构节点、${t.elements} 个承重单元；历史总耗时 ${Number(t.wall_s).toFixed(3)} s\n全楼位移峰值 ${(t.peaks.displacement_m*1000).toFixed(6)} mm；钢筋原始采样点应力绝对峰值 ${(t.peaks.steel_abs_pa/1e6).toFixed(6)} MPa`;
 for(const[id,name]of [['buildingTrialCsv','curves.csv'],['buildingTrialJson','result.json'],['buildingTrialReport','report.md']]){$(id).hidden=!a[name];if(a[name])$(id).href=a[name];}
 for(const[id,name]of [['buildingTrialDeformation','deformation-and-steel.png'],['buildingTrialCurves','response-curves.png']]){$(id+'Figure').hidden=!a[name];if(a[name])$(id).src=a[name];}
 $('buildingTrialDialog').showModal();
});
$('closeBuildingTrial').addEventListener('click',()=>$('buildingTrialDialog').close());loadBuildingTrial();
