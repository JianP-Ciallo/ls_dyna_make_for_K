/* Scoped demonstration mechanics: no native solver or heavy model generator. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../lsprepost_mcp/web/static'),load=require('./blast-demo-modules.cjs');
(async()=>{
 const panel=await load(path.join(root,'blast_panel_fracture.js')),api=await load(path.join(root,'blast_demo_model.js')),debris=await load(path.join(root,'blast_debris_contact.js')),dt=1/180;
 const body={id:0,role:'slab',center:[0,0,8],size:[2,2,.16],supports:[],fixed:false,capacity:1};
 const free=panel.createPanelSystem({bodies:[body]},{source:[0,-30,.8],mass:1},dt);free.activate(0,1,true,[1,0,0]);
 let f=free.sample();assert.equal(f.brokenBonds,0,'support loss must not pre-break internal bonds');assert(f.detachedFlags.every(Boolean),'released anchors must leave the island unsupported');
 for(let i=1;i<=90;i++)free.step(1+i*dt,new Uint8Array(1));f=free.sample();assert.equal(f.brokenBonds,0,'uniform free fall must not create internal cracks');assert(f.vertices.every(Number.isFinite));
 const meanZ=f.vertices.filter((_,i)=>i%3===2).reduce((a,b)=>a+b,0)/(f.vertices.length/3);assert(Math.abs(meanZ-(8-9.80665*.5**2/2))<.025,'free-falling heavy fragments must follow the gravity trajectory, without excessive artificial air drag');
 const moved=panel.createPanelSystem({bodies:[body]},{source:[0,-30,.8],mass:1},dt),angle=Math.PI/2;
 moved.activate(0,1,true,[2,0,0],{center:[3,4,8],rotation:[0,0,Math.sin(angle/2),Math.cos(angle/2)],angularVelocity:[0,0,1]});
 const patch=panel.panelPatch(body),mf=moved.sample();for(let i=0;i<mf.vertices.length;i+=3){const old=patch.triangles.flatMap(t=>t.vertices),dx=old[i],dy=old[i+1];assert(Math.abs(mf.vertices[i]-(3-dy))<1e-5&&Math.abs(mf.vertices[i+1]-(4+dx))<1e-5,'activation must inherit the current pose');}
 const before=mf.vertices.slice();moved.step(1+dt,new Uint8Array(1));const after=moved.sample().vertices;assert(after[0]>before[0],'activation must inherit linear and angular velocity');
 const contact=await load(path.join(root,'blast_demo_contact.js'));
 const slab={id:0,role:'slab',center:[0,0,3],size:[4,4,.2],supports:[],fixed:true},surface=contact.createContactSystem({bodies:[slab]});surface.update(new Uint8Array(1));
 const p=[0,0,2.5],previous=[0,0,4],v=[3,0,-8],hit=surface.resolve(p,previous,v,.1,-1);assert(hit&&p[2]>=3.2-1e-9,'retained upper floor must intercept a swept falling fragment');assert(v[2]>=0&&Math.hypot(...v)<Math.hypot(3,0,-8),'contact must dissipate energy');
 const brokenSurface=contact.createContactSystem({bodies:[{...slab,fixed:false}]});brokenSurface.update(new Uint8Array([1]));const through=[0,0,2.5];brokenSurface.resolve(through,previous,[0,0,-8],.1,-1);assert.equal(through[2],2.5,'failed floors must stop acting as invisible catch planes');
 let alive=true;const partial=contact.createContactSystem({bodies:[{...slab,fixed:false}]}),patchSurface={owns:()=>true,contactTriangles:()=>[{points:[[-2,-2,3.1],[2,-2,3.1],[0,2,3.1]],alive:()=>alive}]};partial.update(new Uint8Array(1),null,patchSurface);alive=false;const hole=[0,0,2.5];partial.resolve(hole,previous,[0,0,-8],.1,-1);assert.equal(hole[2],2.5,'a locally detached triangle must stop catching fragments before the next spatial refresh');
 const pit=contact.createContactSystem({bodies:[],groundCutout:[-2,-2,2,2],contactFloorZ:-2.8});pit.update(new Uint8Array(0));const underground=[2.2,0,-1];pit.resolve(underground,[1.9,0,-1],[4,0,0],.05,-1);assert(underground[0]<=1.95+1e-8&&underground[2]<-.9,'pit wall must block sideways escape without teleporting to street level');
 const post=[1.96,0,-1];pit.resolve(post,[1.94,0,-1],[1,0,0],1.4,-1,[.05,.05]);assert(Math.abs(post[0]-1.95)<1e-8,'a tall thin post must use horizontal extent at excavation walls');
 const summaries=[];
 for(const preset of api.SCENE_PRESETS){
  const model=api.buildBuilding({building:preset.id}),rails=model.bodies.filter(b=>b.role==='rail'&&!b.fixed&&panel.isPanel(b));
  assert(rails.every(b=>b.supports.length&&b.supports.some(i=>['balcony','slab','roof'].includes(model.bodies[i].role))),'solid parapets need a local floor or balcony support: '+preset.id);
  for(const b of rails.filter(b=>!b.isRoof&&b.center[1]<0&&model.bodies.some(a=>a.role==='balcony'&&(a.instanceId||'')===(b.instanceId||'')&&Math.abs(a.center[2]-b.center[2])<1)))assert(b.supports.some(i=>model.bodies[i].role==='balcony'),'balcony parapet attached remotely: '+preset.id);
  const podium=model.bodies.filter(b=>b.component==='podium'&&b.role==='wall');assert(podium.every(b=>!b.fixed),'visible podium walls must participate in damage');
  const tall=model.bodies.filter(b=>b.role==='wall'&&!b.fixed&&b.center[2]>4&&b.size[2]<2&&!b.component);
  assert(tall.some(b=>b.supports.some(i=>model.bodies[i].role==='wall'))||!tall.length,'upper wall tiles must use adjacent lower tiles: '+preset.id);
  assert(!model.bodies.some(b=>b.role==='wall'&&!b.fixed&&!b.rotation&&!b.component&&b.supports.some(i=>{const a=model.bodies[i];return ['slab','roof'].includes(a.role)&&b.center[2]-b.size[2]/2-(a.center[2]+a.size[2]/2)>.4;})),'wall tiles still remotely attached to a floor: '+preset.id);
  const done=new Set(),stack=new Set();function visit(id){if(done.has(id))return;assert(!stack.has(id),'cyclic facade support path: '+preset.id);stack.add(id);for(const parent of model.bodies[id].supports)if(model.bodies[parent].role==='wall')visit(parent);stack.delete(id);done.add(id);}for(const b of model.bodies.filter(b=>b.role==='wall'))visit(b.id);
  const result=await api.simulate(model,{building:preset.id,source:preset.source,mass:600,duration:1,response:'fracture'}),last=result.frames.at(-1);
  assert.equal(result.method,panel.PANEL_FRACTURE_METHOD);assert(result.frames.every(f=>panel.validFractureFrame(f.fracture,model)&&f.poses.every(Number.isFinite)));assert(last.fracture.cracked>0&&last.fracture.detached>0,preset.id+' must develop progressive fracture');
  assert(result.frames.every(f=>debris.validDebrisFrame(f.debris)));assert(result.metrics.debris.contacts>0,'scene must exercise actual debris/debris contact: '+preset.id);
  for(const b of model.bodies.filter(b=>b.fixed))for(let k=0;k<3;k++)assert(Math.abs(last.poses[b.id*7+k]-b.center[k])<2e-5,preset.id+' fixed reference moved');
  const active=new Set(last.fracture.ids);assert(model.bodies.filter(b=>last.damage[b.id]===1&&panel.isPanel(b)).every(b=>active.has(b.id)),'failed eligible panels must enter network, not detach as a box');
  const zero=await api.simulate(model,{building:preset.id,source:preset.source,mass:0,duration:1,response:'fracture'});assert.equal(zero.metrics.maxDisplacement,0);assert.equal(zero.metrics.broken,0);assert.equal(zero.metrics.debris.contacts,0);assert.equal(zero.metrics.debris.pileHeight,0);
  summaries.push({id:preset.id,bodies:model.bodies.length,panels:last.fracture.ids.length,cracks:last.fracture.cracked,detached:last.fracture.detached,limited:last.fracture.limited,wallMs:result.metrics.wallMs});
 }
 console.log(JSON.stringify({status:'passed',checks:12,scenes:summaries,method:panel.PANEL_FRACTURE_METHOD}));
})().catch(e=>{console.error(e);process.exitCode=1;});
