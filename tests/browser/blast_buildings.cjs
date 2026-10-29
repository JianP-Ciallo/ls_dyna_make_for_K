/* Four separate Edge tabs, real geometry, Workers and downloaded results. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const out=path.resolve(process.argv[2]),base=process.argv[3]||'http://127.0.0.1:8917';
const pause=ms=>new Promise(r=>setTimeout(r,ms)),checks=[],errors=[],requests=[],connections=[];
const check=(name,value)=>{assert(value,name);checks.push(name);};
async function until(fn,ms=20000){const end=Date.now()+ms;while(Date.now()<end){if(await fn())return;await pause(80);}throw Error('Timeout: '+fn);}
async function connect(target){
 const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
 let seq=0;const pending=new Map();
 const call=(method,params={})=>new Promise((r,j)=>{const id=++seq,timer=setTimeout(()=>{pending.delete(id);j(Error('CDP timeout: '+method));},30000);pending.set(id,{r,j,timer});ws.send(JSON.stringify({id,method,params}));});
 ws.addEventListener('close',()=>{for(const p of pending.values()){clearTimeout(p.timer);p.j(Error('CDP connection closed'));}pending.clear();});
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);clearTimeout(p.timer);m.error?p.j(Error(JSON.stringify(m.error))):p.r(m.result);}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails);else if(m.method==='Network.requestWillBeSent')requests.push(m.params.request);});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const shot=async name=>{const r=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,name),Buffer.from(r.data,'base64'));};
 await call('Page.enable');await call('Runtime.enable');await call('Network.enable');await call('Emulation.setDeviceMetricsOverride',{width:1536,height:1000,deviceScaleFactor:1,mobile:false});
 const c={ws,call,evaluate,shot};connections.push(c);return c;
}
(async()=>{
 fs.mkdirSync(out,{recursive:true});const profile=path.join(out,'edge-profile');fs.mkdirSync(profile,{recursive:true});
 const browser=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new','--no-first-run','--disable-background-networking','--disable-gpu','--remote-debugging-port=0','--user-data-dir='+profile,'--use-angle=swiftshader','--enable-unsafe-swiftshader','about:blank'],{windowsHide:true,stdio:'ignore'});
 let port,main;
 try{
  await until(()=>{try{port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);return port>0;}catch{return false;}});
  const targets=async()=>(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json());
  const target=(await targets()).find(t=>t.type==='page'&&!t.url.startsWith('edge://'));
  main=await connect(target);await main.call('Page.navigate',{url:base+'/blast_buildings.html'});
  await until(()=>main.evaluate('document.body.dataset.catalogReady==="true"&&Array.from(document.querySelectorAll(".preview img")).every(i=>i.complete&&i.naturalWidth>0)'));
  check('five independent entries have actual geometry previews',await main.evaluate('document.querySelectorAll(".card").length===5&&document.querySelectorAll(".preview img").length===5'));
  check('catalog opens each building in its own tab',await main.evaluate('Array.from(document.querySelectorAll(".open")).every(a=>a.target==="_blank")&&new Set(Array.from(document.querySelectorAll(".open"),a=>a.href)).size===5'));
  await main.shot('00-catalog.png');
  const expected=[['residence-2',1006,2],['apartment-5',2383,5],['office-4',1933,4],['tower-8',3765,8]],pages=[],summaries=[];
  const downloads=path.join(out,'downloads');fs.mkdirSync(downloads,{recursive:true});await main.call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads});
  for(const [id,bodies,storeys] of expected){
   const created=await main.call('Target.createTarget',{url:base+'/blast_demo.html?building='+id});let target;
   await until(async()=>{target=(await targets()).find(t=>t.id===created.targetId);return !!target;});const c=await connect(target);pages.push({id,c});await c.call('Page.bringToFront');
   await until(()=>c.evaluate('document.body.dataset.demoReady==="true"'));
   check(id+' renders alone with its own geometry',await c.evaluate(`document.body.dataset.buildingId===${JSON.stringify(id)}&&document.body.dataset.buildingCount==="1"&&Number(document.body.dataset.bodyCount)===${bodies}&&document.querySelector("#modelCount").textContent.startsWith("${storeys}层")`));
   check(id+' starts with independent strong-explosion parameters',await c.evaluate('document.querySelector("#charge").value==="600"&&document.body.dataset.result==="empty"'));
   await c.shot(id+'-before.png');await c.evaluate('document.querySelector("#startDemo").click()');await until(()=>c.evaluate('document.body.dataset.result==="completed"'));
   await c.evaluate('{if(document.querySelector("#playDemo").textContent==="Ⅱ")document.querySelector("#playDemo").click();const t=document.querySelector("#timeline");t.value=54;t.dispatchEvent(new Event("input"));}');
   await c.shot(id+'-flying.png');
   await c.evaluate('{const t=document.querySelector("#timeline");t.value=t.max;t.dispatchEvent(new Event("input"));}');await c.shot(id+'-landed.png');
   await c.evaluate('document.querySelector("#downloadModel").click();document.querySelector("#downloadDemo").click()');
   const resultPath=path.join(downloads,id+'-blast-result.json'),modelPath=path.join(downloads,id+'-solid-geometry.json');
   await until(()=>fs.existsSync(resultPath)&&fs.existsSync(modelPath),20000);
   const result=JSON.parse(fs.readFileSync(resultPath,'utf8')),model=JSON.parse(fs.readFileSync(modelPath,'utf8'));
   check(id+' downloads only its own actual calculated history',model.buildingId===id&&model.buildingCount===1&&model.bodies.length===bodies&&result.config.building===id&&result.model.buildingId===id&&result.metrics.broken>0&&result.frames.at(-1).time===6&&result.frames[0].poses.length===bodies*7);
   summaries.push({id,bodies,broken:result.metrics.broken,wallMs:result.metrics.wallMs,frames:result.frames.length});
  }
  for(const {id,c} of pages)check(id+' result remains independent of other tabs',await c.evaluate(`document.body.dataset.buildingId===${JSON.stringify(id)}&&document.body.dataset.result==="completed"&&document.querySelector("#timeDisplay").textContent==="6.00 / 6.00 s"`));
  const last=pages.at(-1).c;await last.evaluate('const e=document.querySelector("#charge");e.value="650";e.dispatchEvent(new Event("input"));');
  check('editing one building clears only that result',await last.evaluate('document.body.dataset.result==="empty"&&document.querySelector("#timeline").disabled')&&await pages[0].c.evaluate('document.body.dataset.result==="completed"'));
  await last.call('Page.reload',{ignoreCache:true});await until(()=>last.evaluate('document.body.dataset.demoReady==="true"'));
  check('tower configuration is restored separately',await last.evaluate('document.querySelector("#charge").value==="650"&&document.body.dataset.buildingId==="tower-8"&&document.body.dataset.result==="empty"'));
  await main.call('Page.navigate',{url:base+'/blast_demo.html'});await until(()=>main.evaluate('document.body.dataset.demoReady==="true"'));
  check('original building and its default configuration remain available',await main.evaluate('document.body.dataset.buildingId==="residence-3"&&Number(document.body.dataset.bodyCount)===1465&&document.querySelector("#charge").value==="160"'));
  check('all four configuration keys are isolated',await main.evaluate('["residence-2","apartment-5","office-4","tower-8"].every((id,i)=>JSON.parse(localStorage.getItem("simple-blast-demo-config-v1:"+id)).mass===(i===3?650:600))'));
  await main.call('Page.bringToFront');await main.call('Page.navigate',{url:base+'/blast_buildings.html'});await until(()=>main.evaluate('document.body.dataset.catalogReady==="true"'));
  await main.call('Emulation.setDeviceMetricsOverride',{width:390,height:900,deviceScaleFactor:1,mobile:false});await pause(200);await main.shot('catalog-mobile.png');
  check('catalog fits mobile width',await main.evaluate('document.documentElement.scrollWidth<=innerWidth+1'));
  check('no native API or remote computation',!requests.some(r=>r.method==='POST'||new URL(r.url).pathname.startsWith('/api/')));
  check('no browser exceptions',errors.length===0);
  const record={status:'passed',browser:'Edge',checks,summaries,errors};fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify(record,null,2));console.log(JSON.stringify(record));
  await main.call('Browser.close').catch(()=>{});
 }catch(e){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(e),checks,errors},null,2));throw e;}
 finally{for(const c of connections)c.ws.close();browser.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
