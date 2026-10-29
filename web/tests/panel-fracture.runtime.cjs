const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const file=path.resolve(__dirname,'../../lsprepost_mcp/web/static/blast_panel_fracture.js');
(async()=>{
 assert(fs.existsSync(file),'flexible panel network is missing');
 const api=await require('./blast-demo-modules.cjs')(file);
 const bodies=[{id:0,role:'slab',center:[4,-6,.05],size:[4,1,.1],supports:[],fixed:true,capacity:1},{id:1,role:'wall',center:[4,-6,1.5],size:[3,.2,2.8],supports:[0],capacity:.22,normal:[0,-1,0]}];
 const model={bodies},dt=1/180;
 function run(mass){const s=api.createPanelSystem(model,{source:[4,-10,.8],mass},dt),broken=new Uint8Array(2),samples=[];s.activate(1,0);for(let step=1;step<=540;step++){s.step(step*dt,broken);if(step%6===0)samples.push(s.sample());}return {s,samples};}
 const rest=run(0);assert(rest.samples.every(f=>f.maxDeflection===0&&f.cracked===0&&f.detached===0),'zero impact must remain still');
 const weak=run(4),strong=run(600);
 assert(Math.max(...weak.samples.map(f=>f.maxDeflection))>1e-4,'weak pulse must bend panel internally');
 assert(strong.samples.some(f=>f.cracked>0),'strong pulse must create cracks');
 assert(strong.samples.at(-1).detached>0,'strong pulse must detach fragments: '+JSON.stringify({...strong.samples.at(-1),vertices:undefined,damage:undefined,ids:undefined,offsets:undefined,cracks:undefined,detachedFlags:undefined}));
 assert(strong.samples.some(f=>f.cracked>0&&f.detached<strong.samples.at(-1).detached),'fracture must develop progressively');
 assert(strong.samples.every(f=>f.vertices.every(Number.isFinite)&&f.damage.every(Number.isFinite)));
 const again=run(600);assert.deepEqual(again.samples.at(-1).vertices,strong.samples.at(-1).vertices);
 const patch=api.panelPatch(bodies[1]);assert(patch.triangles.length>=8);const area=patch.triangles.reduce((sum,t)=>sum+t.area,0);assert(Math.abs(area-3*2.8)<1e-8,'subdivision must preserve area');
 const restVertices=patch.triangles.flatMap(t=>t.vertices),peak=weak.samples.reduce((a,b)=>a.maxDeflection>b.maxDeflection?a:b),corner=(x,z)=>{for(let i=0;i<restVertices.length;i+=3)if(Math.abs(restVertices[i]-x)<1e-8&&Math.abs(restVertices[i+2]-z)<1e-8)return Array.from(peak.vertices.subarray(i,i+3));throw Error('missing corner');};
 const a=corner(2.5,.1),b=corner(5.5,.1),c=corner(2.5,2.9),u=b.map((x,k)=>x-a[k]),v=c.map((x,k)=>x-a[k]),normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...normal);let nonplanarity=0;
 for(let i=0;i<peak.vertices.length;i+=3)nonplanarity=Math.max(nonplanarity,Math.abs(normal.reduce((sum,x,k)=>sum+x*(peak.vertices[i+k]-a[k]),0))/length);assert(nonplanarity>1e-4,'whole-panel rotation is not internal bending');
 const core=await require('./blast-demo-modules.cjs')(path.join(path.dirname(file),'blast_demo_model.js')),building=core.buildBuilding(),zero=await core.simulate(building,{mass:0,duration:1,response:'fracture'});assert.equal(zero.metrics.maxDisplacement,0);assert(zero.frames.every(f=>api.validFractureFrame(f.fracture,building)));
 const result=await core.simulate(building,{mass:160,duration:1,response:'fracture'});assert.equal(result.method,'progressive-panel-fracture@5');assert(result.frames.every(f=>api.validFractureFrame(f.fracture,building)));assert(result.frames.at(-1).fracture.detached>0);
 const invalid={...result.frames.at(-1).fracture,vertices:result.frames.at(-1).fracture.vertices.slice()};invalid.vertices[0]=NaN;assert(!api.validFractureFrame(invalid,building));
 const final=strong.samples.at(-1);for(let t=0;t<patch.triangles.length;t++){const tri=patch.triangles[t],point=[0,1,2].map(k=>(tri.vertices[k]+tri.vertices[3+k]+tri.vertices[6+k])/3);assert.equal(strong.s.supportAt(1,point).lost,!!final.detachedFlags[t],'local support must follow its own triangle');}
 const center=new Float64Array(6),parentDamage=new Float32Array(2);strong.s.updateBody(1,center,parentDamage);for(let k=0;k<3;k++){let sum=0,count=0;for(let i=k;i<final.vertices.length;i+=3)if(!final.detachedFlags[Math.floor(i/9)]){sum+=final.vertices[i];count++;}assert(Math.abs(center[3+k]-sum/count)<1e-5,'falling fragments must not drag surviving support center');}
 const stacked={bodies:[...bodies,{...bodies[1],id:2,center:[4,-6,4.3],supports:[1]}]},network=api.createPanelSystem(stacked,{source:[4,-10,.8],mass:600},dt);network.activate(1,0);network.activate(2,0);for(let i=1;i<=540;i++)network.step(i*dt,new Uint8Array(3));const layers=network.sample();assert(layers.detachedFlags.subarray(18).some(x=>x===1),'local loss in a partly attached parent must release an upper panel');
 assert(result.frames.every(f=>f.moving>=f.fracture.moving&&result.metrics.maxDisplacement>=f.fracture.maxDisplacement));
 console.log(JSON.stringify({status:'passed',checks:13,weakDeflection:Math.max(...weak.samples.map(f=>f.maxDeflection)),nonplanarity,strong:{cracks:final.cracked,detached:final.detached,triangles:patch.triangles.length},integrated:{panels:result.frames.at(-1).fracture.ids.length,detached:result.frames.at(-1).fracture.detached,wallMs:result.metrics.wallMs}}));
})().catch(e=>{console.error(e);process.exitCode=1;});
