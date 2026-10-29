/* Five independent CPU demonstrations, real Edge Workers and complete histories. */
const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const base=process.argv[2]||'http://127.0.0.1:8917',out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
const selectedScenes=process.argv[4]?process.argv[4].split(','):['residence-3','commercial_supermarket','residential_community','subway_entrance','city_street'];
const computeWait=Number(process.argv[5]||60000);assert(Number.isFinite(computeWait)&&computeWait>=1000&&computeWait<=180000,'invalid computation wait budget');
const checks=[],errors=[],graphicsErrors=[],requests=[],summaries=[],pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,ms=60000){const end=Date.now()+ms;while(Date.now()<end){if(await fn())return;await pause(120);}throw Error('Timeout: '+fn);}
function check(name,value){assert(value,name);checks.push(name);}
(async()=>{
 const panel=await require('../../web/tests/blast-demo-modules.cjs')(path.resolve('lsprepost_mcp/web/static/blast_panel_fracture.js'));
 const debris=await require('../../web/tests/blast-demo-modules.cjs')(path.resolve('lsprepost_mcp/web/static/blast_debris_contact.js'));
 const profile=path.join(out,'edge-profile');fs.mkdirSync(profile,{recursive:true});
 const browser=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new','--disable-gpu','--no-first-run','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'--use-angle=swiftshader','--enable-unsafe-swiftshader','about:blank'],{windowsHide:true,stdio:'ignore'});let ws,diagnostic;
 try{
  let port;await until(()=>{try{port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);return port>0;}catch{return false;}});
  const target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));let seq=0;const pending=new Map();
  const call=(method,params={})=>new Promise((r,j)=>{const id=++seq,timer=setTimeout(()=>{pending.delete(id);j(Error('CDP timeout '+method));},60000);pending.set(id,{r,j,timer});ws.send(JSON.stringify({id,method,params}));});
  ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);clearTimeout(p.timer);m.error?p.j(Error(JSON.stringify(m.error))):p.r(m.result);}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails);else if(m.method==='Network.requestWillBeSent')requests.push(m.params.request);else if(m.method==='Log.entryAdded'&&m.params.entry.level==='error')graphicsErrors.push(m.params.entry);else if(m.method==='Runtime.consoleAPICalled'&&m.params.type==='error')graphicsErrors.push(m.params.args.map(a=>a.value||a.description).join(' '));});
  const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  diagnostic=()=>evaluate('({state:document.body.dataset.result,progress:document.getElementById("computeLabel")?.textContent,message:document.getElementById("inputMessage")?.textContent})');
  const set=(id,value)=>evaluate(`{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));}`);
  const shot=async name=>{const r=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,name),Buffer.from(r.data,'base64'));};
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');await call('Log.enable');await call('Emulation.setDeviceMetricsOverride',{width:1536,height:1000,deviceScaleFactor:1,mobile:false});
  await call('Page.addScriptToEvaluateOnNewDocument',{source:'window.__workers=0;const W=window.Worker;window.Worker=class extends W{constructor(...args){super(...args);window.__workers++;}};'});
  const downloads=path.join(out,'downloads');fs.mkdirSync(downloads,{recursive:true});await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads});
  for(const id of selectedScenes){
   const navigation=await call('Page.navigate',{url:base+'/cpu-blast?building='+id});assert(!navigation.errorText,'static preview navigation failed: '+navigation.errorText);await until(()=>evaluate('document.body.dataset.cpuReady==="true"'));
   check(id+' loads independently without calculation',await evaluate(`document.body.dataset.buildingId===${JSON.stringify(id)}&&document.body.dataset.result==="empty"&&window.__workers===0&&document.getElementById('responseModel').value==='fracture'`));
   // An actual previous-version cache key must survive calculation and refresh.
   await evaluate(`new Promise((resolve,reject)=>{const r=indexedDB.open('lsprepost-simple-blast-results',1);r.onsuccess=()=>{const db=r.result,tx=db.transaction('recent','readwrite');tx.objectStore('recent').put({marker:'preserved-v4'},'progressive-panel-fracture@4:'+${JSON.stringify(id)});tx.oncomplete=()=>{db.close();resolve();};tx.onerror=()=>reject(tx.error);};})`);
   await set('charge','600');await set('duration','6');await shot(id+'-initial.png');
   await evaluate('document.getElementById("startDemo").click()');await until(async()=>{const state=await evaluate('({state:document.body.dataset.result,message:document.getElementById("inputMessage").textContent,saved:document.getElementById("cacheStatus").dataset.saved})');if(state.state==='error')throw Error(state.message);return state.state==='completed'&&state.saved==='true';},computeWait);
   for(const [frame,stage] of [[12,'cracks'],[54,'flying'],[180,'landed']]){await set('timeline',String(frame));await shot(id+'-'+stage+'.png');}
   await evaluate('document.getElementById("downloadDemo").click()');const rawPath=path.join(downloads,(id==='residence-3'?'three-storey':id)+'-blast-result.json');await until(()=>fs.existsSync(rawPath));
   const raw=fs.readFileSync(rawPath),result=JSON.parse(raw),last=result.frames.at(-1).fracture;
   check(id+' saves a complete six-second new response',result.method===panel.PANEL_FRACTURE_METHOD&&result.model.buildingId===id&&result.frames.length===181&&result.frames.at(-1).time===6);
   check(id+' develops finite damage and separated local fragments',result.frames.every(f=>panel.validFractureFrame(f.fracture,result.model)&&f.poses.every(Number.isFinite))&&last.cracked>0&&last.detached>0&&last.limited===0);
   check(id+' computes two-way debris contact with finite supported pile states',result.frames.every(f=>debris.validDebrisFrame(f.debris))&&result.metrics.debris.contacts>0&&result.metrics.debris.limited===0);
   check(id+' displays settled fragments and pile history',await evaluate('document.getElementById("fractureFacts").textContent.includes("个静止碎片")&&document.getElementById("fractureFacts").textContent.includes("近地堆积")'));
   const active=new Set(last.ids),eligible=result.model.bodies.filter(panel.isPanel);check(id+' has no whole-box fallback for failed eligible panels',eligible.filter(b=>result.frames.at(-1).damage[b.id]===1).every(b=>active.has(b.id)));
   const rails=eligible.filter(b=>b.role==='rail'),activeRails=rails.filter(b=>active.has(b.id));
   const summary={id,bodies:result.model.bodies.length,metrics:result.metrics,panels:last.ids.length,cracks:last.cracked,detached:last.detached,eligibleParapets:rails.length,activeParapets:activeRails.length,method:result.method};summaries.push(summary);console.log(JSON.stringify(summary));
   const compressed=zlib.gzipSync(raw,{level:6}),gzipPath=rawPath+'.gz';fs.writeFileSync(gzipPath,compressed);assert(zlib.gunzipSync(compressed).equals(raw));fs.writeFileSync(rawPath+'.sha256',crypto.createHash('sha256').update(raw).digest('hex')+'\n');fs.unlinkSync(rawPath);
   const oldOrigin=await evaluate('performance.timeOrigin');await call('Page.reload',{ignoreCache:true});await until(()=>evaluate(`performance.timeOrigin!==${oldOrigin}&&document.body.dataset.cpuReady==='true'`));
   check(id+' restores its own result without recomputation',await evaluate('document.body.dataset.result==="completed"&&window.__workers===0'));
   check(id+' preserves the prior v4 cache',await evaluate(`new Promise(resolve=>{const r=indexedDB.open('lsprepost-simple-blast-results',1);r.onsuccess=()=>{const db=r.result,q=db.transaction('recent').objectStore('recent').get('progressive-panel-fracture@4:'+${JSON.stringify(id)});q.onsuccess=()=>{resolve(q.result?.marker==='preserved-v4');db.close();};};})`));
  }
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:1000,deviceScaleFactor:1,mobile:false});await shot('city-mobile.png');check('enhanced city page fits mobile',await evaluate('document.documentElement.scrollWidth<=innerWidth+1'));
  check('retained floor contact is exercised by actual scene histories',summaries.some(s=>s.metrics.contacts.floorContacts>0));
  check('only static GET resources, no native/API computation',!requests.some(r=>r.method!=='GET'||new URL(r.url).pathname.startsWith('/api/')));
  check('no JavaScript or GPU errors in all five scenes',errors.length===0&&graphicsErrors.length===0);
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'passed',browser:'Edge',checks,summaries,errors,graphicsErrors},null,2));console.log(JSON.stringify({status:'passed',checks:checks.length,scenes:summaries.length}));await call('Browser.close').catch(()=>{});
 }catch(e){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(e),checks,summaries,errors,graphicsErrors,state:await diagnostic?.().catch(()=>null)},null,2));throw e;}
 finally{ws?.close();browser.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
