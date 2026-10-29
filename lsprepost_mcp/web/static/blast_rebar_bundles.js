/* Simplified K-area-weighted steel constraints. No native FE or gravity balance. */
export const REINFORCED_METHOD='simplified-rc-bundles@1';
export const REBAR_RESPONSE='k-bundles@1';
const length=(a,b)=>Math.hypot(...a.map((v,k)=>v-b[k]));
const area=b=>Math.PI*b.diameter*b.diameter/4;
function resample(points,spacing=.7){
 const out=[[...points[0]]];for(let segment=1;segment<points.length;segment++){const a=points[segment-1],b=points[segment],n=Math.max(1,Math.ceil(length(a,b)/spacing));for(let i=1;i<=n;i++)out.push(a.map((v,k)=>v+(b[k]-v)*i/n));}return out;
}
export function buildBundlePlan(layout){
 const cohorts=new Map(),bundles=[],barBundle=new Int32Array(layout.bars.length).fill(-1);let nodeCount=0,edgeCount=0;
 for(const bar of layout.bars){const axis=bar.axis??(bar.kind==='column_longitudinal'?2:bar.kind==='stair_longitudinal'?1:0),ends=bar.closed||bar.points.length>2?'polyline':bar.points.map(p=>p[axis].toFixed(4)).join(':'),key=[bar.member,bar.kind,bar.layer??0,axis,ends].join(':');if(!cohorts.has(key))cohorts.set(key,{axis,bars:[]});cohorts.get(key).bars.push(bar);}
 for(const {axis,bars} of cohorts.values()){
  const member=layout.members[bars[0].member],normal=member.rules?.[bars[0].kind]?.normalAxis,across=bars[0].kind==='column_stirrup'?2:[0,1,2].find(k=>k!==axis&&k!==normal)??0;
  bars.sort((a,b)=>a.points.reduce((s,p)=>s+p[across],0)/a.points.length-b.points.reduce((s,p)=>s+p[across],0)/b.points.length||a.id-b.id);
  const lanes=Math.min(bars[0].closed?2:4,Math.max(1,Math.ceil(bars.length/8)));
  for(let lane=0;lane<lanes;lane++){const selected=bars.slice(Math.floor(lane*bars.length/lanes),Math.floor((lane+1)*bars.length/lanes));if(!selected.length)continue;const representative=selected[Math.floor(selected.length/2)],points=resample(representative.points),bundle={id:bundles.length,member:member.id,bodyIds:member.bodyIds,barIds:selected.map(b=>b.id),points,nodeOffset:nodeCount,edgeOffset:edgeCount,area:selected.reduce((s,b)=>s+area(b),0),secondMoment:selected.reduce((s,b)=>s+Math.PI*b.diameter**4/64,0),diameter:representative.diameter,representative:representative.id};for(const b of selected)barBundle[b.id]=bundle.id;bundles.push(bundle);nodeCount+=points.length;edgeCount+=points.length-1;}
 }
 return {schema:'equivalent-k-steel-bundles@1',bundles,barBundle,nodeCount,edgeCount,source:layout.source,barCount:layout.bars.length};
}
export function steelSegment(rest,sectionArea,steel){
 return {rest,area:sectionArea,elasticModulus:steel.elasticModulus,yieldStrain:steel.yieldStress/steel.elasticModulus,hardeningRatio:steel.hardeningModulus/steel.elasticModulus,failureStrain:steel.failureStrain,plastic:0,broken:false,maxStrain:0,strain:0,tension:0};
}
export function projectSteelSegment(a,b,state,dt){
 if(state.broken)return 0;const x=a.position(),y=b.position(),distance=length(x,y);if(distance<1e-10)return 0;const normal=y.map((v,k)=>(v-x[k])/distance),strain=(distance-state.rest)/state.rest;state.strain=strain;state.maxStrain=Math.max(state.maxStrain,strain);
 const excess=strain-state.plastic-state.yieldStrain*(1+state.hardeningRatio*state.plastic);if(excess>0)state.plastic+=excess/(1+state.hardeningRatio);
 if(state.plastic>=state.failureStrain){state.broken=true;state.tension=0;return 0;}
 const extension=distance-state.rest*(1+state.plastic),stiffness=state.area*(state.elasticModulus/30e9)*1e5*(extension<0?.035:1),alpha=state.rest/Math.max(1e-12,stiffness*dt*dt),wa=a.weight(normal),wb=b.weight(normal),lambda=extension/Math.max(1e-12,wa+wb+alpha);
 state.tension=Math.max(0,lambda/(dt*dt));a.move(normal,lambda,dt);b.move(normal,-lambda,dt);return Math.abs(lambda);
}
function bend(a,c,rest,stiffness,dt){const x=a.position(),z=c.position(),d=length(x,z);if(d<1e-9||!stiffness)return;const n=z.map((v,k)=>(v-x[k])/d),alpha=1/(stiffness*dt*dt),lambda=(d-rest)/Math.max(1e-12,a.weight(n)+c.weight(n)+alpha);a.move(n,lambda,dt);c.move(n,-lambda,dt);}
export function createRebarBundles(layout,adapter,{iterations=2}={}){
 const cosine=(a,p,b)=>{const u=a.map((v,k)=>v-p[k]),v=b.map((x,k)=>x-p[k]);return u.reduce((s,x,k)=>s+x*v[k],0)/Math.max(1e-12,Math.hypot(...u)*Math.hypot(...v));};
 const plan=buildBundlePlan(layout),states=plan.bundles.map(bundle=>({bundle,refs:bundle.points.map(p=>adapter.bind(bundle.bodyIds,p,bundle)),segments:bundle.points.slice(1).map((p,i)=>steelSegment(length(p,bundle.points[i]),bundle.area,layout.steel)),bends:bundle.points.slice(2).map((p,i)=>length(p,bundle.points[i])),restCos:bundle.points.slice(2).map((p,i)=>cosine(bundle.points[i],bundle.points[i+1],p)),active:false}));
 let maximumStrain=0,feedback=0;
 function step(dt){
  for(const state of states){state.active=adapter.active?.(state.bundle)!==false;if(!state.active)continue;
   for(let iteration=0;iteration<iterations;iteration++){
    for(let i=0;i<state.segments.length;i++)feedback+=projectSteelSegment(state.refs[i],state.refs[i+1],state.segments[i],dt);
    for(let i=0;i<state.bends.length;i++)if(!state.segments[i].broken&&!state.segments[i+1].broken)bend(state.refs[i],state.refs[i+2],state.bends[i],state.bundle.secondMoment*(layout.steel.elasticModulus/30e9)*1e5,dt);
   }
   for(const segment of state.segments)maximumStrain=Math.max(maximumStrain,segment.maxStrain);
  }
 }
 function sample(){
  const positions=new Float32Array(plan.nodeCount*3),strains=new Float32Array(plan.edgeCount),plastic=new Float32Array(plan.edgeCount),failed=new Uint8Array(plan.edgeCount),exposed=new Uint8Array(states.length);let yielded=0,broken=0,bent=0,held=0,active=0;
  for(const state of states){const {bundle,refs,segments}=state,points=refs.map(r=>r.position());for(let i=0;i<points.length;i++)positions.set(points[i],(bundle.nodeOffset+i)*3);if(state.active)active++;
   exposed[bundle.id]=Number(adapter.exposed?.(bundle)||false);
   for(let i=0;i<segments.length;i++){const segment=segments[i],index=bundle.edgeOffset+i;strains[index]=segment.strain;plastic[index]=segment.plastic;failed[index]=Number(segment.broken);if(segment.plastic>1e-6)yielded++;if(segment.broken)broken++;if(segment.tension>1e-5&&exposed[bundle.id]&&!segment.broken)held++;}
   for(let i=1;i<points.length-1;i++)if(Math.abs(cosine(points[i-1],points[i],points[i+1])-state.restCos[i-1])>1e-4){bent++;break;}
  }
  return {schema:'steel-bundle-frame@1',positions,strains,plastic,failed,exposed,bars:layout.bars.length,bundles:states.length,active,yielded,broken,bent,held,maxStrain:maximumStrain,feedback};
 }
 return {plan,step,sample};
}
export function validRebarFrame(frame,plan){return !!frame&&frame.schema==='steel-bundle-frame@1'&&frame.positions?.length===plan.nodeCount*3&&frame.positions.every(Number.isFinite)&&frame.strains?.length===plan.edgeCount&&frame.strains.every(Number.isFinite)&&frame.plastic?.length===plan.edgeCount&&frame.plastic.every(v=>Number.isFinite(v)&&v>=0)&&frame.failed?.length===plan.edgeCount&&frame.failed.every(v=>v===0||v===1)&&frame.exposed?.length===plan.bundles.length&&frame.exposed.every(v=>v===0||v===1)&&['bars','bundles','active','yielded','broken','bent','held','maxStrain','feedback'].every(k=>Number.isFinite(frame[k])&&frame[k]>=0)&&frame.bars===plan.barCount&&frame.bundles===plan.bundles.length&&frame.active<=frame.bundles&&frame.bent<=frame.bundles&&frame.yielded<=plan.edgeCount&&frame.broken<=frame.yielded&&frame.held<=plan.edgeCount;}
