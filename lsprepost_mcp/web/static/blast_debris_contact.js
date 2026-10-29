/* Small convex-contact solver for demonstration debris. Unit relative density;
 * no structural capacity is used as a mass, and no rendered rubble is invented.
 */
const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
const unit=a=>{const d=Math.hypot(...a);return d>1e-10?a.map(v=>v/d):null;};
const mul=(a,v)=>[a[0]*v[0]+a[1]*v[1]+a[2]*v[2],a[3]*v[0]+a[4]*v[1]+a[5]*v[2],a[6]*v[0]+a[7]*v[1]+a[8]*v[2]];
function rotate(p,q){const [x,y,z,w]=q,[a,b,c]=p,tx=2*(y*c-z*b),ty=2*(z*a-x*c),tz=2*(x*b-y*a);return [a+w*tx+y*tz-z*ty,b+w*ty+z*tx-x*tz,c+w*tz+x*ty-y*tx];}
function inverse(a){const c=[a[4]*a[8]-a[5]*a[7],a[2]*a[7]-a[1]*a[8],a[1]*a[5]-a[2]*a[4],a[5]*a[6]-a[3]*a[8],a[0]*a[8]-a[2]*a[6],a[2]*a[3]-a[0]*a[5],a[3]*a[7]-a[4]*a[6],a[1]*a[6]-a[0]*a[7],a[0]*a[4]-a[1]*a[3]],d=a[0]*c[0]+a[1]*c[3]+a[2]*c[6];return Math.abs(d)>1e-22?c.map(v=>v/d):[0,0,0,0,0,0,0,0,0];}
function bounds(p){
 p.min=[Infinity,Infinity,Infinity];p.max=[-Infinity,-Infinity,-Infinity];
 for(let i=0;i<p.vertices.length;i+=3)for(let k=0;k<3;k++){p.min[k]=Math.min(p.min[k],p.vertices[i+k]);p.max[k]=Math.max(p.max[k],p.vertices[i+k]);}
 p.motion=sub(p.center,p.oldCenter);p.radius=Math.max(.02,Math.hypot(...sub(p.max,p.min))/2);
}
export function triangleDebris(value){
 const p={...value,kind:'triangle',inverseMass:1/Math.max(1e-5,value.mass),vertices:new Float64Array(18)};
 p.refresh=()=>{
  const x=p.positions;p.center=[0,1,2].map(k=>(x[k]+x[k+3]+x[k+6])/3);p.oldCenter=[0,1,2].map(k=>(p.previous[k]+p.previous[k+3]+p.previous[k+6])/3);
  const ab=[0,1,2].map(k=>x[k+3]-x[k]),ac=[0,1,2].map(k=>x[k+6]-x[k]),normal=unit(cross(ab,ac))||[0,0,1];p.edges=[unit(ab),unit(sub(ac,ab)),unit(ac),normal].filter(Boolean);p.axes=[normal,...p.edges.slice(0,3).map(e=>unit(cross(e,normal))).filter(Boolean)];
  const inertia=Array(9).fill(0),nodeMass=1/(p.inverseMass*3);
  for(let i=0;i<3;i++){const r=[0,1,2].map(k=>x[i*3+k]-p.center[k]),rr=dot(r,r);for(let a=0;a<3;a++)for(let b=0;b<3;b++)inertia[a*3+b]+=nodeMass*((a===b?rr:0)-r[a]*r[b]);for(let side=0;side<2;side++)for(let k=0;k<3;k++)p.vertices[(i+side*3)*3+k]=x[i*3+k]+(side?-.5:.5)*p.thickness*normal[k];}
  const fitInverse=inverse(inertia);for(let k=0;k<3;k++)inertia[k*3+k]+=nodeMass*p.thickness**2/4;p.inverseInertia=inverse(inertia);bounds(p);
  p.linear=[0,1,2].map(k=>(p.velocities[k]+p.velocities[k+3]+p.velocities[k+6])/3);const moment=[0,0,0];for(let i=0;i<3;i++){const r=[0,1,2].map(k=>x[i*3+k]-p.center[k]),dv=[0,1,2].map(k=>p.velocities[i*3+k]-p.linear[k]),term=cross(r,dv);for(let k=0;k<3;k++)moment[k]+=term[k]*nodeMass;}p.angular=mul(fitInverse,moment);
 };
 p.translate=d=>{for(let i=0;i<9;i++)p.positions[i]+=d[i%3];for(let i=0;i<18;i++)p.vertices[i]+=d[i%3];for(let k=0;k<3;k++){p.center[k]+=d[k];p.min[k]+=d[k];p.max[k]+=d[k];p.motion[k]+=d[k];}};
 p.velocityAt=point=>{const spin=cross(p.angular,sub(point,p.center));return p.linear.map((v,k)=>v+spin[k]);};
 p.impulse=(j,point)=>{const dw=mul(p.inverseInertia,cross(sub(point,p.center),j));for(let k=0;k<3;k++){p.linear[k]+=j[k]*p.inverseMass;p.angular[k]+=dw[k];}for(let i=0;i<3;i++){const spin=cross(dw,[0,1,2].map(k=>p.positions[i*3+k]-p.center[k]));for(let k=0;k<3;k++)p.velocities[i*3+k]+=j[k]*p.inverseMass+spin[k];}};
 p.speed=()=>Math.max(...[0,1,2].map(i=>Math.hypot(...p.velocities.subarray(i*3,i*3+3))));p.refresh();return p;
}
export function boxDebris(value){
 const p={...value,kind:'box',inverseMass:1/Math.max(1e-5,value.mass),vertices:new Float64Array(24)};
 p.refresh=()=>{
  p.center=Array.from(p.position);p.oldCenter=Array.from(p.previous);p.axes=[[1,0,0],[0,1,0],[0,0,1]].map(v=>rotate(v,p.rotation));p.edges=p.axes;
  for(let i=0;i<8;i++){const local=p.size.map((s,k)=>(i&(1<<k)?1:-1)*s/2),world=rotate(local,p.rotation);for(let k=0;k<3;k++)p.vertices[i*3+k]=p.position[k]+world[k];}
  const diagonal=[0,1,2].map(k=>12*p.inverseMass/(p.size[(k+1)%3]**2+p.size[(k+2)%3]**2));p.inverseInertia=Array(9).fill(0);for(let a=0;a<3;a++)for(let b=0;b<3;b++)for(let k=0;k<3;k++)p.inverseInertia[a*3+b]+=diagonal[k]*p.axes[k][a]*p.axes[k][b];bounds(p);
 };
 p.translate=d=>{for(let k=0;k<3;k++){p.position[k]+=d[k];p.center[k]+=d[k];p.min[k]+=d[k];p.max[k]+=d[k];p.motion[k]+=d[k];}for(let i=0;i<24;i++)p.vertices[i]+=d[i%3];};
 p.velocityAt=point=>{const spin=cross(p.angularVelocity,sub(point,p.center));return Array.from(p.velocity,(v,k)=>v+spin[k]);};
 p.impulse=(j,point)=>{const dw=mul(p.inverseInertia,cross(sub(point,p.center),j));for(let k=0;k<3;k++){p.velocity[k]+=j[k]*p.inverseMass;p.angularVelocity[k]+=dw[k];}};
 p.speed=()=>Math.hypot(...p.velocity)+Math.hypot(...p.angularVelocity)*p.radius;p.refresh();return p;
}
function project(p,n){let min=Infinity,max=-Infinity;for(let i=0;i<p.vertices.length;i+=3){const v=p.vertices[i]*n[0]+p.vertices[i+1]*n[1]+p.vertices[i+2]*n[2];min=Math.min(min,v);max=Math.max(max,v);}return [min,max];}
function support(p,n){let best=-Infinity,count=0,sum=[0,0,0];for(let i=0;i<p.vertices.length;i+=3){const d=p.vertices[i]*n[0]+p.vertices[i+1]*n[1]+p.vertices[i+2]*n[2];if(d>best+1e-6){best=d;count=0;sum=[0,0,0];}if(d>=best-1e-6){count++;for(let k=0;k<3;k++)sum[k]+=p.vertices[i+k];}}return sum.map(v=>v/count);}
function closestTriangle(p,a,b,c){
 const ab=sub(b,a),ac=sub(c,a),ap=sub(p,a),d1=dot(ab,ap),d2=dot(ac,ap);if(d1<=0&&d2<=0)return a;
 const bp=sub(p,b),d3=dot(ab,bp),d4=dot(ac,bp);if(d3>=0&&d4<=d3)return b;
 const vc=d1*d4-d3*d2;if(vc<=0&&d1>=0&&d3<=0){const v=d1/(d1-d3);return a.map((x,k)=>x+v*ab[k]);}
 const cp=sub(p,c),d5=dot(ab,cp),d6=dot(ac,cp);if(d6>=0&&d5<=d6)return c;
 const vb=d5*d2-d1*d6;if(vb<=0&&d2>=0&&d6<=0){const w=d2/(d2-d6);return a.map((x,k)=>x+w*ac[k]);}
 const va=d3*d6-d5*d4;if(va<=0&&d4-d3>=0&&d5-d6>=0){const w=(d4-d3)/(d4-d3+d5-d6);return b.map((x,k)=>x+w*(c[k]-x));}
 const den=va+vb+vc;if(Math.abs(den)<1e-15)return a;const v=vb/den,w=vc/den;return a.map((x,k)=>x+ab[k]*v+ac[k]*w);
}
function closestEdges(a,b,c,d){
 const u=sub(b,a),v=sub(d,c),r=sub(a,c),aa=dot(u,u),ee=dot(v,v),f=dot(v,r);let s=0,t=0;
 if(aa<1e-15&&ee<1e-15)return [a,c];
 if(aa<1e-15)t=Math.max(0,Math.min(1,f/ee));else{const cc=dot(u,r);if(ee<1e-15)s=Math.max(0,Math.min(1,-cc/aa));else{const bb=dot(u,v),den=aa*ee-bb*bb;if(den>1e-15)s=Math.max(0,Math.min(1,(bb*f-cc*ee)/den));t=(bb*s+f)/ee;if(t<0){t=0;s=Math.max(0,Math.min(1,-cc/aa));}else if(t>1){t=1;s=Math.max(0,Math.min(1,(bb-cc)/aa));}}}
 return [a.map((x,k)=>x+s*u[k]),c.map((x,k)=>x+t*v[k])];
}
// Rounded edge contact is used only at low speed; intersecting middle surfaces
// and fast trajectories retain the swept convex test below.
function slowTriangleContact(a,b){
 const aa=[0,3,6].map(i=>Array.from(a.positions.subarray(i,i+3))),bb=[0,3,6].map(i=>Array.from(b.positions.subarray(i,i+3))),radius=(a.thickness+b.thickness)/2+.0008;
 const da=bb.map(p=>dot(sub(p,aa[0]),a.axes[0])),db=aa.map(p=>dot(sub(p,bb[0]),b.axes[0]));
 if(Math.min(...da)>radius||Math.max(...da)<-radius||Math.min(...db)>radius||Math.max(...db)<-radius)return null;
 if(Math.min(...da)<=0&&Math.max(...da)>=0&&Math.min(...db)<=0&&Math.max(...db)>=0)return undefined;
 let best=Infinity,first=[0,0,0],second=[0,0,0],count=0;
 const candidate=(p,q)=>{const delta=sub(p,q),distance=dot(delta,delta);if(distance<best-1e-10){best=distance;first=[0,0,0];second=[0,0,0];count=0;}if(distance<=best+1e-10){count++;for(let k=0;k<3;k++){first[k]+=p[k];second[k]+=q[k];}}};
 for(const p of aa)candidate(p,closestTriangle(p,...bb));for(const q of bb)candidate(closestTriangle(q,...aa),q);
 const lower=Math.max(Math.min(...da)>0?Math.min(...da):Math.max(...da)<0?-Math.max(...da):0,Math.min(...db)>0?Math.min(...db):Math.max(...db)<0?-Math.max(...db):0)**2;
 if(best>lower+1e-10)for(let i=0;i<3;i++)for(let j=0;j<3;j++){const [p,q]=closestEdges(aa[i],aa[(i+1)%3],bb[j],bb[(j+1)%3]);candidate(p,q);}
 if(best>radius*radius)return null;if(best<1e-15)return undefined;first=first.map(v=>v/count);second=second.map(v=>v/count);const distance=Math.sqrt(best);return {normal:unit(sub(first,second)),depth:radius-distance,point:first.map((v,k)=>(v+second[k])/2)};
}
function contact(a,b){
 if(a.kind==='triangle'&&b.kind==='triangle'&&Math.hypot(...sub(a.motion,b.motion))<Math.min(a.thickness,b.thickness)*.3&&Math.max(a.speed(),b.speed())/60<Math.min(a.thickness,b.thickness)*.3){const fast=slowTriangleContact(a,b);if(fast!==undefined)return fast;}
 let depth=Infinity,normal=null,separated=false,enter=0,leave=1,entryAxis=null;const skin=.0008;
 function axisTest(axis){
  let loA=Infinity,hiA=-Infinity,loB=Infinity,hiB=-Infinity;const ax=axis[0],ay=axis[1],az=axis[2];for(let i=0;i<a.vertices.length;i+=3){const p=a.vertices[i]*ax+a.vertices[i+1]*ay+a.vertices[i+2]*az;if(p<loA)loA=p;if(p>hiA)hiA=p;}for(let i=0;i<b.vertices.length;i+=3){const p=b.vertices[i]*ax+b.vertices[i+1]*ay+b.vertices[i+2]*az;if(p<loB)loB=p;if(p>hiB)hiB=p;}const overlap=Math.min(hiA-loB,hiB-loA),da=dot(a.motion,axis),db=dot(b.motion,axis),relative=da-db;
  if(overlap<0)separated=true;
  if(overlap<depth){depth=overlap;normal=axis.map(v=>v*(hiB-loA<hiA-loB?1:-1));}
  const oldLoA=loA-da,oldHiA=hiA-da,oldLoB=loB-db,oldHiB=hiB-db;
  if(Math.abs(relative)<1e-10){if(oldHiA<oldLoB-skin||oldHiB<oldLoA-skin)return false;}
  else {let t0=(oldLoB-oldHiA)/relative,t1=(oldHiB-oldLoA)/relative;if(t0>t1)[t0,t1]=[t1,t0];if(t0>enter){enter=t0;entryAxis=axis.map(v=>v*(relative>0?-1:1));}leave=Math.min(leave,t1);if(enter>leave+1e-7)return false;}
  return true;
 }
 for(const axis of a.axes)if(!axisTest(axis))return null;for(const axis of b.axes)if(!axisTest(axis))return null;
 if(!(a.kind==='triangle'&&b.kind==='triangle'&&Math.abs(dot(a.axes[0],b.axes[0]))>1-1e-8))for(const u of a.edges)for(const v of b.edges){const cx=u[1]*v[2]-u[2]*v[1],cy=u[2]*v[0]-u[0]*v[2],cz=u[0]*v[1]-u[1]*v[0],length=Math.sqrt(cx*cx+cy*cy+cz*cz);if(length>1e-10&&!axisTest([cx/length,cy/length,cz/length]))return null;}
 if(separated&&(!entryAxis||enter<0||enter>1||leave<0))return null;
 if(entryAxis&&enter>1e-7&&enter<=1&&leave>=0){normal=entryAxis;depth=Math.max(0,-dot(sub(a.motion,b.motion),normal)*(1-enter));}
 if(depth<-.0001)return null;
 const sa=support(a,normal.map(v=>-v)),sb=support(b,normal),point=sa.map((v,k)=>(v+sb[k])/2);
 return {normal,depth:Math.max(0,depth)+skin,point};
}
function effective(p,point,n){const r=sub(point,p.center),term=cross(r,n);return p.inverseMass+dot(term,mul(p.inverseInertia,term));}
function impulse(a,b,c){
 const n=c.normal,relative=sub(a.velocityAt(c.point),b.velocityAt(c.point)),vn=dot(relative,n);if(vn>=0)return;
 const denom=effective(a,c.point,n)+effective(b,c.point,n),j=-(1+(vn<-.5?.06:0))*vn/denom,normalImpulse=n.map(v=>v*j);a.impulse(normalImpulse,c.point);b.impulse(normalImpulse.map(v=>-v),c.point);
 const after=sub(a.velocityAt(c.point),b.velocityAt(c.point)),tangent=after.map((v,k)=>v-dot(after,n)*n[k]),speed=Math.hypot(...tangent);
 if(speed>1e-10){const direction=tangent.map(v=>v/speed),amount=Math.min(.6*j,speed/(effective(a,c.point,direction)+effective(b,c.point,direction))),friction=direction.map(v=>-v*amount);a.impulse(friction,c.point);b.impulse(friction.map(v=>-v),c.point);}
}
export function createDebrisSystem({iterations=2,interval=0,groundLevel=()=>0,projectConstraints=rows=>rows,allowRetirement=false}={}){
 let active=[],lastPairs=[],contacts=0,pairs=0,maxCandidates=0,maxPenetration=0,settled=0,pileHeight=0,grounded=0;
 const quietTicks=new Map();
 const previousCenters=new Map();let elapsed=0,pairChecks=0,maxBucket=0,maxSolveMs=0;
 let restingPairs=[];let groups=new Map(),sleepContacts=new Map();
 function wake(p){const queue=[p],seen=new Set();for(let i=0;i<queue.length;i++){const current=queue[i];if(seen.has(current))continue;seen.add(current);for(const member of groups.get(current.sleepGroup||current)||[current]){member.sleeping=false;quietTicks.set(member,0);if(!seen.has(member))queue.push(member);}for(const other of sleepContacts.get(current)||[])if(!seen.has(other))queue.push(other);}}
 function refresh(p){p.refresh();if(previousCenters.has(p)){p.oldCenter=previousCenters.get(p);p.motion=sub(p.center,p.oldCenter);}}
 function candidates(rows,budget){
  const cells=new Map(),result=[],seen=new Set(),cellSize=1.5;let visits=0,cellVisits=0;
  for(let i=0;i<rows.length;i++){const p=rows[i],lo=p.min.map((v,k)=>Math.floor((Math.min(v,v-p.motion[k])-.002)/cellSize)),hi=p.max.map((v,k)=>Math.floor((Math.max(v,v-p.motion[k])+.002)/cellSize));
   if((hi[0]-lo[0]+1)*(hi[1]-lo[1]+1)*(hi[2]-lo[2]+1)>12000)throw Error('碎片扫掠范围超出演示接触预算，已停止。');
   for(let x=lo[0];x<=hi[0];x++)for(let y=lo[1];y<=hi[1];y++)for(let z=lo[2];z<=hi[2];z++){if(++cellVisits%1024===0)budget();if(cellVisits>500000)throw Error('碎片分桶访问超出演示预算，已停止。');const key=x+':'+y+':'+z,list=cells.get(key)||[];maxBucket=Math.max(maxBucket,list.length+1);if(list.length>=512)throw Error('碎片密集桶超出演示预算，已停止；未跳过碰撞。');for(const j of list){if(++visits%1024===0)budget();if(visits>4000000)throw Error('碎片原始访问超出演示预算，已停止；未跳过碰撞。');const other=rows[j],pair=j*rows.length+i;if(p.sleeping&&other.sleeping||seen.has(pair))continue;seen.add(pair);pairChecks++;if(seen.size>600000)throw Error('碎片原始配对超出演示预算，已停止；未跳过碰撞。');if(p.exclude?.(other)||other.exclude?.(p))continue;let disjoint=false;for(let k=0;k<3;k++)if(Math.max(p.max[k],p.max[k]-p.motion[k])+.002<Math.min(other.min[k],other.min[k]-other.motion[k])||Math.max(other.max[k],other.max[k]-other.motion[k])+.002<Math.min(p.min[k],p.min[k]-p.motion[k])){disjoint=true;break;}if(disjoint)continue;result.push([other,p]);if(result.length>180000)throw Error('碎片候选碰撞超过演示预算，已停止；未跳过碰撞。');}list.push(i);cells.set(key,list);}
  }
  result.sort((a,b)=>Math.min(a[0].center[2],a[1].center[2])-Math.min(b[0].center[2],b[1].center[2]));return result;
 }
 function solve(rows,dt,environment=()=>{}){
  active=rows;if(allowRetirement){const live=new Set(rows);let retired=false;for(const [a,b]of restingPairs){if(!live.has(a)&&live.has(b))wake(b);if(!live.has(b)&&live.has(a))wake(a);}restingPairs=restingPairs.filter(([a,b])=>live.has(a)&&live.has(b));for(const p of previousCenters.keys())if(!live.has(p)){previousCenters.delete(p);quietTicks.delete(p);retired=true;}lastPairs=lastPairs.filter(([a,b])=>live.has(a)&&live.has(b));if(retired)elapsed=Math.max(elapsed,interval);}if(!rows.length){settled=grounded=0;pileHeight=0;return;}
  for(const p of rows)if(!previousCenters.has(p))previousCenters.set(p,p.oldCenter.slice());elapsed+=dt;if(elapsed+1e-9<interval)return;elapsed=interval?elapsed%interval:0;
  const started=performance.now(),budget=()=>{if(performance.now()-started>1000)throw Error('碎片单步接触超出演示时间预算，已停止；未跳过碰撞。');};groups=new Map();for(const p of rows){const key=p.sleepGroup||p;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p);}sleepContacts=new Map();for(const [a,b] of restingPairs){if(!sleepContacts.has(a))sleepContacts.set(a,[]);if(!sleepContacts.has(b))sleepContacts.set(b,[]);sleepContacts.get(a).push(b);sleepContacts.get(b).push(a);}for(let i=0;i<rows.length;i++){if(i%128===0)budget();const p=rows[i];refresh(p);if(p.justWoke||p.sleeping&&(Math.hypot(...p.motion)>.003||p.speed()>.2)){wake(p);p.justWoke=false;}}lastPairs=restingPairs.filter(([a,b])=>a.sleeping&&b.sleeping);const possible=candidates(rows,budget);for(const pair of lastPairs)possible.push(pair);budget();pairs+=possible.length;maxCandidates=Math.max(maxCandidates,possible.length);const touchedPairs=new Set();
  for(let pass=0;pass<iterations;pass++){
   const moved=new Set();
   for(let i=0;i<possible.length;i++){if(i%256===0)budget();const [a,b]=possible[i];if(a.sleeping&&b.sleeping)continue;const c=contact(a,b);if(!c)continue;if(a.sleeping)wake(a);if(b.sleeping)wake(b);maxPenetration=Math.max(maxPenetration,c.depth);if(!touchedPairs.has(i)){touchedPairs.add(i);contacts++;lastPairs.push([a,b]);}
    const sum=a.inverseMass+b.inverseMass,depth=Math.max(0,c.depth-.0002);
    a.translate(c.normal.map(v=>v*depth*a.inverseMass/sum));b.translate(c.normal.map(v=>-v*depth*b.inverseMass/sum));impulse(a,b,c);moved.add(a);moved.add(b);
   }
   const affected=projectConstraints(moved)||moved;budget();for(const p of affected){environment(p);refresh(p);}budget();
   if(!moved.size)break;
  }
  for(const p of rows)if(!p.positions?.every(Number.isFinite)&&p.kind==='triangle'||!p.center.every(v=>Number.isFinite(v)&&Math.abs(v)<5000))throw Error('碎片接触状态超出有限范围，已停止。');
  const quiet=new Set(rows.filter(p=>p.speed()<.13)),support=new Map(),supported=new Set();for(const p of quiet){const gap=p.min[2]-groundLevel(p.center),s=p.support?.()||{supported:gap>=-.015&&gap<.004,grounded:gap>=-.015&&gap<.004};support.set(p,s);if(s.supported)supported.add(p);}
  let propagated=true;while(propagated){propagated=false;for(const [a,b] of lastPairs)if(quiet.has(a)&&quiet.has(b)){if(supported.has(a)&&!supported.has(b)){supported.add(b);propagated=true;}else if(supported.has(b)&&!supported.has(a)){supported.add(a);propagated=true;}}}
  for(const p of rows)quietTicks.set(p,supported.has(p)?(quietTicks.get(p)||0)+1:0);const stable=new Set([...supported].filter(p=>quietTicks.get(p)>=12));settled=stable.size;const resting=new Set([...stable].filter(p=>support.get(p)?.grounded));grounded=resting.size;
  let changed=true;while(changed){changed=false;for(const [a,b] of lastPairs)if(stable.has(a)&&stable.has(b)){if(resting.has(a)&&!resting.has(b)){resting.add(b);changed=true;}else if(resting.has(b)&&!resting.has(a)){resting.add(a);changed=true;}}}
  pileHeight=0;for(const p of resting)pileHeight=Math.max(pileHeight,p.max[2]-groundLevel(p.center));
  for(const members of groups.values()){if(members.some(p=>p.sleeping&&!supported.has(p))){wake(members[0]);continue;}if(members.every(p=>stable.has(p)&&quietTicks.get(p)>=30))for(const p of members){p.sleeping=true;if(p.kind==='triangle'){p.velocities.fill(0);p.linear=[0,0,0];p.angular=[0,0,0];}else{p.velocity.fill(0);p.angularVelocity.fill(0);}}}
  restingPairs=lastPairs.filter(([a,b])=>a.sleeping&&b.sleeping);
  for(const p of rows)previousCenters.set(p,p.center.slice());budget();maxSolveMs=Math.max(maxSolveMs,performance.now()-started);
 }
 function sample(){return {fragments:active.length,contacts,pairs,pairChecks,maxCandidates,maxBucket,maxSolveMs,maxPenetration,settled,sleeping:active.filter(p=>p.sleeping).length,grounded,pileHeight,limited:0};}
 return {solve,sample};
}
export function validDebrisFrame(f){return !!f&&['fragments','contacts','pairs','pairChecks','maxCandidates','maxBucket','maxSolveMs','maxPenetration','settled','sleeping','grounded','pileHeight','limited'].every(k=>Number.isFinite(f[k])&&f[k]>=0)&&f.settled<=f.fragments&&f.sleeping<=f.fragments&&f.grounded<=f.settled&&f.limited===0;}
