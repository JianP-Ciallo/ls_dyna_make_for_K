/* K-derived member rules mapped to the retained display geometry, without mutation. */
import {K_REBAR_CATALOG as catalog} from './blast_rebar_catalog.js';
export const REBAR_LAYOUT_METHOD='k-rebar-layout@1';
const range=(lo,hi,pitch)=>{const out=[];if(!(pitch>0)||hi<lo)return out;for(let x=lo;x<=hi+1e-7&&out.length<500;x+=pitch)out.push(x);return out;};
const bounds=bodies=>({min:[0,1,2].map(k=>Math.min(...bodies.map(b=>b.center[k]-b.size[k]/2))),max:[0,1,2].map(k=>Math.max(...bodies.map(b=>b.center[k]+b.size[k]/2)))});
const midpoint=box=>box.min.map((v,k)=>(v+box.max[k])/2);
const centerOf=c=>[0,1,2].map(k=>(c.bounds[k]+c.bounds[k+3])/2);
const rounded=x=>Number(x.toFixed(7));
function selectSource(candidates,target,kind){
 const point=midpoint(target),native=catalog.buildingBounds,scaled=[(point[0]+8.4)/16.8,(point[1]+6)/12];
 return candidates.map(c=>{const p=centerOf(c),dx=(p[0]-native[0])/(native[3]-native[0])-scaled[0],dy=(p[1]-native[1])/(native[4]-native[1])-scaled[1],size=c.bounds.slice(3).map((v,k)=>v-c.bounds[k]);return {c,score:dx*dx+dy*dy-(kind==='slab'||kind==='roof'?.00001*size[0]*size[1]:0)};}).sort((a,b)=>a.score-b.score||a.c.id.localeCompare(b.c.id))[0]?.c;
}
export function buildRebarLayout(model){
 const result={schema:REBAR_LAYOUT_METHOD,source:catalog.source,steel:catalog.steel,members:[],bars:[],unmapped:[],bounds:null};
 if(model.buildingId!=='residence-3')return result;
 const groups=new Map(),put=(key,kind,b)=>{if(!groups.has(key))groups.set(key,{kind,floor:b.floor,bodies:[]});groups.get(key).bodies.push(b);};
 for(const b of model.bodies){
  if(b.role==='column')put(`column:${b.floor}:${b.chain}`,'column',b);
  else if(b.role==='slab')put(`slab:${b.floor}`,b.floor===model.storeys?'roof':'slab',b);
  else if(b.role==='balcony')put(`balcony:${b.floor}:${Math.sign(b.center[0])}`,'balcony',b);
  else if(b.role==='wall'&&!b.interior){const normal=b.normal?Math.abs(b.normal[0])>.5?0:1:b.size[0]<b.size[1]?0:1;put(`wall:${b.floor}:${normal}:${b.center[normal]}`,'wall',b);}
  else if(b.role==='stairs')put(`stairs:${b.floor}`,'stairs',b);
  else if(b.role==='roofbox'){
   if(b.size[2]<.2)put('roof-cap','cap',b);
   else if(b.size[2]<.6){const normal=b.size[0]<b.size[1]?0:1;put(`parapet:${normal}:${b.center[normal]}`,'parapet',b);}
   else result.unmapped.push({body:b.id,reason:'no_matching_K_stair_enclosure_wall'});
  }else result.unmapped.push({body:b.id,reason:b.interior?'K_partition_has_no_rebar':'no_explicit_K_rebar_family'});
 }
 function add(member,kind,rule,points,extra={}){
  if(points.length<2||points.some(p=>!p.every(Number.isFinite)))return;
  result.bars.push({id:result.bars.length,member:member.id,kind,diameter:rule.diameter,sourcePart:rule.part,points:points.map(p=>p.map(rounded)),...extra});
 }
 for(const [key,group] of groups){
  const box=bounds(group.bodies),normal=box.max[0]-box.min[0]<box.max[1]-box.min[1]?0:1,side=Math.sign(midpoint(box)[normal]);let candidates=catalog.components.filter(c=>c.floor===group.floor);
  if(group.kind==='column')candidates=candidates.filter(c=>c.kind==='column');
  else if(group.kind==='slab')candidates=candidates.filter(c=>c.kind==='slab'&&c.id.includes('.floor.'));
  else if(group.kind==='roof')candidates=candidates.filter(c=>c.id.startsWith('roof.'));
  else if(group.kind==='balcony')candidates=candidates.filter(c=>c.id.includes((midpoint(box)[0]<0?'west':'east')+'.balcony_slab'));
  else if(group.kind==='wall')candidates=candidates.filter(c=>c.kind==='wall'&&c.groups.wall_rebar?.normalAxis===normal&&c.bounds[5]-c.bounds[2]>(box.max[2]-box.min[2])*.7);
  else if(group.kind==='stairs')candidates=candidates.filter(c=>c.kind==='stairs'&&c.id.endsWith('flightA'));
  else if(group.kind==='parapet'){const prefix='parapet_'+(normal?'y':'x');candidates=candidates.filter(c=>c.id.startsWith(prefix)&&(side<0?c.id===prefix+'0':c.id!==prefix+'0'));}
  else if(group.kind==='cap')candidates=candidates.filter(c=>c.id==='lift_overrun_cap');
  const source=selectSource(candidates,box,group.kind);
  if(!source){for(const b of group.bodies)result.unmapped.push({body:b.id,reason:'no_K_rebar_at_this_floor_and_role'});continue;}
  const member={id:result.members.length,key,kind:group.kind,floor:group.floor,bounds:box,bodyIds:group.bodies.map(b=>b.id),sourceComponent:source.id,sourceParts:Object.values(source.groups).map(g=>g.part),rules:source.groups};result.members.push(member);
  const center=midpoint(box);
  if(group.kind==='column'){
   const longitudinal=source.groups.column_longitudinal,stirrup=source.groups.column_stirrup;
   if(longitudinal){const sourceHalf=(source.bounds[3]-source.bounds[0])/2,cover=sourceHalf-Math.max(...longitudinal.positions.map(p=>Math.abs(p[0]))),z0=box.min[2]+cover,z1=box.max[2]-cover;
    // Continue through the slab-column joint; the existing floor volume is the host.
    for(const xy of longitudinal.positions)add(member,'column_longitudinal',longitudinal,[[center[0]+xy[0],center[1]+xy[1],group.floor*3.1+.09],[center[0]+xy[0],center[1]+xy[1],(group.floor+1)*3.1+.09]],{jointAnchorage:true});
   }
   if(stirrup){const offsets=stirrup.offsets,cover=(source.bounds[3]-source.bounds[0])/2-offsets[0];for(const z of range(box.min[2]+cover,box.max[2]-cover,stirrup.spacing)){const points=[[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]].map(([a,b])=>[center[0]+a*offsets[0],center[1]+b*offsets[1],z]);add(member,'column_stirrup',stirrup,points,{closed:true});}}
   continue;
  }
  if(group.kind==='stairs'){
   const longitudinal=source.groups.stair_longitudinal,transverse=source.groups.stair_transverse,steps=[...group.bodies].sort((a,b)=>a.center[1]-b.center[1]);
   const offsets=[...(longitudinal?.layers||[]).map(l=>l.offset),...(transverse?.crossLayers||[]).map(l=>l.offset)],mid=(Math.min(...offsets)+Math.max(...offsets))/2,thickness=Math.min(...steps.map(b=>b.size[2])),cover=Math.max(longitudinal?.cover||0,transverse?.cover||0),scale=Math.min(1,(thickness-2*cover)/Math.max(1e-8,Math.max(...offsets)-Math.min(...offsets))),layerZ=l=>(l.offset-mid)*scale;
   if(longitudinal)for(let layerIndex=0;layerIndex<(longitudinal.layers||[]).length;layerIndex++){const layer=longitudinal.layers[layerIndex],positions=layer.positions,pitch=positions.length>1?positions[1]-positions[0]:null,edge=positions[0];if(!pitch)continue;for(const x of range(box.min[0]+edge,box.max[0]-edge,pitch))add(member,'stair_longitudinal',longitudinal,steps.map(b=>[x,b.center[1],b.center[2]+layerZ(layer)]),{layer:layerIndex});}
   if(transverse){for(let layerIndex=0;layerIndex<(transverse.crossLayers||[]).length;layerIndex++){const layer=transverse.crossLayers[layerIndex],pitch=layer.spacing;if(!(pitch>0))continue;for(const y of range(box.min[1]+transverse.cover,box.max[1]-transverse.cover,pitch)){const step=steps.reduce((best,b)=>Math.abs(b.center[1]-y)<Math.abs(best.center[1]-y)?b:best),z=step.center[2]+layerZ(layer);add(member,'stair_transverse',transverse,[[box.min[0]+transverse.cover,y,z],[box.max[0]-transverse.cover,y,z]],{layer:layerIndex});}}
   }
   continue;
  }
  for(const [role,rule] of Object.entries(source.groups)){
   if(!rule.layers)continue;const thin=rule.normalAxis,sourceThickness=source.bounds[thin+3]-source.bounds[thin],targetThickness=box.max[thin]-box.min[thin];
   for(let layerIndex=0;layerIndex<rule.layers.length;layerIndex++){
    const layer=rule.layers[layerIndex],axis=layer.axis,across=[0,1,2].find(k=>k!==thin&&k!==axis),margin=Math.max(rule.diameter/2,Math.min(layer.margin,.06)),endMargin=Math.max(rule.diameter/2,Math.min(layer.endMargin,.06)),pitch=layer.spacing||Math.max(.1,box.max[across]-box.min[across]-margin-endMargin),depth=layer.depth/sourceThickness*targetThickness;
    if(depth<rule.diameter/2||depth>targetThickness-rule.diameter/2){result.unmapped.push({member:member.id,layer:layerIndex,reason:'K_layer_does_not_fit_target_thickness'});continue;}
    for(const u of range(box.min[across]+margin,box.max[across]-endMargin,pitch)){
     const start=box.min[axis]+Math.max(rule.diameter/2,Math.min(Math.max(0,layer.startCover),.06)),end=box.max[axis]-Math.max(rule.diameter/2,Math.min(Math.max(0,layer.endCover),.06)),intervals=[];
     // Display seams merge; door/window voids split physical bars.
     for(const body of group.bodies){const lo=body.center[across]-body.size[across]/2,hi=body.center[across]+body.size[across]/2;if(u<lo-.014||u>hi+.014)continue;
      if(u<lo||u>hi){const seam=group.bodies.some(other=>{if(other===body)return false;const a=other.center[across]-other.size[across]/2,b=other.center[across]+other.size[across]/2,overlap=Math.min(body.center[axis]+body.size[axis]/2,other.center[axis]+other.size[axis]/2)-Math.max(body.center[axis]-body.size[axis]/2,other.center[axis]-other.size[axis]/2);return overlap>.01&&(u<lo?b<=lo&&lo-b<.045&&u>=b:a>=hi&&a-hi<.045&&u<=a);});if(!seam)continue;}
      const a=Math.max(start,body.center[axis]-body.size[axis]/2),b=Math.min(end,body.center[axis]+body.size[axis]/2);if(b>a)intervals.push([a,b]);}
     intervals.sort((a,b)=>a[0]-b[0]);const merged=[];for(const interval of intervals){const last=merged.at(-1);if(last&&interval[0]-last[1]<.045)last[1]=Math.max(last[1],interval[1]);else merged.push([...interval]);}
     for(const interval of merged){const a=[0,0,0],b=[0,0,0];a[thin]=b[thin]=box.min[thin]+depth;a[across]=b[across]=u;a[axis]=interval[0];b[axis]=interval[1];
      if(group.kind==='wall'&&axis===2){if(Math.abs(a[axis]-start)<.01)a[axis]=group.floor*3.1+.09;if(Math.abs(b[axis]-end)<.01)b[axis]=(group.floor+1)*3.1+.09;}
      if(group.kind==='balcony'&&axis===1&&Math.abs(b[axis]-end)<.01)b[axis]=box.max[axis]+.16;
      if(b[axis]-a[axis]>rule.diameter*2)add(member,role,rule,[a,b],{layer:layerIndex,axis,jointAnchorage:group.kind==='wall'&&axis===2||group.kind==='balcony'&&axis===1});}
    }
   }
  }
 }
 result.bounds=bounds(model.bodies);return result;
}
