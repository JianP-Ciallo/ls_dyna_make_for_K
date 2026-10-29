const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const file=path.resolve(__dirname,'../../lsprepost_mcp/web/static/blast_demo_model.js');
(async()=>{
 const api=fs.existsSync(file)?await require('./blast-demo-modules.cjs')(file):{};
 const model=api.buildBuilding?.();
 assert.ok(model?.bodies?.length,'three-storey solid geometry is not implemented');
 assert.equal(model.storeys,3);assert(model.bodies.length>300&&model.bodies.length<2500);
 assert(model.bodies.some(b=>b.role==='balcony')&&model.bodies.some(b=>b.role==='column')&&model.bodies.some(b=>b.role==='stairs'));
 assert(model.bodies.every(b=>b.size.every(x=>x>0)&&b.center.every(Number.isFinite)));
 const contains=(b,p)=>p.every((x,i)=>Math.abs(x-b.center[i])<b.size[i]/2-1e-6);
 assert(!model.bodies.some(b=>contains(b,[0,-6,.9])),'central entrance was filled');
 assert.throws(()=>api.validateConfig({mass:100,source:[0,0,1],duration:6}),/建筑外/);
 assert.throws(()=>api.validateConfig({mass:100,source:[0,.6,10.6],duration:6}),/建筑外/,'roof enclosure must exclude an internal source');
 assert.deepEqual(api.validateConfig({source:[0,.6,11]}).source,[0,.6,11]);
 const rest=await api.simulate(model,{mass:0,source:[4,-10,.8],duration:2});
 assert.equal(rest.metrics.broken,0);assert.equal(rest.metrics.maxDisplacement,0);
 const weak=await api.simulate(model,{mass:5,source:[4,-10,.8],duration:3});
 const strong=await api.simulate(model,{mass:160,source:[4,-10,.8],duration:3});
 assert(strong.metrics.broken>weak.metrics.broken,'intensity does not affect failure');
 assert(strong.metrics.maxDisplacement>weak.metrics.maxDisplacement);
 const far=await api.simulate(model,{mass:160,source:[4,-35,.8],duration:3});
 assert(strong.metrics.broken>far.metrics.broken,'distance does not attenuate impact');
 const repeat=await api.simulate(model,{mass:160,source:[4,-10,.8],duration:3});
 assert.deepEqual(strong.frames.at(-1).poses,repeat.frames.at(-1).poses,'same inputs changed computed motion');
 for(const frame of strong.frames){
  assert(frame.poses.every(Number.isFinite));
  for(let i=0;i<model.bodies.length;i++){
   const q=Array.from(frame.poses.slice(i*7+3,i*7+7));assert(Math.abs(Math.hypot(...q)-1)<2e-5);
  }
 }
 assert(strong.events.length>0&&strong.frames[0].time===0&&strong.frames.at(-1).time===3);
 assert(strong.metrics.workerSteps>0);assert.equal(strong.method,'simplified-breakable-components@2');
 console.log(JSON.stringify({status:'passed',checks:8,bodies:model.bodies.length,weak:weak.metrics,strong:strong.metrics,far:far.metrics}));
})().catch(e=>{console.error(e);process.exitCode=1;});
