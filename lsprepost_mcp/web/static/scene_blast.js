import {createSceneView} from './scene_blast_view.js';

const $=id=>document.getElementById(id),API='/api/cpu-blast/';
const sourceIds=['commercial_supermarket','residential_community','subway_entrance','city_street','fixed_three_storey'];
const inputIds=['sourceKind','projectName','tntX','tntY','tntZ','tntMass','duration','meshSize'];
const state={model:null,modelFingerprint:null,result:null,runId:null,activeRun:null,selected:0,selectedItem:null,frame:0,playing:false,epoch:0,loadEpoch:0,loading:false,busy:false,drafts:{},sourceKey:null,history:[]};
const labels={queued:'排队中',running:'CPU 计算中',completed:'计算完成',partial:'部分结果',failed:'计算失败',cancelled:'已停止',timed_out:'达到时间预算',interrupted:'服务重启中断'};
let view,timer=null,lastTick=0,playTime=0;

async function api(path,payload){
  const response=await fetch(API+path,payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'场景请求失败');return data;
}
function message(text,error=false){$('jobMessage').textContent=text;$('jobMessage').style.color=error?'var(--wb-danger)':'';}
function download(name,data,type='application/json'){
  const a=document.createElement('a'),url=URL.createObjectURL(new Blob([typeof data==='string'?data:JSON.stringify(data,null,2)],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function configKey(v){return JSON.stringify([v.source.kind,v.source.project_name||null,v.source.scene_id||null,v.source.tnt_scene_id||null,...v.tnt.position_m,v.tnt.mass_kg,v.analysis.duration_s,v.analysis.mesh_m]);}
function rawFields(){return Object.fromEntries(inputIds.map(id=>[id,$(id).value]));}
function applyRaw(raw){for(const id of inputIds)if(typeof raw?.[id]==='string')$(id).value=raw[id];}
function sourceKey(){const q=new URL(location.href).searchParams;return $('sourceKind').value+'@'+$('projectName').value+'@'+($('sourceKind').value==='fixed_three_storey'?JSON.stringify([q.get('scene_id'),q.get('tnt_scene_id')]):'');}
function getConfig(preview=false){
  const num=id=>{if($(id).value.trim()==='')throw Error('请填写 '+$(id).closest('label').textContent.trim());const v=Number($(id).value);if(!Number.isFinite(v))throw Error('参数必须为有效数字');return v;};
  const source={kind:$('sourceKind').value,project_name:$('projectName').value||null};
  const query=new URL(location.href).searchParams;if(source.kind==='fixed_three_storey')for(const key of ['scene_id','tnt_scene_id'])if(query.has(key))source[key]=query.get(key);
  const config={schema_version:'scene-blast-input@1',source,tnt:{position_m:preview?[10,-10,0]:[num('tntX'),num('tntY'),num('tntZ')],mass_kg:preview?10:num('tntMass')},analysis:{duration_s:preview?.25:num('duration'),mesh_m:Number($('meshSize').value)}};
  if(!preview&&(config.tnt.position_m[2]!==0||config.tnt.mass_kg<.01||config.tnt.mass_kg>10000||config.analysis.duration_s<.05||config.analysis.duration_s>1))throw Error('请检查参数范围：贴地 Z=0，当量 0.01–10000 kg，时长 0.05–1 s');
  return config;
}
function updateUrl(){
  const url=new URL(location.href);url.searchParams.set('source',$('sourceKind').value);
  if($('projectName').value)url.searchParams.set('project_name',$('projectName').value);else url.searchParams.delete('project_name');
  if(state.runId)url.searchParams.set('run_id',state.runId);else url.searchParams.delete('run_id');
  history.replaceState(history.state,'',url.pathname+url.search);
}
function checkpoint(){try{window.WorkbenchNavigation?.checkpoint();}catch(error){message(error.message,true);}}
function updateButtons(){
  let valid=true;try{getConfig();}catch{valid=false;}
  $('startSimulation').disabled=!valid||!state.model||!state.model.checks.supported||state.loading||state.busy||!!state.activeRun||state.sourceKey!==sourceKey();
  $('cancelSimulation').hidden=!state.activeRun;$('jobProgress').hidden=!state.activeRun;
  for(const id of ['downloadCurves','downloadResult','playScene','sceneTime'])$(id).disabled=!state.result;
}
function invalidate(){
  state.epoch++;state.resultTargetRun=null;state.result=null;state.runId=null;state.playing=false;state.frame=0;$('playScene').textContent='▶';$('sceneTime').value=0;$('sceneTime').max=0;$('timeLabel').textContent='0.000 s';
  for(const id of ['maxDisplacement','maxSteel','failureCount'])$(id).textContent='—';$('terminationNote').hidden=true;$('sceneLegend').hidden=true;$('resultState').textContent='待计算';
  state.gravity=null;$('gravityPanel').hidden=true;$('downloadGravity').disabled=true;
  $('timingFacts').textContent='当前参数尚未计算。原结果保留在历史记录。';$('sceneChart').replaceChildren(svgNode('text',{x:30,y:85},'计算后查看曲线，当前参数没有计算结果。'));
  if(state.model)view.frame(null,null);updateUrl();updateButtons();
}
function syncTnt(){
  const xyz=['tntX','tntY','tntZ'].map(id=>Number($(id).value));if(xyz.every(Number.isFinite))view.setTnt(xyz);
}
function materialText(m){$('materialFacts').textContent=`参考混凝土 E=${m.e_pa/1e9} GPa，ft=${m.ft_pa/1e6} MPa，fc=${m.fc_pa/1e6} MPa，Gf=${m.gf_n_m} N/m；钢筋 fy=${m.steel_fy_pa/1e6} MPa，理想弹塑性，塑性断裂应变 ${m.steel_rupture_strain}。缺失配筋采用 ${(m.reference_steel_ratio*100).toFixed(2)}% 参考率。参数尚未经该建筑试验校准。`;}
function listText(id,values){$(id).replaceChildren(...values.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));}
function installModel(prepared){
  state.model=prepared.model;state.modelFingerprint=prepared.model_fingerprint;state.selected=0;state.selectedItem=state.model.display[0]||null;
  view.load(state.model);syncTnt();state.sourceKey=sourceKey();
  const b=state.model.budget;$('modelFacts').textContent=`${b.bodies} 个计算块 · ${b.dofs} 自由度 · ${b.springs} 个分布连接点\n质量 ${(state.model.mass_ledger.total_kg/1000).toFixed(1)} t · ${state.model.checks.supported?'承载路径已连到基础':'发现未支承构件，禁止计算'}`;
  $('modelSystem').textContent=state.model.source.kind==='fixed_three_storey'?'柱与楼板承重；填充墙计质量、传压力。沿用已核验的规整参考。':'沿用既有粗壳外形与支承，采用承重壳参考。缺失材料与配筋使用参考假设。';
  $('sceneName').textContent=$('sourceKind').selectedOptions[0].textContent+($('projectName').value?' · '+$('projectName').value:'');
  $('sceneIdentity').textContent='模型 '+state.modelFingerprint.slice(0,10)+' · 原模型外观 / 独立 CPU 宏单元';
  listText('assumptions',state.model.assumptions||[]);materialText(prepared.material);$('sceneLoading').hidden=true;$('resultState').textContent='待计算';
  document.body.dataset.sceneReady='true';document.body.dataset.sceneKind=$('sourceKind').value;updateButtons();
}
async function loadModel(){
  const epoch=++state.loadEpoch,key=sourceKey();state.loading=true;document.body.dataset.sceneReady='false';$('sceneLoading').hidden=false;$('sceneLoading').textContent='正在准备已有建筑几何与连接…';updateButtons();
  try{const prepared=await api('prepare',getConfig(true));if(epoch!==state.loadEpoch||key!==sourceKey())return;installModel(prepared);message('模型已载入。调整 TNT 后点击“开始 CPU 模拟”。');}
  catch(error){if(epoch===state.loadEpoch){state.model=null;$('sceneLoading').textContent=error.message;message(error.message,true);$('resultState').textContent='模型未就绪';}}
  finally{if(epoch===state.loadEpoch){state.loading=false;updateButtons();}}
}
function selectItem(item,body){state.selected=body;state.selectedItem=item;$('selectionName').textContent=item.id;$('selectionNote').textContent=item.response==='attached_mass_display'?'附属外观随承载块映射；此处曲线属于承载块，不代表该填充墙自身开裂。':'计算宏单元 '+state.model.bodies[body].id+'；钢筋值为连接轴向包络。';drawFrame();}
function svgNode(tag,attributes,text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attributes))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
function chart(){
  if(!state.result)return;const field=$('curveField').value,idx=state.selected,frames=state.result.frames,values=frames.map(f=>f[field]?.[idx]||0),max=Math.max(...values,1e-12),last=frames.at(-1).time_s||1;
  const path=values.map((v,i)=>(i?'L':'M')+(55+frames[i].time_s/last*820).toFixed(2)+','+(125-v/max*100).toFixed(2)).join(' ');
  $('chartTitle').textContent=state.selectedItem?'选中构件的响应':'首个计算块的响应';
  $('sceneChart').replaceChildren(svgNode('path',{d:'M55 20V125H875',fill:'none',stroke:'#d3dfe4'}),svgNode('path',{d:path,fill:'none',stroke:'#16758a','stroke-width':2}),svgNode('text',{x:5,y:28},max.toPrecision(3)),svgNode('text',{x:30,y:129},'0'),svgNode('text',{x:55,y:150},'0 s'),svgNode('text',{x:785,y:150},last.toFixed(3)+' s'));
}
function drawFrame(){
  if(!state.model)return;const result=state.result,frame=result?.frames[state.frame],field=$('field').value;
  let max=1;if(result&&field!=='appearance'){max=field==='damage'?1:1e-12;if(field!=='damage')for(const frame of result.frames)for(const value of frame[field]||[])max=Math.max(max,value);}
  view.frame(frame,result?.frames[0],field,Math.min(100,Math.max(1,Number($('deformationScale').value)||1)),max);
  $('sceneLegend').hidden=!result||field==='appearance';$('legendLabel').textContent=$('field').selectedOptions[0].textContent;$('legendMax').textContent=max.toPrecision(4);
  if(frame){$('timeLabel').textContent=frame.time_s.toFixed(3)+' s';$('sceneTime').value=state.frame;}chart();
}
function showResult(result,job){
  if(result.input_fingerprint!==job.input_fingerprint||result.model_fingerprint!==state.modelFingerprint)throw Error('结果身份与当前模型不一致，已拒绝混用');
  state.result=result;state.runId=job.run_id;state.frame=0;state.playing=false;state.frameMax=null;$('sceneTime').max=result.frames.length-1;
  $('maxDisplacement').textContent=Math.max(...result.peaks.displacement_mm).toFixed(3)+' mm';$('maxSteel').textContent=Math.max(...result.peaks.steel_mpa).toFixed(2)+' MPa';
  const cracks=new Set(result.events.filter(e=>e.kind==='cracking').map(e=>e.body_id)),ruptures=new Set(result.events.filter(e=>e.kind==='steel_rupture').map(e=>e.body_id));
  (result.initial_state?.damage||[]).forEach((v,i)=>{if(v>1e-8)cracks.add(state.model.bodies[i].id);});
  (result.initial_state?.ruptured||[]).forEach((v,i)=>{if(v>.5)ruptures.add(state.model.bodies[i].id);});$('failureCount').textContent=cracks.size+' / '+ruptures.size;
  $('resultState').textContent=labels[result.status]||result.status;$('terminationNote').hidden=!result.termination_reason;$('terminationNote').textContent=result.termination_reason||'';
  const m=result.metrics;$('timingFacts').textContent=`CPU 实际耗时 ${m.wall_s.toFixed(2)} s\n积分步长 ${(m.dt_s*1000).toPrecision(3)} ms · ${m.completed_steps}/${m.planned_steps} 步\n初始重力相对残差 ${m.gravity_relative_residual.toExponential(2)}\n曲线为回放采样，峰值逐步保留。`;
  listText('resultLimits',result.limitations||[]);$('field').value='damage';drawFrame();updateUrl();updateButtons();checkpoint();showGravity(job);
}
async function showGravity(job){
  const epoch=state.epoch;state.gravity=null;$('gravityPanel').hidden=false;$('downloadGravity').disabled=true;
  if(!job.gravity_sha256){$('gravityFacts').textContent='该历史记录未保存逐次自重诊断；不会自动重算。';return;}
  $('gravityFacts').textContent='正在载入已保存的自重诊断…';
  try{
    const d=await api('runs/'+job.run_id+'/gravity');if(epoch!==state.epoch)return;
    if(d.input_fingerprint!==job.input_fingerprint||d.model_fingerprint!==job.model_fingerprint||JSON.stringify(d.method)!==JSON.stringify(job.method))throw Error('自重诊断身份校验失败');
    state.gravity=d;const f=d.final||d.last_trial||{},c=f.connections||{},worst=f.worst_body?.body_id||'—',spring=f.worst_connection;
    const num=(v,digits=3)=>Number.isFinite(v)?Number(v).toPrecision(digits):'—';
    $('gravityFacts').textContent=`自重状态：${d.status==='converged'?'已平衡':labels[d.status]||d.status}\n已收敛荷载：${(100*(d.accepted_load_factor||0)).toFixed(1)}%\n${d.restored_to_accepted_state?'回滚状态对完整自重的残差':'已记录状态的残差'}：${num(f.scaled_relative_residual)}\n力残差 ${num(f.force_residual_n)} N · 力矩残差 ${num(f.moment_residual_nm)} N·m\n最不平衡构件：${worst}\n${spring?'连接利用率最高：#'+spring.spring_index+' · '+spring.a_body_id+' ↔ '+spring.b_body_id+'\n':''}开裂连接 ${c.cracked_concrete??'—'} · 压塑性 ${c.compression_plastic??'—'} · 钢筋塑性 ${c.steel_plastic??'—'}\n自重阶段用时 ${num(d.wall_s)} s\n${d.reason||'自重已有应力与损伤保留为初态，爆炸事件单独记录。'}${d.terminal_observation?'\n进程已终止；仅保留末次快照，不能确认回滚。':''}`;
    const stability=d.last_stability||d.attempts?.at(-1)?.stability;
    if(stability){
      const status={positive_definite:'正定验证已通过',non_positive:'未满足正定阈值',unresolved:'数值判定未完成',running:'正在验证'}[stability.status]||stability.status;
      $('gravityFacts').textContent+='\n稳定性判定：'+status+(stability.status==='unresolved'?'；不能据此判定建筑失稳':'');
    }
    $('downloadGravity').disabled=false;
  }catch(error){if(epoch===state.epoch)$('gravityFacts').textContent='自重诊断读取失败：'+error.message;}
}
async function poll(){
  clearTimeout(timer);const rid=state.activeRun;if(!rid)return;
  try{
    const job=await api('runs/'+rid);if(state.activeRun!==rid)return;
    $('jobProgress').value=job.progress?.fraction||.02;message((labels[job.status]||job.status)+(job.progress?.time_s!==undefined?' · '+job.progress.time_s.toFixed(3)+' s':''));
    if(['queued','running'].includes(job.status)){timer=setTimeout(poll,450);return;}
    state.activeRun=null;updateButtons();await historyList();
    let same=false;try{same=state.resultTargetRun===rid&&configKey(job.config)===configKey(getConfig())&&job.model_fingerprint===state.modelFingerprint;}catch{}
    if(job.result_sha256&&same){const epoch=state.epoch,result=await api('runs/'+rid+'/result');if(epoch===state.epoch)showResult(result,job);}
    else if(job.result_sha256)message('后台任务已结束，结果保存在历史记录；当前参数或历史场景已切换，未覆盖当前视图。');
    else{message(job.error||labels[job.status],true);if(same){$('resultState').textContent=labels[job.status]||job.status;await showGravity(job);}}
    checkpoint();
  }catch(error){message('任务查询失败：'+error.message+'。刷新页面可重新查询，任务不会自动重跑。',true);updateButtons();}
}
async function start(){
  const config=getConfig();state.busy=true;updateButtons();const epoch=state.epoch;
  try{const job=await api('runs',{input:config,model_fingerprint:state.modelFingerprint,request_id:crypto.randomUUID().replaceAll('-','')});
    state.activeRun=job.run_id;if(epoch===state.epoch){invalidate();state.resultTargetRun=job.run_id;$('resultState').textContent='CPU 计算中';}checkpoint();poll();
  }finally{state.busy=false;updateButtons();}
}
async function historyList(){
  const epoch=state.historyEpoch=(state.historyEpoch||0)+1,key=sourceKey(),deleted=$('showTrash').checked,previous=$('sceneHistory').value;
  state.history=[];$('sceneHistory').replaceChildren(new Option('正在载入记录…',''));$('sceneHistory').dataset.historyMode='loading';historyButtons();
  const data=await api(deleted?'deleted-runs':'runs');if(epoch!==state.historyEpoch||key!==sourceKey()||deleted!==$('showTrash').checked)return;state.history=data.runs;
  const q=new URL(location.href).searchParams,fixed=$('sourceKind').value==='fixed_three_storey',scene=fixed?(q.get('scene_id')||''):'',tntScene=fixed?(q.get('tnt_scene_id')||''):'';
  $('sceneHistory').replaceChildren(new Option('选择已保存记录',''),...data.runs.filter(j=>j.source.kind===$('sourceKind').value&&(j.source.project_name||'')===$('projectName').value&&(j.source.scene_id||'')===scene&&(j.source.tnt_scene_id||'')===tntScene).map(j=>new Option(new Date(j.created_at).toLocaleString('zh-CN',{hour12:false})+' · '+(labels[j.status]||j.status)+' · '+j.run_id.slice(0,6),j.run_id)));
  $('sceneHistory').dataset.historyMode=deleted?'deleted':'active';
  if([...$('sceneHistory').options].some(o=>o.value===previous))$('sceneHistory').value=previous;historyButtons();
}
function historyButtons(){const j=state.history.find(j=>j.run_id===$('sceneHistory').value),deleted=$('showTrash').checked;$('loadHistory').disabled=!j||deleted;$('deleteHistory').disabled=!j||deleted||['queued','running'].includes(j.status);$('deleteHistory').hidden=deleted;$('restoreHistory').hidden=!deleted;$('restoreHistory').disabled=!j;}
async function restoreRecord(rid){
  state.loadEpoch++;state.loading=false;const epoch=++state.epoch;const [job,snap]=await Promise.all([api('runs/'+rid),api('runs/'+rid+'/input')]);if(epoch!==state.epoch)return;
  const c=snap.config;$('sourceKind').value=c.source.kind;$('projectName').value=c.source.project_name||'';
  const url=new URL(location.href);for(const key of ['scene_id','tnt_scene_id']){if(c.source[key])url.searchParams.set(key,c.source[key]);else url.searchParams.delete(key);}history.replaceState(history.state,'',url.pathname+url.search);
  ['tntX','tntY','tntZ'].forEach((id,i)=>$(id).value=c.tnt.position_m[i]);$('tntMass').value=c.tnt.mass_kg;$('duration').value=c.analysis.duration_s;$('meshSize').value=String(c.analysis.mesh_m);
  invalidate();installModel({model:snap.model,model_fingerprint:snap.model_fingerprint,material:snap.material});
  if(job.result_sha256){const current=state.epoch,result=await api('runs/'+rid+'/result');if(current===state.epoch)showResult(result,job);}
  else if(['queued','running'].includes(job.status)){state.activeRun=rid;state.resultTargetRun=rid;poll();}
  else{message(job.error||labels[job.status],true);$('resultState').textContent=labels[job.status]||job.status;await showGravity(job);}
  updateButtons();checkpoint();
}
function bind(id,event,fn){$(id).addEventListener(event,e=>Promise.resolve().then(()=>fn(e)).catch(error=>{message(error.message,true);updateButtons();}));}

async function init(){
  try{view=createSceneView($('sceneViewport'),{onSelect:selectItem,onMove:xyz=>{['tntX','tntY','tntZ'].forEach((id,i)=>$(id).value=xyz[i].toFixed(3));invalidate();$('tntX').dispatchEvent(new Event('input',{bubbles:true}));}});}
  catch(error){$('sceneLoading').textContent='三维视图初始化失败：'+error.message;throw error;}
  const url=new URL(location.href);if(sourceIds.includes(url.searchParams.get('source')))$('sourceKind').value=url.searchParams.get('source');
  $('projectName').value=url.searchParams.get('project_name')||'';
  const capabilities=await api('catalog');materialText(capabilities.material);
  if(!capabilities.available)throw Error('当前 Python 缺少 NumPy / SciPy，尚不能准备 CPU 场景');
  const importedProject=capabilities.projects?.find(p=>p.project_name===$('projectName').value);
  if(importedProject&&!url.searchParams.has('source'))$('sourceKind').value=importedProject.kind;
  const fixedMesh=()=>{const fixed=$('sourceKind').value==='fixed_three_storey';$('meshSize').disabled=fixed;if(fixed)$('meshSize').value='2.5';};fixedMesh();
  bind('sourceKind','change',async()=>{
    if(state.sourceKey){const previous=rawFields();previous.sourceKind=state.model?.source.kind||previous.sourceKind;state.drafts[state.sourceKey]=previous;}const kind=$('sourceKind').value;$('projectName').value='';
    const key=sourceKey();applyRaw(state.drafts[key]);$('sourceKind').value=kind;fixedMesh();invalidate();await loadModel();await historyList();checkpoint();
  });
  for(const id of inputIds.filter(id=>id!=='sourceKind'))bind(id,'input',()=>{invalidate();syncTnt();try{getConfig();message(state.sourceKey===sourceKey()?'参数已修改，等待开始模拟。':'项目已改变，请点击“载入当前模型”。');}catch(error){message(error.message,true);}});
  bind('meshSize','change',async()=>{invalidate();await loadModel();checkpoint();});
  bind('loadScene','click',async()=>{fixedMesh();invalidate();await loadModel();await historyList();checkpoint();});
  bind('startSimulation','click',start);bind('cancelSimulation','click',async()=>{if(state.activeRun)await api('runs/'+state.activeRun+'/cancel',{});message('已请求停止；输入与日志会保留。');poll();});
  bind('field','change',drawFrame);bind('deformationScale','input',drawFrame);bind('curveField','change',chart);bind('fitScene','click',()=>view.fit());
  bind('saveImage','click',()=>{const a=document.createElement('a');a.href=view.image();a.download='cpu-blast-scene.png';a.click();});
  bind('sceneTime','input',()=>{state.playing=false;$('playScene').textContent='▶';state.frame=Number($('sceneTime').value);drawFrame();});
  bind('playScene','click',()=>{state.playing=!state.playing;$('playScene').textContent=state.playing?'Ⅱ':'▶';playTime=state.result.frames[state.frame].time_s;lastTick=performance.now();});
  bind('showTrash','change',historyList);bind('sceneHistory','change',historyButtons);bind('loadHistory','click',()=>restoreRecord($('sceneHistory').value));
  bind('deleteHistory','click',async()=>{const rid=$('sceneHistory').value;await api('runs/'+rid+'/delete',{});if(state.runId===rid)invalidate();await historyList();message('记录已移入已删除列表，原文件保留，可恢复。');checkpoint();});
  bind('restoreHistory','click',async()=>{await api('runs/'+$('sceneHistory').value+'/restore',{});await historyList();message('记录已恢复，可在正常历史列表载入。');});
  bind('saveScene','click',()=>download('cpu-blast-scene.json',{schema_version:'cpu-blast-draft@1',fields:rawFields()}));
  bind('importScene','change',async()=>{const file=$('importScene').files[0];if(!file)return;if(file.size>100000)throw Error('场景参数文件过大');const data=JSON.parse(await file.text());if(data.schema_version!=='cpu-blast-draft@1'||!sourceIds.includes(data.fields?.sourceKind))throw Error('不支持的场景参数文件');applyRaw(data.fields);fixedMesh();invalidate();await loadModel();await historyList();checkpoint();$('importScene').value='';});
  bind('downloadResult','click',()=>download('cpu-blast-result.json',state.result));
  bind('downloadGravity','click',()=>{if(state.gravity)download('cpu-blast-gravity-diagnostics.json',state.gravity);});
  bind('downloadCurves','click',()=>{const i=state.selected;download('cpu-blast-curves.csv','time_s,body_id,displacement_mm,steel_mpa,damage,pressure_kpa\n'+state.result.frames.map(f=>[f.time_s,JSON.stringify(state.model.bodies[i].id),f.displacement_mm[i],f.steel_mpa[i],f.damage[i],f.pressure_kpa[i]].join(',')).join('\n'),'text/csv;charset=utf-8');});
  await loadModel();await historyList();
  while(!window.WorkbenchNavigation)await new Promise(resolve=>setTimeout(resolve,10));
  await window.WorkbenchNavigation.register('blast',{
    context:()=>({identity:'scene-blast:'+sourceKey(),revision:'scene-blast-draft@1',label:$('sceneName').textContent,url:location.pathname+location.search}),
    restoreIdentity:()=> 'scene-blast:'+sourceKey(),
    capture:()=>({schema_version:'scene-blast-draft@1',fields:window.WorkbenchNavigation.captureFields(document),drafts:state.drafts,activeRun:state.activeRun,resultTargetRun:state.resultTargetRun,runId:state.runId}),
    restore:async saved=>{if(saved.schema_version!=='scene-blast-draft@1')throw Error('CPU 场景草稿版本不支持');window.WorkbenchNavigation.restoreFields(document,saved.fields);state.drafts=saved.drafts||{};fixedMesh();invalidate();await loadModel();await historyList();state.activeRun=saved.activeRun||null;state.resultTargetRun=saved.resultTargetRun||null;if(saved.runId)await restoreRecord(saved.runId);else if(state.activeRun)poll();updateButtons();},
  });
  if(url.searchParams.get('run_id')&&!state.runId&&!state.activeRun)await restoreRecord(url.searchParams.get('run_id'));
  document.body.dataset.sceneInitialized='true';
  function tick(now){
    if(state.playing&&state.result){playTime+=(now-lastTick)/1000*Number($('playSpeed').value);const frames=state.result.frames;let index=state.frame;while(index<frames.length-1&&frames[index+1].time_s<=playTime)index++;
      if(index!==state.frame){state.frame=index;drawFrame();}if(playTime>=frames.at(-1).time_s){state.playing=false;$('playScene').textContent='▶';state.frame=0;}}
    lastTick=now;requestAnimationFrame(tick);
  }requestAnimationFrame(tick);
}
init().catch(error=>{message(error.message,true);$('sceneLoading').hidden=false;$('sceneLoading').textContent=error.message;$('resultState').textContent='初始化失败';});
