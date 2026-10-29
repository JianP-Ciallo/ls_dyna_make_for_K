import {ORIGINAL_SCENE_PRESETS,buildOriginalScene} from './blast_original_scenes.js';
import {createPanelSystem,PANEL_FRACTURE_METHOD} from './blast_panel_fracture.js';
import {createContactSystem} from './blast_demo_contact.js';
import {refinePanelSupports} from './blast_demo_supports.js';
import {boxDebris,createDebrisSystem} from './blast_debris_contact.js';
import {buildRebarLayout} from './blast_rebar_layout.js';
import {createRebarBundles,REINFORCED_METHOD,REBAR_RESPONSE} from './blast_rebar_bundles.js';
import {createConcreteAdapter} from './blast_rebar_coupling.js';
import {createLocalRebar,LOCAL_REBAR_RESPONSE,LOCAL_REBAR_METHOD} from './blast_local_rebar.js';
import {POWDER_RESPONSE,POWDER_METHOD} from './blast_powder.js';
/* Small deterministic demonstration dynamics, independent of native OpenSees
 * and gravity equilibration. Optional K rules supply reinforcement layout.
 * Concrete damage is a dimensionless component
 * failure index; it is not a reinforced-concrete constitutive material model.
 */
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const noise=i=>{const x=Math.sin(i*127.1+311.7)*43758.5453;return x-Math.floor(x);};
export const DEFAULT_CONFIG=Object.freeze({mass:160,source:[4,-10,.8],duration:6});
export const DEFAULT_BUILDING_ID='residence-3';
export const COMPONENT_RESPONSE_METHOD='simplified-breakable-components@2';
export const BUILDING_PRESETS=Object.freeze([
 {id:'residence-3',name:'三层阳台住宅',storeys:3,scale:[1,1],balconies:true,facade:'residential',color:'#d9d6c9'},
 {id:'residence-2',name:'两层联排住宅',storeys:2,scale:[1.1,.8],balconies:true,facade:'residential',color:'#e1cdbb'},
 {id:'apartment-5',name:'五层公寓',storeys:5,scale:[.8,.95],balconies:true,facade:'residential',color:'#c6d0cc'},
 {id:'office-4',name:'四层办公楼',storeys:4,scale:[1.3,1],balconies:false,facade:'office',color:'#d1d7df'},
 {id:'tower-8',name:'八层塔楼',storeys:8,scale:[.65,.75],balconies:false,facade:'office',color:'#d3c6b9'}
].map(p=>Object.freeze({...p,scale:Object.freeze(p.scale),source:Object.freeze([4,-6*p.scale[1]-4,.8])})));
export const SCENE_PRESETS=Object.freeze([BUILDING_PRESETS[0],...ORIGINAL_SCENE_PRESETS]);
export const ALL_PRESETS=Object.freeze([...BUILDING_PRESETS,...ORIGINAL_SCENE_PRESETS]);

export function getBuildingPreset(id=DEFAULT_BUILDING_ID) {
 const preset=ALL_PRESETS.find(p=>p.id===id);if(!preset)throw Error('未知建筑，请从建筑列表选择');return preset;
}

