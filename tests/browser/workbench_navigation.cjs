/* Actual same-tab navigation/recovery. All API writes and calculations forbidden. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const base=process.argv[2]||'http://127.0.0.1:8898',out=path.resolve(process.argv[3]||'artifacts/workbench-navigation-20261022-01');fs.mkdirSync(out,{recursive:true});
const checks=[],errors=[],writes=[],badAssets=[],getMocks=new Map();let ws,call,evaluate,current='';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,timeout=20000){const end=Date.now()+timeout;while(Date.now()<end){if(await fn())return;await sleep(70);}throw Error('timeout '+fn);}
const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
(async()=>{
 const chrome=['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);assert(chrome);
 const profile=path.join(out,'chrome-profile');fs.mkdirSync(profile,{recursive:true});
 const browser=spawn(chrome,['--headless=new','--no-first-run','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist','about:blank'],{windowsHide:true,stdio:'ignore'});
 try{
  let port;await until(async()=>{try{port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);return port>0;}catch{return false;}});
  const target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});let seq=0;const pending=new Map();
  call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  ws.addEventListener('message',ev=>{
   const m=JSON.parse(ev.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}return;}
   if(m.method==='Runtime.exceptionThrown')errors.push({current,detail:m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text});
   if(m.method==='Network.responseReceived'){const r=m.params.response;if(r.status>=400&&/\.(js|css)(\?|$)/.test(r.url))badAssets.push(r.url);}
   if(m.method==='Page.javascriptDialogOpening')call('Page.handleJavaScriptDialog',{accept:false}).catch(()=>{});
   if(m.method==='Fetch.requestPaused'){const p=m.params,mock=getMocks.get(new URL(p.request.url).pathname);if(p.request.method==='GET'&&mock){mock.seen=true;setTimeout(()=>call('Fetch.fulfillRequest',{requestId:p.requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(JSON.stringify(mock.body)).toString('base64')}).catch(()=>{}),mock.delay||0);}else if(p.request.method==='GET')call('Fetch.continueRequest',{requestId:p.requestId}).catch(()=>{});else{writes.push({url:p.request.url,method:p.request.method});call('Fetch.failRequest',{requestId:p.requestId,errorReason:'Aborted'}).catch(()=>{});}}
  });
  evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  const click=s=>evaluate(`document.querySelector(${JSON.stringify(s)}).click()`);
  const set=(s,value,event='input')=>evaluate(`{const e=document.querySelector(${JSON.stringify(s)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event(${JSON.stringify(event)},{bubbles:true}));}`);
  async function ready(id){current=id;await until(()=>evaluate(`document.body?.dataset.activeWorkbench===${JSON.stringify(id)}&&document.querySelector('.workbench-global-context [role="status"]')?.textContent.includes('保留')`));}
  async function load(url,reload=false){const previous=await evaluate('performance.timeOrigin');await call(reload?'Page.reload':'Page.navigate',reload?{ignoreCache:true}:{url});await until(async()=>{try{return await evaluate('performance.timeOrigin')!==previous;}catch{return false;}});}
  async function go(id){
   if(['building','pressure'].includes(id)){
    if(!['building','pressure'].includes(await evaluate('document.body.dataset.activeWorkbench'))){
     await click('.workbench-global-header > nav [data-workbench-group="fixed-building"]');
     await until(()=>evaluate('["building","pressure"].includes(document.body?.dataset.activeWorkbench)&&document.querySelector(".workbench-global-context [role=status]")?.textContent.includes("保留")'));
    }
    if(await evaluate('document.body.dataset.activeWorkbench')!==id)await click(`.workbench-subnavigation [data-workbench-destination="${id}"]`);
   }else await click(`.workbench-global-header > nav [data-workbench-destination="${id}"]`);
   await ready(id);
  }
  async function shot(name){const r=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,name),Buffer.from(r.data,'base64'));}
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');await call('Page.bringToFront');await call('Emulation.setFocusEmulationEnabled',{enabled:true});
  await call('Fetch.enable',{patterns:[{urlPattern:'*/api/*',requestStage:'Request'}]});
  await call('Emulation.setDeviceMetricsOverride',{width:1500,height:1000,deviceScaleFactor:1,mobile:false});await call('Page.navigate',{url:base+'/'});await ready('modeling');
  if(process.argv.includes('--visuals-only')){
   for(const id of ['modeling','refined','building','pressure','response','assessment']){
    await go(id);for(const width of[1500,390]){await call('Emulation.setDeviceMetricsOverride',{width,height:950,deviceScaleFactor:1,mobile:false});await sleep(160);await shot(`${id}-${width}.png`);}
   }
   await go('refined');await click('[data-damage-demo]');
   await until(()=>evaluate('document.querySelector("[data-damage-demo-frame]")?.contentDocument?.body?.dataset.activeWorkbench==="assessment"'));
   check('embedded demo hides duplicate global navigation',await evaluate('getComputedStyle(document.querySelector("[data-damage-demo-frame]").contentDocument.querySelector(".workbench-global-header")).display==="none"'));
   await until(()=>evaluate('document.querySelector("[data-damage-demo-frame]")?.contentDocument?.querySelector(".workbench-global-context [role=status]")?.textContent.includes("保留")'));
   await evaluate('const f=document.querySelector("[data-damage-demo-frame]"),e=f.contentDocument.querySelector("[data-source-x]");e.value="-7.89";e.dispatchEvent(new f.contentWindow.Event("input",{bubbles:true}));document.querySelector("[data-damage-demo-exit]").click();document.querySelector("[data-damage-demo]").click();');
   await until(()=>evaluate('document.querySelector("[data-damage-demo-frame]")?.contentDocument?.querySelector(".workbench-global-context [role=status]")?.textContent.includes("保留")'));
   check('closing an embedded demo immediately retains its latest input',await evaluate('document.querySelector("[data-damage-demo-frame]").contentDocument.querySelector("[data-source-x]").value==="-7.89"'));
   check('visual checks issue no backend writes',writes.length===0);check('visual checks have no JS exceptions',errors.length===0);
   fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'passed',checks,errors,writes,badAssets},null,2));console.log('PASS',checks.length,'visual/embed checks');await call('Browser.close').catch(()=>{});return;
  }
  check('five top-level entries with one fixed-building workbench',await evaluate('document.querySelectorAll(".workbench-global-header > nav a").length===5&&document.querySelector("[data-workbench-group=fixed-building]").textContent==="固定建筑压力分析"'));
  await set('#projectName','navigation_unsaved_project');await set('#prompt','未保存的建模需求');await set('[data-param]','1.234');
  const parameter=await evaluate('document.querySelector("[data-param]").value');
  await go('refined');await until(()=>evaluate('!!document.querySelector("[data-refined-draft-path]")'));
  const field=await evaluate('document.querySelector("[data-refined-draft-path]").dataset.refinedDraftPath');await set('[data-refined-draft-path]','4.321');
  await go('modeling');check('legacy current project and raw parameters round-trip',await evaluate(`document.querySelector('#projectName').value==='navigation_unsaved_project'&&document.querySelector('#prompt').value==='未保存的建模需求'&&document.querySelector('[data-param]').value===${JSON.stringify(parameter)}`));
  await set('#projectName','navigation_renamed_project');await sleep(220);await load(null,true);await ready('modeling');
  check('renaming synchronizes URL identity and survives refresh',await evaluate('new URL(location.href).searchParams.get("project_name")==="navigation_renamed_project"&&document.querySelector("#projectName").value==="navigation_renamed_project"&&document.querySelector("#prompt").value==="未保存的建模需求"'));
  await set('#projectName','');await set('#prompt','项目名暂时留空也要保留');
  fs.writeFileSync(path.join(out,'empty-project-before-reload.json'),JSON.stringify(await evaluate('({url:location.href,records:JSON.parse(sessionStorage.getItem("lsprepost.workbench.session@1")).records.filter(r=>r.workspace==="modeling").map(r=>({identity:r.identity,url:r.url}))})'),null,2));
  await load(null,true);await ready('modeling');
  check('temporarily empty project name preserves its unsaved fields on refresh',await evaluate('document.querySelector("#projectName").value===""&&document.querySelector("#prompt").value==="项目名暂时留空也要保留"'));
  // Restore a tiny cached editor state; never call the city template/generator.
  await evaluate(`window.dispatchEvent(new CustomEvent('phase17:restore-navigation-state',{detail:{snapshot:{draft:{revision:2,spec:{ground_response:{mode:'validation_crater',anticipated_crater_depth_m:0.6,ale_overlap_layers:5}},transforms:{},blast_source:{position_m:[0,0,1]}},preview:{bounds:{min:[-1,-1,0],max:[1,1,2]},parts:[],components:[],editable_sources:[{source_id:'draft-source',position_m:[0,0,1],editable:true,mobility_profile:'blast_source',allowed_dofs:['tx','ty','tz']}]},selectedId:'draft-source',active:true}}}));`);
  await set('#phase17X','9.876');await set('#phase17GroundCraterDepth','0.91');await go('building');await go('modeling');
  check('city editor preserves raw transforms and ground inputs after rebuilding cached state',await evaluate('document.querySelector("#phase17X").value==="9.876"&&document.querySelector("#phase17GroundCraterDepth").value==="0.91"'));
  await go('refined');check('refined unsubmitted field round-trips',await evaluate(`document.querySelector('[data-refined-draft-path]').dataset.refinedDraftPath===${JSON.stringify(field)}&&document.querySelector('[data-refined-draft-path]').value==='4.321'`));
  await go('pressure');
  check('building and pressure are two local pages under the active fixed-building parent',await evaluate('document.querySelectorAll(".workbench-subnavigation nav a").length===2&&!document.querySelector(".workbench-subnavigation").hidden&&document.querySelector(".workbench-global-header > nav [aria-current]").dataset.workbenchGroup==="fixed-building"&&document.querySelector(".workbench-subnavigation [aria-current]").dataset.workbenchDestination==="pressure"'));
  await set('#sceneName','未保存压力草稿');await set('#curveText','0,0\n尚未写完的 CSV');await click('#addMonitor');await set('[data-coordinate="X"]','');
  await go('building');await go('pressure');
  check('local page switching preserves unfinished pressure parameters',await evaluate('document.querySelector("#curveText").value.includes("尚未写完")&&document.querySelector("[data-coordinate=X]").value===""'));
  await go('response');await set('#benchmark','rc-panel-v1','change');await set('#meshN','16','change');await set('#dtMs','0.05','change');await set('#pressureScale','0.75','change');
  check('local building navigation hides outside its parent workbench',await evaluate('document.querySelector(".workbench-subnavigation").hidden'));
  await go('pressure');check('invalid CSV and blank monitor preserved without forced save',await evaluate('document.querySelector("#sceneName").value==="未保存压力草稿"&&document.querySelector("#curveText").value.includes("尚未写完")&&document.querySelector("[data-coordinate=X]").value===""'));
  await load(null,true);await ready('pressure');check('pressure draft survives refresh',await evaluate('document.querySelector("#curveText").value.includes("尚未写完")'));
  await go('response');check('CPU parameters restored without computation or invented results',await evaluate('document.querySelector("#benchmark").value==="rc-panel-v1"&&document.querySelector("#meshN").value==="16"&&document.querySelector("#dtMs").value==="0.05"&&document.querySelector("#pressureScale").value==="0.75"&&!document.querySelector("#emptyState").hidden'));
  await go('building');await click('[data-view="plan"]');await set('#level','2','change');await evaluate('document.querySelector("#showLabels").checked=false;document.querySelector("#showLabels").dispatchEvent(new Event("change",{bubbles:true}))');
  await go('assessment');await click('[data-demo-add-source]');await set('[data-source-x]','-12.3');
  await go('building');check('building display choices restored',await evaluate('document.querySelector("#level").value==="2"&&!document.querySelector("#showLabels").checked&&document.querySelector(\'[data-view="plan"]\').classList.contains("active")'));
  await go('assessment');check('synthetic demo parameters restored without evaluation',await evaluate('document.querySelectorAll("[data-source-row]").length===2&&document.querySelector("[data-source-x]").value==="-12.3"&&document.querySelector(".demo-shell").dataset.demoState==="ready"'));
  await go('pressure');await go('response');const history=await call('Page.getNavigationHistory');await call('Page.navigateToHistoryEntry',{entryId:history.entries[history.currentIndex-1].id});await ready('pressure');check('browser back restores the unsaved draft',await evaluate('document.querySelector("#curveText").value.includes("尚未写完")'));
  for(const width of[1500,1024,390]){await call('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});await sleep(150);check(`top bar fits ${width}px`,await evaluate('document.documentElement.scrollWidth<=innerWidth+1'));await shot(`pressure-${width}.png`);}
  await evaluate('window.__setItem=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k==="lsprepost.workbench.session@1")throw Error("quota");return window.__setItem.call(this,k,v);}');
  await set('#notes','配额不足也不能丢失的参数');await click('.workbench-subnavigation [data-workbench-destination="building"]');await sleep(300);
  check('quota failure blocks navigation and leaves edits visible',await evaluate('location.pathname==="/structural-pressure"&&document.querySelector("#notes").value.includes("不能丢失")&&document.querySelector(".workbench-global-context [role=status]").textContent.includes("取消切换")'));
  await evaluate('Storage.prototype.setItem=window.__setItem');await go('building');await go('pressure');check('navigation recovers after storage is available',await evaluate('document.querySelector("#notes").value.includes("不能丢失")'));
  // Saved scene responses are synthetic GET fixtures, with no backend mutations.
  const schema=await(await fetch(base+'/api/architecture/pressure/schema')).json(),sceneA='a'.repeat(32),sceneB='b'.repeat(32),runId='c'.repeat(32);
  const record=id=>({scene_id:id,revision:1,config:{...structuredClone(schema.default_config),name:id===sceneA?'场景 A':'场景 B'}});
  getMocks.set('/api/architecture/pressure/scenes/'+sceneA,{body:record(sceneA)});
  getMocks.set('/api/architecture/pressure/scenes/'+sceneB,{body:record(sceneB),delay:1300});
  await load(base+'/structural-pressure?scene_id='+sceneA);await ready('pressure');await set('#notes','场景 A 未保存的参数');await go('response');await set('#pressureScale','0.33','input');await go('modeling');
  await load(base+'/structural-pressure?scene_id='+sceneB);await until(()=>getMocks.get('/api/architecture/pressure/scenes/'+sceneB).seen);
  await set('#notes','慢请求期间的新输入');await ready('pressure');
  check('typing during delayed scene load keeps new input and registers navigation',await evaluate('document.querySelector("#notes").value==="慢请求期间的新输入"'));
  await go('response');check('scene B does not inherit scene A CPU parameters or run',await evaluate(`new URL(location.href).searchParams.get('scene_id')==='${sceneB}'&&document.querySelector('#pressureScale').value!=='0.33'&&!new URL(location.href).searchParams.has('run_id')`));
  await go('pressure');await click('#newScene');await sleep(220);await go('response');
  check('new unsaved scene clears older scene identity in all fixed-building entries',await evaluate('!new URL(location.href).searchParams.has("scene_id")&&!new URL(document.querySelector("nav [data-workbench-destination=pressure]").href).searchParams.has("scene_id")'));
  await load(base+'/structural-pressure?scene_id='+sceneA);await ready('pressure');check('scene A draft remains isolated and recoverable',await evaluate('document.querySelector("#notes").value==="场景 A 未保存的参数"'));
  getMocks.set('/api/architecture/pressure/scenes',{body:{scenes:[{scene_id:sceneB,name:'打开场景 B',revision:1,updated_at:new Date().toISOString()}]}});
  await click('#openSaved');await until(()=>evaluate('!!document.querySelector("#savedList button")'));await click('#savedList button');await until(()=>evaluate(`new URL(location.href).searchParams.get('scene_id')==='${sceneB}'`));
  await load(null,true);await ready('pressure');check('opening saved scene B updates URL and refresh restores its own draft',await evaluate(`new URL(location.href).searchParams.get('scene_id')==='${sceneB}'&&document.querySelector('#notes').value==='慢请求期间的新输入'`));
  const runPath='/api/architecture/pressure/cpu-response/runs/'+runId;
  const run={run_id:runId,status:'running',source:{id:'rc-column-v1'}};getMocks.set(runPath,{body:run});
  await load(base+'/fixed-building-pressure/response?scene_id='+sceneB+'&run_id='+runId);await ready('response');
  check('existing running job does not delay navigation registration',await evaluate(`new URL(location.href).searchParams.get('run_id')==='${runId}'&&document.querySelector('#runState').textContent==='正在计算'`));
  await go('pressure');await go('response');check('running job attachment survives a navigation round-trip without new run',await evaluate(`new URL(location.href).searchParams.get('run_id')==='${runId}'&&!document.querySelector('#cancelRun').hidden`));
  await go('pressure');getMocks.set(runPath,{body:run,delay:1200,seen:false});await load(base+'/fixed-building-pressure/response?run_id='+runId);await until(()=>getMocks.get(runPath).seen);await set('#pressureScale','0.42','input');await ready('response');
  check('delayed saved-run response cannot overwrite new inputs or block navigation',await evaluate('document.querySelector("#pressureScale").value==="0.42"&&!document.querySelector("#emptyState").hidden&&!new URL(location.href).searchParams.has("run_id")'));
  // Reuse a result artifact from earlier work as read-only replay; never solve it again.
  const savedResult=JSON.parse(fs.readFileSync('tests/fixtures/cpu_response/column-navigation-replay.json','utf8'));
  getMocks.set(runPath,{body:{...run,status:'completed',process:{wall_s:1}}});getMocks.set(runPath+'/results',{body:savedResult});
  await go('pressure');await load(base+'/fixed-building-pressure/response?run_id='+runId);await ready('response');
  check('saved result replays using GET only',await evaluate('document.querySelector("#emptyState").hidden'));
  await set('#pressureScale','0.77','input');
  check('unblurred CPU parameter edit immediately invalidates the old result',await evaluate('!document.querySelector("#emptyState").hidden&&!new URL(location.href).searchParams.has("run_id")'));
  await load(null,true);await ready('response');check('refresh preserves edited CPU parameter without restoring mismatched results',await evaluate('document.querySelector("#pressureScale").value==="0.77"&&!document.querySelector("#emptyState").hidden'));
  await go('pressure');await load(base+'/fixed-building-pressure/response?run_id='+runId);await ready('response');
  await evaluate('document.querySelector("#pressureScale").value="0.88"');await load(null,true);await ready('response');
  check('replay provenance rejects raw draft parameters even without an input/change event',await evaluate('document.querySelector("#pressureScale").value==="0.88"&&!document.querySelector("#emptyState").hidden&&!new URL(location.href).searchParams.has("run_id")'));
  for(const id of ['modeling','refined','building','pressure','response','assessment']){
   await go(id);for(const width of[1500,390]){await call('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});await sleep(100);check(`${id} header fits ${width}px`,await evaluate('document.querySelector(".workbench-global-header").getBoundingClientRect().right<=innerWidth+1'));}
  }
  check('no backend write/create/save/preview/run/evaluate requests',writes.length===0);check('no missing JS/CSS',badAssets.length===0);check('no browser JS exceptions',errors.length===0);
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'passed',checks,errors,writes,badAssets},null,2));console.log('PASS',checks.length,'navigation/recovery checks');await call('Browser.close').catch(()=>{});
 }catch(e){if(call)try{const r=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'failure.png'),Buffer.from(r.data,'base64'));fs.writeFileSync(path.join(out,'page.txt'),await evaluate('document.body.innerText'));fs.writeFileSync(path.join(out,'state.json'),JSON.stringify(await evaluate('({url:location.href,fields:window.WorkbenchSession?.captureFields(document.body),records:sessionStorage.getItem("lsprepost.workbench.session@1")})'),null,2));}catch{}
  fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(e),current,checks,errors,writes,badAssets},null,2));throw e;
 }finally{ws?.close();browser.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
