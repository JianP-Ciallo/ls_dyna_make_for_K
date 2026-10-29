/* Constraint attachments transfer steel forces into concrete points and rigid poses. */
const rotate=(p,q)=>{const [x,y,z,w]=q,[a,b,c]=p,tx=2*(y*c-z*b),ty=2*(z*a-x*c),tz=2*(x*b-y*a);return [a+w*tx+y*tz-z*ty,b+w*ty+z*tx-x*tz,c+w*tz+x*ty-y*tx];};
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
export function createConcreteAdapter(model,{x,v,q,w,broken,damage,panels,wakeBody}){
 const concrete=new Set(['slab','column','wall','balcony','stairs','roofbox']);
 function distance(body,p){return p.reduce((s,n,k)=>s+Math.max(0,Math.abs(n-body.center[k])-body.size[k]/2)**2,0);}
 function locateBody(ids,point){
  let id=ids[0],best=Infinity;for(const index of ids){const d=distance(model.bodies[index],point);if(d<best){best=d;id=index;}}
  // Joint extensions may be hosted in the existing slab rather than the column/wall.
  if(best>.000004)for(const body of model.bodies)if(concrete.has(body.role)&&!body.interior){const d=distance(body,point);if(d<best-1e-10){best=d;id=body.id;}}
  return id;
 }
 function bind(ids,point){
  const id=locateBody(ids,point),body=model.bodies[id],surface=panels?.bindPoint(id,point),original=body.rotation||[0,0,0,1],local=rotate(point.map((p,k)=>p-body.center[k]),[-original[0],-original[1],-original[2],original[3]]),mass=Math.max(1e-5,body.size.reduce((s,n)=>s*n,1)),im=body.fixed?0:1/mass;
  // A small copy is required: move() updates q while using this prior pose.
  // Direct reads avoid typed-array iterators in every embedded steel constraint.
  const orientation=()=>[q[id*4],q[id*4+1],q[id*4+2],q[id*4+3]];
  let cachedPose=null,cachedWeight=null;
  function pose(){const h=id*4;if(!cachedPose||cachedPose.rotation.some((n,j)=>n!==q[h+j])){const rotation=orientation();cachedPose={rotation,offset:rotate(local,rotation)};cachedWeight=null;}return cachedPose;}
  const arm=()=>pose().offset;
  function inverseInertia(torque,rotation=pose().rotation){const localTorque=rotate(torque,[-rotation[0],-rotation[1],-rotation[2],rotation[3]]),localResponse=localTorque.map((n,k)=>n*12*im/(body.size[(k+1)%3]**2+body.size[(k+2)%3]**2));return rotate(localResponse,rotation);}
  function rotationalWeight(normal){const current=pose();if(!cachedWeight||cachedWeight.normal!==normal||cachedWeight.values.some((n,j)=>n!==normal[j])){const torque=cross(current.offset,normal);cachedWeight={normal,values:[...normal],torque,angular:inverseInertia(torque,current.rotation)};}return cachedWeight;}
  return {body:id,
   position(){const p=surface?.position();if(p)return p;const offset=arm();return offset.map((n,k)=>n+x[id*3+k]);},
   weight(normal){if(!im)return 0;const weight=surface?.weight();if(weight!==null&&weight!==undefined)return weight;const {torque,angular}=rotationalWeight(normal);return im+torque.reduce((s,n,k)=>s+n*angular[k],0);},
   velocity(){const pv=surface?.velocity();if(pv)return pv;const spin=cross(Array.from(w.subarray(id*3,id*3+3)),arm());return spin.map((n,k)=>n+v[id*3+k]);},
   damage:()=>surface?.damage()??damage[id],
   exposed:()=>surface?.exposed()??!!broken[id],
   removed:()=>surface?.removed?.()||false,
   move(normal,lambda,dt){if(!im||Math.abs(lambda)<1e-15||surface?.removed?.())return;if(surface?.move(normal,lambda,dt))return;
    const angular=rotationalWeight(normal).angular.map(n=>n*lambda),h=id*4,k=id*3,rotation=pose().rotation,spin=cross(angular,rotation.slice(0,3));
    for(let j=0;j<3;j++){const delta=normal[j]*lambda*im;x[k+j]+=delta;v[k+j]+=delta/dt;w[k+j]+=angular[j]/dt;q[h+j]+=.5*(angular[j]*rotation[3]+spin[j]);}q[h+3]-=.5*angular.reduce((s,n,j)=>s+n*rotation[j],0);const norm=Math.hypot(...q.subarray(h,h+4));for(let j=0;j<4;j++)q[h+j]/=norm;wakeBody?.(id);
   },
  };
 }
 return {bind,locateBody,barActive:ids=>ids.some(id=>broken[id]||damage[id]>.15||panels?.steelActive(id)),active:bundle=>bundle.bodyIds.some(id=>broken[id]||damage[id]>.08||panels?.owns(id)),exposed:bundle=>bundle.bodyIds.some(id=>broken[id]||damage[id]>.45||panels?.exposed(id))};
}
