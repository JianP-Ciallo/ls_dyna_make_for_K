/* Outdoor-only validation and real camera interaction. All POST requests are blocked. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {chromium}=require('C:/Users/14989/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base=process.argv[2],out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist']}),checks=[],failures=[],errors=[],requests=[];
try{for(const name of ['outdoor-policy','camera-interaction','historical-indoor-record','indoor-draft-preserved']){
 const context=await browser.newContext({viewport:{width:1600,height:1000}}),page=await context.newPage();page.setDefaultTimeout(12000);page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',r=>{const q=r.request();requests.push({path:new URL(q.url()).pathname,method:q.method()});return q.method()==='GET'&&!/cpu|solve|\/runs/.test(q.url())?r.continue():r.abort();});
 try{
  if(name==='historical-indoor-record'){
   const schema=await(await context.request.get(base+'/api/architecture/tnt/schema')).json(),c=structuredClone(schema.defaults),[rid,room]=Object.entries(schema.rooms).find(([,r])=>r.eligible);
   c.scenario='indoor';c.location.room_id=rid;c.location.xy_m=[(room.bounds_m[0]+room.bounds_m[3])/2,(room.bounds_m[1]+room.bounds_m[4])/2];
   await page.route('**/api/architecture/tnt/scenes/'+('d'.repeat(32)),r=>r.fulfill({json:{scene_id:'d'.repeat(32),revision:1,config:c}}));
   await page.route('**/api/architecture/tnt/scenes/'+('d'.repeat(32))+'/exports',r=>r.fulfill({json:{exports:[]}}));
  }
  await page.goto(base+'/structural-pressure'+(name==='historical-indoor-record'?'?tnt_scene_id='+('d'.repeat(32)):''));await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('TNT设置已载入'));
  if(name==='outdoor-policy'){
   assert.equal(await page.locator('#scenario option[value="indoor"]').count(),0,'indoor placement must not be offered');
   const b=await page.evaluate(async()=>{const s=await(await fetch('/api/architecture/tnt/schema')).json();return s.geometry.building_bounds_m;});
   await page.locator('#tntX').fill(String((b[0]+b[3])/2));await page.locator('#tntY').fill(String((b[1]+b[4])/2));
   assert.ok(await page.locator('#saveScene').isDisabled(),'invalid interior coordinates must block save');assert.ok(await page.locator('#previewScene').isDisabled());
   assert.match(await page.locator('#placementStatus').textContent(),/建筑外|建筑内部/);
   await page.locator('#tntX').fill(String(b[0]-.025));assert.ok(await page.locator('#saveScene').isDisabled(),'center outside with radius crossing wall must be rejected');
   await page.locator('#tntX').fill('-3.1');await page.locator('#tntY').fill('6.3');assert.ok(await page.locator('#saveScene').isEnabled());
   await page.screenshot({path:path.join(out,'outdoor-constraint.png'),fullPage:true});
  }else if(name==='camera-interaction'){
   const canvas=page.locator('#sceneView canvas');await canvas.waitFor({timeout:4000});await page.waitForFunction(()=>document.querySelector('#sceneView').dataset.viewReady==='true');await canvas.scrollIntoViewIfNeeded();
   const state=()=>page.evaluate(()=>{WorkbenchNavigation.checkpoint();return WorkbenchNavigation.read('pressure','tnt:new','draft').snapshot.view.camera;});
   const initial=await state(),box=await canvas.boundingBox();assert.ok(initial?.position,'camera must be persisted');
   const before=crypto.createHash('sha256').update(await canvas.screenshot()).digest('hex');
   await page.mouse.move(box.x+box.width*.55,box.y+box.height*.4);await page.mouse.down();await page.mouse.move(box.x+box.width*.7,box.y+box.height*.52,{steps:8});await page.mouse.up();
   const rotated=await state();assert.notDeepEqual(rotated.position,initial.position,'drag must rotate the view');
   const after=crypto.createHash('sha256').update(await canvas.screenshot()).digest('hex');assert.notEqual(after,before,'drag must change visible rendering');
   await page.mouse.move(box.x+box.width*.5,box.y+box.height*.4);await page.mouse.wheel(0,-300);await page.waitForFunction(z=>{WorkbenchNavigation.checkpoint();return WorkbenchNavigation.read('pressure','tnt:new','draft').snapshot.view.camera.zoom!==z;},rotated.zoom);
   const zoomed=await state();assert.notEqual(zoomed.zoom,rotated.zoom,'wheel must zoom');
   await page.mouse.down({button:'right'});await page.mouse.move(box.x+box.width*.6,box.y+box.height*.45,{steps:5});await page.mouse.up({button:'right'});const panned=await state();assert.notDeepEqual(panned.target,zoomed.target,'right drag must pan');
   await page.locator('#tntX').fill('-3.2');assert.deepEqual(await state(),panned,'editing TNT must not reset camera');
   await page.screenshot({path:path.join(out,'interactive-camera.png'),fullPage:true});
   await page.reload();await page.waitForFunction(()=>document.querySelector('#sceneView')?.dataset.viewReady==='true');const restored=await state();
   for(const key of ['position','target'])for(let i=0;i<3;i++)assert.ok(Math.abs(restored[key][i]-panned[key][i])<1e-8,'reload must restore camera pose');
   for(const key of ['zoom','frame'])assert.ok(Math.abs(restored[key]-panned[key])<1e-8,'reload must restore camera scale');
   await page.locator('#viewPlan').click();const top=await state();await page.mouse.move(box.x+box.width*.5,box.y+box.height*.4);await page.mouse.down();await page.mouse.move(box.x+box.width*.65,box.y+box.height*.5,{steps:5});await page.mouse.up();assert.notDeepEqual((await state()).position,top.position,'top preset must remain rotatable');
   await page.locator('#view3d').click();await page.locator('#fitView').click();await page.screenshot({path:path.join(out,'interactive-default.png'),fullPage:true});
  }else if(name==='historical-indoor-record'){
   assert.ok(await page.locator('#saveScene').isDisabled());assert.ok(await page.locator('#previewScene').isDisabled());assert.ok(await page.locator('#sceneName').isDisabled());assert.match(await page.locator('#placementStatus').textContent(),/历史室内.*只读/);
   await page.locator('#newScene').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('新建TNT'));assert.ok(await page.locator('#saveScene').isEnabled());
  }else{
   const before=await page.evaluate(()=>{WorkbenchNavigation.checkpoint();const key='lsprepost.workbench.session@1',data=JSON.parse(sessionStorage.getItem(key)),r=data.records.find(r=>r.identity==='tnt:new');r.snapshot.fields.find(f=>f.key==='id:scenario').value='indoor';const raw=JSON.stringify(data);sessionStorage.setItem(key,raw);return raw;});
   // Avoid a beforeunload checkpoint replacing the seeded historical browser state.
   await page.addInitScript(raw=>sessionStorage.setItem('lsprepost.workbench.session@1',raw),before);await page.reload();await page.waitForFunction(()=>!document.querySelector('.workbench-global-context button').hidden);
   assert.equal(await page.evaluate(()=>sessionStorage.getItem('lsprepost.workbench.session@1')),before,'old indoor draft must remain byte-identical');
   await page.locator('#newScene').click();assert.match(await page.locator('#status').textContent(),/草稿.*保留|下载.*草稿/,'blocked new action must explain how to retain the old draft');
   const download=page.waitForEvent('download');await page.getByRole('button',{name:'下载保留草稿'}).click();const backup=await download;await backup.saveAs(path.join(out,'historical-draft-backup.json'));
   const kept=JSON.parse(fs.readFileSync(path.join(out,'historical-draft-backup.json'),'utf8'));assert.ok(kept.snapshot.fields.some(f=>f.key==='id:scenario'&&f.value==='indoor'));
   await page.locator('#newScene').click();assert.ok(await page.locator('#saveScene').isEnabled());
  }checks.push(name);
 }catch(e){failures.push({name,error:String(e)});}finally{await context.close();}
}}finally{await browser.close();}
fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({checks,failures,errors,requests,solver_started:false},null,2));console.log(JSON.stringify({checks,failures,errors}));if(failures.length||errors.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
