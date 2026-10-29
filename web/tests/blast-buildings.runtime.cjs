const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const api=await require('./blast-demo-modules.cjs')(path.resolve(__dirname,'../../lsprepost_mcp/web/static/blast_demo_model.js'));
 assert.equal(api.BUILDING_PRESETS?.length,5,'four independent buildings are not implemented');
 const original=api.buildBuilding();assert.equal(original.bodies.length,1465);assert.equal(original.storeys,3);
 assert.throws(()=>api.buildBuilding({building:'unknown'}),/建筑/);
 assert.throws(()=>api.validateConfig({building:'unknown'}),/建筑/);
 const measurements=[];
 for(const p of api.BUILDING_PRESETS){
  const model=api.buildBuilding({building:p.id});assert.equal(model.buildingId,p.id);assert.equal(model.storeys,p.storeys);
  assert.equal(model.buildingCount,1,'buildings must not share one scene');
  assert(model.bodies.every((b,i)=>b.id===i&&b.center.every(Number.isFinite)&&b.size.every(x=>x>0)&&b.supports.every(s=>Number.isInteger(s)&&s>=0&&s<model.bodies.length)));
  for(const slab of model.bodies.filter(b=>b.role==='slab'&&!b.fixed)){
   const distance=b=>(b.center[0]-slab.center[0])**2+(b.center[1]-slab.center[1])**2;
   const excluded=model.bodies.filter(b=>b.role==='column'&&b.floor===slab.floor-1&&b.segment===2&&!slab.supports.includes(b.id));
   assert(Math.max(...slab.supports.map(id=>distance(model.bodies[id])))<=Math.min(...excluded.map(distance))+1e-9,p.id+' slab supports must be nearest after scaling');
  }
  assert.throws(()=>api.validateConfig({building:p.id,source:[0,0,1]}),/建筑外/);
  assert.throws(()=>api.validateConfig({building:p.id,source:[0,.6*p.scale[1],p.storeys*3.1+1.3]}),/建筑外/);
  const config=api.validateConfig({building:p.id,mass:600,source:p.source,duration:1.5});
  const rest=await api.simulate(model,{...config,mass:0,duration:1});assert.equal(rest.metrics.broken,0);assert.equal(rest.metrics.maxDisplacement,0);
  const strong=await api.simulate(model,config);assert(strong.metrics.broken>0);assert.equal(strong.model.buildingId,p.id);assert.equal(strong.config.building,p.id);
  const final=strong.frames.at(-1);assert(final.poses.every(Number.isFinite));assert(final.damage.every(d=>d>=0&&d<=1));
  for(let i=0;i<model.bodies.length;i++)assert(Math.abs(Math.hypot(...final.poses.subarray(i*7+3,i*7+7))-1)<2e-5);
  assert.equal(final.time,1.5);assert(final.maxDisplacement>0);
  measurements.push({id:p.id,storeys:model.storeys,bodies:model.bodies.length,broken:strong.metrics.broken,wallMs:strong.metrics.wallMs});
 }
 assert.equal(new Set(measurements.map(x=>x.bodies)).size,5,'new buildings must have distinct geometry');
 const office=api.buildBuilding({building:'office-4'});assert(!office.bodies.some(b=>b.role==='balcony'));
 const originalRepeat=api.buildBuilding();assert.deepEqual(originalRepeat,original,'building another type mutated the original');
 await assert.rejects(()=>api.simulate(office,{building:'residence-2',mass:600,source:[4,-10,.8],duration:1}),/建筑/);
 const tower=api.buildBuilding({building:'tower-8'}),base=api.BUILDING_PRESETS.find(p=>p.id==='tower-8');
 const near=await api.simulate(tower,{building:base.id,mass:600,source:base.source,duration:1});
 const far=await api.simulate(tower,{building:base.id,mass:600,source:[4,-40,.8],duration:1});assert(near.metrics.broken>far.metrics.broken);
 console.log(JSON.stringify({status:'passed',checks:9,buildings:measurements}));
})().catch(e=>{console.error(e);process.exitCode=1;});
