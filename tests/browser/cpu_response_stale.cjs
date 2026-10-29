/* Deterministic delayed HTTP responses, using the shipped page module. No solve. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('lsprepost_mcp/web/static/fixed_building_response.js','utf8').replace(/^import .*;\r?\n/gm,'');
function context(query=''){
  const elements=new Map();
  const el=id=>{if(!elements.has(id))elements.set(id,{value:id==='benchmark'?'rc-column-v1':id==='pressureScale'?'1':'',textContent:'',hidden:false,disabled:false,style:{},classList:{toggle(){}},addEventListener(){},replaceChildren(){},append(){},add(){}});return elements.get(id);};
  const ctx=vm.createContext({document:{getElementById:el,createElement:()=>({})},location:{href:'http://localhost/fixed-building-pressure/response'+query},window:{history:{replaceState(){}}},URL,Option:class{},performance:{now:()=>0},requestAnimationFrame(){},setTimeout,crypto:{randomUUID:()=> 'request'},ResponseView:class{setResult(){}setScale(){}},ResponseCharts:class{setResult(){}},fetch:async()=>({ok:true,json:async()=>({available:true,verified:true,runs:[]})})});
  vm.runInContext(source,ctx);return {ctx,el,run:code=>vm.runInContext(code,ctx)};
}
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
(async()=>{
  // Old polling is already in flight when a new run takes ownership.
  const a=context();await tick();
  a.run("epoch=20;request=async()=>new Promise(resolve=>globalThis.release=resolve);globalThis.waiting=follow({run_id:'old',status:'running'},20)");
  await new Promise(r=>setTimeout(r,330));
  a.run("epoch=21;currentRun={run_id:'new',status:'running'};release({run_id:'old',status:'cancelled'})");await a.run('waiting');
  assert.equal(a.run('currentRun.run_id'),'new','old poll must not steal currentRun/cancel target');
  // Delayed initial URL record must not change a new user selection.
  const b=context('?run_id='+'a'.repeat(32));
  let registrations=0;b.ctx.window.WorkbenchNavigation={register:async()=>{registrations++;}};
  b.run("request=async path=>path.startsWith('runs/')?new Promise(resolve=>globalThis.release=resolve):({available:true,verified:true,runs:[]})");
  await tick();b.run("epoch++;document.getElementById('benchmark').value='rc-panel-v1';release({source:{id:'rc-column-v1'},run_id:'old',status:'cancelled'})");await tick();
  assert.equal(b.el('benchmark').value,'rc-panel-v1','initial saved run must not overwrite later source choice');
  assert.equal(registrations,1,'stale initial run must still register navigation');
  const c=context('?run_id='+'b'.repeat(32));let runningRegistration=0;
  c.ctx.window.WorkbenchNavigation={register:async()=>{runningRegistration++;}};
  c.run("request=async path=>path.startsWith('runs/')?({source:{id:'rc-column-v1'},run_id:'running',status:'running'}):({available:true,verified:true,runs:[]})");
  await tick();await tick();assert.equal(runningRegistration,1,'navigation must not wait for an existing running job');c.run('epoch++');
  console.log('3 delayed response checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
