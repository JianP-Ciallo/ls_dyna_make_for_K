/* Demonstration-only cohesive triangle network. No engineering material constants.
 * Nodes bend before edge/attachment failure; disconnected islands fall and contact ground.
 */
import {createContactSystem} from './blast_demo_contact.js';
import {triangleDebris,createDebrisSystem} from './blast_debris_contact.js';
import {refinementDivisions,compressionState,stepCompression,materialDamage} from './blast_damage_fields.js';
import {POWDER_RESPONSE,POWDER_SCHEMA,advancePowder,powderConcrete} from './blast_powder.js';
const rand=i=>{const x=Math.sin(i*127.1+17.37)*43758.5453;return x-Math.floor(x);};
export const PANEL_FRACTURE_METHOD='progressive-panel-fracture@5';
const roles=new Set(['wall','slab','roof','glass','balcony','canopy','sign','roofbox','rail']);
export function isPanel(b){const sizes=[...b.size].sort((a,c)=>a-c);return !b.fixed&&roles.has(b.role)&&sizes[0]<sizes[1]*.46&&sizes[1]>.25;}
function rotate(p,q=[0,0,0,1]){const [x,y,z,w]=q,[a,b,c]=p,tx=2*(y*c-z*b),ty=2*(z*a-x*c),tz=2*(x*b-y*a);return [a+w*tx+y*tz-z*ty,b+w*ty+z*tx-x*tz,c+w*tz+x*ty-y*tx];}
export function panelPatch(body,divisions=null){
 const thin=body.size.indexOf(Math.min(...body.size)),axes=[0,1,2].filter(i=>i!==thin),W=body.size[axes[0]],H=body.size[axes[1]],n=W*H>6?3:2,nx=divisions?.nx||n,ny=divisions?.ny||n,points=[],triangles=[];
 const normal=rotate([0,1,2].map(i=>i===thin?1:0),body.rotation);
 for(let j=0;j<=ny;j++)for(let i=0;i<=nx;i++){
  const p=[0,0,0];p[axes[0]]=W*(i/nx-.5)+(i>0&&i<nx?(rand(body.id*53+i+j*7)-.5)*W/nx*.3:0);p[axes[1]]=H*(j/ny-.5)+(j>0&&j<ny?(rand(body.id*71+i*3+j)-.5)*H/ny*.3:0);
  const edge=(body.role==='wall'||body.role==='column'||(body.role==='rail'&&thin!==2))?j===0:['balcony','canopy'].includes(body.role)?j===ny:i===0||j===0||i===nx||j===ny;
  points.push({p:rotate(p,body.rotation).map((v,k)=>v+body.center[k]),edge});
 }
 function triangle(ids){let v=ids.map(i=>points[i].p),a=v[1].map((x,k)=>x-v[0][k]),b=v[2].map((x,k)=>x-v[0][k]),cross=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];if(cross.reduce((s,x,k)=>s+x*normal[k],0)<0)ids=[ids[0],ids[2],ids[1]];
  triangles.push({indices:ids,vertices:ids.flatMap(i=>points[i].p),anchors:ids.map(i=>points[i].edge),area:Math.hypot(...cross)/2});}
 for(let j=0;j<ny;j++)for(let i=0;i<nx;i++){const a=j*(nx+1)+i,b=a+1,c=a+nx+1,d=c+1;if(rand(body.id+i*13+j*7)>.5){triangle([a,b,d]);triangle([a,d,c]);}else{triangle([a,b,c]);triangle([b,d,c]);}}
 const pairs=new Map(),bonds=[];
 triangles.forEach((t,ti)=>{for(let k=0;k<3;k++){const a=t.indices[k],b=t.indices[(k+1)%3],key=[a,b].sort((x,y)=>x-y).join(':'),other=pairs.get(key);if(other){const old=triangles[other.t];bonds.push({a:other.t,b:ti,pairs:[a,b].map(id=>[other.t*3+old.indices.indexOf(id),ti*3+t.indices.indexOf(id)]),edge:[ti*3+k,ti*3+(k+1)%3]});}else pairs.set(key,{t:ti});}});
 return {triangles,bonds,normal,thickness:body.size[thin],nx,ny};
}

