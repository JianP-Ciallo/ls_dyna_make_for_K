import {createTntScene,renderPressureChart} from './fixed_building_tnt_view.js';

const $=id=>document.getElementById(id),clone=v=>structuredClone(v),api='/api/architecture/tnt/';
let schema=null,scene=null,preview=null,epoch=0,generation=0,busy=false,openingStates={},resultCurves=[],resultToken=0,exportRecords=[];
let sceneViewer=null,placementAllowed=false,readOnlyHistory=false,tntDrag=null;
const view={plan:false,zoom:1,layers:{building:true,ground:true,air:true,monitors:true,tnt:true}};
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
const number=id=>{const v=$(id).value;if(!v.trim()||!Number.isFinite(Number(v)))throw Error('请填写有效数值');return Number(v);};
function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
function checkpointView(){try{window.WorkbenchNavigation?.checkpoint();}catch(e){status(e.message,true);}}
async function request(path,payload){
 const response=await fetch(api+path,payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 const body=await response.json();if(!response.ok)throw Error(typeof body.error==='string'?body.error:body.error?.message||`HTTP ${response.status}`);return body;
}
function buttons(){for(const id of ['newScene','openSaved'])$(id).disabled=!schema||busy;for(const id of ['saveScene','previewScene'])$(id).disabled=!schema||busy||!placementAllowed||readOnlyHistory;$('exportScene').disabled=!preview?.exportable||busy||!placementAllowed||readOnlyHistory;for(const id of ['resultExport','refreshResults'])$(id).disabled=busy;$('attachResults').disabled=busy||!$('resultExport').value;}
function tab(name){for(const b of document.querySelectorAll('[data-tab]')){const active=b.dataset.tab===name;b.classList.toggle('active',active);b.setAttribute('aria-selected',active);}for(const p of document.querySelectorAll('[data-pane]'))p.hidden=p.dataset.pane!==name;}
function monitorValues(){return [...$('monitorList').children].map(card=>({id:card.querySelector('[data-id]').value,kind:card.querySelector('select').value,position_m:[...card.querySelectorAll('[data-xyz]')].map(i=>{if(!i.value.trim()||!Number.isFinite(Number(i.value)))throw Error('监测坐标无效');return Number(i.value);})}));}
function config(){
 const cylinder=$('cylinderMode').value==='mass'?{mode:'mass',mass_kg:number('tntMass'),aspect_ratio:number('tntAspect')}:{mode:'dimensions',diameter_m:number('tntDiameter'),height_m:number('tntHeight')};
 return {schema_version:schema.schema_version,template_id:schema.defaults.template_id,template_fingerprint:schema.defaults.template_fingerprint,name:$('sceneName').value,notes:$('notes').value,
  scenario:readOnlyHistory?'indoor':$('scenario').value,location:{room_id:readOnlyHistory?scene?.config.location.room_id:null,xy_m:[number('tntX'),number('tntY')],bottom_clearance_m:number('tntClearance')},cylinder,detonation_time_s:number('detonation')/1000,
  opening_states:clone(openingStates),mesh:{background_cell_m:number('backgroundCell'),charge_cell_m:number('chargeCell'),room_cell_m:number('roomCell'),opening_cell_m:number('openingCell'),margins_m:Object.fromEntries(['xmin','xmax','ymin','ymax','top'].map(k=>[k,number('margin_'+k)]))},
  controls:{termination_s:number('termination')/1000,plot_interval_s:number('plotInterval')/1000,history_interval_s:number('historyInterval')/1000},monitors:monitorValues()};
}
function cylinderValues(c){
 const rho=schema.tnt_density_kg_m3||1630;let d,h;
 if(c.mode==='dimensions'){d=c.diameter_m;h=c.height_m;}else{d=Math.cbrt(4*c.mass_kg/(rho*Math.PI*c.aspect_ratio));h=d*c.aspect_ratio;}
 if(!(d>0&&h>0&&Number.isFinite(d+h)))throw Error('圆柱尺寸或质量必须为正数');return {diameter_m:d,height_m:h,mass_kg:rho*Math.PI*d*d*h/4};
}
function localPlacement(c){
 if(readOnlyHistory||c.scenario!=='outdoor')throw Error('当前仅允许室外TNT；历史室内工况保留只读，请新建室外工况。');
 const v=cylinderValues(c.cylinder),floor=schema.geometry.grade_m;
 if(c.location.bottom_clearance_m<0)throw Error('离地高度不能为负数');const [x,y]=c.location.xy_m,z=floor+c.location.bottom_clearance_m,r=v.diameter_m/2,b=schema.geometry.building_bounds_m;
 const dx=Math.max(b[0]-x,0,x-b[3]),dy=Math.max(b[1]-y,0,y-b[4]);
 if(z+v.height_m>=b[2]-1e-9&&z<=b[5]+1e-9&&Math.hypot(dx,dy)<=r+1e-9)throw Error('TNT整个圆柱必须位于建筑外，不得进入建筑内部或接触建筑外包络。');
 return {...v,bottom_elevation_m:z,center_m:[x,y,z+v.height_m/2],bounds_m:[x-r,y-r,z,x+r,y+r,z+v.height_m]};
}
function dragPathEntersBuilding(from,to,p){
 const b=schema.geometry.building_bounds_m;if(p.bounds_m[5]<b[2]-1e-9||p.bounds_m[2]>b[5]+1e-9)return false;
 const d=[to[0]-from[0],to[1]-from[1]],length2=d[0]*d[0]+d[1]*d[1];let enter=0,leave=1,intersects=true;
 for(let i=0;i<2;i++){
  if(Math.abs(d[i])<1e-12){if(from[i]<b[i]||from[i]>b[i+3])intersects=false;}
  else{const a=(b[i]-from[i])/d[i],z=(b[i+3]-from[i])/d[i];enter=Math.max(enter,Math.min(a,z));leave=Math.min(leave,Math.max(a,z));}
 }
 if(intersects&&enter<=leave)return true;
 const distance=q=>Math.hypot(Math.max(b[0]-q[0],0,q[0]-b[3]),Math.max(b[1]-q[1],0,q[1]-b[4]));
 let gap=Math.min(distance(from),distance(to));
 if(length2>0)for(const x of [b[0],b[3]])for(const y of [b[1],b[4]]){const t=Math.max(0,Math.min(1,((x-from[0])*d[0]+(y-from[1])*d[1])/length2));gap=Math.min(gap,Math.hypot(x-from[0]-t*d[0],y-from[1]-t*d[1]));}
 return gap<=p.diameter_m/2+1e-9;
}
const tntDragging={
 start(mode='xy'){if(busy||readOnlyHistory||!placementAllowed)return false;tntDrag={epoch,mode,origin:[$('tntX').value,$('tntY').value,$('tntClearance').value],moved:false};status(mode==='height'?'拖动高度手柄升降；X/Y保持不变，Esc取消。':'拖动TNT调整X/Y；高度手柄用于升降，Esc取消。');return true;},
 move(xy){
  if(!tntDrag||tntDrag.mode!=='xy'||tntDrag.epoch!==epoch||busy)return false;
  try{
   if(!xy.every(Number.isFinite))throw Error('无法从当前视角确定拖动位置，请调整视角。');const to=xy.map(v=>Number(v.toFixed(6))),c=config(),from=c.location.xy_m;c.location.xy_m=to;const p=localPlacement(c),b=schema.geometry.building_bounds_m,m=c.mesh.margins_m,r=p.diameter_m/2,h=c.mesh.charge_cell_m;
   const air=[b[0]-m.xmin,b[1]-m.ymin,b[3]+m.xmax,b[4]+m.ymax];if(to.some((v,i)=>v-r-h<=air[i]+1e-9||v+r+h>=air[i+2]-1e-9))throw Error('拖动位置超出空气域及爆源缓冲范围。');
   if(dragPathEntersBuilding(from,to,p))throw Error('移动路线不能穿过建筑，请沿建筑外侧拖动。');
   if(to.every((v,i)=>v===from[i]))return true;$('tntX').value=to[0];$('tntY').value=to[1];tntDrag.moved=true;dirty();status('TNT拖动中；位置保持在建筑外，Esc取消。');return true;
  }catch(e){$('placementStatus').textContent='已拦截：'+e.message+' 已保留上一次合法位置。';$('placementStatus').classList.add('error');return false;}
 },
 height(value){
  if(!tntDrag||tntDrag.mode!=='height'||tntDrag.epoch!==epoch||busy)return false;
  try{
   if(!Number.isFinite(value))throw Error('无法确定拖动高度，请调整视角。');const c=config(),from=localPlacement(c),height=Number(value.toFixed(6));c.location.bottom_clearance_m=height;const p=localPlacement(c),b=schema.geometry.building_bounds_m,grade=schema.geometry.grade_m,h=c.mesh.charge_cell_m;
   if(p.bounds_m[5]+h>=b[5]+c.mesh.margins_m.top-1e-9||(p.bounds_m[2]>grade+1e-9&&p.bounds_m[2]-h<=grade+1e-9))throw Error('拖动高度超出空气域及爆源缓冲范围。');
   const [x,y]=c.location.xy_m,gap=Math.hypot(Math.max(b[0]-x,0,x-b[3]),Math.max(b[1]-y,0,y-b[4]));
   if(gap<=p.diameter_m/2+1e-9&&Math.min(from.bounds_m[2],p.bounds_m[2])<=b[5]+1e-9&&Math.max(from.bounds_m[5],p.bounds_m[5])>=b[2]-1e-9)throw Error('升降路线不能穿过建筑，请先移到建筑外侧。');
   if(height===number('tntClearance'))return true;$('tntClearance').value=height;tntDrag.moved=true;dirty();status('TNT高度调整中；位置保持在建筑外，Esc取消。');return true;
  }catch(e){$('placementStatus').textContent='已拦截：'+e.message+' 已保留上一次合法高度。';$('placementStatus').classList.add('error');return false;}
 },
 end({cancelled}){const drag=tntDrag;tntDrag=null;if(!drag||drag.epoch!==epoch)return;if(cancelled&&drag.moved){$('tntX').value=drag.origin[0];$('tntY').value=drag.origin[1];$('tntClearance').value=drag.origin[2];dirty();}status(cancelled?'已取消TNT拖动，位置已恢复。':drag.moved?'TNT位置已调整；请更新预览后导出。':'TNT位置未改变。');checkpointView();}
};
function draw(){
 if(!schema)return;let c,p;
 try{c=config();p=localPlacement(c);placementAllowed=true;$('placementStatus').textContent='整个TNT圆柱位于建筑外。';$('placementStatus').classList.remove('error');$('cylinderSummary').textContent=`直径 ${p.diameter_m.toPrecision(5)} m · 高度 ${p.height_m.toPrecision(5)} m · 质量 ${p.mass_kg.toPrecision(5)} kg`;$('tntTreeSummary').textContent=`中心 ${p.center_m.map(v=>v.toFixed(3)).join(', ')} m`;}catch(e){placementAllowed=false;$('placementStatus').textContent=e.message;$('placementStatus').classList.add('error');$('cylinderSummary').textContent='';$('tntTreeSummary').textContent='位置未通过校验';c={monitors:[]};}
 const g={...schema.geometry};
 if(c.mesh){const b=g.building_bounds_m,m=c.mesh.margins_m;g.air_bounds_m=[b[0]-m.xmin,b[1]-m.ymin,g.grade_m,b[3]+m.xmax,b[4]+m.ymax,b[5]+m.top];}
 sceneViewer?.update(g,c,p,view);
}
function clearResults(){resultToken++;resultCurves=[];renderPressureChart($('resultChart'),null);$('resultMonitor').hidden=true;$('resultCsv').hidden=true;$('resultCsv').removeAttribute('href');$('resultMetrics').textContent='';$('resultStatus').textContent='尚无该工况求解结果。';}
function dirty(){generation++;preview=null;$('saveState').textContent=readOnlyHistory?'历史室内工况 · 只读':scene?'已修改 · r'+scene.revision:'未保存';$('previewState').textContent='待预估';$('surfaceSummary').textContent='参数已修改，请更新预览';$('checks').textContent='当前版本尚未进行网格预估。';clearResults();draw();buttons();}
function modes(){const mass=$('cylinderMode').value==='mass';$('massFields').hidden=!mass;$('dimensionFields').hidden=mass;}
function openingOptions(){
 const id=$('openingTarget').value,door=schema.door_leaves[id],window=schema.openings[id];let options;
 if(door)options=door.elevator?[['keep','保留模板关闭状态'],['closed','初始关闭']]:[['keep','保留模板'],['closed','初始关闭（未锁闭）'],['open_90','初始打开90°（可转动）']];
 else options=[['keep_glass','保留玻璃'],['clear_opening','净开口（保留窗框）']];
 $('openingState').replaceChildren();for(const[value,label]of options){const o=node('option',label);o.value=value;$('openingState').append(o);}$('openingState').value=openingStates[id]||options[0][0];$('openingSummary').textContent=`已覆盖 ${Object.keys(openingStates).length} 项初始状态`;
}
function addMonitor(m){
 const card=node('div');card.className='monitor';const label=node('label','监测名称'),id=node('input');id.dataset.id='';id.value=m.id;label.append(id);card.append(label);
 const select=node('select');select.setAttribute('aria-label','监测类型');for(const[k,v]of [['air_pressure','空气单元压力'],['structure_node','建筑节点响应'],['ground_node','地面节点响应'],['solid_stress','实体应力']]){const o=node('option',v);o.value=k;select.append(o);}select.value=m.kind;card.append(select);
 const xyz=node('div');xyz.className='xyz';for(let i=0;i<3;i++){const l=node('label','XYZ'[i]+' / m'),input=node('input');input.type='number';input.step='any';input.dataset.xyz=i;input.value=m.position_m[i];l.append(input);xyz.append(l);}card.append(xyz);card.append(Object.assign(node('p','生成时解析实际采样位置'),{className:'sample'}));const remove=node('button','删除');remove.type='button';remove.onclick=()=>{card.remove();dirty();};card.append(remove);$('monitorList').append(card);
}
function renderConfig(c){
 readOnlyHistory=c.scenario!=='outdoor';$('sceneName').disabled=readOnlyHistory;for(const input of $('tntEditor').querySelectorAll('input,select,textarea'))input.disabled=readOnlyHistory;$('addMonitor').disabled=readOnlyHistory;
 $('sceneName').value=c.name;$('notes').value=c.notes;$('scenario').value='outdoor';$('tntX').value=c.location.xy_m[0];$('tntY').value=c.location.xy_m[1];$('tntClearance').value=c.location.bottom_clearance_m;$('detonation').value=c.detonation_time_s*1000;
 $('cylinderMode').value=c.cylinder.mode;const v=cylinderValues(c.cylinder);$('tntDiameter').value=v.diameter_m;$('tntHeight').value=v.height_m;$('tntMass').value=v.mass_kg;$('tntAspect').value=v.height_m/v.diameter_m;
 for(const[id,key]of [['backgroundCell','background_cell_m'],['chargeCell','charge_cell_m'],['roomCell','room_cell_m'],['openingCell','opening_cell_m']])$(id).value=c.mesh[key];
 for(const[k,v]of Object.entries(c.mesh.margins_m))$('margin_'+k).value=v;
 $('termination').value=c.controls.termination_s*1000;$('plotInterval').value=c.controls.plot_interval_s*1000;$('historyInterval').value=c.controls.history_interval_s*1000;
 openingStates=clone(c.opening_states);openingOptions();$('monitorList').replaceChildren();for(const m of c.monitors)addMonitor(m);if(readOnlyHistory)for(const input of $('monitorList').querySelectorAll('input,select,button'))input.disabled=true;modes();$('resultExport').replaceChildren();exportRecords=[];$('jobResult').replaceChildren();$('jobResult').hidden=true;dirty();
}
async function operation(fn){if(busy)return;busy=true;buttons();try{await fn();}catch(e){status(e.message,true);}finally{busy=false;buttons();}}
async function saveCurrent(){
 const version=generation,active=epoch,payload={config:config()};localPlacement(payload.config);if(scene)Object.assign(payload,{scene_id:scene.scene_id,revision:scene.revision});
 const r=await request('scenes/save',payload);if(active!==epoch)return null;scene=r;const u=new URL(location.href);u.searchParams.set('tnt_scene_id',r.scene_id);u.searchParams.delete('scene_id');history.replaceState(null,'',u);$('saveState').textContent=(version===generation?'已保存':'已修改')+' · r'+r.revision;window.WorkbenchNavigation?.checkpoint();return {record:r,version,active};
}
async function updatePreview(){
 const saved=await saveCurrent();if(!saved||saved.version!==generation)return;const p=await request(`scenes/${saved.record.scene_id}/preview`,{revision:saved.record.revision});if(saved.active!==epoch||saved.version!==generation)return;
 preview=p;$('previewState').textContent='轻量预估完成';$('surfaceSummary').textContent=`空气 ${p.grid.element_count.toLocaleString()} 单元 · ${p.grid.node_count.toLocaleString()} 节点`;$('locationSummary').textContent=`底面绝对高度 ${p.placement.bottom_elevation_m.toFixed(3)} m · 中心 ${p.placement.center_m.map(v=>v.toFixed(3)).join(', ')} m`;
 $('checks').replaceChildren(node('p',`网格预估 ${p.grid.element_count.toLocaleString()} 单元 / ${p.grid.node_count.toLocaleString()} 节点`),...p.warnings.map(v=>node('p',v)));status('轻量预估完成；尚未生成实际网格或启动求解');buttons();draw();await refreshExports();
}
async function loadScene(id){const active=++epoch,r=await request('scenes/'+id);if(active!==epoch)return;scene=r;renderConfig(r.config);const u=new URL(location.href);u.searchParams.set('tnt_scene_id',id);u.searchParams.delete('scene_id');history.replaceState(null,'',u);$('saveState').textContent='已载入 · r'+r.revision;await registerNavigation();await refreshExports();}
async function savedList(){
 $('savedDialog').showModal();$('savedList').textContent='正在读取…';try{const r=await request('scenes');$('savedList').replaceChildren();if(!r.scenes.length)$('savedList').textContent='尚未保存TNT工况';for(const s of r.scenes){const b=node('button',`${s.name} · r${s.revision}`);b.onclick=()=>operation(async()=>{window.WorkbenchNavigation?.checkpoint();await loadScene(s.scene_id);$('savedDialog').close();status('工况已恢复，请更新预览');});$('savedList').append(b);}}catch(e){$('savedList').textContent=e.message;}
}
function exportDialog(){
 if(!preview?.exportable)return;const p=preview;$('scopeAccepted').checked=false;$('confirmExport').disabled=true;
 $('exportSummary').replaceChildren(node('p',`${p.config.name} · r${p.revision}`),node('p',`范围：本栋建筑、固定地面、单个TNT圆柱、空气与流固耦合`),node('p',`${p.grid.element_count.toLocaleString()} 个ALE单元 / ${p.grid.node_count.toLocaleString()} 个空气节点`),node('p','生成阶段粗估 10–30 分钟；尚未经此配置实测，复杂门窗或网格可能更久。'),node('p','本次仅生成K包，包含精确几何和体积分数检查；不启动求解。'));$('exportDialog').showModal();
}
async function exportPackage(){
 if(!$('scopeAccepted').checked||!preview?.exportable)throw Error('请先确认当前生成范围');$('exportDialog').close();const p=preview,active=epoch;
 let job=await request(`scenes/${p.scene_id}/exports`,{revision:p.revision,scene_fingerprint:p.scene_fingerprint,scope_accepted:true});$('jobResult').hidden=false;
 for(let n=0;n<4500;n++){
  if(active!==epoch)return;$('jobResult').textContent=`${p.config.name} · r${p.revision} · ${job.status==='queued'?'等待生成':'正在生成K包'}`;
  if(job.status==='exported'){const a=node('a','下载TNT＋空气＋流固耦合K包');a.href=job.download_url;a.download='building-tnt-fsi.zip';$('jobResult').replaceChildren(node('strong',`K包已生成 · r${p.revision}`),node('p','入口：'+job.entry),a);status('K包已生成，未启动求解');await refreshExports(job.job_id);return;}
  if(['failed','interrupted'].includes(job.status))throw Error(job.error||'生成未完成');await new Promise(r=>setTimeout(r,400));job=await request('exports/'+job.job_id);
 }status('生成任务仍在执行，可稍后刷新已保存的导出记录。');
}
async function refreshExports(selected){
 const active=epoch;if(!scene)return;const r=await request(`scenes/${scene.scene_id}/exports`);if(active!==epoch)return;exportRecords=r.exports;const previous=selected||$('resultExport').value;$('resultExport').replaceChildren();for(const j of r.exports.filter(j=>j.status==='exported')){const o=node('option',`r${j.revision} · ${j.job_id.slice(0,8)}`);o.value=j.job_id;$('resultExport').append(o);}if(previous&&[...$('resultExport').options].some(o=>o.value===previous))$('resultExport').value=previous;showExport(exportRecords.find(j=>j.job_id===$('resultExport').value)||exportRecords[0]);
}
function showExport(job){
 $('jobResult').replaceChildren();$('jobResult').hidden=!job;if(!job)return;
 $('jobResult').append(node('strong',`${job.config?.name||scene?.config.name||'TNT工况'} · r${job.revision} · ${job.status==='exported'?'K包已生成':job.status}`));
 if(job.status==='exported'){const a=node('a','下载此版本的TNT流固耦合K包');a.id='existingPackage';a.href=job.download_url;a.download='building-tnt-fsi.zip';$('jobResult').append(node('p','入口：'+job.entry),a);}
 else if(job.error)$('jobResult').append(node('p',job.error));
}
function showCurve(){
 const c=resultCurves[Number($('resultMonitor').value)||0];renderPressureChart($('resultChart'),c);if(!c)return;
 $('resultMetrics').textContent=`峰值超压 ${(c.peak_overpressure_pa/1000).toPrecision(5)} kPa · 正相冲量 ${c.positive_impulse_pa_s.toPrecision(5)} Pa·s\n${c.pressure_description}\n参考压力 ${c.reference_pressure_pa} Pa；单元 ${c.element_id}；实际位置 ${c.sample_position_m.map(v=>Number(v).toFixed(4)).join(', ')} m\n实际时间窗 ${c.actual_window_s.map(v=>(v*1000).toPrecision(5)).join(' ～ ')} ms，保留原生输出时钟。`;
}
async function readResults(selectFolder=false){
 const jid=$('resultExport').value;if(!jid){clearResults();$('resultStatus').textContent='尚无已生成的K包。完成求解后可关联本工况结果。';return;}
 clearResults();showExport(exportRecords.find(j=>j.job_id===jid));const token=++resultToken,active=epoch;$('resultStatus').textContent=selectFolder?'请在本机对话框选择保留原K文件和binout的求解文件夹。':'正在读取已有结果…';
 const r=await request(`exports/${jid}/results${selectFolder?'/select':''}`,selectFolder?{}:undefined);if(token!==resultToken||active!==epoch||$('resultExport').value!==jid)return;
 if(r.status!=='available'){clearResults();$('resultStatus').textContent=r.status==='cancelled'?'已取消选择结果。':'尚无该导出版本的求解结果。';return;}
 resultCurves=r.curves;$('resultMonitor').replaceChildren();for(const[c,i]of resultCurves.map((c,i)=>[c,i])){const o=node('option',c.id);o.value=i;$('resultMonitor').append(o);}$('resultMonitor').hidden=false;$('resultCsv').hidden=false;$('resultCsv').href=api+`exports/${jid}/results/csv`;$('resultCsv').download='tnt-pressure-results.csv';$('resultStatus').textContent=`已关联导出版本 r${r.revision} · 仅显示真实原生结果。`;showCurve();
}
function resultView(enabled){$('tntResults').hidden=!enabled;for(const id of ['view3d','viewPlan','viewResults'])$(id).classList.toggle('active',enabled?id==='viewResults':id===(view.plan?'viewPlan':'view3d'));}
async function registerNavigation(){
 const n=window.WorkbenchNavigation;if(!n)return;const identity='tnt:'+(scene?.scene_id||'new');
 await n.register('pressure',{context:()=>({identity:'tnt:'+(scene?.scene_id||'new'),revision:String(scene?.revision||'draft'),label:scene?.config.name||'TNT爆炸工况',url:'/structural-pressure'+(scene?'?tnt_scene_id='+scene.scene_id:'')}),restoreIdentity:()=>identity,
  beforeLeave:()=>{if(busy)throw Error('当前工况操作尚未完成，请稍后切换。');},
  capture:()=>({analysis_type:'tnt_air_fsi',template:schema.defaults.template_fingerprint,fields:n.captureFields(document.body),openings:clone(openingStates),monitorRows:[...$('monitorList').children].map(()=>({id:'',kind:'air_pressure',position_m:['','','']})),view:clone(view),tab:document.querySelector('[data-tab].active')?.dataset.tab}),
  restore:s=>{if(s.analysis_type!=='tnt_air_fsi'||s.template!==schema.defaults.template_fingerprint)throw Error('工况类型或模板不同，原草稿保留。');if(!readOnlyHistory&&s.fields?.some(f=>f.key==='id:scenario'&&f.value==='indoor'))throw Error('当前仅支持室外TNT，原室内草稿已保留，可下载备份。');$('monitorList').replaceChildren();for(const m of s.monitorRows||[])addMonitor(m);n.restoreFields(document.body,s.fields);openingStates=clone(s.openings||{});Object.assign(view,s.view||{});modes();dirty();if(s.view?.camera)sceneViewer?.restoreCamera(s.view.camera);else sceneViewer?.fit(view.plan?'plan':'3d');if(readOnlyHistory)for(const input of $('monitorList').querySelectorAll('input,select,button'))input.disabled=true;tab(s.tab||'load');status('已恢复本标签页的TNT参数；导出前请更新预览。');}});
}
for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>tab(b.dataset.tab);
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
$('tntEditor').addEventListener('input',()=>{if(schema)dirty();});$('tntEditor').addEventListener('change',()=>{if(schema)dirty();});$('sceneName').oninput=()=>dirty();
$('cylinderMode').onchange=()=>{try{const rho=schema.tnt_density_kg_m3||1630;if($('cylinderMode').value==='mass'){const d=number('tntDiameter'),h=number('tntHeight');$('tntMass').value=rho*Math.PI*d*d*h/4;$('tntAspect').value=h/d;}else{const v=cylinderValues({mode:'mass',mass_kg:number('tntMass'),aspect_ratio:number('tntAspect')});$('tntDiameter').value=v.diameter_m;$('tntHeight').value=v.height_m;}}catch(e){status(e.message,true);}modes();dirty();};
$('openingTarget').onchange=openingOptions;$('openingState').onchange=()=>{const id=$('openingTarget').value;if(['keep','keep_glass'].includes($('openingState').value))delete openingStates[id];else openingStates[id]=$('openingState').value;openingOptions();dirty();};
$('addMonitor').onclick=()=>{let i=1;while([...$('monitorList').querySelectorAll('[data-id]')].some(n=>n.value==='p'+i))i++;let position=[1.2,.5,.5];try{position=localPlacement(config()).center_m.map((v,a)=>v+(a===0?.5:0));}catch{}addMonitor({id:'p'+i,kind:'air_pressure',position_m:position});dirty();};
$('saveScene').onclick=()=>operation(async()=>{await saveCurrent();status('TNT工况已保存；尚未生成网格。');});$('previewScene').onclick=()=>operation(updatePreview);$('openSaved').onclick=savedList;
$('newScene').onclick=()=>operation(async()=>{window.WorkbenchNavigation?.checkpoint();epoch++;scene=null;renderConfig(clone(schema.defaults));history.replaceState(null,'','/structural-pressure');await registerNavigation();status('新建TNT工况');});
$('exportScene').onclick=exportDialog;$('scopeAccepted').onchange=()=>{$('confirmExport').disabled=!$('scopeAccepted').checked;};$('confirmExport').onclick=()=>operation(exportPackage);
$('view3d').onclick=()=>{view.plan=false;resultView(false);sceneViewer?.fit('3d');checkpointView();};$('viewPlan').onclick=()=>{view.plan=true;resultView(false);sceneViewer?.fit('plan');checkpointView();};$('viewResults').onclick=()=>operation(async()=>{resultView(true);await refreshExports();await readResults();});
$('refreshResults').onclick=()=>operation(async()=>{await refreshExports();await readResults();});$('attachResults').onclick=()=>operation(()=>readResults(true));$('resultExport').onchange=()=>operation(()=>readResults());$('resultMonitor').onchange=showCurve;
for(const[id,factor]of [['zoomIn',1.2],['zoomOut',1/1.2]])$(id).onclick=()=>{sceneViewer?.zoom(factor);checkpointView();};$('fitView').onclick=()=>{sceneViewer?.fit();checkpointView();};for(const input of document.querySelectorAll('[data-layer]'))input.onchange=()=>{view.layers[input.dataset.layer]=input.checked;draw();};

async function init(){
 try{
  schema=await request('schema');schema.tnt_density_kg_m3=schema.tnt_density_kg_m3||1630;
  $('templateName').textContent=schema.defaults.template_id+' · TNT与空气参考模板';const g=schema.geometry,b=g.ground_bounds_m;$('componentCount').textContent=g.components.length+' 个构件';$('treeCount').textContent=g.components.length;const dimensions=[0,1,2].map(i=>(b[i+3]-b[i]).toFixed(1)).join(' × ')+' m';$('groundSize').textContent='混凝土地面 '+dimensions;$('groundInfo').textContent=dimensions;
  const groups=new Map();for(const c of g.components)groups.set(c.level,(groups.get(c.level)||0)+1);for(const[level,count]of groups)$('buildingGroups').append(node('span',`第 ${Number(level)+1} 层 · ${count} 个构件`));
  for(const[k,label]of Object.entries({xmin:'西侧',xmax:'东侧',ymin:'南侧',ymax:'北侧',top:'顶部'})){const l=node('label',label),input=node('input');input.id='margin_'+k;input.type='number';input.min='0';input.step='any';l.append(input);$('marginFields').append(l);}
  for(const[id,key]of [['termination','termination_s'],['plotInterval','plot_interval_s'],['historyInterval','history_interval_s']]){$(id).min=schema.control_ranges[key][0]*1000;$(id).max=schema.control_ranges[key][1]*1000;}
  for(const[id,v]of [...Object.entries(schema.door_leaves),...Object.entries(schema.openings).filter(([,v])=>v.kind==='window')]){const o=node('option',id);o.value=id;$('openingTarget').append(o);}
  try{sceneViewer=createTntScene($('sceneView'),camera=>{view.camera=camera;},checkpointView,tntDragging);window.addEventListener('pagehide',()=>sceneViewer?.dispose(),{once:true});}catch(e){$('sceneView').textContent='三维视图不可用：'+e.message;}
  renderConfig(clone(schema.defaults));const query=new URL(location.href).searchParams,id=query.get('tnt_scene_id')||query.get('scene_id');
  if(/^[a-f0-9]{32}$/.test(id||'')){try{await loadScene(id);}catch(e){const legacy=await fetch('/api/architecture/pressure/scenes/'+id);if(legacy.ok){location.replace('/structural-pressure?legacy=1&scene_id='+id);return;}throw e;}}
  else await registerNavigation();buttons();status('TNT设置已载入，压力曲线将在结果视图查看。');renderPressureChart($('resultChart'),null);
 }catch(e){status(e.message,true);$('checks').textContent=e.message;buttons();}
}
buttons();init();
