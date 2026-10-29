const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../lsprepost_mcp/web/static');
function dataModule(file){let code=fs.readFileSync(path.join(root,file),'utf8');code=code.replace(/from ['"]\.\/([^'"]+\.js)['"]/g,(_m,name)=>'from '+JSON.stringify(dataModule(name)));return 'data:text/javascript;base64,'+Buffer.from(code).toString('base64');}
(async()=>{
 const api=await import(dataModule('blast_demo_model.js'));
 const ids=['commercial_supermarket','residential_community','subway_entrance','city_street'];
 assert(ids.every(id=>api.SCENE_PRESETS?.some(p=>p.id===id)),'the four original designed scenes are missing');
 const contains=(b,p)=>{if(b.rotation)return false;return p.every((v,i)=>Math.abs(v-b.center[i])<b.size[i]/2-1e-6);};
 const summaries=[];
 for(const id of ids){
  const model=api.buildBuilding({building:id}),preset=api.getBuildingPreset(id);
  assert.equal(model.buildingId,id);assert(model.designReferences.length>0);assert(model.bodies.length>80&&model.bodies.length<10000);
  const invalid=model.bodies.find((b,i)=>b.id!==i||b.supports.some(j=>j<0||j>=model.bodies.length||j===i)||b.size.some(v=>v<=0)||!Number.isFinite(b.capacity));assert(!invalid,id+' invalid body: '+JSON.stringify(invalid));
  assert(model.bodies.every(b=>!b.normal||Math.abs(Math.hypot(...b.normal)-1)<1e-10),id+' exterior normals must be unit vectors');
  const rest=await api.simulate(model,{building:id,source:preset.source,mass:0,duration:1});assert.equal(rest.metrics.broken,0);assert.equal(rest.metrics.maxDisplacement,0);
  const result=await api.simulate(model,{building:id,source:preset.source,mass:600,duration:2});assert(result.metrics.broken>0,id+' must compute a blast response');
  const end=result.frames.at(-1);assert(end.poses.every(Number.isFinite));for(let i=0;i<model.bodies.length;i++)assert(Math.abs(Math.hypot(...end.poses.subarray(i*7+3,i*7+7))-1)<2e-5);
  assert.equal(result.config.building,id);summaries.push({id,bodies:model.bodies.length,broken:result.metrics.broken,wallMs:result.metrics.wallMs});
 }
 const shop=api.buildBuilding({building:ids[0]});assert.equal(shop.width,22);assert.equal(shop.depth,18);assert(shop.bodies.some(b=>b.role==='canopy')&&shop.bodies.some(b=>b.role==='sign')&&shop.bodies.some(b=>b.component==='roof_equipment'));
 assert(!shop.bodies.some(b=>contains(b,[0,-9,1.2])),'supermarket entrance was filled');
 for(const roof of shop.bodies.filter(b=>b.role==='roof'&&b.component!=='roof_equipment'))assert(roof.supports.length>0&&roof.supports.every(i=>{const c=shop.bodies[i];return c.role==='steel'&&c.center[2]+c.size[2]/2>7.5;}),'shop roof must depend on column tops');
 const community=api.buildBuilding({building:ids[1]});assert.equal(community.instances.length,3);assert.equal(community.instances[1].center[0]-community.instances[0].center[0],12);assert(community.bodies.some(b=>b.role==='balcony'));
 const metro=api.buildBuilding({building:ids[2]});assert.equal(metro.topology.fixedStaircases,1);assert.equal(metro.topology.escalators,2);assert.equal(metro.topology.route,'A/B/C -> 8 -> 9 -> 10');assert(metro.bodies.some(b=>b.transparent));assert(metro.bodies.some(b=>b.rotation));assert(!metro.bodies.some(b=>contains(b,metro.topology.passageProbe)),'passage cavity was filled');
 for(const panel of metro.bodies.filter(b=>b.component==='pavilion_roof'))assert(panel.size[0]*Math.cos(panel.roofSlope)>=panel.roofInterval[1]-panel.roofInterval[0],'roof panels must cover their full horizontal interval');
 const metroRest=await api.simulate(metro,{building:ids[2],source:api.getBuildingPreset(ids[2]).source,mass:0,duration:1});
 for(const b of metro.bodies.filter(b=>b.rotation))assert.deepEqual(Array.from(metroRest.frames[0].poses.subarray(b.id*7+3,b.id*7+7)).map(v=>Number(v.toFixed(6))),b.rotation.map(v=>Number(v.toFixed(6))));
 assert(metro.bodies.filter(b=>b.underground).every(b=>b.fixed),'underground reference geometry must be explicitly fixed');assert.equal(metro.contactFloorZ,-2.8);
 const city=api.buildBuilding({building:ids[3]});assert.equal(city.instances.filter(i=>i.kind==='residential_tower').length,2);assert.equal(city.instances.filter(i=>i.kind==='vehicle').length,4);assert.equal(city.instances.filter(i=>i.kind==='traffic_light').length,4);assert.equal(city.layout.roadWidth,16);assert.equal(city.width,72);assert.equal(city.depth,72);
 assert(city.instances.some(i=>i.kind==='supermarket'&&i.origin[0]===-34&&i.origin[1]===12));
 assert(city.bodies.some(b=>b.component==='podium'));
 for(const roof of city.bodies.filter(b=>b.role==='roof'&&b.instanceId==='city_subway'))assert(roof.supports.length&&roof.supports.every(i=>city.bodies[i].role==='wall'),'city entrance roof must depend on walls');
 for(const head of city.bodies.filter(b=>b.role==='equipment'&&b.instanceId.startsWith('signal_')))assert(head.supports.some(i=>city.bodies[i].role==='steel'),'signal head must depend on pole or arm');
 for(const signal of city.instances.filter(i=>i.kind==='traffic_light')){const head=city.bodies.find(b=>b.instanceId===signal.id&&b.role==='equipment'),angle=signal.rotationDegrees*Math.PI/180;assert(Math.abs(head.center[0]-signal.origin[0]-Math.cos(angle)*3.3)<1e-8&&Math.abs(head.center[1]-signal.origin[1]-Math.sin(angle)*3.3)<1e-8,'signal arms must retain original quadrant rotations');}
 assert(!community.bodies.some(b=>contains(b,[0,-5.5,.6])),'community podium blocks entry');
 assert(!community.bodies.some(b=>contains(b,[0,-6,.6])),'community podium front wall blocks entry');
 assert(!city.bodies.some(b=>contains(b,[-31.5,-26.5,.6])),'city podium blocks entry');
 assert(!city.bodies.some(b=>contains(b,[-31.5,-27,.6])),'city podium front wall blocks entry');
 assert.throws(()=>api.validateConfig({building:ids[0],source:[0,0,1]}),/建筑外|场景外|内部/);
 assert.throws(()=>api.validateConfig({building:ids[1],source:[-12,0,1]}),/建筑外|场景外|内部/);
 assert.deepEqual(api.validateConfig({building:ids[1],source:[-6,0,3]}).source,[-6,0,3],'tower gap above podium must remain open');
 assert.deepEqual(api.validateConfig({building:ids[3],source:[0,0,.8]}).source,[0,0,.8]);
 console.log(JSON.stringify({status:'passed',checks:12,scenes:summaries}));
})().catch(e=>{console.error(e);process.exitCode=1;});