export function createPanelSystem(model,config,dt,sharedContact=null){
 const powderEnabled=config.pulverization===POWDER_RESPONSE;let powderQueue=[],powderInitialMass=0,powderMass=0,powderedCount=0;
 const contact=sharedContact||createContactSystem(model,{spatial3D:config.reinforcement==='k-bundles@2'});let contactStep=0;
 const localDebris=sharedContact?null:createDebrisSystem({interval:1/60,allowRetirement:powderEnabled,projectConstraints:projectDebrisConstraints,groundLevel:point=>model.groundCutout&&point[0]>model.groundCutout[0]&&point[0]<model.groundCutout[2]&&point[1]>model.groundCutout[1]&&point[1]<model.groundCutout[3]?model.contactFloorZ:0});
 const adaptive=config.reinforcement==='k-bundles@2'||powderEnabled,patches=new Map(),eligible=model.bodies.map(b=>isPanel(b)||(adaptive&&!b.fixed&&['column','stairs'].includes(b.role))),budget=420,hardLimit=1600;
 const ranked=model.bodies.filter(b=>eligible[b.id]).map(b=>{const r=Math.hypot(...b.center.map((v,k)=>v-config.source[k]));return {id:b.id,score:1/(r+1)**2/Math.max(.03,b.capacity)};}).sort((a,b)=>b.score-a.score);
 const preferred=new Set(ranked.slice(0,budget).map(b=>b.id));let limited=0,maximumDisplacement=0;
 const fine=new Set(adaptive?ranked.filter(a=>{const b=model.bodies[a.id];return b.role!=='glass'&&Math.hypot(...b.center.map((v,k)=>v-config.source[k]))<8;}).map(a=>{const sizes=[...model.bodies[a.id].size].sort((x,y)=>x-y);return {...a,score:a.score*sizes[1]*sizes[2]};}).sort((a,b)=>b.score-a.score).slice(0,14).map(a=>a.id):[]);
 function nearestSupport(body,point){let best=null,distance=Infinity;for(const id of body.supports){const b=model.bodies[id];let d=0;for(let k=0;k<3;k++)d+=Math.max(0,Math.abs(point[k]-b.center[k])-b.size[k]/2)**2;if(d<distance){best=id;distance=d;}}return best;}
 function supportAt(id,point,broken,supportPositions,link){
  if(broken?.[id])return {lost:true,offset:[0,0,0]};const p=patches.get(id);
  if(!p)return {lost:false,offset:[0,1,2].map(k=>supportPositions?supportPositions[id*3+k]-model.bodies[id].center[k]:0)};
  if(!link||link.parent!==id){let best=0,distance=Infinity;for(let t=0;t<p.triangles.length;t++){let d=0;for(let k=0;k<3;k++)d+=((p.rest[t*9+k]+p.rest[t*9+3+k]+p.rest[t*9+6+k])/3-point[k])**2;if(d<distance){best=t;distance=d;}}
   const k=best*9,a=Array.from(p.rest.subarray(k,k+3)),u=[0,1,2].map(j=>p.rest[k+3+j]-a[j]),v=[0,1,2].map(j=>p.rest[k+6+j]-a[j]),w=point.map((x,j)=>x-a[j]),dot=(x,y)=>x.reduce((s,a,j)=>s+a*y[j],0),uu=dot(u,u),uv=dot(u,v),vv=dot(v,v),wu=dot(w,u),wv=dot(w,v),den=Math.max(1e-12,uu*vv-uv*uv),b=(vv*wu-uv*wv)/den,c=(uu*wv-uv*wu)/den,weights=[1-b-c,b,c].map(x=>Math.max(0,x)),sum=weights.reduce((a,b)=>a+b,0);
   link={parent:id,triangle:best,weights:weights.map(x=>x/sum)};
  }
  const lost=!!p.detached[link.triangle]||!!p.powdered?.[link.triangle],offset=[0,0,0];if(!lost)for(let n=0;n<3;n++)for(let k=0;k<3;k++)offset[k]+=(p.x[link.triangle*9+n*3+k]-p.rest[link.triangle*9+n*3+k])*link.weights[n];
  return {lost,offset,link};
 }
 function activate(id,time,free=false,velocity=[0,0,0],motion=null){
  if(patches.has(id))return true;if(!eligible[id]||patches.size>=hardLimit){if(eligible[id])limited++;return false;}
  const body=model.bodies[id],shape=panelPatch(body,adaptive?refinementDivisions(body,fine.has(id)):null),rest=new Float64Array(shape.triangles.flatMap(t=>t.vertices)),x=rest.slice(),v=new Float64Array(rest.length),prev=rest.slice(),anchors=[],springs=[];
  for(let i=0;i<rest.length;i+=3){let offset=Array.from(rest.subarray(i,i+3)).map((a,k)=>a-body.center[k]);if(motion){const q=body.rotation||[0,0,0,1];offset=rotate(rotate(offset,[-q[0],-q[1],-q[2],q[3]]),motion.rotation);x.set(offset.map((a,k)=>a+motion.center[k]),i);}const w=motion?.angularVelocity||[0,0,0],spin=[w[1]*offset[2]-w[2]*offset[1],w[2]*offset[0]-w[0]*offset[2],w[0]*offset[1]-w[1]*offset[0]];v.set(velocity.map((a,k)=>a+spin[k]),i);}prev.set(x);
  // Position corrections scale with dt²; thresholds represent an illustrative nodal load.
  const correctionScale=(dt*180)**2;
  shape.triangles.forEach((tri,ti)=>{tri.center=[0,1,2].map(k=>(tri.vertices[k]+tri.vertices[3+k]+tri.vertices[6+k])/3);for(let a=0;a<3;a++){const node=ti*3+a;if(tri.anchors[a])anchors.push({node,parent:nearestSupport(body,Array.from(rest.subarray(node*3,node*3+3))),offset:[0,0,0],damage:free?1:0,limit:(body.role==='glass'?.0007:.0027)*correctionScale*(.75+rand(id*89+node)*.65)*Math.sqrt(body.capacity/.22)});const other=ti*3+(a+1)%3;let length=0;for(let k=0;k<3;k++)length+=(rest[node*3+k]-rest[other*3+k])**2;springs.push({a:node,b:other,length:Math.sqrt(length),triangle:ti});}});
  const patch={id,body,...shape,rest,x,v,prev,anchors,springs,free,activation:time,bonds:shape.bonds.map((b,i)=>{const a=b.a*3+[0,1,2].find(k=>!b.pairs.some(pair=>pair[0]===b.a*3+k)),c=b.b*3+[0,1,2].find(k=>!b.pairs.some(pair=>pair[1]===b.b*3+k));return {...b,damage:0,limit:(body.role==='glass'?.001:.0045)*correctionScale*(.65+rand(id*47+i)*.85)*Math.sqrt(body.capacity/.22),hinge:[a,c,Math.hypot(...[0,1,2].map(k=>rest[a*3+k]-rest[c*3+k]))]};}),detached:new Uint8Array(shape.triangles.length),damage:new Float32Array(shape.triangles.length),normals:new Float64Array(shape.triangles.length*3)};
  patch.islands=new Int16Array(shape.triangles.length);patch.debris=[];
  if(adaptive){patch.adaptive=true;patch.compression=shape.triangles.map(()=>compressionState(shape.thickness));patch.cohesive=new Float32Array(shape.triangles.length);patch.anchorDamage=new Float32Array(shape.triangles.length);patch.nodeDamage=new Float32Array(shape.triangles.length*3);}
  if(powderEnabled){patch.powder=shape.triangles.map(()=>({dose:0,time:-1}));patch.powdered=new Uint8Array(shape.triangles.length);if(powderConcrete(body))powderInitialMass+=shape.triangles.reduce((s,t)=>s+t.area*shape.thickness,0);}
  patch.pulseEnd=.225;for(let k=0;k<rest.length;k+=3)patch.pulseEnd=Math.max(patch.pulseEnd,.225+Math.hypot(rest[k]-config.source[0],rest[k+1]-config.source[1],rest[k+2]-config.source[2])/343);
  connectivity(patch);patches.set(id,patch);return true;
 }
 function connectivity(p){
  const reachable=new Uint8Array(p.triangles.length),queue=[];
  for(const a of p.anchors)if(a.damage<1){const t=Math.floor(a.node/3);if(!reachable[t]){reachable[t]=1;queue.push(t);}}
  for(let i=0;i<queue.length;i++)for(const bond of p.bonds)if(bond.damage<1){const next=bond.a===queue[i]?bond.b:bond.b===queue[i]?bond.a:-1;if(next>=0&&!reachable[next]){reachable[next]=1;queue.push(next);}}
  for(let i=0;i<reachable.length;i++)p.detached[i]=reachable[i]?0:1;
  p.islands.fill(-1);for(let seed=0;seed<p.triangles.length;seed++)if(p.islands[seed]<0){const island=[seed];p.islands[seed]=seed;for(let j=0;j<island.length;j++)for(const b of p.bonds)if(b.damage<1){const next=b.a===island[j]?b.b:b.b===island[j]?b.a:-1;if(next>=0&&p.islands[next]<0){p.islands[next]=seed;island.push(next);}}}
  p.weld=Int16Array.from({length:p.triangles.length*3},(_,i)=>i);const root=i=>{while(p.weld[i]!==i)i=p.weld[i];return i;};for(const bond of p.bonds)if(bond.damage<1)for(const [a,b] of bond.pairs){const ra=root(a),rb=root(b);p.weld[Math.max(ra,rb)]=Math.min(ra,rb);}for(let i=0;i<p.weld.length;i++)p.weld[i]=root(i);
 }
 function spring(p,a,b,length,stiffness){
  if(p.powdered?.[Math.floor(a/3)]||p.powdered?.[Math.floor(b/3)])return;
  const ai=a*3,bi=b*3;let squared=0;for(let k=0;k<3;k++)squared+=(p.x[bi+k]-p.x[ai+k])**2;const d=Math.sqrt(squared);if(d<1e-12)return;
  const f=(d-length)/d*.5*stiffness;for(let k=0;k<3;k++){const delta=(p.x[bi+k]-p.x[ai+k])*f;p.x[ai+k]+=delta;p.x[bi+k]-=delta;}
 }
 function step(time,broken,supportPositions){
  if(config.mass===0)return;
  if(!sharedContact&&contactStep++%3===0)contact.update(broken,supportPositions,{owns:id=>patches.has(id),contactTriangles});
  for(const p of patches.values()){
   const {x,v,prev,rest,body}=p;prev.set(x);
   if(p.detached.every(Boolean)&&p.triangles.every((_,t)=>p.debris[t]?.sleeping))continue;
   if(p.adaptive&&body.role!=='glass')for(let tri=0;tri<p.triangles.length;tri++){const delta=p.triangles[tri].center.map((v,k)=>v-config.source[k]),r=Math.max(.1,Math.hypot(...delta)),age=time-(.15+r/343),normal=Math.abs(delta.reduce((s,v,k)=>s+v*p.normal[k]/r,0)),facing=body.normal?Math.max(.1,-body.normal.reduce((s,v,k)=>s+v*delta[k]/r,0)):.7,severity=Math.cbrt(config.mass)**2/(r+1)**2*facing*(body.interior?.38:1),load=age>0&&age<.075?severity*4/(1+Math.cbrt(body.size.reduce((s,v)=>s*v,1)))*2*(1-age/.075)/.075*normal:0;stepCompression(p.compression[tri],load,dt);}
   if(powderEnabled)for(let t=0;t<p.triangles.length;t++)if(advancePowder(p.powder[t],{body,point:p.triangles[t].center,config,damage:Math.max(p.damage[t],p.compression[t].damage),time,dt})){
    p.powdered[t]=1;p.detached[t]=1;p.damage[t]=1;for(const b of p.bonds)if(b.a===t||b.b===t)b.damage=1;for(const a of p.anchors)if(Math.floor(a.node/3)===t)a.damage=1;if(p.debris[t]){p.debris[t].retired=true;p.debris[t].sleeping=false;}
    const k=t*9,position=[0,1,2].map(j=>(x[k+j]+x[k+3+j]+x[k+6+j])/3),velocity=[0,1,2].map(j=>(v[k+j]+v[k+3+j]+v[k+6+j])/3),mass=p.triangles[t].area*p.thickness;powderMass+=mass;powderedCount++;powderQueue.push({kind:'pulverized',time,body:p.id,triangle:t,seed:p.id*128+t,mass,thickness:p.thickness,position,velocity,vertices:Array.from(x.slice(k,k+9))});
   }
   for(const anchor of p.anchors)if(anchor.damage<1&&anchor.parent!==null){const state=supportAt(anchor.parent,Array.from(rest.subarray(anchor.node*3,anchor.node*3+3)),broken,supportPositions,anchor.link);anchor.link=state.link;anchor.offset=state.offset;if(state.lost)anchor.damage=1;}
   for(let i=0;i<x.length/3;i++){if(p.powdered?.[Math.floor(i/3)]||p.debris[Math.floor(i/3)]?.sleeping)continue;
    const k=i*3;if(!p.free&&time<p.pulseEnd){const delta=[rest[k]-config.source[0],rest[k+1]-config.source[1],rest[k+2]-config.source[2]],r=Math.max(.1,Math.hypot(...delta)),age=time-(.15+r/343),pulse=.075;
    if(age>0&&age<pulse){const facing=body.normal?Math.max(.1,-body.normal.reduce((s,a,j)=>s+a*delta[j]/r,0)):.7,severity=Math.cbrt(config.mass)**2/(r+1)**2*facing*(body.interior?.38:1),speed=severity*4/(1+Math.cbrt(body.size.reduce((s,a)=>s*a,1))),force=2*(1-age/pulse)/pulse;
     for(let j=0;j<3;j++)v[k+j]+=speed*force*dt*(delta[j]/r+(rand(body.id*31+i*3+j)-.5)*.07);}}
    if(p.detached[Math.floor(i/3)])v[k+2]-=9.80665*dt;
    for(let j=0;j<3;j++)x[k+j]+=v[k+j]*dt;
   }
   for(let tri=0;tri<p.triangles.length;tri++){const k=tri*9,ax=x[k+3]-x[k],ay=x[k+4]-x[k+1],az=x[k+5]-x[k+2],bx=x[k+6]-x[k],by=x[k+7]-x[k+1],bz=x[k+8]-x[k+2],nx=ay*bz-az*by,ny=az*bx-ax*bz,nz=ax*by-ay*bx,len=Math.max(1e-12,Math.hypot(nx,ny,nz));p.normals.set([nx/len,ny/len,nz/len],tri*3);}
   for(const bond of p.bonds)if(bond.damage<1){let gap=0;for(const [a,b] of bond.pairs){let d=0;for(let j=0;j<3;j++)d+=(x[a*3+j]-x[b*3+j])**2;gap=Math.max(gap,Math.sqrt(d));}let dot=0;for(let j=0;j<3;j++)dot+=p.normals[bond.a*3+j]*p.normals[bond.b*3+j];const curvature=(1-Math.min(1,dot))/((body.role==='glass'?.012:.04)*Math.sqrt(body.capacity/.22));bond.damage=Math.min(1,bond.damage+dt*Math.max(0,Math.max(gap/bond.limit,curvature)-.6)*12);}
   for(const anchor of p.anchors)if(anchor.damage<1){const k=anchor.node*3,gap=Math.hypot(x[k]-rest[k]-anchor.offset[0],x[k+1]-rest[k+1]-anchor.offset[1],x[k+2]-rest[k+2]-anchor.offset[2]);anchor.damage=Math.min(1,anchor.damage+dt*Math.max(0,gap/anchor.limit-.6)*10);}
   if(p.adaptive)for(const bond of p.bonds)bond.damage=Math.min(1,bond.damage+dt*8*Math.max(p.compression[bond.a].damage,p.compression[bond.b].damage));
   connectivity(p);
   for(let iteration=0;iteration<3;iteration++){
    for(const s of p.springs)if(!p.debris[Math.floor(s.a/3)]?.sleeping)spring(p,s.a,s.b,s.length*(p.adaptive?1+.12*p.compression[s.triangle].plastic:1),.9*(p.adaptive?1-.75*p.compression[s.triangle].damage:1));
    for(const bond of p.bonds)if(bond.damage<1&&!p.debris[bond.a]?.sleeping){spring(p,...bond.hinge,.35*(1-bond.damage)**2);for(const [a,b] of bond.pairs){const f=.85*(1-bond.damage)**2;for(let k=0;k<3;k++){const d=(x[b*3+k]-x[a*3+k])*.5*f;x[a*3+k]+=d;x[b*3+k]-=d;}}}
    for(const anchor of p.anchors)if(anchor.damage<1){const f=.8*(1-anchor.damage)**2,k=anchor.node*3;for(let j=0;j<3;j++)x[k+j]+=(rest[k+j]+anchor.offset[j]-x[k+j])*f;}
   }
   for(let i=0;i<x.length/3;i++){if(p.powdered?.[Math.floor(i/3)]||p.debris[Math.floor(i/3)]?.sleeping)continue;
    const k=i*3;for(let j=0;j<3;j++)v[k+j]=(x[k+j]-prev[k+j])/dt*(p.detached[Math.floor(i/3)]?Math.exp(-.035*dt):.985);
    if(p.detached[Math.floor(i/3)]){const point=x.subarray(k,k+3),velocity=v.subarray(k,k+3);contact.resolve(point,prev.subarray(k,k+3),velocity,(p.adaptive?p.compression[Math.floor(i/3)].thickness:p.thickness)/2,p.id);}
    for(let j=0;j<3;j++)if(!Number.isFinite(x[k+j])||Math.abs(x[k+j])>5000)throw Error('柔性板片状态超出有限演示范围，已停止。');
    maximumDisplacement=Math.max(maximumDisplacement,Math.hypot(x[k]-rest[k],x[k+1]-rest[k+1],x[k+2]-rest[k+2]));
   }
   p.damage.fill(0);for(const bond of p.bonds){p.damage[bond.a]=Math.max(p.damage[bond.a],bond.damage);p.damage[bond.b]=Math.max(p.damage[bond.b],bond.damage);}
   if(p.adaptive){p.cohesive.fill(0);p.anchorDamage.fill(0);for(const bond of p.bonds){p.cohesive[bond.a]+=bond.damage/3;p.cohesive[bond.b]+=bond.damage/3;}for(const a of p.anchors)p.anchorDamage[Math.floor(a.node/3)]=Math.max(p.anchorDamage[Math.floor(a.node/3)],a.damage);for(let t=0;t<p.damage.length;t++)p.damage[t]=materialDamage(p.cohesive[t],p.compression[t].damage);
    if(powderEnabled)for(let t=0;t<p.powdered.length;t++)if(p.powdered[t])p.damage[t]=1;
    const sums=new Float64Array(p.weld.length),weights=new Float64Array(p.weld.length);for(let i=0;i<p.weld.length;i++){const root=p.weld[i],area=p.triangles[Math.floor(i/3)].area;sums[root]+=p.damage[Math.floor(i/3)]*area;weights[root]+=area;}for(let i=0;i<p.weld.length;i++)p.nodeDamage[i]=sums[p.weld[i]]/Math.max(1e-12,weights[p.weld[i]]);
   }
  }
  if(localDebris){localDebris.solve(debrisProxies(),dt,p=>p.environment());finalizeDebris();}
 }
 function debrisProxies(){const rows=[];for(const p of patches.values())for(let t=0;t<p.triangles.length;t++)if(p.detached[t]&&!p.powdered?.[t]){
  if(!p.debris[t]){const k=t*9,proxy=triangleDebris({id:p.id*(adaptive?128:18)+t,bodyId:p.id,patch:p,triangle:t,positions:p.x.subarray(k,k+9),previous:p.prev.subarray(k,k+9),velocities:p.v.subarray(k,k+9),thickness:p.thickness,mass:Math.max(1e-5,p.triangles[t].area*p.thickness)});
   proxy.exclude=other=>other.patch===p&&[0,1,2].some(a=>[0,1,2].some(b=>p.weld[t*3+a]===p.weld[other.triangle*3+b]));
   proxy.environment=()=>{for(let i=0;i<9;i+=3)contact.resolve(proxy.positions.subarray(i,i+3),proxy.previous.subarray(i,i+3),proxy.velocities.subarray(i,i+3),proxy.thickness/2,p.id);};p.debris[t]=proxy;
   proxy.support=()=>{const states=[0,3,6].map(i=>contact.support(proxy.positions.subarray(i,i+3),proxy.thickness/2,p.id));return {supported:states.some(s=>s.supported),grounded:states.some(s=>s.grounded)};};
  }const proxy=p.debris[t],group='panel:'+p.id+':'+p.islands[t];if(p.adaptive)proxy.thickness=p.compression[t].thickness;if(proxy.sleepGroup&&proxy.sleepGroup!==group){proxy.sleeping=false;proxy.justWoke=true;}proxy.sleepGroup=group;rows.push(proxy);
 }return rows;}
 function projectDebrisConstraints(moved){const affected=new Set(moved),selected=new Set([...moved].map(a=>a.patch).filter(Boolean));for(const p of selected){
  const groups=new Map();for(let node=0;node<p.weld.length;node++){const root=p.weld[node];if(!groups.has(root))groups.set(root,[]);groups.get(root).push(node);}
  for(const s of p.springs)if(!p.debris[Math.floor(s.a/3)]?.sleeping)spring(p,s.a,s.b,s.length*(p.adaptive?1+.12*p.compression[s.triangle].plastic:1),.9*(p.adaptive?1-.75*p.compression[s.triangle].damage:1));for(const nodes of groups.values())if(nodes.length>1&&!p.debris[Math.floor(nodes[0]/3)]?.sleeping){let mass=0;const position=[0,0,0],velocity=[0,0,0];for(const node of nodes){const weight=p.triangles[Math.floor(node/3)].area*p.thickness;mass+=weight;for(let k=0;k<3;k++){position[k]+=p.x[node*3+k]*weight;velocity[k]+=p.v[node*3+k]*weight;}}for(const node of nodes)for(let k=0;k<3;k++){p.x[node*3+k]=position[k]/mass;p.v[node*3+k]=velocity[k]/mass;}}
  for(let t=0;t<p.debris.length;t++)if(p.detached[t]&&!p.powdered?.[t]&&p.debris[t]&&!p.debris[t].sleeping)affected.add(p.debris[t]);
 }return affected;}
 function finalizeDebris(){for(const p of patches.values())for(let k=0;k<p.x.length;k+=3)maximumDisplacement=Math.max(maximumDisplacement,Math.hypot(p.x[k]-p.rest[k],p.x[k+1]-p.rest[k+1],p.x[k+2]-p.rest[k+2]));}
 function contactTriangles(id){const p=patches.get(id),faces=[];if(!p)return faces;for(let t=0;t<p.triangles.length;t++)if(!p.detached[t]&&!p.powdered?.[t]){let normal=[0,0,1],thickness=p.thickness;if(p.adaptive){const k=t*9,u=[0,1,2].map(j=>p.x[k+3+j]-p.x[k+j]),v=[0,1,2].map(j=>p.x[k+6+j]-p.x[k+j]);normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];const l=Math.max(1e-12,Math.hypot(...normal));normal=normal.map(n=>n/l);thickness=p.compression[t].thickness;}faces.push({triangle:t,points:[0,1,2].map(n=>Array.from(p.x.subarray(t*9+n*3,t*9+n*3+3)).map((v,k)=>v+normal[k]*thickness/2)),alive:()=>!p.detached[t]&&!p.powdered?.[t]});}return faces;}
 function sample(){
  const ids=[],offsets=[0],vertices=[],damage=[],detachedFlags=[],cracks=[],crackIds=[];let cracked=0,detached=0,maxDeflection=0,failedAttachments=0,brokenBonds=0,peakAnchorDamage=0,peakBondDamage=0,moving=0;
  const divisions=[],thickness=[],compression=[],cohesive=[],anchorDamage=[],nodeDamage=[],powderedFlags=[],powderDose=[],powderTimes=[];
  for(const p of patches.values()){
   ids.push(p.id);vertices.push(...p.x);damage.push(...p.damage);detachedFlags.push(...p.detached);offsets.push(vertices.length);
   if(adaptive){divisions.push(p.nx,p.ny);thickness.push(...p.compression.map(s=>s.thickness));compression.push(...p.compression.map(s=>s.damage));cohesive.push(...p.cohesive);anchorDamage.push(...p.anchorDamage);nodeDamage.push(...p.nodeDamage);}
   if(powderEnabled){powderedFlags.push(...p.powdered);powderDose.push(...p.powder.map(s=>s.dose));powderTimes.push(...p.powder.map(s=>s.time));}
   let mean=0;for(let k=0;k<p.x.length;k+=3)mean+=(p.x[k]-p.rest[k])*p.normal[0]+(p.x[k+1]-p.rest[k+1])*p.normal[1]+(p.x[k+2]-p.rest[k+2])*p.normal[2];mean/=p.x.length/3;
   for(let k=0;k<p.x.length;k+=3)maxDeflection=Math.max(maxDeflection,Math.abs((p.x[k]-p.rest[k])*p.normal[0]+(p.x[k+1]-p.rest[k+1])*p.normal[1]+(p.x[k+2]-p.rest[k+2])*p.normal[2]-mean));
   for(const bond of p.bonds)if(bond.damage>.3&&!p.powdered?.[bond.a]&&!p.powdered?.[bond.b]){cracked++;for(const side of [-1,1]){crackIds.push(p.id);for(const node of bond.edge)for(let k=0;k<3;k++)cracks.push(p.x[node*3+k]+side*p.normals[bond.b*3+k]*(p.thickness/2+.004));}}
   for(let tri=0;tri<p.detached.length;tri++)if(p.detached[tri]&&!p.powdered?.[tri]){detached++;let speed=0;for(let k=0;k<3;k++)speed+=((p.v[tri*9+k]+p.v[tri*9+3+k]+p.v[tri*9+6+k])/3)**2;if(speed>.01)moving++;}
   for(const a of p.anchors){if(a.damage===1)failedAttachments++;peakAnchorDamage=Math.max(peakAnchorDamage,a.damage);}for(const b of p.bonds){if(b.damage===1)brokenBonds++;peakBondDamage=Math.max(peakBondDamage,b.damage);}
  }
  return {ids:Uint32Array.from(ids),offsets:Uint32Array.from(offsets),vertices:Float32Array.from(vertices),damage:Float32Array.from(damage),detachedFlags:Uint8Array.from(detachedFlags),cracks:Float32Array.from(cracks),crackIds:Uint32Array.from(crackIds),cracked,detached,maxDeflection,limited,failedAttachments,brokenBonds,peakAnchorDamage,peakBondDamage,moving,maxDisplacement:maximumDisplacement,...(adaptive?{topology:'adaptive-prism@2',divisions:Uint8Array.from(divisions),thickness:Float32Array.from(thickness),compression:Float32Array.from(compression),cohesive:Float32Array.from(cohesive),anchorDamage:Float32Array.from(anchorDamage),nodeDamage:Float32Array.from(nodeDamage)}:{}),...(powderEnabled?{powderSchema:POWDER_SCHEMA,powderedFlags:Uint8Array.from(powderedFlags),powderDose:Float32Array.from(powderDose),powderTimes:Float32Array.from(powderTimes),powdered:powderedCount,powderInitialMass,powderMass,solidMass:Math.max(0,powderInitialMass-powderMass)}:{})};
 }
 function bindPoint(id,point){let cached=null;
  function locate(){const p=patches.get(id);if(!p)return null;
   if(p.weldCache!==p.weld){p.weldGroups=new Map();p.weldMass=new Float64Array(p.weld.length);for(let i=0;i<p.weld.length;i++){const r=p.weld[i];if(!p.weldGroups.has(r))p.weldGroups.set(r,[]);p.weldGroups.get(r).push(i);p.weldMass[r]+=p.triangles[Math.floor(i/3)].area*p.thickness/3;}p.weldCache=p.weld;}
   if(cached?.p===p)return cached;
   let best=null,distance=Infinity;
   for(let t=0;t<p.triangles.length;t++){const k=t*9,a=Array.from(p.rest.subarray(k,k+3)),u=[0,1,2].map(j=>p.rest[k+3+j]-a[j]),v=[0,1,2].map(j=>p.rest[k+6+j]-a[j]),w=point.map((n,j)=>n-a[j]),dot=(x,y)=>x.reduce((s,n,j)=>s+n*y[j],0),uu=dot(u,u),uv=dot(u,v),vv=dot(v,v),wu=dot(w,u),wv=dot(w,v),den=Math.max(1e-12,uu*vv-uv*uv),b=(vv*wu-uv*wv)/den,c=(uu*wv-uv*wu)/den,weights=[1-b-c,b,c].map(n=>Math.max(0,n)),sum=weights.reduce((s,n)=>s+n,0);for(let i=0;i<3;i++)weights[i]/=sum;
    const projected=[0,1,2].map(j=>weights.reduce((s,n,i)=>s+n*p.rest[k+i*3+j],0)),d=point.reduce((s,n,j)=>s+(n-projected[j])**2,0);if(d<distance){const unit=a=>{const l=Math.max(1e-12,Math.hypot(...a));return a.map(v=>v/l);},cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],e1=unit(u),e3=unit(cross(u,v)),e2=cross(e3,e1),offset=point.map((n,j)=>n-projected[j]);distance=d;best={p,t,weights,offset:[e1,e2,e3].map(e=>dot(offset,e)),restBasis:[e1,e2,e3]};}
   }cached=best;return best;
  }
  return {position(){const link=locate();if(!link)return null;const {p,t,weights,offset}=link,k=t*9,u=[0,1,2].map(j=>p.x[k+3+j]-p.x[k+j]),v=[0,1,2].map(j=>p.x[k+6+j]-p.x[k+j]),normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],ul=Math.hypot(...u),nl=Math.hypot(...normal),e1=ul>1e-10?u.map(v=>v/ul):link.restBasis[0],e3=nl>1e-10?normal.map(v=>v/nl):link.restBasis[2],e2=[e3[1]*e1[2]-e3[2]*e1[1],e3[2]*e1[0]-e3[0]*e1[2],e3[0]*e1[1]-e3[1]*e1[0]];return [0,1,2].map(j=>weights.reduce((s,n,i)=>s+n*p.x[k+i*3+j],0)+offset[0]*e1[j]+offset[1]*e2[j]+offset[2]*e3[j]);},
   weight(){const link=locate();if(!link)return null;if(link.p.powdered?.[link.t])return 0;return link.weights.reduce((s,n,i)=>s+n*n/Math.max(1e-6,link.p.weldMass[link.p.weld[link.t*3+i]]),0);},
   velocity(){const link=locate();return link?[0,1,2].map(j=>link.weights.reduce((s,n,i)=>s+n*link.p.v[link.t*9+i*3+j],0)):null;},
   damage(){const link=locate();return link?link.p.damage[link.t]:null;},
   exposed(){const link=locate();return link?!!link.p.detached[link.t]||link.p.damage[link.t]>.1:null;},
   removed(){const link=locate();return !!link?.p.powdered?.[link.t];},
   move(n,lambda,dt){const link=locate();if(!link||link.p.powdered?.[link.t])return false;const {p,t,weights}=link;for(let i=0;i<3;i++){const root=p.weld[t*3+i],scale=lambda*weights[i]/Math.max(1e-6,p.weldMass[root]);for(const node of p.weldGroups.get(root)){for(let j=0;j<3;j++){const delta=n[j]*scale,k=node*3+j;p.x[k]+=delta;p.v[k]+=delta/dt;}const proxy=p.debris[Math.floor(node/3)];if(proxy?.sleeping&&Math.abs(scale)>1e-6){proxy.sleeping=false;proxy.justWoke=true;}}}return true;},
  };
 }
 return {eligible:id=>eligible[id],preferred:id=>preferred.has(id),owns:id=>patches.has(id),activate,step,sample,supportAt,contactTriangles,debrisProxies,projectDebrisConstraints,finalizeDebris,maxDisplacement:()=>maximumDisplacement,bindPoint,
  exposed:id=>{const p=patches.get(id);return !!p&&(p.detached.some(Boolean)||p.damage.some(d=>d>.3));},
  steelActive:id=>{const p=patches.get(id);return !!p&&(p.detached.some(Boolean)||p.damage.some(d=>d>.1));},
  drainPowderEvents(){const events=powderQueue;powderQueue=[];return events;},
  powderStats:()=>({powdered:powderedCount,powderInitialMass,powderMass,solidMass:Math.max(0,powderInitialMass-powderMass)}),
  updateBody(id,positions,damage){const p=patches.get(id);if(!p)return false;if(p.powdered?.every(Boolean)){damage[id]=1;return true;}const allDetached=p.detached.every(x=>x===1);for(let j=0;j<3;j++){let mean=0,count=0;for(let i=j;i<p.x.length;i+=3)if(!p.powdered?.[Math.floor(i/9)]&&(allDetached||!p.detached[Math.floor(i/9)])){mean+=p.x[i];count++;}positions[id*3+j]=mean/count;}damage[id]=p.damage.reduce((s,x)=>s+x,0)/p.damage.length;return allDetached;},
 };
}

