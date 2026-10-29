import * as THREE from 'three';
import {buildRebarLayout} from './blast_rebar_layout.js';
import {buildBundlePlan} from './blast_rebar_bundles.js';
import {createLocalRebarView} from './blast_local_rebar_view.js';

// Every mapped physical bar is drawn; the displacement field comes from its bundle.
export function createRebarView(scene,model){
 const layout=buildRebarLayout(model),plan=buildBundlePlan(layout),geometry=new THREE.BufferGeometry(),material=new THREE.LineBasicMaterial({vertexColors:true,toneMapped:false}),mesh=new THREE.LineSegments(geometry,material);mesh.frustumCulled=false;mesh.name='K reinforcing steel';scene.add(mesh);
 const localView=createLocalRebarView(scene,layout);let localMode=false;
 const vectors=plan.bundles.map(b=>b.points.map((p,i)=>{const a=b.points[Math.max(0,i-1)],c=b.points[Math.min(b.points.length-1,i+1)];return new THREE.Vector3(...c.map((v,k)=>v-a[k])).normalize();})),paths=layout.bars.map(bar=>{const bundle=plan.bundles[plan.barBundle[bar.id]],representative=layout.bars[bundle.representative],offset=bar.points[0].map((v,k)=>v-representative.points[0][k]);return {bar,bundle,points:bundle.points.map(p=>p.map((v,k)=>v+offset[k]))};});
 const capacity=Math.max(1,paths.reduce((s,p)=>s+(p.points.length-1)*12,0)),positions=new Float32Array(capacity),colors=new Float32Array(capacity);geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));geometry.setDrawRange(0,0);
 let enabled=false,inspection=false,last=null,roof=true,visibleBars=0,roofSegments=0;const rotation=new THREE.Quaternion(),tangent=new THREE.Vector3(),offsetVector=new THREE.Vector3(),cold=new THREE.Color('#53585f'),yieldColor=new THREE.Color('#c38035'),brokenColor=new THREE.Color('#954c3d');
 function update(){let cursor=0;visibleBars=0;roofSegments=0;
  const data=last?.rebar;
  function line(a,b,color){positions.set(a,cursor);positions.set(b,cursor+3);for(let k=0;k<2;k++){colors[cursor+k*3]=color.r;colors[cursor+k*3+1]=color.g;colors[cursor+k*3+2]=color.b;}cursor+=6;}
  if(enabled)for(const {bar,bundle,points} of paths){
   if(!inspection&&!data?.exposed[bundle.id])continue;const member=layout.members[bar.member],isRoof=['roof','cap','parapet'].includes(member.kind);
   let rendered=false;const deformed=points.map((p,i)=>{if(!data)return p;const node=bundle.nodeOffset+i,k=node*3,a=(bundle.nodeOffset+Math.max(0,i-1))*3,c=(bundle.nodeOffset+Math.min(bundle.points.length-1,i+1))*3;tangent.set(data.positions[c]-data.positions[a],data.positions[c+1]-data.positions[a+1],data.positions[c+2]-data.positions[a+2]);if(tangent.lengthSq()<1e-12)tangent.copy(vectors[bundle.id][i]);else tangent.normalize();rotation.setFromUnitVectors(vectors[bundle.id][i],tangent);offsetVector.fromArray(p.map((v,j)=>v-bundle.points[i][j])).applyQuaternion(rotation);return [data.positions[k]+offsetVector.x,data.positions[k+1]+offsetVector.y,data.positions[k+2]+offsetVector.z];});
   for(let i=0;i<deformed.length-1;i++){const a=deformed[i],b=deformed[i+1],edge=bundle.edgeOffset+i;
    // Roof observation removes the stationary covering grid; displaced and broken
    // roof bars remain, and explicit full-steel inspection always includes them.
    if(!roof&&!inspection&&isRoof&&data&&!data.failed[edge]){const moved=index=>Math.hypot(...bundle.points[index].map((v,k)=>v-data.positions[(bundle.nodeOffset+index)*3+k]));if(Math.max(moved(i),moved(i+1))<.08)continue;}
    if(isRoof)roofSegments++;
    if(data?.failed[edge]){const d=Math.hypot(...a.map((v,k)=>v-b[k])),rest=Math.hypot(...points[i].map((v,k)=>v-points[i+1][k])),portion=Math.min(.42,rest*(1+Math.min(.15,data.plastic[edge]))*.5/Math.max(1e-8,d));line(a,a.map((v,k)=>v+(b[k]-v)*portion),brokenColor);line(b,b.map((v,k)=>v+(a[k]-v)*portion),brokenColor);}
    else line(a,b,data?.plastic[edge]>1e-5?yieldColor:cold);rendered=true;
   }if(rendered)visibleBars++;
  }
  mesh.visible=enabled;geometry.setDrawRange(0,cursor/3);geometry.attributes.position.needsUpdate=true;geometry.attributes.color.needsUpdate=true;
 }
 return {layout,plan,frame(frame,showRoof=true){last=frame?.rebar?.schema==='local-steel-frame@2'?null:frame;roof=showRoof;localView.frame(frame,showRoof);if(!localMode)update();},mode(value,inspect=false,revision='k-bundles@1'){localMode=revision==='k-bundles@2';enabled=value&&!localMode;inspection=inspect;localView.mode(value&&localMode,inspect);material.depthTest=!inspect;mesh.renderOrder=inspect?10:0;update();},stats:()=>localMode?localView.stats():({enabled,inspection,bars:layout.bars.length,bundles:plan.bundles.length,visibleBars,vertices:geometry.drawRange.count,roofSegments})};
}
