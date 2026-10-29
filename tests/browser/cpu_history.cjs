/* Real Chrome + isolated fixture HTTP API; no solver/profile/task creation allowed. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const base=process.argv[2]||'http://127.0.0.1:8899',out=path.resolve(process.argv[3]||'artifacts/cpu-history-browser-20261022-01');fs.mkdirSync(out,{recursive:true});
const checks=[],errors=[],writes=[],forbidden=[],responses=[];let ws,call,evaluate,accept=false;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,timeout=20000){const end=Date.now()+timeout;while(Date.now()<end){if(await fn())return;await sleep(65);}throw Error('timeout '+fn);}
const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
(async()=>{
 const fixture=await(await fetch(base+'/api/test-cpu-history')).json();assert.equal((fixture.result||fixture).isolated_no_compute,true,'must use isolated fixture server');
 for(const ch of ['a','b']){const r=await fetch(base+'/api/architecture/pressure/cpu-response/runs/'+ch.repeat(32)+'/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});assert.equal(r.status,200);}
 const chrome='C:/Program Files/Google/Chrome/Application/chrome.exe',profile=path.join(out,'chrome-profile');fs.mkdirSync(profile,{recursive:true});
 const browser=spawn(chrome,['--headless=new','--no-first-run','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'--use-angle=swiftshader','--enable-unsafe-swiftshader','about:blank'],{windowsHide:true,stdio:'ignore'});
 try{
  let port;await until(async()=>{try{port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);return port>0;}catch{return false;}});
  const target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});let seq=0;const pending=new Map();
  call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  ws.addEventListener('message',ev=>{
   const m=JSON.parse(ev.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}return;}
   if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
   if(m.method==='Network.responseReceived')responses.push({url:m.params.response.url,status:m.params.response.status});
   if(m.method==='Page.javascriptDialogOpening')call('Page.handleJavaScriptDialog',{accept}).catch(()=>{});
   if(m.method==='Fetch.requestPaused'){const p=m.params;if(p.request.method==='GET')call('Fetch.continueRequest',{requestId:p.requestId}).catch(()=>{});else if(p.request.method==='POST'&&/\/runs\/[ab]{32}\/(delete|restore)$/.test(new URL(p.request.url).pathname)){writes.push(p.request.url);call('Fetch.continueRequest',{requestId:p.requestId}).catch(()=>{});}else{forbidden.push(p.request.url);call('Fetch.failRequest',{requestId:p.requestId,errorReason:'Aborted'}).catch(()=>{});}}
  });
  evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  const click=s=>evaluate(`document.querySelector(${JSON.stringify(s)}).click()`);
  const select=id=>evaluate(`{const e=document.querySelector('#history');e.value=${JSON.stringify(id)};e.dispatchEvent(new Event('change',{bubbles:true}));}`);
  async function ready(){await until(()=>evaluate('document.querySelector(".workbench-global-context [role=status]")?.textContent.includes("保留")&&document.querySelectorAll("#history option").length===4'));}
  async function shot(name){const r=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,name),Buffer.from(r.data,'base64'));}
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');await call('Fetch.enable',{patterns:[{urlPattern:'*/api/*',requestStage:'Request'}]});
  await call('Emulation.setDeviceMetricsOverride',{width:1500,height:1000,deviceScaleFactor:1,mobile:false});await call('Page.navigate',{url:base+'/fixed-building-pressure/response'});await ready();
  await until(()=>evaluate('!document.querySelector("#openBuildingTrial").disabled'));
  check('three-storey building status is visible above component benchmarks',await evaluate('document.querySelector("#buildingTrialState").textContent.includes("首试已完成")&&document.querySelector("#buildingTrialState").textContent.includes("收敛待验证")'));
  const a='a'.repeat(32),b='b'.repeat(32),c='c'.repeat(32);
  await select(a);await until(()=>evaluate('document.querySelector("#runState").textContent==="失败"'));await click('#deleteHistory');await sleep(150);
  check('cancelling delete keeps the record and issues no mutation',writes.length===0&&await evaluate(`!!document.querySelector('#history option[value="${a}"]')`));
  accept=true;await click('#deleteHistory');await until(()=>evaluate(`!document.querySelector('#history option[value="${a}"]')`));
  check('confirmed deletion hides only selected failed record',await evaluate(`!!document.querySelector('#history option[value="${b}"]')&&!!document.querySelector('#history option[value="${c}"]')`));
  await click('#showDeleted');await until(()=>evaluate(`!!document.querySelector('#history option[value="${a}"]')`));await select(a);
  check('deleted record offers restoration',await evaluate('!document.querySelector("#restoreHistory").hidden&&!document.querySelector("#restoreHistory").disabled'));
  await click('#restoreHistory');await until(()=>evaluate('document.querySelectorAll("#history option").length===1'));await click('#showDeleted');await ready();
  check('restore returns original failed record to normal history',await evaluate(`!!document.querySelector('#history option[value="${a}"]')`));
  await select(b);await until(()=>evaluate('document.querySelector("#emptyState").hidden'));await click('#deleteHistory');await until(()=>evaluate('!document.querySelector("#emptyState").hidden&&!new URL(location.href).searchParams.has("run_id")'));
  check('deleting displayed completed result clears result and stale run URL',await evaluate('document.querySelector("#peakDisplacement").textContent==="—"'));
  const previous=await evaluate('performance.timeOrigin');await call('Page.reload',{ignoreCache:true});await until(async()=>{try{return await evaluate('performance.timeOrigin')!==previous;}catch{return false;}});await until(()=>evaluate('document.querySelector(".workbench-global-context [role=status]")?.textContent.includes("保留")&&document.querySelectorAll("#history option").length===3'));
  check('deleted record stays hidden after page reload',await evaluate(`!document.querySelector('#history option[value="${b}"]')&&!document.querySelector('#emptyState').hidden`));
  await select(c);await until(()=>evaluate('document.querySelector("#runState").textContent==="正在计算"'));
  check('running record cannot be deleted',await evaluate('document.querySelector("#deleteHistory").disabled'));
  await evaluate('document.querySelector("#history").scrollIntoView({block:"center"})');await shot('history-desktop.png');
  await click('#openBuildingTrial');await until(()=>evaluate('document.querySelector("#buildingTrialDeformation").complete&&document.querySelector("#buildingTrialDeformation").naturalWidth>0&&document.querySelector("#buildingTrialCurves").naturalWidth>0'));
  check('building dialog shows saved 10kPa/150ms trial and original result figures',await evaluate('document.querySelector("#buildingTrialFacts").textContent.includes("10 kPa")&&document.querySelector("#buildingTrialFacts").textContent.includes("150 ms")&&document.querySelector(".building-trial-warning").textContent.includes("尚未验收")'));
  await shot('building-saved-trial.png');await click('#closeBuildingTrial');await call('Emulation.setDeviceMetricsOverride',{width:390,height:900,deviceScaleFactor:1,mobile:false});await evaluate('scrollTo(0,0)');await sleep(150);await shot('mobile.png');
  check('mobile page fits viewport',await evaluate('document.documentElement.scrollWidth<=innerWidth+1'));
  check('only fixture delete/restore mutations occurred',forbidden.length===0&&writes.length===3);
  check('no browser exceptions or missing app assets',errors.length===0&&!responses.some(r=>r.status>=400&&!r.url.endsWith('/favicon.ico')));
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'passed',checks,errors,writes,forbidden},null,2));console.log('PASS',checks.length,'history/building-evidence checks');await call('Browser.close').catch(()=>{});
 }catch(e){if(call)try{await call('Page.captureScreenshot',{format:'png'}).then(r=>fs.writeFileSync(path.join(out,'failure.png'),Buffer.from(r.data,'base64')));fs.writeFileSync(path.join(out,'page.txt'),await evaluate('document.body.innerText'));}catch{}fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(e),checks,errors,writes,forbidden,responses},null,2));throw e;}
 finally{ws?.close();browser.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