export function validateConfig(value={}) {
 const preset=getBuildingPreset(value.building),[sx,sy]=preset.scale,roofZ=preset.storeys*3.1;
 const source=value.source??preset.source;
 if(!Array.isArray(source))throw Error('爆点坐标无效');
 const c={building:preset.id,mass:Number(value.mass??160),source:source.map(Number),duration:Number(value.duration??6)};
 c.response=value.response||'components';if(!['components','fracture'].includes(c.response))throw Error('未知破坏表现模式');
 if(value.reinforcement){if(![REBAR_RESPONSE,LOCAL_REBAR_RESPONSE].includes(value.reinforcement)||preset.id!=='residence-3'||c.response!=='fracture')throw Error('K 配筋仅用于三层住宅增强碎裂模式');c.reinforcement=value.reinforcement;}
 if(value.pulverization){if(value.pulverization!==POWDER_RESPONSE||preset.id!=='residence-3'||c.response!=='fracture'||(c.reinforcement&&c.reinforcement!==LOCAL_REBAR_RESPONSE))throw Error('近爆粉化仅用于三层住宅简化碎裂模式');c.pulverization=POWDER_RESPONSE;}
 if(!Number.isFinite(c.mass)||c.mass<0||c.mass>2000)throw Error('爆源当量应在0–2000 kg之间');
 const maxHeight=Math.max(15,Math.ceil(roofZ+6));
 if(c.source.length!==3||!c.source.every(Number.isFinite)||c.source.some(x=>Math.abs(x)>60)||c.source[2]<0||c.source[2]>maxHeight)throw Error(`爆点坐标无效，高度应为0–${maxHeight} m`);
 if(preset.originalScene){
  const scene=buildOriginalScene(preset.id),point=c.source;
  const insideEnvelope=scene.envelopes.some(e=>point.every((v,j)=>v>e.min[j]&&v<e.max[j]));
  const insidePart=scene.bodies.some(b=>!['road','marking'].includes(b.role)&&(b.role!=='ground'||b.component==='podium')&&point.every((v,j)=>Math.abs(v-b.center[j])<b.size[j]/2));
  if(insideEnvelope||insidePart)throw Error('请把爆点放在建筑外部空地，不要放进结构内部');
  if(!Number.isFinite(c.duration)||c.duration<1||c.duration>10)throw Error('模拟时长应在1–10秒之间');
  return c;
 }
 const insideMain=Math.abs(c.source[0]/sx)<8.8&&c.source[1]/sy>-(preset.balconies?7.9:6.4)&&c.source[1]/sy<6.4&&c.source[2]<roofZ+.8;
 const insideRoof=Math.abs(c.source[0]/sx)<1.05&&c.source[1]/sy>-.5&&c.source[1]/sy<1.8&&c.source[2]<roofZ+1.45;
 if(insideMain||insideRoof)throw Error('请把爆点放在建筑外');
 if(!Number.isFinite(c.duration)||c.duration<1||c.duration>10)throw Error('模拟时长应在1–10秒之间');
 return c;
}

export function responseMethod(config){return config.pulverization===POWDER_RESPONSE?POWDER_METHOD:config.response==='fracture'?(config.reinforcement===LOCAL_REBAR_RESPONSE?LOCAL_REBAR_METHOD:config.reinforcement?REINFORCED_METHOD:PANEL_FRACTURE_METHOD):COMPONENT_RESPONSE_METHOD;}

