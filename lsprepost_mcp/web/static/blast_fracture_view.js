import * as THREE from 'three';
import {damageRGB} from './blast_damage_fields.js';

// Triangular prisms keep thickness while their corner nodes deform independently.
export function createFractureView(scene,model){
 const opaque=new THREE.Mesh(new THREE.BufferGeometry(),new THREE.MeshStandardMaterial({vertexColors:true,roughness:.92,side:THREE.DoubleSide}));
 const glass=new THREE.Mesh(new THREE.BufferGeometry(),new THREE.MeshStandardMaterial({vertexColors:true,roughness:.3,transparent:true,opacity:.55,side:THREE.DoubleSide,depthWrite:false}));
 for(const mesh of [opaque,glass]){mesh.castShadow=true;mesh.receiveShadow=true;mesh.frustumCulled=false;scene.add(mesh);}
 const lines=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:'#403a31',transparent:true,opacity:.82}));lines.frustumCulled=false;scene.add(lines);
 let ids=new Set();const color=new THREE.Color();
 function install(mesh,positions,colors){
  const size=positions.length,geometry=mesh.geometry;
  if(!geometry.getAttribute('position')||geometry.getAttribute('position').array.length<size){const capacity=Math.ceil(Math.max(size,1024)/9)*18;geometry.dispose();geometry.deleteAttribute('normal');geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(capacity),3));geometry.setAttribute('color',new THREE.BufferAttribute(new Float32Array(capacity),3));}
  if(size){geometry.attributes.position.array.set(positions);geometry.attributes.color.array.set(colors);geometry.attributes.position.needsUpdate=true;geometry.attributes.color.needsUpdate=true;geometry.setDrawRange(0,size/3);geometry.computeVertexNormals();}else geometry.setDrawRange(0,0);
 }
 function frame(data,damageMode,roof,cutaway){
  ids=new Set(data?.ids||[]);const solid=[],solidColors=[],clear=[],clearColors=[];
  let damageOffset=0;
  if(data)for(let p=0;p<data.ids.length;p++){
   const body=model.bodies[data.ids[p]],start=data.offsets[p],end=data.offsets[p+1];
   const hidden=(!roof&&(body.isRoof??body.floor>=model.storeys))||(cutaway&&body.cutawayHidden),positions=body.role==='glass'?clear:solid,colors=body.role==='glass'?clearColors:solidColors;
   for(let k=start;k<end;k+=9){const a=[data.vertices[k],data.vertices[k+1],data.vertices[k+2]],b=[data.vertices[k+3],data.vertices[k+4],data.vertices[k+5]],c=[data.vertices[k+6],data.vertices[k+7],data.vertices[k+8]],u=b.map((v,j)=>v-a[j]),v=c.map((n,j)=>n-a[j]),normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.max(1e-12,Math.hypot(...normal)),half=(data.thickness?.[damageOffset]??Math.min(...body.size))/2;
    const corners=[a,b,c].flatMap(point=>[1,-1].map(side=>point.map((n,j)=>n+side*normal[j]/length*half)));
    const triangles=[[0,2,4],[1,5,3],[0,1,3],[0,3,2],[2,3,5],[2,5,4],[4,5,1],[4,1,0]],triangleIndex=damageOffset++,d=data.damage[triangleIndex];
    // Cut away covering surfaces, but retain debris that has left the surface.
    if(data.powderedFlags?.[triangleIndex]||(hidden&&!data.detachedFlags[triangleIndex]))continue;if(damageMode)color.setHSL(.55*(1-d),.6,.56);else color.set(body.color);
    for(let face=0;face<triangles.length;face++)for(const vertex of triangles[face]){positions.push(...corners[vertex]);const shade=face<2?1:.86;if(damageMode&&data.nodeDamage){const rgb=damageRGB(data.nodeDamage[triangleIndex*3+Math.floor(vertex/2)]);colors.push(...rgb.map(v=>v*shade));}else colors.push(color.r*shade,color.g*shade,color.b*shade);}
   }
  }
  install(opaque,solid,solidColors);install(glass,clear,clearColors);
  // Crack segments originate from the computed cohesive-edge damage.
  const visible=[];if(data)for(let i=0;i<data.crackIds.length;i++){const b=model.bodies[data.crackIds[i]];if((!roof&&(b.isRoof??b.floor>=model.storeys))||(cutaway&&b.cutawayHidden))continue;for(let k=0;k<6;k++)visible.push(data.cracks[i*6+k]);}
  const cracks=Float32Array.from(visible);let attribute=lines.geometry.getAttribute('position');if(!attribute||attribute.array.length<cracks.length){attribute=new THREE.BufferAttribute(new Float32Array(Math.max(6,cracks.length)*2),3);lines.geometry.setAttribute('position',attribute);}attribute.array.set(cracks);attribute.needsUpdate=true;lines.geometry.setDrawRange(0,cracks.length/3);lines.visible=true;
 }
 return {frame,contains:id=>ids.has(id),stats:()=>({prisms:(opaque.geometry.drawRange.count+glass.geometry.drawRange.count)/24,patches:ids.size}),inspection(value){opaque.material.transparent=value;opaque.material.opacity=value?.06:1;opaque.material.depthWrite=!value;opaque.material.needsUpdate=true;glass.material.opacity=value?.06:.55;}};
}
