/* Actual local Chrome/CDP acceptance. Only the two bounded reference solves run. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const base=process.argv[2]||'http://127.0.0.1:8897',out=path.resolve(process.argv[3]||'artifacts/cpu-response-browser');
fs.mkdirSync(out,{recursive:true});
const checks=[],errors=[];const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function check(name,value){assert.ok(value,name);checks.push(name);}
async function until(fn,timeout=15000){const end=Date.now()+timeout;let value;while(Date.now()<end){value=await fn();if(value)return value;await sleep(100);}throw Error('timeout waiting for '+fn);}
(async()=>{
  const chrome=process.env.CHROME_PATH||['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
  assert.ok(chrome,'Chrome/Edge must be installed');
  const profile=path.join(out,'chrome-profile');fs.mkdirSync(profile,{recursive:true});
  const browser=spawn(chrome,['--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist','about:blank'],{windowsHide:true,stdio:'ignore'});
  let ws;try{
    const port=await until(async()=>{try{return Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);}catch{return null;}});
    const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();const target=targets.find(t=>t.type==='page');
    ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
    let seq=0;const pending=new Map();
    ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text+': '+(m.params.exceptionDetails.exception?.description||''));});
    function call(method,params={}){return new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});}
    async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
    async function screenshot(name){const r=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,name),Buffer.from(r.data,'base64'));}
    await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1500,height:1080,deviceScaleFactor:1,mobile:false});
    await call('Page.navigate',{url:base+'/fixed-building-pressure/response'});
    try{await until(()=>evaluate('document.querySelector("#startRun") && !document.querySelector("#startRun").disabled'));}
    catch(error){fs.writeFileSync(path.join(out,'page-diagnostic.json'),JSON.stringify(await evaluate('({text:document.body.innerText,canvas:!!document.querySelector("canvas"),resources:performance.getEntriesByType("resource").map(x=>({name:x.name,status:x.responseStatus}))})'),null,2));await screenshot('failure.png');throw error;}
    check('empty state shows no invented numerical result',await evaluate('!document.querySelector("#emptyState").hidden && document.querySelector("#peakDisplacement").textContent.includes("—")'));
    await screenshot('01-empty.png');
    await evaluate('document.querySelector("#startRun").click()');
    await until(()=>evaluate('document.querySelector("#runState").textContent==="计算完成" && !document.querySelector("#downloadCsv").hidden'),45000);
    check('real column solve produces displacement and fiber stress',await evaluate('parseFloat(document.querySelector("#peakDisplacement").textContent)>0 && parseFloat(document.querySelector("#peakSteel").textContent)>0'));
    const colRun=await evaluate('new URL(location.href).searchParams.get("run_id")');
    await screenshot('02-column-displacement.png');
    await evaluate('document.querySelector("#field").value="steel"; document.querySelector("#field").dispatchEvent(new Event("change"))');
    check('steel mode has signed MPa legend and original sample metadata',await evaluate('document.querySelector("#legendLabel").textContent.includes("MPa") && document.querySelector("#sampleDetails").textContent.includes("bar-")'));
    await screenshot('03-column-steel.png');
    await evaluate('document.querySelector("#timeline").value=0; document.querySelector("#timeline").dispatchEvent(new Event("input"))');
    check('timeline moves actual time cursor to zero',await evaluate('document.querySelector("#timeValue").textContent==="0.00 ms"'));
    await evaluate('document.querySelector("#benchmark").value="rc-panel-v1";document.querySelector("#benchmark").dispatchEvent(new Event("change"))');
    check('switch source clears previous result',await evaluate('document.querySelector("#emptyState").hidden===false && document.querySelector("#peakSteel").textContent==="—"'));
    await evaluate('document.querySelector("#startRun").click()');
    await until(()=>evaluate('document.querySelector("#runState").textContent==="计算完成" && !document.querySelector("#downloadCsv").hidden'),45000);
    check('real panel solve produces nonzero plate deflection and layer stress',await evaluate('parseFloat(document.querySelector("#peakDisplacement").textContent)>0 && document.querySelector("#sampleDetails").textContent.includes("smeared_rebar_layer")'));
    const panelRun=await evaluate('new URL(location.href).searchParams.get("run_id")');
    await evaluate('document.querySelector("#field").value="displacement";document.querySelector("#field").dispatchEvent(new Event("change"))');
    await screenshot('04-panel-displacement.png');
    await evaluate('document.querySelector("#field").value="steel";document.querySelector("#field").dispatchEvent(new Event("change"));document.querySelector("#steelFilter").value="bottom-Y";document.querySelector("#steelFilter").dispatchEvent(new Event("change"))');
    check('panel supports upper/lower and orthogonal rebar layer selection',await evaluate('document.querySelector("#steelFilter").options.length===4 && document.querySelector("#fieldNote").textContent.includes("原始积分点")'));
    await screenshot('05-panel-steel.png');
    const csv=await fetch(base+'/api/architecture/pressure/cpu-response/runs/'+panelRun+'/artifacts/curves.csv');
    check('CSV download keeps correct MIME and real units',csv.status===200&&csv.headers.get('content-type').includes('text/csv')&&(await csv.text()).includes('steel_max_pa'));
    await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
    check('mobile layout has no horizontal overflow',await evaluate('document.documentElement.scrollWidth<=innerWidth'));
    await screenshot('06-mobile.png');
    await call('Emulation.setDeviceMetricsOverride',{width:1500,height:1080,deviceScaleFactor:1,mobile:false});
    await call('Page.navigate',{url:base+'/fixed-building-pressure/response?run_id='+colRun});
    await until(()=>evaluate('document.querySelector("#runState").textContent==="计算完成" && !document.querySelector("#downloadCsv").hidden'));
    check('saved run reloads without another computation',await evaluate('new URL(location.href).searchParams.get("run_id")==='+JSON.stringify(colRun)));
    await until(()=>evaluate('document.querySelector("#history").options.length>1'));
    await evaluate('document.querySelector("#history").value='+JSON.stringify(colRun)+';document.querySelector("#history").dispatchEvent(new Event("change"))');
    await until(()=>evaluate('!document.querySelector("#downloadCsv").hidden'));
    check('history selection synchronizes the reload URL',await evaluate('new URL(location.href).searchParams.get("run_id")==='+JSON.stringify(colRun)));
    await call('Page.navigate',{url:base+'/structural-pressure'});
    await until(()=>evaluate('document.querySelector("#sceneName") && !document.querySelector("#saveScene").disabled'));
    await evaluate('document.querySelector("#openCpuResponse").click()');
    await until(()=>evaluate('location.pathname==="/fixed-building-pressure/response"'));
    check('clean pressure form can open CPU page directly',await evaluate('location.pathname==="/fixed-building-pressure/response"'));
    await call('Page.navigate',{url:base+'/structural-pressure'});
    await until(()=>evaluate('document.querySelector("#sceneName") && !document.querySelector("#saveScene").disabled'));
    await evaluate('document.querySelector("#sceneName").value="CPU navigation draft";document.querySelector("#sceneName").dispatchEvent(new Event("input"));document.querySelector("#openCpuResponse").click()');
    check('old K page preserves unsaved input before CPU navigation',await evaluate('document.querySelector("#cpuLeaveDialog").open && document.querySelector("#sceneName").value==="CPU navigation draft"'));
    check('no JavaScript runtime exceptions',errors.length===0);
    fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'passed',checks,errors,column_run_id:colRun,panel_run_id:panelRun,scope:'two_real_small_cases_and_saved_replay_no_building_or_LSDYNA'},null,2));
    console.log(JSON.stringify({passed:checks.length,column_run_id:colRun,panel_run_id:panelRun}));
    await call('Browser.close').catch(()=>{});
  }finally{if(ws)ws.close();browser.kill();}
})().catch(error=>{fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(error),checks,errors},null,2));console.error(error);process.exitCode=1;});
