/* Local demonstration attachment graph. No cross-instance links or remote
 * floor anchoring for stacked facade tiles and solid parapets. */
export function refinePanelSupports(model){
 const groups=new Map(),planes=new Map(),vertical=[];
 for(const b of model.bodies){const group=b.instanceId||'building';if(!groups.has(group))groups.set(group,[]);groups.get(group).push(b);
  if(b.fixed||b.rotation||!['wall','rail','roofbox'].includes(b.role))continue;
  const thin=b.role==='wall'&&b.normal?Math.abs(b.normal[0])>.5?0:1:b.size.indexOf(Math.min(...b.size));if(thin===2||b.size[thin]>.4)continue;
  const key=group+':'+thin+':'+b.center[thin].toFixed(3);if(!planes.has(key))planes.set(key,[]);planes.get(key).push(b);vertical.push({b,thin,key,group});
 }
 const direct=new Map();
 const overlap=(a,b,k)=>Math.min(a.center[k]+a.size[k]/2,b.center[k]+b.size[k]/2)-Math.max(a.center[k]-a.size[k]/2,b.center[k]-b.size[k]/2);
 for(const {b,thin,key,group} of vertical){
  const bottom=b.center[2]-b.size[2]/2,axis=1-thin;
  const lower=planes.get(key).filter(a=>a.id!==b.id&&a.center[2]<b.center[2]-.01&&Math.abs(a.center[2]+a.size[2]/2-bottom)<.065&&overlap(a,b,axis)>.002);
  const floors=groups.get(group).filter(a=>['slab','roof','balcony'].includes(a.role)&&a.id!==b.id&&bottom-(a.center[2]+a.size[2]/2)<.16&&bottom-(a.center[2]+a.size[2]/2)>-.22&&overlap(a,b,0)>-.025&&overlap(a,b,1)>-.025);
  const candidates=b.role==='rail'&&floors.some(a=>a.role==='balcony')?floors.filter(a=>a.role==='balcony'):lower.length?lower:floors;
  if(candidates.length){b.supports=candidates.sort((a,c)=>Math.abs(a.center[axis]-b.center[axis])-Math.abs(c.center[axis]-b.center[axis])).slice(0,3).map(a=>a.id);direct.set(b.id,true);}
 }
 // A lintel over an opening can bridge to a jamb that itself has a lower support.
 let changed=true;while(changed){changed=false;for(const {b,thin,key} of vertical)if(!direct.has(b.id)&&b.role==='wall'){
  const axis=1-thin,side=planes.get(key).filter(a=>direct.has(a.id)&&Math.abs(overlap(a,b,axis))<.065&&overlap(a,b,2)>.02);
  if(side.length){b.supports=side.slice(0,2).map(a=>a.id);direct.set(b.id,true);changed=true;}
 }}
 return model;
}
