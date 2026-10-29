/* Real Edge, shipped CPU shell and real lightweight Workers; no native API. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const base=process.argv[2]||'http://127.0.0.1:8918',out=path.resolve(process.argv[3]);
fs.mkdirSync(out,{recursive:true});const checks=[],errors=[],requests=[],summaries=[];
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,ms=25000){const end=Date.now()+ms;while(Date.now()<end){try{if(await fn())return;}catch{}await pause(90);}throw Error('Timeout: '+fn);}
const check=(name,value)=>{assert(value,name);checks.push(name);};
(async()=>{
 const profile=path.join(out,'edge-profile');fs.mkdirSync(profile,{recursive:true});
 const browser=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new','--disable-gpu','--no-first-run','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'--use-angle=swiftshader','--enable-unsafe-swiftshader','about:blank'],{windowsHide:true,stdio:'ignore'});
 let ws;
 try{
  let port;await until(()=>{try{port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);return port>0;}catch{return false;}});
  const target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');
  ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
  let seq=0;const pending=new Map();
  const call=(method,params={})=>new Promise((r,j)=>{const id=++seq,timer=setTimeout(()=>{pending.delete(id);j(Error('CDP timeout '+method));},30000);pending.set(id,{r,j,timer});ws.send(JSON.stringify({id,method,params}));});
  ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);if(p){clearTimeout(p.timer);pending.delete(m.id);m.error?p.j(Error(JSON.stringify(m.error))):p.r(m.result);}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails);else if(m.method==='Network.requestWillBeSent')requests.push(m.params.request);});
  const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  const shot=async name=>{const r=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,name),Buffer.from(r.data,'base64'));};
  const set=(id,value,event='input')=>evaluate(`{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event(${JSON.stringify(event)},{bubbles:true}));}`);
  const ready=()=>until(()=>evaluate('document.body.dataset.cpuReady==="true"&&document.body.dataset.activeWorkbench==="blast"'));
  async function load(url,reload=false){const previous=await evaluate('performance.timeOrigin');await call(reload?'Page.reload':'Page.navigate',reload?{ignoreCache:true}:{url});await until(()=>evaluate('performance.timeOrigin') .then(t=>t!==previous));await ready();}
  async function switchTo(id){const previous=await evaluate('performance.timeOrigin');await set('buildingSelect',id,'change');await until(()=>evaluate('performance.timeOrigin').then(t=>t!==previous));await ready();}
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');
  await call('Page.addScriptToEvaluateOnNewDocument',{source:'window.__workerCount=0;const NativeWorker=window.Worker;window.Worker=class extends NativeWorker{constructor(...args){super(...args);window.__workerCount++;}};'});
  await call('Emulation.setDeviceMetricsOverride',{width:1536,height:1000,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:base+'/cpu-blast'});await ready();
  check('original CPU route now opens lightweight simulator',await evaluate('document.body.dataset.buildingId==="residence-3"&&document.querySelectorAll("#buildingSelect option").length===5&&window.__workerCount===0'));
  check('one active workbench navigation',await evaluate('document.querySelectorAll(".workbench-global-header").length===1&&document.querySelector("[data-workbench-destination=blast]").getAttribute("aria-current")==="page"'));
  check('application palette and primary action match',await evaluate('getComputedStyle(document.body).backgroundColor==="rgb(243, 246, 248)"&&getComputedStyle(document.getElementById("startDemo")).backgroundColor==="rgb(22, 117, 138)"'));
  check('desktop parameters sit beside an unobstructed 3D stage',await evaluate('document.querySelector(".cpu-settings").getBoundingClientRect().right<document.querySelector(".cpu-stage").getBoundingClientRect().left&&document.getElementById("viewport").clientHeight>=390'));
  await shot('00-cpu-desktop.png');
  for(const id of ['residence-3','commercial_supermarket','residential_community','subway_entrance','city_street']){
   if(id!=='residence-3')await switchTo(id);
   check(id+' has independent identity without automatic computation',await evaluate(`document.body.dataset.buildingId===${JSON.stringify(id)}&&window.__workerCount===0&&new URL(location.href).searchParams.get('building')===${JSON.stringify(id)}`));
   await set('charge','600');await set('duration','6');await evaluate('document.getElementById("startDemo").click()');
   await until(()=>evaluate('document.body.dataset.result==="completed"&&document.getElementById("cacheStatus").dataset.saved==="true"'));
   await evaluate('{const t=document.getElementById("timeline");t.value=54;t.dispatchEvent(new Event("input"));}');
   await shot(id+'-flying.png');
   await evaluate('{const t=document.getElementById("timeline");t.value=t.max;t.dispatchEvent(new Event("input"));}');
   const summary=await evaluate('({id:document.body.dataset.buildingId,bodies:Number(document.body.dataset.bodyCount),broken:document.getElementById("brokenCount").textContent,time:document.getElementById("timeDisplay").textContent,wallTime:document.getElementById("wallTime").textContent})');summaries.push(summary);
   check(id+' completes real response and full timeline',summary.time==='6.00 / 6.00 s'&&Number(summary.broken.split('/')[0].trim())>0);
   await shot(id+'-landed.png');await load(null,true);
   check(id+' restores its own result after refresh without a new Worker',await evaluate('document.body.dataset.result==="completed"&&document.getElementById("timeDisplay").textContent==="6.00 / 6.00 s"&&window.__workerCount===0'));
  }
  await set('charge','650');await load(null,true);
  check('changed parameters never reuse mismatching cached results',await evaluate('document.body.dataset.result==="empty"&&document.getElementById("charge").value==="650"&&window.__workerCount===0'));
  await switchTo('subway_entrance');
  check('switching back keeps a different scene result and parameters',await evaluate('document.body.dataset.result==="completed"&&document.getElementById("charge").value==="600"&&window.__workerCount===0'));
  await evaluate('document.getElementById("showRoof").click();document.getElementById("damage").click()');await load(null,true);
  check('display controls survive refresh',await evaluate('!document.getElementById("showRoof").checked&&document.getElementById("damage").getAttribute("aria-pressed")==="true"'));
  await evaluate('document.getElementById("showRoof").click();document.getElementById("appearance").click()');
  for(const width of [1920,1024,768,390]){
   await call('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});await pause(200);await evaluate('document.getElementById("fitDemo").click()');
   check('layout fits '+width+'px',await evaluate('document.documentElement.scrollWidth<=innerWidth+1&&document.querySelectorAll(".chart-card").length===2&&Array.from(document.querySelectorAll(".chart-card")).every(e=>getComputedStyle(e).display!=="none")'));
   await shot('cpu-'+width+'.png');
  }
  await load(base+'/cpu-blast?source=city_street&run_id='+'a'.repeat(32));
  check('legacy links select the right new scene and retain old record access',await evaluate('document.body.dataset.buildingId==="city_street"&&document.getElementById("legacyCpu").href.includes("run_id="+"a".repeat(32))&&document.getElementById("legacyCpu").href.includes("legacy=1")&&window.__workerCount===0'));
  await load(null,true);
  check('legacy record identity survives refresh',await evaluate('new URL(location.href).searchParams.get("run_id")==="a".repeat(32)&&document.getElementById("legacyCpu").href.includes("run_id="+"a".repeat(32))'));
  await set('sourceX','');await load(null,true);
  check('unfinished coordinate stays blank and prevents computation',await evaluate('document.getElementById("sourceX").value===""&&document.getElementById("startDemo").disabled&&window.__workerCount===0'));
  await set('sourceX','0');
  const delayed=await call('Page.addScriptToEvaluateOnNewDocument',{source:'const open=indexedDB.open.bind(indexedDB);indexedDB.open=(...args)=>{const r=open(...args);Object.defineProperty(r,"onsuccess",{set(fn){r.addEventListener("success",()=>setTimeout(()=>fn.call(r),900));}});return r;};'});
  const prior=await evaluate('performance.timeOrigin');await call('Page.reload',{ignoreCache:true});
  await until(()=>evaluate('performance.timeOrigin').then(t=>t!==prior));await until(()=>evaluate('document.body.dataset.demoReady==="true"&&document.body.dataset.cpuReady!=="true"'));
  check('delayed cache restoration keeps Start and scene switching locked',await evaluate('document.getElementById("startDemo").disabled&&document.getElementById("buildingSelect").disabled'));
  await evaluate('document.getElementById("startDemo").click()');check('cache waiting cannot launch a competing Worker',await evaluate('window.__workerCount===0'));
  await ready();await call('Page.removeScriptToEvaluateOnNewDocument',{identifier:delayed.identifier});
  const badResult=await call('Page.addScriptToEvaluateOnNewDocument',{source:'const WorkerBeforeFault=window.Worker;window.Worker=class extends WorkerBeforeFault{set onmessage(fn){super.onmessage=e=>{if(e.data.kind==="result")e.data.result.schema="invalid-fixture";fn(e);};}};'});
  await load(base+'/cpu-blast?building=commercial_supermarket');await set('charge','200');await set('duration','3');await evaluate('document.getElementById("startDemo").click()');
  await until(()=>evaluate('document.body.dataset.result==="error"'));
  check('invalid Worker result enters an explicit stopped error state',await evaluate('document.getElementById("stageStatus").textContent==="已停止"&&document.getElementById("downloadDemo").disabled&&document.body.dataset.running==="false"'));
  await call('Page.removeScriptToEvaluateOnNewDocument',{identifier:badResult.identifier});
  const cacheFailure=await call('Page.addScriptToEvaluateOnNewDocument',{source:'indexedDB.open=()=>{throw Error("Storage denied fixture");};'});
  await load(null,true);check('unavailable cache leaves calculation available',await evaluate('document.getElementById("cacheStatus").dataset.error==="true"&&!document.getElementById("startDemo").disabled&&window.__workerCount===0'));
  await evaluate('document.getElementById("startDemo").click()');await until(()=>evaluate('document.body.dataset.result==="completed"'));
  check('cache write failure preserves completed playback and download',await evaluate('document.getElementById("cacheStatus").dataset.error==="true"&&!document.getElementById("downloadDemo").disabled&&!document.getElementById("timeline").disabled'));
  await evaluate('document.getElementById("startDemo").click()');await set('buildingSelect','city_street','change');await pause(150);
  check('running computation blocks scene switch without losing identity',await evaluate('document.body.dataset.buildingId==="commercial_supermarket"&&document.getElementById("buildingSelect").value==="commercial_supermarket"&&document.body.dataset.running==="true"'));
  await evaluate('document.getElementById("cancelDemo").click()');check('integrated calculation stops explicitly',await evaluate('document.body.dataset.result==="cancelled"&&document.body.dataset.running==="false"'));
  await call('Page.removeScriptToEvaluateOnNewDocument',{identifier:cacheFailure.identifier});
  await evaluate('document.querySelector(".cpu-heading-actions a").click()');
  await until(()=>evaluate('document.body.dataset.catalogReady==="true"'));await shot('catalog-light.png');
  check('catalog opens the same five CPU routes',await evaluate('document.querySelectorAll(".card").length===5&&Array.from(document.querySelectorAll(".card .open")).every(e=>new URL(e.href).pathname==="/cpu-blast")'));
  check('no engineering API or backend mutation requested',!requests.some(r=>r.method!=='GET'||new URL(r.url).pathname.startsWith('/api/')));
  check('no browser exceptions',errors.length===0);
  const result={status:'passed',browser:'Edge',checks,summaries,errors};fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));await call('Browser.close').catch(()=>{});
 }catch(error){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(error),checks,summaries,errors},null,2));throw error;}
 finally{ws?.close();browser.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
