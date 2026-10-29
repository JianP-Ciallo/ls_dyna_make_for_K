/* Demonstration pulverization and deterministic aerosol display.
 * These thresholds are an effect rule, not calibrated concrete strength. */
export const POWDER_RESPONSE='near-source@1';
export const POWDER_METHOD='near-source-powder@1';
export const POWDER_SCHEMA='powdered-prisms@1';
export const POWDER_LIFETIME=2.6;
const concrete=new Set(['wall','slab','roof','balcony','canopy','roofbox','column','stairs','rail']);
const random=i=>{const n=Math.sin(i*127.1+13.7)*43758.5453;return n-Math.floor(n);};
// In this house, rail bodies are solid balcony parapets; the K steel is separate.
export const powderConcrete=body=>!!body&&!body.fixed&&concrete.has(body.role)&&!['steel','metal','glass'].includes(body.material);
export function advancePowder(state,{body,point,config,damage,time,dt}){
 if(state.time>=0||!powderConcrete(body)||!(config.mass>0)||damage<.6)return false;
 const delta=point.map((v,k)=>v-config.source[k]),r=Math.max(.1,Math.hypot(...delta)),age=time-(.15+r/343),facing=body.normal?Math.max(.1,-body.normal.reduce((s,v,k)=>s+v*delta[k]/r,0)):.7;
 if(age<=0||age>.2||r>Math.max(1,.75*Math.cbrt(config.mass)))return false;
 const strength=Math.cbrt(config.mass)**2/(r+1)**2*facing*(body.interior?.38:1)/body.capacity;
 state.dose=Math.min(1,state.dose+dt*30*Math.max(0,strength/8-1));if(state.dose===1){state.time=time;return true;}return false;
}
function merge(events,cell){const groups=new Map();for(const e of events){const key=e.position.map(v=>Math.floor(v/cell)).join(':')+':'+Math.floor(e.time/.1);let g=groups.get(key);if(!g){g={...e,mass:0,position:[0,0,0],velocity:[0,0,0],time:0};groups.set(key,g);}g.mass+=e.mass;g.time+=e.time*e.mass;for(let k=0;k<3;k++){g.position[k]+=e.position[k]*e.mass;g.velocity[k]+=e.velocity[k]*e.mass;}}return [...groups.values()].map(g=>({...g,time:g.time/g.mass,position:g.position.map(v=>v/g.mass),velocity:g.velocity.map(v=>v/g.mass)}));}
export function samplePowder(events,time,enabled=true){
 const active=enabled?events.filter(e=>e.kind==='pulverized'&&time>=e.time&&time-e.time<POWDER_LIFETIME):[],representedMass=active.reduce((s,e)=>s+e.mass,0);let clouds=active,cell=.5;
 while(clouds.length>512){clouds=merge(active,cell);cell*=2;}
 const positions=[],sizes=[],opacities=[],grains=[],countPerCloud=Math.min(8,Math.max(1,Math.floor(4096/Math.max(1,clouds.length))));
 for(const e of clouds){const age=Math.max(0,time-e.time),drag=(1-Math.exp(-2.5*age))/2.5,center=[0,1,2].map(k=>(e.vertices[k]+e.vertices[k+3]+e.vertices[k+6])/3);
  for(let i=0;i<countPerCloud;i++){const seed=e.seed*31+i*7,r=Math.sqrt(random(seed)),s=random(seed+1),weights=[1-r,r*(1-s),r*s],grain=i===0,life=grain?.8:POWDER_LIFETIME;if(age>=life)continue;
   const offset=[0,1,2].map(k=>weights.reduce((sum,w,j)=>sum+w*e.vertices[j*3+k],0)-center[k]),jitter=[0,1,2].map(k=>(random(seed+2+k)-.5)),position=e.position.map((v,k)=>v+offset[k]+e.velocity[k]*drag+jitter[k]*age*(grain?1.2:1.7)+(k===2?(grain?-4.903325*age*age:.5*age-.16*age*age):0));position[2]=Math.max(.012,position[2]);positions.push(...position);sizes.push(grain?.025+random(seed+8)*.035:Math.min(2.4,.25+age*.75+Math.cbrt(e.mass)*.5));opacities.push((grain?.85:.38)*(1-age/life)**2);grains.push(Number(grain));
  }
 }
 return {count:sizes.length,clouds:clouds.length,representedMass,positions:Float32Array.from(positions),sizes:Float32Array.from(sizes),opacities:Float32Array.from(opacities),grains:Uint8Array.from(grains)};
}
export function validPowderEvents(events,model,duration){return Array.isArray(events)&&events.every(e=>e&&typeof e==='object'&&(e.kind!=='pulverized'||(powderConcrete(model.bodies[e.body])&&Number.isInteger(e.triangle)&&e.triangle>=0&&e.triangle<72&&Number.isFinite(e.time)&&e.time>=0&&e.time<=duration&&Number.isFinite(e.mass)&&e.mass>0&&Number.isFinite(e.seed)&&e.vertices?.length===9&&e.vertices.every(Number.isFinite)&&e.position?.length===3&&e.position.every(Number.isFinite)&&e.velocity?.length===3&&e.velocity.every(Number.isFinite))));}
export function validPowderHistory(frames,events,model,duration){
 if(!Array.isArray(frames)||!frames.length||frames[0].time!==0||frames.at(-1).time!==duration||!validPowderEvents(events,model,duration))return false;
 const conversions=new Map();for(const e of events)if(e.kind==='pulverized'){const key=e.body+':'+e.triangle;if(conversions.has(key))return false;conversions.set(key,e);}
 let previous=-1;for(const f of frames){const p=f.fracture;if(!Number.isFinite(f.time)||f.time<=previous||f.time>duration||p?.powderSchema!==POWDER_SCHEMA||!p.ids||!p.offsets||!p.powderedFlags||!p.powderTimes)return false;previous=f.time;const seen=new Set();
  for(let i=0;i<p.ids.length;i++)for(let t=0;t<(p.offsets[i+1]-p.offsets[i])/9;t++){const n=p.offsets[i]/9+t,key=p.ids[i]+':'+t,e=conversions.get(key);if(p.powderedFlags[n]){if(!e||e.time>f.time+1e-9||Math.abs(p.powderTimes[n]-e.time)>1e-6)return false;seen.add(key);}else if(p.powderTimes[n]!==-1)return false;}
  let mass=0,expected=0;for(const [key,e]of conversions)if(e.time<=f.time+1e-9){if(!seen.has(key))return false;mass+=e.mass;expected++;}if(expected!==seen.size||p.powdered!==seen.size||!Number.isFinite(p.powderMass)||Math.abs(p.powderMass-mass)>1e-7)return false;
 }return true;
}
