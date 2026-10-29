/* UI state tests use controlled result responses; no native run or whole export. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/14989/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base=process.argv[2],out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});const checks=[],failures=[],createdSceneIds=[];
 try{for(const name of ['download-recovery','stale-result-clear','busy-result-selector']){
  const context=await browser.newContext(),page=await context.newPage();page.setDefaultTimeout(12000);
  try{
   const a='a'.repeat(32),b='b'.repeat(32),curve={id:'test-monitor',kind:'air_pressure',element_id:42,time_s:[0,2e-6,5e-6,7e-6],pressure_pa:[101325,101425,101375,101325],overpressure_pa:[0,100,50,0],reference_pressure_pa:101325,pressure_kind:'cell_mean_hydrostatic',pressure_description:'controlled UI fixture',peak_overpressure_pa:100,positive_impulse_pa_s:.000375,sample_position_m:[1,2,3],actual_window_s:[0,7e-6]};
   await page.route('**/api/architecture/tnt/scenes/*/exports',route=>route.fulfill({json:{exports:[a,b].map((id,i)=>({job_id:id,status:'exported',revision:i+1,entry:'building-blast-reference.k',download_url:'/api/architecture/tnt/exports/'+id+'/download'}))}}));
   await page.route('**/api/architecture/tnt/exports/*/results',async route=>{
    if(route.request().url().includes('/'+b+'/'))return route.fulfill({status:503,json:{error:'controlled read failure'}});
    await new Promise(r=>setTimeout(r,name==='busy-result-selector'?700:20));return route.fulfill({json:{status:'available',revision:1,curves:[curve]}});
   });
   await page.route('**/api/**',route=>{const r=route.request();if(r.method()==='POST'&&!r.url().endsWith('/scenes/save'))return route.abort();return route.fallback();});
   await page.goto(base+'/structural-pressure');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('TNT设置已载入'));
   await page.locator('#saveScene').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('已保存'));
   createdSceneIds.push(new URL(page.url()).searchParams.get('tnt_scene_id'));
   await page.locator('#viewResults').click();
   if(name==='busy-result-selector'){await page.waitForFunction(()=>document.querySelector('#resultExport').options.length===2);assert.ok(await page.locator('#resultExport').isDisabled());}
   else{
    await page.waitForFunction(()=>!document.querySelector('#resultCsv').hidden);
    if(name==='download-recovery')assert.ok((await page.locator('#existingPackage').getAttribute('href')).includes(a));
    else{await page.locator('#resultExport').selectOption(b);await page.waitForFunction(()=>document.querySelector('#status').classList.contains('error'));assert.ok(await page.locator('#resultCsv').isHidden());assert.equal(await page.locator('#resultChart polyline').count(),0);}
   }
   checks.push(name);
  }catch(e){failures.push({name,error:String(e)});}finally{await context.close();}
 }}finally{await browser.close();}
 fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({checks,failures,created_scene_ids:createdSceneIds,scope:'controlled result UI state only',solver_started:false},null,2));console.log(JSON.stringify({checks,failures}));if(failures.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
