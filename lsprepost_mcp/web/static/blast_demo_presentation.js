/* View/demo configuration only. Does not change building or solver state. */
const dot=(a,b)=>a.reduce((s,v,k)=>s+v*b[k],0);
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const unit=v=>{const length=Math.hypot(...v);return length>1e-9?v.map(x=>x/length):unit([1,-1.4,.9]);};
function rotate(p,q=[0,0,0,1]){const [x,y,z,w]=q,[a,b,c]=p,tx=2*(y*c-z*b),ty=2*(z*a-x*c),tz=2*(x*b-y*a);return [a+w*tx+y*tz-z*ty,b+w*ty+z*tx-x*tz,c+w*tz+x*ty-y*tx];}
function bodyBounds(bodies){
 const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
 for(const b of bodies){const axes=[[1,0,0],[0,1,0],[0,0,1]].map(v=>rotate(v,b.rotation));for(let k=0;k<3;k++){const half=axes.reduce((s,v,j)=>s+Math.abs(v[k])*b.size[j]/2,0);min[k]=Math.min(min[k],b.center[k]-half);max[k]=Math.max(max[k],b.center[k]+half);}}
 return {min,max};
}
export function scenePresentation(model,originalSource){
 const instances=(model.instances||[]).filter(i=>!['vehicle','traffic_light'].includes(i.kind)),targets=[];let tower=0;
 for(const instance of instances){
  const bodies=model.bodies.filter(b=>b.instanceId===instance.id);if(!bodies.length)continue;
  const city=model.buildingId==='city_street',label=instance.kind==='supermarket'?(city?'街道商超':'商超主体'):instance.kind.includes('subway')?(city?'街道地铁':'地铁入口'):'住宅 '+(++tower);
  const source=city||instance.kind==='residential_tower'?[instance.center[0],instance.origin[1]-5,.8]:[...originalSource];
  targets.push({id:instance.id,label,source,bounds:bodyBounds(bodies),bodyIds:bodies.map(b=>b.id)});
 }
 if(!targets.length){const bodies=model.bodies.filter(b=>!['ground','road','marking'].includes(b.role));targets.push({id:'building',label:model.name||'建筑主体',source:originalSource?[...originalSource]:[4,-10,.8],bounds:bodyBounds(bodies),bodyIds:bodies.map(b=>b.id)});}
 const preferredId=model.buildingId==='residential_community'?'tower_2':model.buildingId==='city_street'?'supermarket':targets[0].id;
 const bodyTarget=new Int16Array(model.bodies.length).fill(-1);targets.forEach((t,i)=>t.bodyIds.forEach(id=>bodyTarget[id]=i));
 return {targets,preferredId,bodyTarget,smokeOpacity:model.buildingId==='residence-3'?1:model.buildingId==='subway_entrance'?.42:.62,smokeLimit:model.buildingId==='residence-3'?200:120};
}
export function chooseFocusTarget(profile,frame,selection='auto'){
 if(selection&&selection!=='auto'){const target=profile.targets.find(t=>t.id===selection);if(target)return target;}
 let best=profile.targets.find(t=>t.id===profile.preferredId)||profile.targets[0];if(!frame)return best;
 const scores=profile.targets.map(t=>t.bodyIds.reduce((s,id)=>s+(frame.damage?.[id]||0),0));
 if(frame.fracture)for(let p=0;p<frame.fracture.ids.length;p++){const index=profile.bodyTarget[frame.fracture.ids[p]];if(index<0)continue;for(let i=frame.fracture.offsets[p]/9;i<frame.fracture.offsets[p+1]/9;i++)scores[index]+=.08*((frame.fracture.damage[i]||0)+(frame.fracture.detachedFlags[i]||0));}
 let score=0;for(let i=0;i<scores.length;i++)if(scores[i]>score){score=scores[i];best=profile.targets[i];}return best;
}
function corners(bounds){return Array.from({length:8},(_,i)=>[0,1,2].map(k=>i&(1<<k)?bounds.max[k]:bounds.min[k]));}
function basis(direction){const back=unit(direction||[1,-1.4,.9]),horizontal=cross([0,0,1],back),right=Math.hypot(...horizontal)>1e-8?unit(horizontal):[1,0,0],up=unit(cross(back,right));return {back,right,up};}
export function cameraForBounds(bounds,aspect=1,direction,source){
 const min=[...bounds.min],max=[...bounds.max],padding=Math.max(.8,Math.min(2.5,Math.max(max[0]-min[0],max[1]-min[1])*.12));
 for(let k=0;k<3;k++){min[k]-=k===2?.35:padding;max[k]+=k===2?.35:padding;if(source){min[k]=Math.min(min[k],source[k]-.5);max[k]=Math.max(max[k],source[k]+.5);}}
 const target=min.map((v,k)=>(v+max[k])/2),axes=basis(direction),tanY=Math.tan(38*Math.PI/360),tanX=tanY*Math.max(.1,aspect);let distance=4;
 for(const point of corners({min,max})){const v=point.map((x,k)=>x-target[k]),depth=dot(v,axes.back);distance=Math.max(distance,depth+Math.abs(dot(v,axes.right))/tanX*1.08,depth+Math.abs(dot(v,axes.up))/tanY*1.08);}
 return {target,position:target.map((v,k)=>v+axes.back[k]*distance),distance};
}
export function projectedCoverage(bounds,camera,aspect=1){const axes=basis(camera.position.map((v,k)=>v-camera.target[k])),tanY=Math.tan(38*Math.PI/360),tanX=tanY*aspect;let maxX=0,maxY=0,inside=true;
 for(const p of corners(bounds)){const v=p.map((x,k)=>x-camera.target[k]),depth=camera.distance-dot(v,axes.back),x=Math.abs(dot(v,axes.right)/depth/tanX),y=Math.abs(dot(v,axes.up)/depth/tanY);maxX=Math.max(maxX,x);maxY=Math.max(maxY,y);inside&&=depth>0&&x<=1&&y<=1;}return {inside,maxX,maxY};
}
