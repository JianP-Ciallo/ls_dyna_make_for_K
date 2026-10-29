/* Existing design appearance adapted to lightweight volumetric demonstration pieces.
 * No old mesher, gravity solver, native runtime, K generator or ALE workflow is called.
 */
const ASSETS='resources/model_library/detailed_buildings/phase18d/';
const DESIGN='docs/superpowers/specs/2026-08-09-phase18d-detailed-building-asset-library-design.md';
export const ORIGINAL_SCENE_PRESETS=Object.freeze([
 {id:'commercial_supermarket',name:'商超',storeys:1,source:[0,-14,.8],summary:'22 × 18 m · 大跨商超',detail:'入口雨棚、立面柱、招牌带与屋顶设备间'},
 {id:'residential_community',name:'住宅小区',storeys:6,source:[0,-10,.8],summary:'三栋住宅 · 每栋6层',detail:'8 × 10 × 18 m塔楼，净距4 m，阳台与屋顶机房'},
 {id:'subway_entrance',name:'地铁入口',storeys:1,source:[-5,-5,.8],summary:'玻璃亭体 · 地下直通通道',detail:'浅弧屋面，1组固定楼梯与2组并排扶梯'},
 {id:'city_street',name:'城市街道',storeys:5,source:[0,0,.8],summary:'72 × 72 m · 原十字街区',detail:'商超、两栋住宅、地铁入口、停车场、四车与四信号灯'}
].map(p=>Object.freeze({...p,source:Object.freeze(p.source),scale:Object.freeze([1,1]),balconies:false,originalScene:true})));

