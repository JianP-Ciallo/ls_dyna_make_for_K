import {renderScene,renderCurve} from './structural_pressure_view.js';
const $=id=>document.getElementById(id),clone=v=>structuredClone(v),api='/api/architecture/pressure/';
let schema=null,scene=null,preview=null,generation=0,epoch=0,busy=false,jobToken=0;
const view={plan:false,zoom:1,layers:{building:true,ground:true,air:true,monitors:true}};

function node(tag,content,className){const n=document.createElement(tag);if(content!==undefined)n.textContent=content;if(className)n.className=className;return n;}
function status(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);}
function buttons(){
  $('saveScene').disabled=!schema||busy;$('previewScene').disabled=!schema||busy;
  $('exportScene').disabled=!schema||busy||!preview?.exportable;
  $('newScene').disabled=!schema||busy;$('openSaved').disabled=!schema||busy;
}
async function request(path,payload){
  const response=await fetch(api+path,payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json();if(!response.ok){const reason=typeof result.error==='string'?result.error:result.error?.message;throw Error((response.status===409?'工况版本冲突：':'')+(reason||`HTTP ${response.status}`));}return result;
}
function parseCurve(value){
  const lines=value.trim().split(/\r?\n/).filter(v=>v.trim());if(!value.trim())return [];
  if(/^time_ms\s*,\s*pressure_kpa$/i.test(lines[0].trim()))lines.shift();
  if(lines.length>10000)throw Error('曲线最多 10,000 行');
  return lines.map((line,i)=>{const fields=line.trim().split(/[,;\s]+/);if(fields.length!==2)throw Error(`曲线第 ${i+1} 行需两个数值`);const values=fields.map(Number);if(!values.every(Number.isFinite))throw Error(`曲线第 ${i+1} 行含非法数值`);return values;});
}
function monitors(){return [...$('monitorList').querySelectorAll('.monitor')].map(card=>({id:card.querySelector('[data-monitor-id]').value,kind:card.querySelector('select').value,position_m:[...card.querySelectorAll('[data-coordinate]')].map(i=>numeric(i))}));}
function numeric(input){if(!input.value.trim()||!Number.isFinite(Number(input.value)))throw Error('请填写有效数值');return Number(input.value);}
function config(){
  return {name:$('sceneName').value,notes:$('notes').value,target:{component_id:$('targetComponent').value,face:$('targetFace').value},
    curve_ms_kpa:parseCurve($('curveText').value),source:{reference:$('sourceReference').value,reviewer:$('sourceReviewer').value,reviewed:$('reviewed').checked},
    monitors:monitors(),controls:{termination_ms:numeric($('termination')),plot_ms:numeric($('plotInterval')),history_ms:numeric($('historyInterval'))}};
}
function drawable(){try{return config();}catch{return {target:{component_id:$('targetComponent').value,face:$('targetFace').value},monitors:[]};}}
function draw(){if(!schema)return;const c=drawable();renderScene($('sceneView'),schema.geometry,c,preview,view,cid=>{if(busy)return;$('componentFilter').value='';fillComponents(cid);dirty();tab('surface');});try{renderCurve($('curveChart'),parseCurve($('curveText').value));}catch{renderCurve($('curveChart'),[]);}}
function dirty(){
  generation++;preview=null;$('saveState').textContent=scene?'已修改 · r'+scene.revision:'未保存';
  $('previewState').textContent='待校验';$('surfaceSummary').textContent='尚未解析受载面';
  $('checks').textContent='参数已修改，需要重新校验。';
  for(const s of $('monitorList').querySelectorAll('.sample'))s.textContent='待解析';
  buttons();draw();targetInfo();
}
function targetInfo(){const c=schema?.geometry.components.find(c=>c.id===$('targetComponent').value);$('targetInfo').textContent=c?`${c.id}\n包络：${c.bounds_m.map(v=>v.toFixed(3)).join(', ')} m`:'';}
function fillComponents(selected){
  const current=selected||$('targetComponent').value,filter=$('componentFilter').value.toLowerCase();$('targetComponent').replaceChildren();
  const groups=new Map();
  for(const c of schema.geometry.components){if(!c.id.toLowerCase().includes(filter)&&c.id!==current)continue;const key=Number.isInteger(c.level)?'第 '+(c.level+1)+' 层':'基础与附属';if(!groups.has(key)){const group=node('optgroup');group.label=key;groups.set(key,group);$('targetComponent').append(group);}const option=node('option',c.id);option.value=c.id;groups.get(key).append(option);}
  if(current)$('targetComponent').value=current;targetInfo();
}
function addMonitor(m){
  const card=node('div',undefined,'monitor');const head=node('label','监测名称');const id=node('input');id.value=m.id;id.maxLength=40;id.dataset.monitorId='';head.append(id);card.append(head);
  const kind=node('select');kind.setAttribute('aria-label','监测类型');for(const[k,label]of [['structure_node','建筑节点响应'],['ground_node','地面节点响应'],['solid_stress','建筑实体应力']]){const o=node('option',label);o.value=k;kind.append(o);}kind.value=m.kind;card.append(kind);
  const xyz=node('div',undefined,'xyz');['X','Y','Z'].forEach((axis,i)=>{const label=node('label',axis+' / m'),input=node('input');input.type='number';input.step='any';input.value=m.position_m[i];input.dataset.coordinate=axis;label.append(input);xyz.append(label);});card.append(xyz);
  card.append(node('p','待解析','sample'));const remove=node('button','删除');remove.type='button';remove.addEventListener('click',()=>{card.remove();dirty();});card.append(remove);$('monitorList').append(card);
}
function renderConfig(c){
  $('sceneName').value=c.name;$('notes').value=c.notes;$('curveText').value=c.curve_ms_kpa.map(r=>r.join(',')).join('\n');$('curveFile').value='';
  $('sourceReference').value=c.source.reference;$('sourceReviewer').value=c.source.reviewer;$('reviewed').checked=c.source.reviewed;
  $('componentFilter').value='';fillComponents(c.target.component_id);$('targetFace').value=c.target.face;
  $('termination').value=c.controls.termination_ms;$('plotInterval').value=c.controls.plot_ms;$('historyInterval').value=c.controls.history_ms;
  $('monitorList').replaceChildren();for(const m of c.monitors)addMonitor(m);dirty();
}
function tab(name){for(const b of document.querySelectorAll('[data-tab]')){b.classList.toggle('active',b.dataset.tab===name);b.setAttribute('aria-selected',b.dataset.tab===name?'true':'false');}for(const p of document.querySelectorAll('[data-pane]'))p.hidden=p.dataset.pane!==name;}
async function operation(fn){if(busy)return;busy=true;buttons();try{await fn();}catch(error){status(error.message,true);}finally{busy=false;buttons();}}
async function saveCurrent(){
  const c=config(),version=generation,active=epoch;
  preview=null;$('previewState').textContent='待校验';$('surfaceSummary').textContent='尚未解析受载面';
  $('checks').textContent='保存会产生新版本，需要重新校验后导出。';
  for(const sample of $('monitorList').querySelectorAll('.sample'))sample.textContent='待解析';
  const args={config:c};if(scene)Object.assign(args,{scene_id:scene.scene_id,revision:scene.revision});
  const record=await request('scenes/save',args);
  if(active!==epoch)return null;scene=record;
  const locationUrl=new URL(location.href);locationUrl.searchParams.set('scene_id',record.scene_id);history.replaceState(null,'',locationUrl);
  $('saveState').textContent=(version===generation?'已保存':'已修改')+' · r'+record.revision;
  return {record,version,active};
}
function showPreview(p){
  $('previewState').textContent='预览已校验';$('surfaceSummary').textContent=p.segment_count+' 个受载面 · '+p.area_m2.toFixed(3)+' m²';
  $('checks').replaceChildren(node('p',`实际受载面 ${p.segment_count} 个，面积 ${p.area_m2.toFixed(3)} m²`,'success'),node('p',`载荷 ${p.curve_si.length} 个采样点；导出单位 s / Pa`));
  for(const warning of p.warnings)$('checks').append(node('p',warning,'error'));
  for(const [i,m]of p.monitors.entries()){
    const card=$('monitorList').querySelectorAll('.monitor')[i];if(!card)continue;
    card.querySelector('.sample').textContent=`实际${m.node_id?'节点 '+m.node_id:'单元 '+m.element_id} · XYZ ${m.sample_position_m.map(v=>v.toFixed(3)).join(', ')} m · 偏差 ${m.distance_m.toFixed(4)} m`;
  }
  draw();status(p.exportable?'当前版本已校验，可导出 K 包':'预览已完成，请补充来源与审核声明后重新校验');
}
async function updatePreview(){
  status('正在保存并解析实际受载面…');const saved=await saveCurrent();if(!saved||saved.version!==generation)return status('已保存先前版本，当前修改待校验');
  const p=await request('scenes/'+saved.record.scene_id+'/preview',{revision:saved.record.revision});
  if(saved.version!==generation||saved.active!==epoch){status('收到先前版本预览，当前修改仍待校验');return;}
  preview=p;showPreview(p);
}
async function savedList(){
  $('savedDialog').showModal();$('savedList').textContent='正在读取…';
  try{const result=await request('scenes');$('savedList').replaceChildren();if(!result.scenes.length)$('savedList').textContent='尚未保存工况';
    for(const row of result.scenes){const b=node('button',row.name);b.append(node('small',`r${row.revision} · ${new Date(row.updated_at).toLocaleString()}`));b.addEventListener('click',()=>operation(async()=>{window.WorkbenchNavigation?.checkpoint();const active=++epoch,r=await request('scenes/'+row.scene_id);if(active!==epoch)return;scene=r;renderConfig(r.config);$('saveState').textContent='已载入 · r'+r.revision;$('savedDialog').close();status('工况已载入，请重新校验后导出');await registerPressureNavigation();}));$('savedList').append(b);}
  }catch(e){$('savedList').textContent=e.message;}
}
function exportDialog(){if(!preview?.exportable)return;const c=config();$('exportSummary').replaceChildren(node('p',c.name),node('p',`${c.target.component_id} · ${c.target.face}`),node('p',`${preview.segment_count} 个受载面 / ${preview.area_m2.toFixed(3)} m²`),node('p',`终止时间 ${c.controls.termination_ms} ms · 监测 ${c.monitors.length} 个`));$('exportDialog').showModal();}
async function exportPackage(){
  $('exportDialog').close();if(!preview?.exportable)throw Error('请重新校验当前版本');
  const p=preview,name=$('sceneName').value,token=++jobToken;
  let job=await request('scenes/'+p.scene_id+'/exports',{revision:p.revision,scene_fingerprint:p.scene_fingerprint});
  $('jobResult').hidden=false;
  for(let attempt=0;attempt<2400;attempt++){
    if(token!==jobToken)return;
    $('jobResult').textContent=`${name} · r${p.revision} · ${job.status==='queued'?'等待导出':'正在导出结构 K 包…'}`;
    if(job.status==='exported'){
      $('jobResult').replaceChildren(node('strong',`${name} · r${p.revision} · K 包已导出`),node('p','入口：'+job.entry),node('code',job.output_dir));
      const link=node('a','下载完整 K 包 ZIP');link.id='downloadPackage';link.href=job.download_url;link.download='structural-pressure.zip';$('jobResult').append(node('br'),link);status('K 包已导出，求解器未启动');return;
    }
    if(['failed','interrupted'].includes(job.status)){const message=job.error||'导出中断';$('jobResult').textContent='导出未完成：'+message;throw Error(message);}
    await new Promise(resolve=>setTimeout(resolve,400));job=await request('exports/'+job.job_id);
  }
  throw Error('导出仍在进行，请稍后查看任务 '+job.job_id);
}
function init(){
  $('templateName').textContent=schema.template_id+' · 固定结构模板';const g=schema.geometry,b=g.ground_bounds_m;
  $('componentCount').textContent=g.components.length+' 个构件';$('treeCount').textContent=g.components.length;
  const size=`${(b[3]-b[0]).toFixed(1)} × ${(b[4]-b[1]).toFixed(1)} × ${(b[5]-b[2]).toFixed(1)} m`;
  $('groundSize').textContent='混凝土地面 '+size;$('groundInfo').textContent=size;
  const groups=new Map();for(const c of g.components){const key=Number.isInteger(c.level)?'第 '+(c.level+1)+' 层':'基础与附属';groups.set(key,(groups.get(key)||0)+1);}for(const[k,count]of groups)$('buildingGroups').append(node('span',k+' · '+count+' 个构件'));
  renderConfig(clone(schema.default_config));status('固定模板已载入，请提供工程压力载荷');buttons();
}
for(const b of document.querySelectorAll('[data-tab]'))b.addEventListener('click',()=>tab(b.dataset.tab));
for(const b of document.querySelectorAll('[data-close]'))b.addEventListener('click',()=>$(b.dataset.close).close());
for(const id of ['sceneName','notes','curveText','sourceReference','sourceReviewer','termination','plotInterval','historyInterval'])$(id).addEventListener('input',dirty);
for(const id of ['targetComponent','targetFace','reviewed'])$(id).addEventListener('change',dirty);
$('monitorList').addEventListener('input',dirty);$('monitorList').addEventListener('change',dirty);
$('componentFilter').addEventListener('input',()=>fillComponents());
$('curveFile').addEventListener('change',async()=>{const file=$('curveFile').files[0];if(!file)return;const active=epoch;try{if(file.size>1_000_000)throw Error('CSV 文件不可超过 1 MB');const raw=await file.text();if(active!==epoch)return;$('curveText').value=raw;dirty();parseCurve(raw);status('已导入 '+file.name+'，请更新预览');}catch(e){preview=null;buttons();status(e.message,true);}});
$('addMonitor').addEventListener('click',()=>{if($('monitorList').children.length>=128)return status('最多 128 个监测点',true);const ids=new Set([...$('monitorList').querySelectorAll('[data-monitor-id]')].map(n=>n.value));let i=1;while(ids.has('m'+i))i++;addMonitor({id:'m'+i,kind:'structure_node',position_m:[0,0,0]});dirty();});
$('saveScene').addEventListener('click',()=>operation(async()=>{await saveCurrent();status('工况已保存');}));
$('previewScene').addEventListener('click',()=>operation(updatePreview));$('openSaved').addEventListener('click',savedList);
$('newScene').addEventListener('click',async()=>{try{window.WorkbenchNavigation?.checkpoint();epoch++;scene=null;renderConfig(clone(schema.default_config));$('jobResult').hidden=true;status('新工况，请填写压力载荷');await registerPressureNavigation(true);}catch(e){status(e.message,true);}});
$('exportScene').addEventListener('click',exportDialog);$('confirmExport').addEventListener('click',()=>operation(exportPackage));
$('openCpuResponse').addEventListener('click',event=>{
  event.preventDefault();if(busy)return;
  const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
  let clean=false;try{clean=canonical(config())===canonical(scene?scene.config:schema.default_config);}catch{}
  if(clean){location.assign('/fixed-building-pressure/response'+(scene?'?scene_id='+scene.scene_id:''));return;}
  $('cpuLeaveDialog').showModal();
});
$('saveAndOpenCpu').addEventListener('click',()=>operation(async()=>{
  const saved=await saveCurrent();if(saved&&saved.version===generation)location.assign('/fixed-building-pressure/response?scene_id='+saved.record.scene_id);
}));
for(const input of document.querySelectorAll('[data-layer]'))input.addEventListener('change',()=>{view.layers[input.dataset.layer]=input.checked;draw();});
for(const[id,plan]of [['view3d',false],['viewPlan',true]])$(id).addEventListener('click',()=>{view.plan=plan;$('view3d').classList.toggle('active',!plan);$('viewPlan').classList.toggle('active',plan);draw();});
$('zoomIn').addEventListener('click',()=>{view.zoom=Math.min(4,view.zoom*1.2);draw();});$('zoomOut').addEventListener('click',()=>{view.zoom=Math.max(.4,view.zoom/1.2);draw();});$('fitView').addEventListener('click',()=>{view.zoom=1;draw();});
async function registerPressureNavigation(preserveInputs=false){
 const n=window.WorkbenchNavigation;if(!n)return;
 await n.register('pressure',{
  restoreIdentity:()=>scene?.scene_id||'new',
  context:()=>({identity:scene?.scene_id||'new',revision:schema?(scene?.revision||''):'unavailable',label:$('sceneName').value||'未保存压力工况',url:'/structural-pressure'+(scene?'?scene_id='+scene.scene_id:'')}),
  beforeLeave:()=>{if(busy)throw Error('当前工况操作尚未完成，请稍后切换。');},
  capture:()=>({template:schema?.template_fingerprint||'unavailable',fields:n.captureFields(document.querySelector('main').parentElement),monitorRows:[...$('monitorList').querySelectorAll('.monitor')].map(()=>({id:'',kind:'structure_node',position_m:['','','']})),view:clone(view),tab:document.querySelector('[data-tab].active')?.dataset.tab}),
  restore:s=>{
   if(preserveInputs)return;
   if(s.template!==(schema?.template_fingerprint||'unavailable'))throw Error('建筑模板已变化，原参数未覆盖新模板。');
   if(!schema){n.restoreFields(document.body,s.fields);return;}
   $('monitorList').replaceChildren();for(const m of s.monitorRows||[])addMonitor(m);
   const selected=s.fields?.find(f=>f.key==='id:targetComponent');fillComponents(selected?.value);
   n.restoreFields(document.body,s.fields);Object.assign(view,s.view||{});dirty();tab(s.tab||'load');
   $('saveState').textContent=scene?'本地草稿 · r'+scene.revision:'本地未保存草稿';status('已恢复本标签页参数；导出前请重新校验。');
  },
 });
}
async function initializePressure(){
 let preserveInputs=false;
 try{
  schema=await request('schema');init();
  const id=new URL(location.href).searchParams.get('scene_id');
  if(/^[a-f0-9]{32}$/.test(id||'')){
   const active=epoch,version=generation,record=await request('scenes/'+id);
   preserveInputs=active!==epoch||version!==generation;
   if(active===epoch){scene=record;if(!preserveInputs){renderConfig(record.config);$('saveState').textContent='已载入 · r'+record.revision;status('已恢复保存的工况；导出前请重新校验。');}}
  }
 }catch(e){buttons();status(e.message,true);$('checks').textContent=e.message;}
 finally{await registerPressureNavigation(preserveInputs);}
}
buttons();initializePressure();
