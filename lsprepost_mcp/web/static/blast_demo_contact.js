/* Demonstration contact with retained floors and the metro excavation walls.
 * Swept, one-sided environment surfaces. The separate convex debris solver
 * handles two-way fragment contact; engineering contact forces are uncalibrated.
 */
const rotate=(p,q=[0,0,0,1])=>{const [x,y,z,w]=q,[a,b,c]=p,tx=2*(y*c-z*b),ty=2*(z*a-x*c),tz=2*(x*b-y*a);return [a+w*tx+y*tz-z*ty,b+w*ty+z*tx-x*tz,c+w*tz+x*ty-y*tx];};
const floorRoles=new Set(['slab','roof','balcony','canopy','stairs']);
export function createContactSystem(model,{spatial3D=false}={}){
 const cellSize=spatial3D?.8:3,cells=new Map(),surfaces=model.bodies.filter(b=>floorRoles.has(b.role));let brokenState=null;
 const counts={floorContacts:0,groundContacts:0,pitWallContacts:0};
 function add(points,id,alive=()=>true){
  const [a,b,c]=points,u=b.map((v,k)=>v-a[k]),v=c.map((v,k)=>v-a[k]),n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...n);
  if(length<1e-8||Math.abs(n[2])/length<.35)return;if(n[2]<0)for(let k=0;k<3;k++)n[k]*=-1;for(let k=0;k<3;k++)n[k]/=length;
  const face={a,b,c,n,id,alive,minZ:Math.min(a[2],b[2],c[2]),maxZ:Math.max(a[2],b[2],c[2])},lo=[0,1].map(k=>Math.floor(Math.min(a[k],b[k],c[k])/cellSize)),hi=[0,1].map(k=>Math.floor(Math.max(a[k],b[k],c[k])/cellSize));
  const z0=spatial3D?Math.floor(face.minZ/cellSize):0,z1=spatial3D?Math.floor(face.maxZ/cellSize):0;for(let x=lo[0];x<=hi[0];x++)for(let y=lo[1];y<=hi[1];y++)for(let z=z0;z<=z1;z++){const key=x+':'+y+(spatial3D?':'+z:'');if(!cells.has(key))cells.set(key,[]);cells.get(key).push(face);}
 }
 function update(broken,positions,panels){
  brokenState=broken;cells.clear();
  for(const b of surfaces){
   if(broken?.[b.id])continue;
   if(panels?.owns(b.id)){
    for(const face of panels.contactTriangles(b.id))add(face.points,b.id,face.alive);
   }else{
    const center=positions?Array.from(positions.subarray(b.id*3,b.id*3+3)):b.center;
    const corners=[[-1,-1],[1,-1],[1,1],[-1,1]].map(([x,y])=>rotate([x*b.size[0]/2,y*b.size[1]/2,b.size[2]/2],b.rotation).map((v,k)=>v+center[k]));
    const alive=()=>!panels?.owns(b.id);add([corners[0],corners[1],corners[2]],b.id,alive);add([corners[0],corners[2],corners[3]],b.id,alive);
   }
  }
 }
 function response(velocity,normal){
  const vn=velocity.reduce((s,v,k)=>s+v*normal[k],0);if(vn>=0)return;
  const tangent=velocity.map((v,k)=>v-vn*normal[k]),speed=Math.hypot(...tangent),restitution=Math.abs(vn)>.5?.08:0,scale=speed>1e-12?Math.max(0,1-.55*(1+restitution)*-vn/speed):0;
  for(let k=0;k<3;k++)velocity[k]=tangent[k]*scale-restitution*vn*normal[k];
 }
 function inside(point,face){
  const {a,b,c}=face,den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);if(Math.abs(den)<1e-10)return false;
  const u=((b[1]-c[1])*(point[0]-c[0])+(c[0]-b[0])*(point[1]-c[1]))/den,v=((c[1]-a[1])*(point[0]-c[0])+(a[0]-c[0])*(point[1]-c[1]))/den;
  return u>=-1e-6&&v>=-1e-6&&u+v<=1+1e-6;
 }
 function resolve(point,previous,velocity,radius=0,ignore=-1,wallExtents=[radius,radius]){
  let touched=false;const pit=model.groundCutout;
  if(pit&&previous[0]>pit[0]&&previous[0]<pit[2]&&previous[1]>pit[1]&&previous[1]<pit[3]&&previous[2]-radius<-.02){
   for(let k=0;k<2;k++){const extent=wallExtents[k];if(point[k]<pit[k]+extent||point[k]>pit[k+2]-extent){const normal=[0,0,0];normal[k]=point[k]<pit[k]+extent?1:-1;point[k]=Math.max(pit[k]+extent,Math.min(pit[k+2]-extent,point[k]));response(velocity,normal);counts.pitWallContacts++;touched=true;}}
  }
  let best=null,bestTime=Infinity;
  const lo=[0,1].map(k=>Math.floor(Math.min(point[k],previous[k])/cellSize)),hi=[0,1].map(k=>Math.floor(Math.max(point[k],previous[k])/cellSize));
  const pad=radius/.35+.05,z0=spatial3D?Math.floor((Math.min(previous[2],point[2])-pad)/cellSize):0,z1=spatial3D?Math.floor((Math.max(previous[2],point[2])+pad)/cellSize):0,seen=spatial3D?new Set():null;
  for(let cx=lo[0];cx<=hi[0];cx++)for(let cy=lo[1];cy<=hi[1];cy++)for(let cz=z0;cz<=z1;cz++)for(const face of cells.get(cx+':'+cy+(spatial3D?':'+cz:''))||[]){
   if(seen){if(seen.has(face))continue;seen.add(face);}
   if(Math.max(previous[2],point[2])<face.minZ-.02||Math.min(previous[2],point[2])>face.maxZ+radius/face.n[2]+.05||face.id===ignore||brokenState?.[face.id]||!face.alive())continue;
   const n=face.n,a=face.a,before=n[0]*(previous[0]-a[0])+n[1]*(previous[1]-a[1])+n[2]*(previous[2]-a[2])-radius,after=n[0]*(point[0]-a[0])+n[1]*(point[1]-a[1])+n[2]*(point[2]-a[2])-radius;
   if(before<-.015||after>=0||after>=before)continue;const time=Math.max(0,before)/(before-after),crossing=point.map((v,k)=>previous[k]+time*(v-previous[k]));
   if(time<bestTime&&inside(crossing,face)){best={face,depth:-after};bestTime=time;}
  }
  if(best){for(let k=0;k<3;k++)point[k]+=best.depth*best.face.n[k];response(velocity,best.face.n);counts.floorContacts++;touched=true;}
  const inPit=pit&&point[0]>pit[0]&&point[0]<pit[2]&&point[1]>pit[1]&&point[1]<pit[3],floor=inPit?model.contactFloorZ:0;
  if(point[2]<floor+radius){point[2]=floor+radius;response(velocity,[0,0,1]);counts.groundContacts++;touched=true;}
  return touched;
 }
 function support(point,radius=0,ignore=-1){const pit=model.groundCutout,inPit=pit&&point[0]>pit[0]&&point[0]<pit[2]&&point[1]>pit[1]&&point[1]<pit[3],floor=inPit?model.contactFloorZ:0,gap=point[2]-radius-floor;if(gap>=-.015&&gap<.004)return {supported:true,grounded:true};
  const pad=radius/.35+.05,z0=spatial3D?Math.floor((point[2]-pad)/cellSize):0,z1=spatial3D?Math.floor((point[2]+pad)/cellSize):0;for(let z=z0;z<=z1;z++)for(const face of cells.get(Math.floor(point[0]/cellSize)+':'+Math.floor(point[1]/cellSize)+(spatial3D?':'+z:''))||[]){if(face.id===ignore||brokenState?.[face.id]||!face.alive())continue;const distance=face.n.reduce((s,n,k)=>s+n*(point[k]-face.a[k]),0)-radius;if(distance>=-.015&&distance<.004&&inside(point,face))return {supported:true,grounded:point[2]-radius-floor<.4};}return {supported:false,grounded:false};
 }
 return {update,resolve,support,stats:()=>({...counts}),gridMode:spatial3D?'spatial3D':'planar'};
}