export function buildOriginalScene(id){
 if(!ORIGINAL_SCENE_PRESETS.some(p=>p.id===id))throw Error('未知原设计场景');
 const bodies=[],instances=[],envelopes=[],labels=[];
 const colors={slab:'#d4d1c5',wall:'#d9d4c6',column:'#b9bdb9',steel:'#707d80',glass:'#9dc4cb',balcony:'#a6c6c6',rail:'#9bb7ba',stairs:'#bfc4c1',roof:'#b7c0c0',canopy:'#8faeac',sign:'#397b73',equipment:'#8d969a',vehicle:'#a57058',road:'#7c8589',ground:'#c9c9bc',marking:'#f0edd4'};
 const capacity={slab:1,wall:.22,column:.62,steel:.7,glass:.035,balcony:.44,rail:.18,stairs:.5,roof:.3,canopy:.35,sign:.06,equipment:.45,vehicle:1.1,road:1,ground:1,marking:1};
 function add(role,center,size,floor=0,extra={}){const b={id:bodies.length,role,center,size,floor,color:colors[role],capacity:capacity[role],supports:[],fixed:false,isRoof:false,instanceId:'site',...extra};bodies.push(b);return b.id;}
 function tiles(role,c,size,floor,extra={},target=2){const nx=Math.ceil(size[0]/target),ny=Math.ceil(size[1]/target);for(let i=0;i<nx;i++)for(let j=0;j<ny;j++)add(role,[c[0]-size[0]/2+(i+.5)*size[0]/nx,c[1]-size[1]/2+(j+.5)*size[1]/ny,c[2]],[size[0]/nx-.006,size[1]/ny-.006,size[2]],floor,extra);}
 function wall(axis,side,lo,hi,z0,z1,holes,floor,extra={}){
  const u=new Set([lo,hi]),v=new Set([z0,z1]);for(let x=lo+1.6;x<hi;x+=1.6)u.add(x);for(let z=z0+1.4;z<z1;z+=1.4)v.add(z);
  for(const h of holes){u.add(h[0]);u.add(h[1]);v.add(h[2]);v.add(h[3]);}
  const xs=[...u].filter(x=>x>=lo&&x<=hi).sort((a,b)=>a-b),zs=[...v].filter(z=>z>=z0&&z<=z1).sort((a,b)=>a-b);
  for(let i=0;i<xs.length-1;i++)for(let j=0;j<zs.length-1;j++){const x=(xs[i]+xs[i+1])/2,z=(zs[j]+zs[j+1])/2;if(xs[i+1]-xs[i]<.012||zs[j+1]-zs[j]<.012||holes.some(h=>x>h[0]&&x<h[1]&&z>h[2]&&z<h[3]))continue;add('wall',axis===0?[x,side,z]:[side,x,z],axis===0?[xs[i+1]-xs[i]-.006,.2,zs[j+1]-zs[j]-.006]:[.2,xs[i+1]-xs[i]-.006,zs[j+1]-zs[j]-.006],floor,{normal:axis===0?[0,side<=0?-1:1,0]:[side<=0?-1:1,0,0],...extra});}
 }
 function supermarket(origin=[-11,-9,0],instanceId='supermarket'){
  const [ox,oy,oz]=origin,L=22,W=18,H=8,e={instanceId};instances.push({id:instanceId,kind:'supermarket',origin:[...origin],center:[ox+11,oy+9,oz+4],size:[L,W,H]});
  envelopes.push({min:[ox,oy,oz],max:[ox+L,oy+W,oz+H]});
  const start=bodies.length;
  tiles('slab',[11,9,.1],[22,18,.2],0,{...e,fixed:true});tiles('roof',[11,9,8],[22,18,.18],1,{...e,isRoof:true});
  for(let i=0;i<5;i++)for(let j=0;j<4;j++)for(let s=0;s<3;s++)add('steel',[.15+i*21.7/4,.15+j*17.7/3,(s+.5)*7.8/3],[.28,.28,7.8/3-.01],0,e);
  wall(0,0,0,22,.2,8,[[8,14,.2,3.4]],0,e);wall(0,18,0,22,.2,8,[],0,e);
  wall(1,0,0,18,.2,8,[],0,e);wall(1,22,0,18,.2,8,[],0,e);
  // The sales hall, stockroom and service area retain empty space and doors.
  wall(1,22*2/3,.2,17.8,.2,7.8,[[5.5,6.5,.2,2.4],[14,15,.2,2.4]],0,{...e,interior:true});
  wall(0,12,22*2/3,21.8,.2,7.8,[[17,18,.2,2.4]],0,{...e,interior:true});
  for(const x of [2,5,17,20])add('glass',[x,-.12,1.7],[2,.035,2.7],0,{...e,normal:[0,-1,0]});
  tiles('canopy',[11,-.75,3.375],[7.5,1.5,.35],0,e,1.5);for(const x of [7.55,14.45])add('column',[x,-.3,1.6],[.6,.6,3.2],0,e);
  const sign=add('sign',[11,-.18,5.2],[14.3,.35,.9],0,e);labels.push({body:sign,text:'商超 SUPERMARKET',color:'#eef2dd'});
  const equipment={...e,isRoof:true,component:'roof_equipment'};
  for(const y of [6.3,10.8])tiles('wall',[11,y,8.6],[5.5,.16,1.2],1,equipment,1.5);
  for(const x of [8.25,13.75])tiles('wall',[x,8.55,8.6],[.16,4.5,1.2],1,equipment,1.5);
  tiles('roof',[11,8.55,9.15],[5.5,4.5,.1],1,equipment);
  for(let i=start;i<bodies.length;i++)bodies[i].center=bodies[i].center.map((x,j)=>x+origin[j]);
 }
 function tower(origin,L=8,W=10,H=18,instanceId='tower'){
  const floors=Math.round(H/3),[ox,oy,oz]=origin,e={instanceId},start=bodies.length;
  instances.push({id:instanceId,kind:'residential_tower',origin:[...origin],center:[ox+L/2,oy+W/2,oz+H/2],size:[L,W,H]});envelopes.push({min:[ox,oy-1.2,oz],max:[ox+L,oy+W,oz+H+1.2]});
  for(let f=0;f<=floors;f++)tiles('slab',[L/2,W/2,f*3+.09],[L,W,.18],f,{...e,fixed:f===0,isRoof:f===floors});
  for(let f=0;f<floors;f++){
   for(const x of [.15,L/2,L-.15])for(const y of [.15,W/2,W-.15])add('column',[x,y,f*3+1.6],[.28,.28,2.82],f,e);
   const holes=[L*.22,L*.5,L*.78].map(x=>[x-.65,x+.65,f*3+.95,f*3+2.3]);
   wall(0,0,0,L,f*3+.18,(f+1)*3,f===0?[...holes.filter((_,i)=>i!==1),[L/2-.7,L/2+.7,.18,2.5]]:holes,f,e);
   wall(0,W,0,L,f*3+.18,(f+1)*3,holes,f,e);
   for(const x of [.22,.5,.78])for(const y of [0,W])if(f>0||x!==.5||y===W)add('glass',[L*x,y,f*3+1.625],[1.26,.035,1.3],f,{...e,normal:[0,y===0?-1:1,0]});
   for(const x of [0,L]){const sideholes=[W*.25,W*.75].map(y=>[y-.6,y+.6,f*3+1,f*3+2.2]);wall(1,x,0,W,f*3+.18,(f+1)*3,sideholes,f,e);for(const y of [W*.25,W*.75])add('glass',[x,y,f*3+1.6],[.035,1.16,1.16],f,{...e,normal:[x===0?-1:1,0,0]});}
   for(let i=0;i<10;i++)add('stairs',[L*.55,W*.35+i*.24,f*3+.3+i*.27],[.85,.26,.14],f,{...e,interior:true});
   wall(1,L*.63,W*.2,W*.8,f*3+.18,(f+1)*3,[[W*.4,W*.5,f*3+.18,f*3+2.3]],f,{...e,interior:true});
  }
  for(const fraction of [.28,.52,.76])for(let i=0;i<4;i++){const z=H*fraction,f=Math.floor(z/3);add('balcony',[(i+.5)*L/4,-.6,z],[L/4-.01,1.2,.17],f,e);add('rail',[(i+.5)*L/4,-1.18,z+.53],[L/4-.02,.10,.9],f,e);}
  for(const y of [0,W])for(let i=0;i<4;i++)add('rail',[(i+.5)*L/4,y,H+.4],[L/4-.01,.12,.65],floors,{...e,isRoof:true});
  add('wall',[L*.5,W*.6,H+.75],[L*.5,W*.5,1.5],floors,{...e,isRoof:true,component:'roof_equipment'});
  for(let i=start;i<bodies.length;i++)bodies[i].center=bodies[i].center.map((x,j)=>x+origin[j]);
 }
 function podium(origin,L,W,doorCenters,instanceId){
  const [x,y,z]=origin,e={instanceId,fixed:true,component:'podium'};
  tiles('slab',[x+L/2,y+W/2,z-.06],[L,W,.12],0,e);
  // A hollow perimeter skirt keeps the old low-base outline without filling rooms.
  const skirt={...e,fixed:false};
  wall(0,y,x,x+L,z,z+1.2,doorCenters.map(c=>[c-.85,c+.85,z,z+1.2]),0,skirt);
  wall(0,y+W,x,x+L,z,z+1.2,[],0,skirt);wall(1,x,y,y+W,z,z+1.2,[],0,skirt);wall(1,x+L,y,y+W,z,z+1.2,[],0,skirt);
 }
 function subway(){
  const e={instanceId:'subway'},x0=-3.45,upperEnd=-3,lowerStart=3,passageStart=3.45,end=4.95,W=4,upper=0,lower=-2.8;
  instances.push({id:'subway',kind:'approved_subway',origin:[x0,-2,0],center:[.75,0,0],size:[8.4,4,6]});envelopes.push({min:[-4.1,-2.1,0],max:[3.6,2.1,3.4]});
  tiles('slab',[(x0+end)/2,0,-2.95],[8.4,4,.3],0,{...e,fixed:true,underground:true});
  for(const y of [-2,2])for(let i=0;i<7;i++)add('wall',[x0+(i+.5)*8.4/7,y,-1.4],[8.4/7-.01,.2,2.8],0,{...e,fixed:true,underground:true,cutawayHidden:y<0});
  tiles('slab',[(passageStart+end)/2,0,.1],[1.5,4,.2],1,{...e,fixed:true,isRoof:true,underground:true,cutawayHidden:true});
  tiles('slab',[(x0+upperEnd)/2,0,upper-.1],[.45,3.6,.2],0,{...e,fixed:true});tiles('slab',[(lowerStart+passageStart)/2,0,lower-.1],[.45,3.6,.2],0,{...e,fixed:true,underground:true});
  for(let j=0;j<3;j++)add('stairs',[x0-.18*(j+.5),0,upper-.1*(j+1)],[.2,3.8,.1],0,{...e,fixed:true,component:'entry_steps'});
  const laneWidths=[1.224,.792,.792],laneCenters=[-.892,.216,1.108],n=24;
  for(let lane=0;lane<3;lane++){
   for(let i=0;i<n;i++){const z=upper-(i+.5)*2.8/n;add(lane===0?'stairs':'equipment',[upperEnd+(i+.5)*6/n,laneCenters[lane],z],[6/n+.004,laneWidths[lane],.11],0,{...e,fixed:true,component:lane===0?'fixed_staircase':`escalator_${lane}`,underground:z<0});}
   const angle=Math.atan2(2.8,6),q=[0,Math.sin(angle/2),0,Math.cos(angle/2)];
   for(const side of [-1,1])add('rail',[0,laneCenters[lane]+side*laneWidths[lane]/2,upper-1.4+.65],[Math.hypot(6,2.8),.06,.08],0,{...e,fixed:true,component:lane===0?'stair_handrail':`escalator_${lane}`,rotation:q});
  }
  const walkZ=x=>upper-2.8*Math.max(0,Math.min(1,(x-upperEnd)/6));
  for(const y of [-1.94,1.94]){
   for(let i=0;i<6;i++){const x=x0+(i+.5)*6.9/6,z=walkZ(x);add('wall',[x,y,z+.25],[6.9/6-.01,.16,.5],0,e);add('glass',[x,y,z+1.65],[6.9/6-.14,.025,2.2],0,{...e,transparent:true,normal:[0,Math.sign(y),0]});}
   for(let i=0;i<=6;i++){const x=x0+i*6.9/6;add('steel',[x,y,walkZ(x)+1.4],[.1,.1,2.8],0,e);}
  }
  const roofCuts=[...new Set([x0-.6,x0,upperEnd,lowerStart,passageStart,...Array.from({length:8},(_,i)=>x0-.6+i*7.5/7)].map(v=>Math.round(v*1e9)/1e9))].sort((a,b)=>a-b);
  for(let i=0;i<roofCuts.length-1;i++)for(let j=0;j<8;j++){
   const y=-2.1+(j+.5)*4.2/8,rise=.28*(1-(y/2.1)**2),slope=Math.atan(-2*.28*y/2.1**2);
   const x=(roofCuts[i]+roofCuts[i+1])/2,dx=roofCuts[i+1]-roofCuts[i],tilt=Math.atan2(walkZ(roofCuts[i])-walkZ(roofCuts[i+1]),dx);
   const ax=Math.sin(slope/2),aw=Math.cos(slope/2),by=Math.sin(tilt/2),bw=Math.cos(tilt/2);
   add('roof',[x,y,walkZ(x)+2.8+rise],[dx/Math.cos(tilt)+.006,(4.2/8)/Math.cos(slope)+.006,.05],1,{...e,isRoof:true,component:'pavilion_roof',roofStrip:j,roofInterval:[roofCuts[i],roofCuts[i+1]],roofSlope:tilt,rotation:[ax*bw,aw*by,-ax*by,aw*bw]});
  }
  const sign=add('sign',[x0-.16,0,2.45],[.12,2.8,.45],0,e);labels.push({body:sign,text:'地铁 METRO',color:'#edf4ed'});
  return {fixedStaircases:1,escalators:2,route:'A/B/C -> 8 -> 9 -> 10',upperLandingEnd:upperEnd,lowerLandingStart:lowerStart,passageStart,interfaceX:end,passageProbe:[4.2,0,-1.4],upperWalkZ:0,lowerWalkZ:-2.8,descentLength:6,pavilionLength:6.9,routeLength:8.4,dimensionsBasis:'existing_asset_compiler_defaults_not_engineering_dimensions_from_drawing'};
 }
 function city(){
  for(const [x,y,w,h] of [[0,0,16,16],[0,22,16,28],[0,-22,16,28],[-22,0,28,16],[22,0,28,16]])add('road',[x,y,-.13],[w,h,.25],0,{fixed:true});
  for(const x of [-22,22])for(const y of [-22,22])add('ground',[x,y,-.15],[28,28,.28],0,{fixed:true});
  for(let d=-32;d<=32;d+=4)if(Math.abs(d)>10){add('marking',[d,0,.008],[2.1,.12,.015],0,{fixed:true});add('marking',[0,d,.008],[.12,2.1,.015],0,{fixed:true});}
  supermarket([-34,12,0]);podium([-35,-27,0],17,10,[-31.5,-21.5],'city_podium');tower([-35,-26,0],7,8,15,'city_tower_1');tower([-25,-26,0],7,8,15,'city_tower_2');
  // The city contract retains its separate old front-open, three-sided entrance.
  const e={instanceId:'city_subway'};instances.push({id:'city_subway',kind:'city_lightweight_subway',origin:[12,12,0],center:[15,14,1.7],size:[6,4,3.3]});envelopes.push({min:[12,12,0],max:[18,16,3.3]});
  tiles('slab',[15,14,.15],[6,4,.3],0,{...e,fixed:true});tiles('roof',[15,14,3.2],[6,4,.2],1,{...e,isRoof:true});wall(0,16,12,18,.3,3.1,[],0,e);wall(1,12,12,16,.3,3.1,[],0,{...e,normal:[-1,0,0]});wall(1,18,12,16,.3,3.1,[],0,e);
  const metroSign=add('sign',[15,11.9,2.85],[4,.12,.4],0,e);labels.push({body:metroSign,text:'地铁 METRO',color:'#eef4ed'});
  add('ground',[23,-25,.03],[18,14,.15],0,{fixed:true,color:'#9caaa7'});
  for(const y of [-30,-25.5])for(const x of [16,21.5]){
   const v={instanceId:'car_'+x+'_'+y},origin=[x,y,.1];instances.push({id:v.instanceId,kind:'vehicle',origin,center:[x+2.2,y+.9,.9],size:[4.4,1.8,1.55]});
   add('vehicle',[x+2.2,y+.9,.65],[4.4,1.8,.8],0,{...v,color:x===16?'#a96950':'#719196'});add('glass',[x+2.3,y+.9,1.35],[2.5,1.6,.65],0,v);
   for(const dx of [.8,3.6])for(const dy of [0,1.8])add('equipment',[x+dx,y+dy,.35],[.55,.18,.55],0,{...v,color:'#343f42'});
  }
  for(const [i,[x,y]] of [[-9,-9],[9,-9],[9,9],[-9,9]].entries()){
   const e={instanceId:'signal_'+i},direction=[[1,0],[0,1],[-1,0],[0,-1]][i];instances.push({id:e.instanceId,kind:'traffic_light',origin:[x,y,0],rotationDegrees:i*90,center:[x,y,2.25],size:[.16,.16,4.5]});add('steel',[x,y,2.25],[.16,.16,4.5],0,e);add('steel',[x+direction[0]*1.75,y+direction[1]*1.75,4.4],i%2?[.12,3.5,.12]:[3.5,.12,.12],0,e);
   const head=add('equipment',[x+direction[0]*3.3,y+direction[1]*3.3,4.05],[.35,.25,.8],0,{...e,color:'#424d4c'});add('sign',[bodies[head].center[0],bodies[head].center[1]-.15,4.23],[.18,.04,.18],0,{...e,color:'#bf715d'});
  }
 }
 let topology;
 if(id==='commercial_supermarket')supermarket();
 if(id==='residential_community'){podium([-16,-6,0],32,12,[-12,0,12],'community_podium');for(let i=0;i<3;i++)tower([-16+i*12,-5,0],8,10,18,'tower_'+(i+1));}
 if(id==='subway_entrance')topology=subway();
 if(id==='city_street')city();
 // Each object has local support links; no tower is connected across empty gaps.
 const byInstance=new Map();for(const b of bodies){if(!byInstance.has(b.instanceId))byInstance.set(b.instanceId,[]);byInstance.get(b.instanceId).push(b);}
 for(const rows of byInstance.values())for(const b of rows){
  if(b.fixed)continue;
  const d=a=>(a.center[0]-b.center[0])**2+(a.center[1]-b.center[1])**2;
  let candidates;
  if(b.role==='column'||b.role==='steel')candidates=rows.filter(a=>a.id!==b.id&&(a.role==='column'||a.role==='steel'||a.fixed)&&a.center[2]<b.center[2]-.05);
  else if((b.role==='slab'&&b.floor>0)||b.role==='roof'||b.role==='canopy'){
   const underside=b.center[2]-b.size[2]/2,nearTop=a=>a.center[2]+a.size[2]/2>=underside-.65&&a.center[2]+a.size[2]/2<=underside+.3;
   candidates=rows.filter(a=>(a.role==='column'||a.role==='steel')&&nearTop(a));
   if(!candidates.length)candidates=rows.filter(a=>a.role==='wall'&&nearTop(a));
  }else if(b.instanceId.startsWith('signal_'))candidates=rows.filter(a=>a.id!==b.id&&(a.role==='steel'||a.role==='equipment'));
  else if(b.instanceId.startsWith('car_'))candidates=rows.filter(a=>a.id!==b.id&&a.role==='vehicle');
  else {candidates=rows.filter(a=>a.id!==b.id&&(a.role==='slab'||a.role==='roof'||a.fixed)&&a.floor<=b.floor&&a.center[2]<=b.center[2]);const level=Math.max(-Infinity,...candidates.map(a=>a.center[2]));candidates=candidates.filter(a=>a.center[2]>=level-.25);}
  if(!candidates.length&&b.role!=='roof'&&b.role!=='canopy')candidates=rows.filter(a=>a.fixed);
  if(!candidates.length&&['steel','vehicle'].includes(b.role))candidates=bodies.filter(a=>a.fixed&&['ground','road','slab'].includes(a.role)&&a.center[2]<=b.center[2]);
  b.supports=candidates.sort((a,c)=>d(a)-d(c)||Math.abs(a.center[2]-b.center[2])-Math.abs(c.center[2]-b.center[2])).slice(0,b.role==='slab'||b.role==='roof'?3:1).map(a=>a.id);
 }
 const mins=[0,1,2].map(j=>Math.min(...bodies.map(b=>b.center[j]-b.size[j]/2))),maxs=[0,1,2].map(j=>Math.max(...bodies.map(b=>b.center[j]+b.size[j]/2)));
 const preset=ORIGINAL_SCENE_PRESETS.find(p=>p.id===id),cityScene=id==='city_street';
 return {schema:'simple-building-geometry@1',buildingId:id,buildingCount:instances.filter(i=>!['vehicle','traffic_light'].includes(i.kind)).length,sceneCount:1,name:preset.name,storeys:preset.storeys,bodies,instances,envelopes,labels,topology,
  width:cityScene?72:id==='commercial_supermarket'?22:maxs[0]-mins[0],depth:cityScene?72:id==='commercial_supermarket'?18:maxs[1]-mins[1],height:maxs[2]-mins[2],bounds:{min:mins,max:maxs},floorLabel:preset.summary,
  cutaway:id==='subway_entrance',groundCutout:id==='subway_entrance'?[-4.4,-5.5,5.4,2.5]:null,contactFloorZ:id==='subway_entrance'?-2.8:0,
  viewDirection:id==='subway_entrance'?[-1,-1.4,.9]:[1,-1.4,.9],layout:cityScene?{roadWidth:16,domain:[-36,-36,36,36]}:null,
  designReferences:[DESIGN,...(id==='city_street'?['docs/reviews/city-street/CITY_STREET_BLAST_SCENE.zh-CN.md','lsprepost_mcp/city_street_blast.py']:id==='subway_entrance'?['docs/superpowers/specs/2026-08-09-phase18d-subway-entrance-approved-baseline.md','docs/assets/phase18d/subway_entrance_cn_generic_A_approved_2026-08-09.png','lsprepost_mcp/refined_building/asset_compiler.py']:[ASSETS+id+'_detailed_building/asset.json'])],
  simplifications:['volumetric_breakable_components_not_solid_FEM','no_flow_shadowing_or_debris_contact',...(id==='subway_entrance'?['fixed_underground_reference_structure_cutaway']:[])]};
}

