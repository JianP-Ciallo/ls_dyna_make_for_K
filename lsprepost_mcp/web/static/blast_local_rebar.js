/* Local inertial steel rods. Intact regions stay bundled; cracking activates
 * actual local bar paths, not translated copies of a distant representative. */
import {steelSegment} from './blast_rebar_bundles.js';
export const LOCAL_REBAR_RESPONSE='k-bundles@2';
export const LOCAL_REBAR_METHOD='local-crush-rebar@2';
const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
export function rodPoints(points,spacing=.65){const out=[[...points[0]]];for(let i=1;i<points.length;i++){const a=points[i-1],b=points[i],n=Math.max(1,Math.ceil(distance(a,b)/spacing));for(let j=1;j<=n;j++)out.push(a.map((v,k)=>v+(b[k]-v)*j/n));}return out;}
export function localRodPlan(layout){return {schema:'local-k-rods@2',source:layout.source,barCount:layout.bars.length,bars:layout.bars.map(bar=>({id:bar.id,member:bar.member,diameter:bar.diameter,closed:!!bar.closed,area:Math.PI*bar.diameter**2/4,points:rodPoints(bar.points),bodyIds:layout.members[bar.member].bodyIds}))};}
export function createLocalRebar(layout,adapter,{ground=0,contact=null,iterations=3}={}){
 const plan=localRodPlan(layout),states=new Map(),probes=plan.bars.map(bar=>adapter.locateBody?[...new Set(bar.points.map(p=>adapter.locateBody(bar.bodyIds,p)))]:bar.bodyIds),density=(layout.steel.density||7850)/2400;
 let cuts=0,feedback=0,maxStrain=0,time=0,stepNumber=0,releasedByPowder=0;
 function particle(p,mass,ref=null,velocity=[0,0,0]){const n={x:[...p],old:[...p],v:[...velocity],mass,ref,bond:ref?0:1,tip:!ref,born:stepNumber,release:ref?Infinity:time};n.position=()=>n.x;n.weight=()=>1/Math.max(1e-8,n.mass);n.move=(normal,lambda)=>{const im=n.weight();for(let k=0;k<3;k++)n.x[k]+=normal[k]*lambda*im;};return n;}
 function edge(a,b,rest,area,canBreak=true){return {a,b,mass:density*area*rest,rest,state:steelSegment(rest,area,layout.steel),active:true,canBreak};}
 function activate(bar){if(states.has(bar.id))return states.get(bar.id);const source=bar.closed?bar.points.slice(0,-1):bar.points,nodes=source.map(p=>{const ref=adapter.bind(bar.bodyIds,p,bar);return particle(ref.position(),0,ref,ref.velocity?.()||[0,0,0]);}),edges=[],bends=[];
  const count=bar.closed?nodes.length:nodes.length-1;for(let i=0;i<count;i++){const next=(i+1)%nodes.length,e=edge(i,next,distance(source[i],source[next]),bar.area);edges.push(e);nodes[i].mass+=e.mass/2;nodes[next].mass+=e.mass/2;}
  for(let i=bar.closed?0:1;i<(bar.closed?nodes.length:nodes.length-1);i++){const a=(i-1+nodes.length)%nodes.length,c=(i+1)%nodes.length,u=source[a].map((v,k)=>v-source[i][k]),v=source[c].map((n,k)=>n-source[i][k]);bends.push({a,b:i,c,left:(i-1+count)%count,right:i,rest:distance(source[a],source[c]),cos:u.reduce((s,n,k)=>s+n*v[k],0)/Math.max(1e-12,Math.hypot(...u)*Math.hypot(...v))});}
  const state={bar,nodes,edges,originalEdges:edges.length,bends};states.set(bar.id,state);return state;
 }
 function rupture(state,index){const e=state.edges[index];if(!e?.active||!e.canBreak)return;e.active=false;e.state.broken=true;const a=state.nodes[e.a],b=state.nodes[e.b],d=Math.max(1e-10,distance(a.x,b.x)),n=b.x.map((v,k)=>(v-a.x[k])/d),half=e.rest*(1+Math.min(layout.steel.failureStrain,e.state.plastic))/2,span=Math.min(half,Math.max(0,d/2-.002)),mass=e.mass/4;
  a.mass=Math.max(1e-10,a.mass-mass);b.mass=Math.max(1e-10,b.mass-mass);const p=particle(a.x.map((v,k)=>v+n[k]*span),mass,null,a.v),q=particle(b.x.map((v,k)=>v-n[k]*span),mass,null,b.v),ia=state.nodes.length;state.nodes.push(p,q);const left=edge(e.a,ia,half,state.bar.area,half>.04),right=edge(ia+1,e.b,half,state.bar.area,half>.04);left.mass=right.mass=e.mass/2;state.edges.push(left,right);cuts++;if(cuts>20000)throw Error('局部钢筋断裂数量超出演示预算，已停止');
 }
 function attachment(node,dt){if(!node.ref||node.bond>=1)return;if(node.ref.removed?.()){node.bond=1;node.release=time;node.ref=null;releasedByPowder++;return;}const target=node.ref.position(),delta=target.map((v,k)=>v-node.x[k]),d=Math.hypot(...delta);if(d<1e-10)return;const damage=node.ref.damage?.()??0;
  if(damage>.12&&d>.055){node.bond=Math.min(1,node.bond+dt*Math.max(0,d/.055-1)*(4+damage*12));if(node.bond===1){node.release=time;return;}}
  const normal=delta.map(v=>v/d),stiffness=18000*Math.max(.015,1-damage*.97)*(1-node.bond)**2,alpha=1/Math.max(1e-10,stiffness*dt*dt),lambda=d/(node.weight()+node.ref.weight(normal)+alpha);node.move(normal,lambda);node.ref.move(normal,-lambda,dt);feedback+=Math.abs(lambda);
 }
 function bend(state,bend,dt){if(!state.edges[bend.left]?.active||!state.edges[bend.right]?.active)return;const a=state.nodes[bend.a],c=state.nodes[bend.c],d=distance(a.x,c.x);if(d<1e-10)return;const n=c.x.map((v,k)=>(v-a.x[k])/d),I=Math.PI*state.bar.diameter**4/64,k=I*(layout.steel.elasticModulus/30e9)*2e6,lambda=(d-bend.rest)/(a.weight()+c.weight()+1/Math.max(1e-12,k*dt*dt));a.move(n,lambda);c.move(n,-lambda);}
 function elasticEdge(state,e,dt){const a=state.nodes[e.a],b=state.nodes[e.b],d=distance(a.x,b.x);if(d<1e-10)return;const normal=b.x.map((v,k)=>(v-a.x[k])/d),C=d-e.rest*(1+e.state.plastic),stiffness=e.state.area*(e.state.elasticModulus/30e9)*1e5*(C<0?.035:1),alpha=e.rest/Math.max(1e-12,stiffness*dt*dt),delta=(C-alpha*(e.lambda||0))/(a.weight()+b.weight()+alpha),yieldLimit=(layout.steel.yieldStress+layout.steel.hardeningModulus*e.state.plastic)/30e9*e.state.area*1e5*dt*dt,next=Math.max(-Infinity,Math.min(yieldLimit,(e.lambda||0)+delta)),lambda=next-(e.lambda||0);e.lambda=next;e.yieldLimit=yieldLimit;a.move(normal,lambda);b.move(normal,-lambda);}
 function groundContact(node,radius,dt){const velocity=node.x.map((v,k)=>(v-node.old[k])/dt);if(node.bond>=1&&contact&&time-node.release>.03)contact(node.x,node.old,velocity,radius,-1);if(node.x[2]<ground+radius){node.x[2]=ground+radius;velocity[2]=Math.max(0,-velocity[2]*.05);velocity[0]*=.8;velocity[1]*=.8;}node.contactPosition=[...node.x];node.v=velocity;}
 function step(dt){time+=dt;stepNumber++;
  for(const bar of plan.bars)if(!states.has(bar.id)&&adapter.barActive?.(probes[bar.id],bar)!==false)activate(bar);
  for(const state of states.values()){
   for(const node of state.nodes){node.old=[...node.x];node.v[2]-=9.80665*dt;for(let k=0;k<3;k++)node.x[k]+=node.v[k]*dt;}
   for(const edge of state.edges)edge.lambda=0;
   for(let iteration=0;iteration<iterations;iteration++){
    for(const node of state.nodes)attachment(node,dt);
    for(const e of state.edges)if(e.active)elasticEdge(state,e,dt);
    for(const b of state.bends)bend(state,b,dt);
   }
   for(const node of state.nodes)groundContact(node,state.bar.diameter/2,dt);
   for(let i=0;i<state.edges.length;i++){const e=state.edges[i];if(!e.active)continue;const a=state.nodes[e.a],b=state.nodes[e.b],d=distance(a.x,b.x),strain=(d-e.rest)/e.rest;e.state.strain=strain;if(e.lambda>=e.yieldLimit*.999){const excess=strain-e.state.plastic-e.state.yieldStrain;e.state.plastic+=Math.max(0,excess)/(1+e.state.hardeningRatio);}if(e.canBreak&&(e.state.plastic>=layout.steel.failureStrain||strain>layout.steel.failureStrain+.02))rupture(state,i);else if(!e.canBreak&&strain>layout.steel.failureStrain){const n=b.x.map((v,k)=>(v-a.x[k])/Math.max(1e-12,d)),lambda=(d-e.rest*(1+layout.steel.failureStrain))/(a.weight()+b.weight());a.move(n,lambda);b.move(n,-lambda);}else maxStrain=Math.max(maxStrain,strain);}
   for(const node of state.nodes){if(!(node.tip&&node.born===stepNumber))for(let k=0;k<3;k++)node.v[k]=(node.v[k]+(node.x[k]-node.contactPosition[k])/dt)*Math.exp(-.06*dt);if(node.x[2]<ground+state.bar.diameter/2){node.x[2]=ground+state.bar.diameter/2;node.v[2]=Math.max(0,node.v[2]);node.v[0]*=.85;node.v[1]*=.85;}}
   for(const node of state.nodes)if(!node.x.every(Number.isFinite)||node.x.some(v=>Math.abs(v)>3000))throw Error('局部钢筋运动超出有限演示范围，已停止');
  }
 }
 function sample(){const ids=[],offsets=[0],positions=[],edgeOffsets=[0],edges=[],plastic=[],restLengths=[],free=[];let yielded=0,bent=0,held=0,activeEdges=0;
  for(const state of states.values()){ids.push(state.bar.id);const base=positions.length/3;for(const n of state.nodes){positions.push(...n.x);free.push(Number(n.bond>=1));}offsets.push(positions.length);
   for(const e of state.edges)if(e.active){edges.push(base+e.a,base+e.b);plastic.push(e.state.plastic);restLengths.push(e.rest);if(e.state.plastic>1e-6)yielded++;activeEdges++;}edgeOffsets.push(edges.length);
   if(state.nodes.some(n=>n.ref&&n.bond<1&&(n.ref.exposed?.()||n.ref.damage?.()>.25)))held++;
   for(const bend of state.bends){if(!state.edges[bend.left]?.active||!state.edges[bend.right]?.active)continue;const a=state.nodes[bend.a].x,b=state.nodes[bend.b].x,c=state.nodes[bend.c].x,ab=a.map((v,k)=>v-b[k]),cb=c.map((v,k)=>v-b[k]);if(Math.abs(ab.reduce((s,v,k)=>s+v*cb[k],0)/Math.max(1e-10,Math.hypot(...ab)*Math.hypot(...cb))-bend.cos)>.003){bent++;break;}}
  }
  return {schema:'local-steel-frame@2',ids:Uint32Array.from(ids),offsets:Uint32Array.from(offsets),positions:Float32Array.from(positions),edgeOffsets:Uint32Array.from(edgeOffsets),edges:Uint32Array.from(edges),plastic:Float32Array.from(plastic),restLengths:Float32Array.from(restLengths),free:Uint8Array.from(free),bars:layout.bars.length,active:ids.length,bundles:ids.length,yielded,broken:cuts,cuts,bent,held,maxStrain,feedback,activeEdges,...(releasedByPowder?{releasedByPowder}:{}),mass:[...states.values()].reduce((s,state)=>s+state.nodes.reduce((sum,n)=>sum+n.mass,0),0)};
 }
 return {plan,step,sample,releaseAll(velocity=null){for(const state of states.values())for(const node of state.nodes){node.bond=1;node.release=time;if(velocity)node.v=[...velocity];}},forceBreak(barId,index){const state=states.get(barId)||activate(plan.bars[barId]);rupture(state,index);}};
}
export function validLocalRebarFrame(f,layout){
 if(!f||f.schema!=='local-steel-frame@2'||!f.ids||new Set(f.ids).size!==f.ids.length||!f.ids.every(id=>id<layout.bars.length)||f.offsets?.length!==f.ids.length+1||f.edgeOffsets?.length!==f.ids.length+1||f.offsets[0]!==0||f.edgeOffsets[0]!==0||f.offsets.at(-1)!==f.positions?.length||f.edgeOffsets.at(-1)!==f.edges?.length||f.positions.length%3||f.edges.length%2||f.plastic?.length!==f.edges.length/2||f.restLengths?.length!==f.plastic.length||f.free?.length!==f.positions.length/3)return false;
 for(let i=0;i<f.ids.length;i++){const start=f.offsets[i]/3,end=f.offsets[i+1]/3;if(start%1||end%1||end<start||f.edgeOffsets[i]%2||f.edgeOffsets[i+1]%2||f.edgeOffsets[i+1]<f.edgeOffsets[i])return false;for(let j=f.edgeOffsets[i];j<f.edgeOffsets[i+1];j++)if(f.edges[j]<start||f.edges[j]>=end)return false;}
 return f.positions.length<=2000000&&f.positions.every(Number.isFinite)&&f.edges.every(i=>i<f.positions.length/3)&&f.plastic.every(v=>Number.isFinite(v)&&v>=0)&&f.restLengths.every(v=>Number.isFinite(v)&&v>0)&&f.free.every(v=>v===0||v===1)&&['bars','active','yielded','broken','cuts','bent','held','maxStrain','feedback'].every(k=>Number.isFinite(f[k])&&f[k]>=0)&&f.bars===layout.bars.length;
}
