/* Real Chrome, real bounded source adapters; ONLY synthetic jobs on isolated server. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const base=process.argv[2]||'http://127.0.0.1:8907',out=path.resolve(process.argv[3]||'artifacts/scene-blast-browser-20261023-01');fs.mkdirSync(out,{recursive:true});
const checks=[],errors=[],responses=[],writes=[];let ws,call,evaluate;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,timeout=30000){const end=Date.now()+timeout;while(Date.now()<end){try{if(await fn())return;}catch{}await pause(70);}throw Error('timeout: '+fn);}
function check(name,value){assert.ok(value,name);checks.push(name);}
(async()=>{
 const health=await(await fetch(base+'/api/test-scene-blast')).json();assert((health.result||health).isolated_no_compute,'must use isolated synthetic fixture');
 const profile=path.join(out,'chrome-profile');fs.mkdirSync(profile,{recursive:true});const browser=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--no-first-run','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'--use-angle=swiftshader','--enable-unsafe-swiftshader','about:blank'],{windowsHide:true,stdio:'ignore'});
 try{
  let port;await until(()=>{try{port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);return port>0;}catch{return false;}});
  const target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
  let sequence=0;const pending=new Map();call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  ws.addEventListener('message',ev=>{const m=JSON.parse(ev.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}return;}
    if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
    if(m.method==='Network.responseReceived')responses.push({url:m.params.response.url,status:m.params.response.status});
    if(m.method==='Network.requestWillBeSent'&&m.params.request.method==='POST')writes.push({url:m.params.request.url,body:m.params.request.postData});
  });
  evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  const click=id=>evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
  const set=(id,value,event='input')=>evaluate(`{const el=document.getElementById(${JSON.stringify(id)});el.value=${JSON.stringify(value)};el.dispatchEvent(new Event(${JSON.stringify(event)},{bubbles:true}));}`);
  const ready=()=>until(()=>evaluate('document.body.dataset.sceneInitialized==="true"&&document.body.dataset.sceneReady==="true"'));
  const shot=async name=>{const s=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,name),Buffer.from(s.data,'base64'));};
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');await call('Emulation.setDeviceMetricsOverride',{width:1536,height:1050,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:base+'/cpu-blast?legacy=1'});await ready();
  check('global CPU entry opens scene simulator; old two-page group remains intact',await evaluate('document.querySelector("[data-workbench-destination=blast]").getAttribute("href").startsWith("/cpu-blast")&&document.querySelectorAll(".workbench-subnavigation a").length===2'));
  check('fixed building loads its original facade and distributed slab model',await evaluate('Number(document.querySelector("#sceneViewport").dataset.loadedBodies)===546&&!!document.querySelector("#sceneViewport canvas")'));
  check('preview and initial navigation never create a job',!writes.some(w=>new URL(w.url).pathname==='/api/cpu-blast/runs'));
  await shot('three-storey-scene.png');
  const marker=await evaluate('(()=>{const h=document.querySelector("#sceneViewport"),r=h.getBoundingClientRect(),l=document.querySelector(".scene-tnt-label");return {x:r.left+parseFloat(l.style.left),y:r.top+parseFloat(l.style.top),before:[document.querySelector("#tntX").value,document.querySelector("#tntY").value]};})()');
  await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:marker.x+19,y:marker.y-6});await call('Input.dispatchMouseEvent',{type:'mousePressed',x:marker.x+19,y:marker.y-6,button:'left',clickCount:1});
  for(let i=1;i<=5;i++)await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:marker.x+19+i*5,y:marker.y-6-i*3,button:'left',buttons:1});
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:marker.x+44,y:marker.y-21,button:'left',clickCount:1});await pause(100);
  check('dragging the TNT gizmo changes world coordinates while staying on ground',await evaluate(`document.querySelector('#tntZ').value==='0.000'&&(document.querySelector('#tntX').value!==${JSON.stringify(marker.before[0])}||document.querySelector('#tntY').value!==${JSON.stringify(marker.before[1])})`));
  await set('tntX','10');await set('tntY','-10');
  for(const source of ['commercial_supermarket','residential_community','subway_entrance','city_street']){
    await set('sourceKind',source,'change');await until(()=>evaluate(`document.body.dataset.sceneKind===${JSON.stringify(source)}&&document.body.dataset.sceneReady==='true'&&!document.querySelector('#startSimulation').disabled`));
    check(source+' uses bounded existing geometry',await evaluate('Number(document.querySelector("#sceneViewport").dataset.loadedBodies)>100'));
    if(source==='city_street')await shot('city-scene.png');
  }
  await set('tntX','7.35');await set('tntY','-11.2');await set('tntMass','25');await pause(200);
  check('editing TNT does not run computation',!writes.some(w=>new URL(w.url).pathname==='/api/cpu-blast/runs'));
  await set('tntZ','2');await pause(80);check('unsupported elevated burst is rejected before Start',await evaluate('document.querySelector("#startSimulation").disabled&&document.querySelector("#jobMessage").textContent.includes("Z=0")'));await set('tntZ','0');await pause(80);
  await click('startSimulation');await until(()=>evaluate('document.querySelector("#resultState").textContent==="计算完成"'));
  check('explicit Start freezes current TNT and model',writes.filter(w=>new URL(w.url).pathname==='/api/cpu-blast/runs').length===1&&JSON.parse(writes.find(w=>new URL(w.url).pathname==='/api/cpu-blast/runs').body).input.tnt.mass_kg===25);
  check('same-scene replay and real-result controls are enabled',await evaluate('!document.querySelector("#sceneTime").disabled&&!document.querySelector("#downloadResult").disabled&&document.querySelector("#maxDisplacement").textContent==="1.000 mm"&&document.querySelector("#resultLimits").textContent.includes("SYNTHETIC")'));
  await until(()=>evaluate('!document.querySelector("#downloadGravity").disabled'));
  check('sealed gravity diagnostics are visible and downloadable without a new solve',await evaluate('!document.querySelector("#gravityPanel").hidden&&document.querySelector("#gravityFacts").textContent.includes("SYNTHETIC")&&document.querySelector("#gravityFacts").textContent.includes("100.0%")'));
  check('stability conclusion is explicit without inventing a minimum eigenvalue',await evaluate('document.querySelector("#gravityFacts").textContent.includes("正定验证已通过")'));
  await set('sceneTime','2');await pause(80);await shot('synthetic-replay.png');
  await set('tntMass','26');await pause(100);check('changed input clears stale result, timeline and run URL',await evaluate('document.querySelector("#maxDisplacement").textContent==="—"&&document.querySelector("#sceneTime").disabled&&!new URL(location.href).searchParams.has("run_id")'));
  check('editing input also clears previous gravity diagnostics',await evaluate('document.querySelector("#gravityPanel").hidden&&document.querySelector("#downloadGravity").disabled'));
  await click('startSimulation');await pause(100);await set('tntMass','27');await until(()=>evaluate('document.querySelector("#cancelSimulation").hidden'));
  check('late job completion does not replace edited scene',await evaluate('document.querySelector("#tntMass").value==="27"&&document.querySelector("#maxDisplacement").textContent==="—"'));
  await evaluate('document.querySelector("#historyDetails").open=true');await until(()=>evaluate('document.querySelectorAll("#sceneHistory option").length===3'));await set('sceneHistory',await evaluate('document.querySelectorAll("#sceneHistory option")[1].value'),'change');await click('deleteHistory');await until(()=>evaluate('document.querySelectorAll("#sceneHistory option").length===2'));
  await click('showTrash');await until(()=>evaluate('document.querySelector("#sceneHistory").dataset.historyMode==="deleted"&&document.querySelectorAll("#sceneHistory option").length===2'));await set('sceneHistory',await evaluate('document.querySelectorAll("#sceneHistory option")[1].value'),'change');await until(()=>evaluate('!document.querySelector("#restoreHistory").disabled'));await click('restoreHistory');await until(()=>evaluate('document.querySelector("#sceneHistory").dataset.historyMode==="deleted"&&document.querySelectorAll("#sceneHistory option").length===1'));await click('showTrash');await until(()=>evaluate('document.querySelector("#sceneHistory").dataset.historyMode==="active"&&document.querySelectorAll("#sceneHistory option").length===3'));check('history deletion and restoration preserve original records',true);
  await set('tntMass','');await pause(250);const previous=await evaluate('performance.timeOrigin');await call('Page.reload',{ignoreCache:true});await until(async()=>(await evaluate('performance.timeOrigin'))!==previous);await ready();
  check('raw unfinished parameters survive reload without calculation',await evaluate('document.querySelector("#tntMass").value===""&&document.querySelector("#tntX").value==="7.35"&&document.querySelector("#startSimulation").disabled'));
  const sceneUrl=await evaluate('location.href');await evaluate('document.querySelector("[data-workbench-destination=assessment]").click()');await until(()=>evaluate('location.pathname==="/damage_assessment_demo.html"'));
  await call('Page.navigate',{url:sceneUrl});await ready();check('workbench switching retains scene and unsaved TNT',await evaluate('document.querySelector("#tntMass").value===""&&document.querySelector("#sourceKind").value==="city_street"'));
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:900,deviceScaleFactor:1,mobile:false});await pause(200);await shot('mobile-scene.png');check('mobile layout does not overflow',await evaluate('document.documentElement.scrollWidth<=innerWidth+1'));
  check('no browser exceptions or missing application assets',errors.length===0&&!responses.some(r=>r.status>=400&&!r.url.endsWith('/favicon.ico')));
  check('only two explicitly clicked synthetic jobs were submitted',writes.filter(w=>new URL(w.url).pathname==='/api/cpu-blast/runs').length===2);
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'passed',checks,errors,writes,responses},null,2));console.log('PASS',checks.length,'scene browser checks; all jobs synthetic');await call('Browser.close').catch(()=>{});
 }catch(error){try{await call('Page.captureScreenshot',{format:'png'}).then(s=>fs.writeFileSync(path.join(out,'failure.png'),Buffer.from(s.data,'base64')));fs.writeFileSync(path.join(out,'page.txt'),await evaluate('document.body.innerText'));}catch{}fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(error),checks,errors,writes,responses},null,2));throw error;}
 finally{ws?.close();browser.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