export function buildBuilding(options={}) {
 const preset=getBuildingPreset(options.building),storeys=preset.storeys,roofZ=storeys*3.1;
 if(preset.originalScene)return refinePanelSupports(buildOriginalScene(preset.id));
 const bodies=[],columns=[],slabs=[];
 const strength={wall:.22,glass:.035,column:.62,slab:1.0,balcony:.44,rail:.18,stairs:.5,roofbox:.3};
 const palette={wall:preset.color,glass:'#8bb7c1',column:'#c4c3b8',slab:'#deded4',balcony:'#b3d0ce',rail:'#91b7b6',stairs:'#d0cfc4',roofbox:'#c6c8bd'};
 function add(role,center,size,floor,extra={}) {
  const b={id:bodies.length,role,center,size,floor,color:palette[role],capacity:strength[role],supports:[],fixed:false,...extra};
  bodies.push(b);return b.id;
 }
 // Floors are volumes, divided into independent pieces for visible fracture.
 for(let level=0;level<=storeys;level++)for(let ix=0;ix<8;ix++)for(let iy=0;iy<6;iy++) {
  const id=add('slab',[-7.35+ix*2.1,-5+iy*2,level*3.1+.09],[2.08,1.98,.18],level,{fixed:level===0});
  slabs.push(id);
 }
 const xs=[-8.23,-2.8,2.8,8.23],ys=[-5.83,-2,2,5.83];
 for(let level=0;level<storeys;level++)for(let ix=0;ix<4;ix++)for(let iy=0;iy<4;iy++)for(let seg=0;seg<3;seg++) {
  columns.push(add('column',[xs[ix],ys[iy],level*3.1+.18+(seg+.5)*2.92/3],[.3,.3,2.92/3-.008],level,{chain:ix*4+iy,segment:seg}));
 }
 // Split each wall at opening boundaries, so windows/doors are real holes.
 function wall(axis,side,floor,holes,interior=false) {
  const lo=axis===0?-8.4:-6,hi=-lo,z0=floor*3.1+.18,z1=(floor+1)*3.1;
  const stops=new Set([lo,hi]);for(let x=lo+1.7;x<hi-.01;x+=1.7)stops.add(x);
  const heights=new Set([z0,z1,z0+1.0,z0+2]);
  for(const h of holes){stops.add(h[0]);stops.add(h[1]);heights.add(z0+h[2]);heights.add(Math.min(z1,z0+h[3]));}
  const u=[...stops].sort((a,b)=>a-b),z=[...heights].filter(x=>x>=z0&&x<=z1).sort((a,b)=>a-b);
  for(let i=0;i<u.length-1;i++)for(let j=0;j<z.length-1;j++) {
   const mid=(u[i]+u[i+1])/2,height=(z[j]+z[j+1])/2;
   if(holes.some(h=>mid>h[0]&&mid<h[1]&&height>z0+h[2]&&height<z0+h[3]))continue;
   const center=axis===0?[mid,side,height]:[side,mid,height],size=axis===0?[u[i+1]-u[i]-.008,.2,z[j+1]-z[j]-.008]:[.2,u[i+1]-u[i]-.008,z[j+1]-z[j]-.008];
   if(size.every(x=>x>.005))add('wall',center,size,floor,{normal:axis===0?[0,Math.sign(side),0]:[Math.sign(side),0,0],interior});
  }
  if(!interior)for(const h of holes)if(h[2]>.1) {
   const mid=(h[0]+h[1])/2,zz=z0+(h[2]+h[3])/2;
   add('glass',axis===0?[mid,side,zz]:[side,mid,zz],axis===0?[h[1]-h[0]-.04,.035,h[3]-h[2]-.04]:[.035,h[1]-h[0]-.04,h[3]-h[2]-.04],floor,{normal:axis===0?[0,Math.sign(side),0]:[Math.sign(side),0,0]});
  }
 }
 for(let floor=0;floor<storeys;floor++) {
  const frontHoles=preset.facade==='office'?(floor===0?[[-6.7,-5.3,.8,2.3],[-3.7,-2.3,.8,2.3],[-1.1,1.1,0,2.4],[2.3,3.7,.8,2.3],[5.3,6.7,.8,2.3]]:[-6,-3,0,3,6].map(x=>[x-.7,x+.7,.8,2.3])):[[-6.5,-4.8,0,2.25],[4.8,6.5,0,2.25],floor===0?[-1.1,1.1,0,2.4]:[-.65,.65,.9,2.25]];
  wall(0,-6,floor,frontHoles);
  wall(0,6,floor,[-6,-2,2,6].map(x=>[x-.6,x+.6,.9,2.25]));
  for(const side of [-8.4,8.4])wall(1,side,floor,[-3.6,0,3.6].map(y=>[y-.55,y+.55,.9,2.25]));
  // Internal partitions are also volumetric; entry/corridor openings remain.
  wall(1,-2.7,floor,[[-4.5,-3.4,0,2.2],[1.4,2.5,0,2.2]],true);
  wall(1,2.7,floor,[[-4.5,-3.4,0,2.2],[1.4,2.5,0,2.2]],true);
  if(preset.balconies)for(const x of [-5.5,5.5]) {
   for(let j=0;j<3;j++)add('balcony',[x+(j-1)*1.7,-6.8,floor*3.1+.15],[1.68,1.6,.2],floor);
   for(let j=0;j<4;j++)add('rail',[x+(j-1.5)*1.26,-7.55,floor*3.1+.72],[1.24,.12,.92],floor);
   for(const dx of [-2.5,2.5])add('rail',[x+dx,-6.8,floor*3.1+.72],[.12,1.5,.92],floor);
  }
  for(let j=0;j<12;j++)add('stairs',[.55,-2.8+j*.29,floor*3.1+.25+j*.245],[1.05,.32,.16],floor);
 }
 // Flat roof parapet and a modest stair enclosure, matching the references.
 for(const y of [-6,6])for(let i=0;i<10;i++)add('roofbox',[-7.56+i*1.68,y,roofZ+.32],[1.66,.14,.48],storeys);
 for(const x of [-8.4,8.4])for(let i=0;i<7;i++)add('roofbox',[x,-5.14+i*1.714,roofZ+.32],[.14,1.69,.48],storeys);
 for(const x of [-.85,.85])add('roofbox',[x,.6,roofZ+.65],[.14,1.8,1.2],storeys);
 for(const y of [-.3,1.5])add('roofbox',[0,y,roofZ+.65],[1.7,.14,1.2],storeys);
 add('roofbox',[0,.6,roofZ+1.3],[1.9,2,.12],storeys);
 const distance=(a,b)=>((a.center[0]-b.center[0])*preset.scale[0])**2+((a.center[1]-b.center[1])*preset.scale[1])**2;
 for(const b of bodies) {
  if(b.fixed)continue;
  if(b.role==='column') {
   const prev=columns.filter(i=>{const a=bodies[i];return a.chain===b.chain&&(b.segment>0?a.floor===b.floor&&a.segment===b.segment-1:a.floor===b.floor-1&&a.segment===2);});
   b.supports=prev;
  } else if(b.role==='slab') {
   b.supports=columns.filter(i=>bodies[i].floor===b.floor-1&&bodies[i].segment===2).sort((i,j)=>distance(b,bodies[i])-distance(b,bodies[j])).slice(0,3);
  } else {
   b.supports=slabs.filter(i=>bodies[i].floor===Math.min(storeys,b.floor)).sort((i,j)=>distance(b,bodies[i])-distance(b,bodies[j])).slice(0,b.role==='balcony'?2:1);
  }
 }
 for(const b of bodies){b.center[0]*=preset.scale[0];b.center[1]*=preset.scale[1];b.size[0]*=preset.scale[0];b.size[1]*=preset.scale[1];}
 return refinePanelSupports({schema:'simple-building-geometry@1',buildingId:preset.id,buildingCount:1,name:preset.name,storeys,width:16.8*preset.scale[0],depth:12*preset.scale[1],height:roofZ+1.36,bodies});
}

