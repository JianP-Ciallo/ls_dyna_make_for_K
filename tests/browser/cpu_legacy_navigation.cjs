/* Actual legacy HTML/global navigation; stub only the old engineering controller.
 * Its native preparation and API calls are forbidden in this lightweight test. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const base=process.argv[2],out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
const pause=ms=>new Promise(r=>setTimeout(r,ms));async function until(fn){const end=Date.now()+20000;while(Date.now()<end){try{if(await fn())return;}catch{}await pause(100);}throw Error('timeout');}
(async()=>{
 const profile=path.join(out,'edge-profile');fs.mkdirSync(profile,{recursive:true});
 const browser=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new','--disable-gpu','--no-first-run','--remote-debugging-port=0','--user-data-dir='+profile,'--use-angle=swiftshader','--enable-unsafe-swiftshader','about:blank'],{windowsHide:true,stdio:'ignore'});let ws;
 try{
  let port;await until(()=>{try{port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);return port>0;}catch{return false;}});
  const target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));let seq=0;const pending=new Map(),requests=[],errors=[];
  const call=(method,params={})=>new Promise((r,j)=>{const id=++seq;pending.set(id,{r,j});ws.send(JSON.stringify({id,method,params}));});
  ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.j(Error(JSON.stringify(m.error))):p.r(m.result);}}else if(m.method==='Fetch.requestPaused')call('Fetch.fulfillRequest',{requestId:m.params.requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'text/javascript'}],body:Buffer.from(`await window.WorkbenchNavigation.register('blast',{context:()=>({identity:'legacy-navigation-fixture',revision:'fixture@1',label:'旧版导航测试',url:location.pathname+location.search}),capture:()=>({fixture:true})});document.body.dataset.legacyFixtureReady='true';`).toString('base64')});else if(m.method==='Network.requestWillBeSent')requests.push(m.params.request);else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails);});
  const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');await call('Fetch.enable',{patterns:[{urlPattern:'*/scene_blast.js',requestStage:'Request'}]});
  await call('Page.navigate',{url:base+'/cpu-blast?legacy=1&source=subway_entrance&run_id='+'b'.repeat(32)});
  await until(()=>evaluate('document.body.dataset.legacyFixtureReady==="true"'));
  assert(await evaluate('document.getElementById("startSimulation")!==null&&document.body.dataset.activeWorkbench==="blast"'));
  await evaluate('document.querySelector(".workbench-global-header [data-workbench-destination=blast]").click()');
  await until(()=>evaluate('document.body.dataset.cpuReady==="true"'));
  assert(await evaluate('document.body.dataset.buildingId==="subway_entrance"&&!new URL(location.href).searchParams.has("legacy")&&new URL(location.href).searchParams.get("run_id")==="b".repeat(32)'));
  assert(!requests.some(r=>r.method!=='GET'||new URL(r.url).pathname.startsWith('/api/')));assert.equal(errors.length,0);
  const result={status:'passed',checks:3,engineeringController:'stubbed; no engineering API or preparation',checksDetail:['legacy static HTML stays available','legacy CPU navigation returns to new default with record context','no engineering API or browser exceptions']};fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));await call('Browser.close').catch(()=>{});
 }finally{ws?.close();browser.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
