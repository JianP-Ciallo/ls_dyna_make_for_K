/* Real Chromium browser + real lightweight Worker dynamics. No native solver/API. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const base=process.argv[2]||'http://127.0.0.1:8917',out=path.resolve(process.argv[3]||'artifacts/simple-blast-demo-20261024-01/browser');fs.mkdirSync(out,{recursive:true});
const errors=[],requests=[],checks=[];let ws,browser,call,evaluate;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,ms=15000){const end=Date.now()+ms;while(Date.now()<end){try{if(await fn())return;}catch{}await pause(70);}throw Error('timeout: '+fn);}
const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
(async()=>{
 const profile=path.join(out,'chrome-profile');fs.mkdirSync(profile,{recursive:true});
 browser=spawn(process.argv[4]||'C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--no-first-run','--disable-background-networking','--disable-gpu','--remote-debugging-port=0','--user-data-dir='+profile,'--use-angle=swiftshader','--enable-unsafe-swiftshader','about:blank'],{windowsHide:true,stdio:'ignore'});
 try{
  let port;await until(()=>{try{port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);return port>0;}catch{return false;}});
  const target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');
  ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
  let seq=0;const pending=new Map();call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  ws.addEventListener('message',ev=>{const m=JSON.parse(ev.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}return;}
   if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
   if(m.method==='Network.requestWillBeSent')requests.push({method:m.params.request.method,url:m.params.request.url});
  });
  evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  const click=id=>evaluate(`document.getElementById('${id}').click()`);
  const set=(id,value,event='input')=>evaluate(`{const e=document.getElementById('${id}');e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('${event}',{bubbles:true}));}`);
  const shot=async name=>{const s=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,name),Buffer.from(s.data,'base64'));};
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');await call('Emulation.setDeviceMetricsOverride',{width:1536,height:1000,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:base+'/blast_demo.html'});await until(()=>evaluate('document.body.dataset.demoReady==="true"'));
  check('three-storey solid geometry renders without K or solver requests',await evaluate('Number(document.body.dataset.bodyCount)>300&&!!document.querySelector("#viewport canvas")&&!document.querySelector("#startDemo").disabled'));
  await shot('01-building.png');await click('startDemo');
  await until(()=>evaluate('document.body.dataset.result==="completed"'),15000);
  await click('playDemo');
  check('real Worker simulation completes with broken components and replay controls',await evaluate('!document.querySelector("#timeline").disabled&&Number(document.querySelector("#timeline").max)>100&&parseInt(document.querySelector("#inputMessage").textContent.match(/共 ([0-9]+)/)[1])>0&&!document.querySelector("#downloadDemo").disabled'));
  const metrics=await evaluate('({time:document.querySelector("#wallTime").textContent,result:document.querySelector("#inputMessage").textContent})');
  await set('timeline','54');await shot('02-blast-motion.png');await click('damage');await shot('03-damage.png');await click('appearance');
  check('scrubbing uses computed time and damage field',await evaluate('document.querySelector("#timeDisplay").textContent.startsWith("1.80")'));
  const downloads=path.join(out,'downloads');fs.mkdirSync(downloads,{recursive:true});
  await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads});
  await click('downloadModel');await until(()=>fs.existsSync(path.join(downloads,'three-storey-solid-geometry.json')));
  await click('downloadDemo');await until(()=>fs.existsSync(path.join(downloads,'three-storey-blast-result.json')));
  const savedModel=JSON.parse(fs.readFileSync(path.join(downloads,'three-storey-solid-geometry.json'),'utf8')),savedResult=JSON.parse(fs.readFileSync(path.join(downloads,'three-storey-blast-result.json'),'utf8'));
  check('downloads preserve the actual geometry and computed motion',savedModel.bodies.length===1465&&savedResult.frames.length>100&&savedResult.metrics.broken>0&&Array.isArray(savedResult.frames[0].poses));
  await click('resetDemo');check('reset returns to intact initial frame',await evaluate('document.querySelector("#timeline").value==="0"&&document.querySelector("#brokenCount").textContent.startsWith("0 ")'));
  await set('charge','600');check('changed inputs clear old results',await evaluate('document.body.dataset.result==="empty"&&document.querySelector("#timeline").disabled&&document.querySelector("#downloadDemo").disabled'));
  await click('startDemo');await until(()=>evaluate('document.body.dataset.result==="completed"'));await click('playDemo');await set('timeline','85');await shot('04-strong-blast.png');
  await set('duration','10');await click('startDemo');await click('cancelDemo');await pause(200);
  check('cancel terminates Worker and ignores late completion',await evaluate('document.body.dataset.result==="cancelled"&&document.body.dataset.running==="false"&&!document.querySelector("#startDemo").disabled'));
  await set('sourceX','0');await set('sourceY','0');check('inside-building source is rejected',await evaluate('document.querySelector("#startDemo").disabled&&document.querySelector("#inputMessage").textContent.includes("建筑外")'));
  await set('sourceY','-12');await set('charge','0');await set('duration','3');await click('startDemo');await until(()=>evaluate('document.body.dataset.result==="completed"'));await click('playDemo');await set('timeline','0');
  const intact=await evaluate('document.querySelector("#viewport canvas").toDataURL()');
  await set('timeline','54');const noBlast=await evaluate('document.querySelector("#viewport canvas").toDataURL()');
  check('zero-charge replay has no explosion or smoke effects',intact===noBlast);
  await set('sourceY','-12');await set('charge','160');await set('duration','6');await call('Page.reload',{ignoreCache:true});await until(()=>evaluate('document.body.dataset.demoReady==="true"'));
  check('parameters survive reload without starting another simulation',await evaluate('document.querySelector("#sourceY").value==="-12"&&document.body.dataset.result==="empty"'));
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:900,deviceScaleFactor:1,mobile:false});await pause(150);await shot('05-mobile.png');
  check('mobile page fits its viewport',await evaluate('document.documentElement.scrollWidth<=innerWidth+1'));
  check('no native API or remote calculation request',!requests.some(r=>r.method==='POST'||new URL(r.url).pathname.startsWith('/api/')));
  check('no browser exceptions',errors.length===0);
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'passed',checks,metrics,errors,requests},null,2));console.log(JSON.stringify({status:'passed',checks:checks.length,metrics}));
  await call('Browser.close').catch(()=>{});
 }catch(e){
  try{const s=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'failure.png'),Buffer.from(s.data,'base64'));fs.writeFileSync(path.join(out,'page.txt'),await evaluate('document.body.innerText'));}catch{}
  fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(e),checks,errors,requests},null,2));throw e;
 }finally{ws?.close();browser?.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