export function validFractureFrame(f,model){
 const adaptive=f?.topology==='adaptive-prism@2';
 if(!f||!f.ids||f.ids.length>1600||!f.offsets||f.offsets.length!==f.ids.length+1||f.offsets[0]!==0||!f.vertices||f.vertices.length>1600*(adaptive?72:18)*9||f.offsets.at(-1)!==f.vertices.length||!f.damage||f.damage.length!==f.vertices.length/9||!f.detachedFlags||f.detachedFlags.length!==f.damage.length||!f.cracks||f.cracks.length%6!==0||!f.crackIds||f.crackIds.length!==f.cracks.length/6)return false;
 if(new Set(f.ids).size!==f.ids.length||!f.vertices.every(Number.isFinite)||!f.damage.every(v=>Number.isFinite(v)&&v>=0&&v<=1)||!f.detachedFlags.every(v=>v===0||v===1)||!f.cracks.every(Number.isFinite)||![f.cracked,f.detached,f.maxDeflection,f.limited].every(v=>Number.isFinite(v)&&v>=0))return false;
 if(adaptive&&(!f.divisions||f.divisions.length!==f.ids.length*2||!['thickness','compression','cohesive','anchorDamage'].every(key=>f[key]?.length===f.damage.length)||f.nodeDamage?.length!==f.damage.length*3||!f.thickness.every(v=>Number.isFinite(v)&&v>0)||!['compression','cohesive','anchorDamage','nodeDamage'].every(key=>f[key].every(v=>Number.isFinite(v)&&v>=0&&v<=1))))return false;
 if(f.powderSchema){if(!adaptive||f.powderSchema!==POWDER_SCHEMA||!['powderedFlags','powderDose','powderTimes'].every(k=>f[k]?.length===f.damage.length)||!f.powderedFlags.every(v=>v===0||v===1)||!f.powderDose.every(v=>Number.isFinite(v)&&v>=0&&v<=1)||!f.powderTimes.every(Number.isFinite)||!['powdered','powderInitialMass','powderMass','solidMass'].every(k=>Number.isFinite(f[k])&&f[k]>=0)||Math.abs(f.powderMass+f.solidMass-f.powderInitialMass)>1e-5||f.powdered!==f.powderedFlags.reduce((s,v)=>s+v,0))return false;for(let i=0;i<f.powderedFlags.length;i++)if(f.powderedFlags[i]?(f.powderTimes[i]<0||f.powderDose[i]!==1||f.detachedFlags[i]!==1):f.powderTimes[i]!==-1)return false;}
 const eligible=b=>isPanel(b)||(adaptive&&!b.fixed&&['column','stairs'].includes(b.role));
 for(let i=0;i<f.ids.length;i++){const b=model.bodies[f.ids[i]];if(!b||!eligible(b)||f.offsets[i+1]<=f.offsets[i])return false;const dimensions=[...b.size].sort((a,c)=>a-c),expected=adaptive?f.divisions[i*2]*f.divisions[i*2+1]*2:dimensions[1]*dimensions[2]>6?18:8;if(adaptive&&(f.divisions[i*2]<2||f.divisions[i*2]>6||f.divisions[i*2+1]<2||f.divisions[i*2+1]>6))return false;if(f.offsets[i+1]-f.offsets[i]!==expected*9)return false;}
 return f.crackIds.every(id=>model.bodies[id]&&eligible(model.bodies[id]));
}
