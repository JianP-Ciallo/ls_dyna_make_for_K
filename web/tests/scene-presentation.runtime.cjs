const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),load=require('./blast-demo-modules.cjs');
const root=path.resolve(__dirname,'../../lsprepost_mcp/web/static');
(async()=>{
 const file=path.join(root,'blast_demo_presentation.js');assert(fs.existsSync(file),'scene-specific damage focus and demonstration profiles are missing');
 const ui=await load(file),api=await load(path.join(root,'blast_demo_model.js')),rows=[];
 for(const preset of api.SCENE_PRESETS){const model=api.buildBuilding({building:preset.id}),before=JSON.stringify(model),profile=ui.scenePresentation(model,preset.source);assert(profile.targets.length>0);assert(profile.targets.some(t=>t.id===profile.preferredId));
  for(const target of profile.targets){api.validateConfig({building:preset.id,response:'fracture',mass:600,duration:6,source:target.source});for(const aspect of [2,1,.55]){const camera=ui.cameraForBounds(target.bounds,aspect,model.viewDirection,target.source);assert(camera.position.every(Number.isFinite)&&camera.distance>0);assert(ui.projectedCoverage(target.bounds,camera,aspect).inside,'target is clipped at aspect '+aspect+': '+preset.id);}}
  assert.equal(JSON.stringify(model),before,'presentation must not mutate geometry, capacity or supports');const fallback=ui.chooseFocusTarget(profile,null,'auto');assert.equal(fallback.id,profile.preferredId);rows.push({id:preset.id,targets:profile.targets.length,defaultSource:fallback.source});
 }
 const city=api.buildBuilding({building:'city_street'}),cp=ui.scenePresentation(city,api.getBuildingPreset('city_street').source);assert.deepEqual(ui.chooseFocusTarget(cp,null).source,[-23,7,.8]);assert(cp.targets.every(t=>!t.id.startsWith('car_')&&!t.id.startsWith('signal_')));
 const target=cp.targets.find(t=>t.id==='city_subway'),damage=new Float32Array(city.bodies.length);for(const b of city.bodies.filter(b=>b.instanceId==='city_subway'))damage[b.id]=1;assert.equal(ui.chooseFocusTarget(cp,{damage},'auto').id,target.id,'cached response should focus the object actually damaged');assert.equal(ui.chooseFocusTarget(cp,{damage},'supermarket').id,'supermarket','explicit target selection must win over automatic focus');
 const above=ui.cameraForBounds(target.bounds,.55,[0,0,1],[15,8,.8]);assert(ui.projectedCoverage(target.bounds,above,.55).inside,'straight-down view must remain a valid camera basis');
 assert(!fs.readFileSync(path.join(root,'blast_demo.js'),'utf8').includes('href="./blast_demo.html?building=${p.id}"'),'primary scene links must not force legacy whole-component response');
 console.log(JSON.stringify({status:'passed',checks:7,scenes:rows}));
})().catch(e=>{console.error(e);process.exitCode=1;});