export async function simulate(model,value={},options={}) {
 const config=validateConfig(value),started=performance.now(),n=model.bodies.length,local=config.reinforcement===LOCAL_REBAR_RESPONSE||config.pulverization===POWDER_RESPONSE,dt=local?1/120:1/180,steps=Math.ceil(config.duration/dt),sampleEvery=local?4:6;
 const profiling=options.profile?{panelsMs:0,steelMs:0,contactMs:0,finalizeMs:0}:null;
 if(model.buildingId&&model.buildingId!==config.building)throw Error('建筑几何与本次计算配置不一致');
 const x=new Float64Array(n*3),v=new Float64Array(n*3),w=new Float64Array(n*3),q=new Float64Array(n*4),damage=new Float32Array(n),broken=new Uint8Array(n),hit=new Uint8Array(n);
 const arrivals=new Float64Array(n),severity=new Float64Array(n),frames=[],events=[];
 const contact=config.response==='fracture'?createContactSystem(model,{spatial3D:local}):null;
 const panels=contact?createPanelSystem(model,config,dt,contact):null;
 const previousPositions=new Float64Array(n*3),boxes=new Map(),debris=panels?createDebrisSystem({interval:1/60,allowRetirement:!!config.pulverization,projectConstraints:rows=>panels.projectDebrisConstraints(rows),groundLevel:point=>model.groundCutout&&point[0]>model.groundCutout[0]&&point[0]<model.groundCutout[2]&&point[1]>model.groundCutout[1]&&point[1]<model.groundCutout[3]?model.contactFloorZ:0}):null;
 for(let i=0;i<n;i++) {
  const b=model.bodies[i];x.set(b.center,i*3);q.set(b.rotation||[0,0,0,1],i*4);
  const d=b.center.map((a,j)=>a-config.source[j]),r=Math.hypot(...d),normal=b.normal;
  const facing=normal?Math.max(.1,-normal.reduce((s,a,j)=>s+a*d[j]/Math.max(r,.1),0)):.7;
  // Illustrative cube-root distance attenuation, not a calibrated pressure law.
  severity[i]=config.mass===0?0:Math.cbrt(config.mass)**2/(r+1)**2*facing*(b.interior?.38:1);
  arrivals[i]=.15+r/343;
 }
 const rebarLayout=config.reinforcement?buildRebarLayout(model):null;
 const adapter=rebarLayout?createConcreteAdapter(model,{x,v,q,w,broken,damage,panels,wakeBody:id=>{const proxy=boxes.get(id);if(proxy?.sleeping){proxy.sleeping=false;proxy.justWoke=true;}}}):null;
 const reinforcement=rebarLayout?(local?createLocalRebar(rebarLayout,adapter,{iterations:2,contact:(position,previous,velocity,radius,body)=>contact.resolve(position,previous,velocity,radius,body)}):createRebarBundles(rebarLayout,adapter)):null;
 let maxDisplacement=0,brokenCount=0;
 function boxEnvironment(i){
  const b=model.bodies[i],k=i*3,h=i*4,a=q[h],bb=q[h+1],c=q[h+2],d=q[h+3],halfZ=(Math.abs(2*(a*c-bb*d))*b.size[0]+Math.abs(2*(bb*c+a*d))*b.size[1]+Math.abs(1-2*(a*a+bb*bb))*b.size[2])/2,halfX=(Math.abs(1-2*(bb*bb+c*c))*b.size[0]+Math.abs(2*(a*bb-c*d))*b.size[1]+Math.abs(2*(a*c+bb*d))*b.size[2])/2,halfY=(Math.abs(2*(a*bb+c*d))*b.size[0]+Math.abs(1-2*(a*a+c*c))*b.size[1]+Math.abs(2*(bb*c-a*d))*b.size[2])/2;
  contact.resolve(x.subarray(k,k+3),previousPositions.subarray(k,k+3),v.subarray(k,k+3),halfZ,i,[halfX,halfY]);
 }
 function dynamicProxies(){const rows=panels.debrisProxies();for(let i=0;i<n;i++)if(broken[i]&&!model.bodies[i].fixed&&!panels.owns(i)){
  if(!boxes.has(i)){const b=model.bodies[i],k=i*3,proxy=boxDebris({id:(local?1000000:40000)+i,bodyId:i,position:x.subarray(k,k+3),previous:previousPositions.subarray(k,k+3),velocity:v.subarray(k,k+3),angularVelocity:w.subarray(k,k+3),rotation:q.subarray(i*4,i*4+4),size:b.size,mass:Math.max(1e-5,b.size.reduce((s,a)=>s*a,1))});proxy.environment=()=>boxEnvironment(i);proxy.support=()=>{const a=q[i*4],bb=q[i*4+1],c=q[i*4+2],d=q[i*4+3],halfZ=(Math.abs(2*(a*c-bb*d))*b.size[0]+Math.abs(2*(bb*c+a*d))*b.size[1]+Math.abs(1-2*(a*a+bb*bb))*b.size[2])/2;return contact.support(proxy.position,halfZ,i);};boxes.set(i,proxy);}rows.push(boxes.get(i));
 }return rows;}
 function release(i,time,why) {
  if(broken[i]||model.bodies[i].fixed)return;
  broken[i]=1;damage[i]=1;brokenCount++;
  const b=model.bodies[i],k=i*3;
  if(panels?.eligible(i)&&!panels.owns(i))panels.activate(i,time,true,Array.from(v.subarray(k,k+3)),{center:Array.from(x.subarray(k,k+3)),rotation:Array.from(q.subarray(i*4,i*4+4)),angularVelocity:Array.from(w.subarray(k,k+3))});
  w[k]=(noise(i+1)-.5)*4;w[k+1]=(noise(i+2)-.5)*4;w[k+2]=(noise(i+3)-.5)*3;
  events.push({time,body:i,position:Array.from(x.slice(k,k+3)),kind:why});
 }
 function sample(time) {
  const poses=new Float32Array(n*7);let moving=0;
  for(let i=0;i<n;i++){poses.set(x.subarray(i*3,i*3+3),i*7);poses.set(q.subarray(i*4,i*4+4),i*7+3);if(broken[i]&&!panels?.owns(i)&&Math.hypot(...v.subarray(i*3,i*3+3))>.1)moving++;}
  const frame={time,poses,damage:damage.slice(),broken:brokenCount,moving,maxDisplacement};if(panels){frame.fracture=panels.sample();frame.debris=debris.sample();frame.moving+=frame.fracture.moving;}if(reinforcement)frame.rebar=reinforcement.sample();frames.push(frame);return frame;
 }
 sample(0);
 for(let step=1;step<=steps;step++) {
  if(options.cancel?.())throw Error('cancelled');
  const t=step*dt;
  if(debris)previousPositions.set(x);
  if(contact&&step%(local?2:3)===1)contact.update(broken,x,panels);
  for(let i=0;i<n;i++) {
   const b=model.bodies[i],k=i*3;
   if(b.fixed)continue;
   if(!hit[i]&&t>=arrivals[i]) {
    hit[i]=1;const strength=severity[i]/b.capacity;damage[i]=clamp((strength-.15)/1.25);
    if(panels?.eligible(i)&&panels.preferred(i)&&strength>.12&&panels.activate(i,t))continue;
    const d=b.center.map((a,j)=>a-config.source[j]),r=Math.max(.1,Math.hypot(...d));
    const speed=severity[i]*7/(1+Math.cbrt(b.size.reduce((s,a)=>s*a,1)));
    for(let j=0;j<3;j++)v[k+j]+=speed*(d[j]/r+(noise(i*5+j)-.5)*.24);
    v[k+2]+=speed*.22;
    if(strength>1.15)release(i,t,'impact');
   }
  }
  if(step%(local?6:9)===0)for(let i=0;i<n;i++) {
   const b=model.bodies[i];if(b.fixed||broken[i]||!b.supports.length||panels?.owns(i))continue;
   const lost=b.supports.filter(j=>broken[j]||(panels?.owns(j)&&panels.supportAt(j,b.center,broken,x).lost)).length/b.supports.length;
   if(lost>=(b.role==='slab'?.66:1)&&t>.35)release(i,t,'support_loss');
  }
  for(let i=0;i<n;i++) {
   const b=model.bodies[i],k=i*3,h=i*4;if(b.fixed||panels?.owns(i)||boxes.get(i)?.sleeping)continue;
   if(broken[i])v[k+2]-=9.80665*dt;
   else for(let j=0;j<3;j++)v[k+j]+=(-(x[k+j]-b.center[j])*625-v[k+j]*14)*dt;
   const previous=contact&&broken[i]?x.slice(k,k+3):null;
   for(let j=0;j<3;j++)x[k+j]+=v[k+j]*dt;
   if(broken[i]) {
    const [qx,qy,qz,qw]=q.subarray(h,h+4),wx=w[k],wy=w[k+1],wz=w[k+2],half=dt*.5;
    q[h]+=half*(wx*qw+wy*qz-wz*qy);q[h+1]+=half*(-wx*qz+wy*qw+wz*qx);q[h+2]+=half*(wx*qy-wy*qx+wz*qw);q[h+3]+=half*(-wx*qx-wy*qy-wz*qz);
    const length=Math.hypot(...q.subarray(h,h+4));for(let j=0;j<4;j++)q[h+j]/=length;
    const a=q[h],bb=q[h+1],c=q[h+2],d=q[h+3];
    const halfZ=(Math.abs(2*(a*c-bb*d))*b.size[0]+Math.abs(2*(bb*c+a*d))*b.size[1]+Math.abs(1-2*(a*a+bb*bb))*b.size[2])/2;
    const pit=model.groundCutout,inPit=pit&&x[k]>pit[0]&&x[k]<pit[2]&&x[k+1]>pit[1]&&x[k+1]<pit[3],groundZ=inPit?model.contactFloorZ:0;
    if(contact){const halfX=(Math.abs(1-2*(bb*bb+c*c))*b.size[0]+Math.abs(2*(a*bb-c*d))*b.size[1]+Math.abs(2*(a*c+bb*d))*b.size[2])/2,halfY=(Math.abs(2*(a*bb+c*d))*b.size[0]+Math.abs(1-2*(a*a+c*c))*b.size[1]+Math.abs(2*(bb*c-a*d))*b.size[2])/2;if(contact.resolve(x.subarray(k,k+3),previous,v.subarray(k,k+3),halfZ,i,[halfX,halfY]))for(let j=0;j<3;j++)w[k+j]*=.8;}
    else if(x[k+2]<groundZ+halfZ){x[k+2]=groundZ+halfZ;v[k+2]=Math.max(0,-v[k+2]*.12);v[k]*=.82;v[k+1]*=.82;for(let j=0;j<3;j++)w[k+j]*=.8;}
   }
   maxDisplacement=Math.max(maxDisplacement,Math.hypot(x[k]-b.center[0],x[k+1]-b.center[1],x[k+2]-b.center[2]));
  }
  if(panels){let phase=profiling?performance.now():0;panels.step(t,broken,x);if(config.pulverization)events.push(...panels.drainPowderEvents());if(profiling){profiling.panelsMs+=performance.now()-phase;phase=performance.now();}if(!local||step%2===0)reinforcement?.step(local?dt*2:dt);if(profiling){profiling.steelMs+=performance.now()-phase;phase=performance.now();}debris.solve(dynamicProxies(),dt,p=>p.environment());if(profiling){profiling.contactMs+=performance.now()-phase;phase=performance.now();}panels.finalizeDebris();for(let i=0;i<n;i++)if(panels.owns(i)){if(panels.updateBody(i,x,damage))release(i,t,'panel_separation');}else maxDisplacement=Math.max(maxDisplacement,Math.hypot(x[i*3]-model.bodies[i].center[0],x[i*3+1]-model.bodies[i].center[1],x[i*3+2]-model.bodies[i].center[2]));maxDisplacement=Math.max(maxDisplacement,panels.maxDisplacement());if(profiling)profiling.finalizeMs+=performance.now()-phase;}
  if(step%sampleEvery===0||step===steps) {
   const frame=sample(Math.min(config.duration,t));
   if(step%(sampleEvery*6)===0||step===steps){options.progress?.({fraction:step/steps,frame,events:events.slice()});await new Promise(resolve=>setTimeout(resolve,0));}
  }
 }
 return {schema:'simple-blast-demo@1',method:responseMethod(config),config,model,frames,events,...(reinforcement?{reinforcement:{schema:rebarLayout.schema,source:rebarLayout.source,bars:rebarLayout.bars.length,bundles:local?reinforcement.plan.bars.length:reinforcement.plan.bundles.length,members:rebarLayout.members.map(({id,key,kind,floor,sourceComponent,sourceParts,bodyIds})=>({id,key,kind,floor,sourceComponent,sourceParts,bodyIds})),unmapped:rebarLayout.unmapped,assumptions:local?['K_layout_preserved_local_debundling_at_cracked_hosts','inertial_steel_rods_breakable_embedding_and_physical_free_tips','local_pressure_compression_damage_not_calibrated_FEM','adaptive_near_source_prism_cells_budget_14','steel_ground_and_retained_surface_contact_no_steel_self_collision']:['K_member_rules_relocated_not_original_whole_building_bar_totals','layer_depth_mapped_to_existing_member_thickness','equivalent_area_massless_steel_constraints_not_individual_bar_FEM','K_yield_and_failure_references_not_calibrated_blast_prediction','ideal_embedded_bond_and_slab_column_joint_anchorage','bar_curves_interpolated_from_bundle_response']}}:{}),
  metrics:{wallMs:performance.now()-started,workerSteps:steps,dt,broken:brokenCount,total:n,maxDisplacement,...(contact?{contacts:contact.stats(),debris:debris.sample()}: {}),...(config.pulverization?{powder:panels.powderStats()}:{}),...(reinforcement?{rebar:Object.fromEntries(Object.entries(reinforcement.sample()).filter(([,v])=>!ArrayBuffer.isView(v)))}:{}),...(profiling?{profiling}:{})},
  assumptions:['initial_reference_pose_without_gravity_equilibration','dimensionless_component_failure_not_rebar_stress','illustrative_blast_attenuation',...(panels?['retained_floor_excavation_and_two_way_convex_debris_contact','uniform_relative_density_geometric_inertia_not_calibrated_materials','translational_swept_contact_small_step_angular_motion','cohesive_triangle_network_not_calibrated_concrete_FEM','support_loss_releases_attachments_not_internal_bonds','near_source_flexible_activation_budget_420','distant_failed_panels_subdivided_on_release','network_hard_limit_1600_panels_reported_in_frames']:['ground_contact_only_no_debris_debris_contact'])]};
}
