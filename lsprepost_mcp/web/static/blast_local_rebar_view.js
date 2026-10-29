import * as THREE from 'three';
import {localRodPlan} from './blast_local_rebar.js';

// Render exactly the physical rod graph, including separate broken tips.
export function createLocalRebarView(scene,layout){
 const plan=localRodPlan(layout),geometry=new THREE.BufferGeometry(),material=new THREE.LineBasicMaterial({vertexColors:true,toneMapped:false}),mesh=new THREE.LineSegments(geometry,material);mesh.frustumCulled=false;mesh.name='Local inertial K steel';scene.add(mesh);
 let enabled=false,inspection=false,last=null,roof=true,count=0,roofSegments=0,vertices=0,capacity=0;const cold=new THREE.Color('#626665'),warm=new THREE.Color('#897352');
 function update(){const data=last?.rebar?.schema==='local-steel-frame@2'?last.rebar:null,lookup=new Map(data?Array.from(data.ids,(id,i)=>[id,i]):[]),lines=[],colors=[];count=0;roofSegments=0;
  function line(a,b,color){lines.push(...a,...b);colors.push(color.r,color.g,color.b,color.r,color.g,color.b);}
  if(enabled)for(const bar of plan.bars){const index=lookup.get(bar.id),member=layout.members[bar.member],isRoof=['roof','cap','parapet'].includes(member.kind);let seen=false;
   if(index!==undefined){const nodeBase=data.offsets[index]/3;for(let e=data.edgeOffsets[index];e<data.edgeOffsets[index+1];e+=2){const ia=data.edges[e],ib=data.edges[e+1],a=[data.positions[ia*3],data.positions[ia*3+1],data.positions[ia*3+2]],b=[data.positions[ib*3],data.positions[ib*3+1],data.positions[ib*3+2]];
     if(!roof&&!inspection&&isRoof){const moved=node=>{const local=node-nodeBase,rest=bar.points[local];return rest?Math.hypot(...rest.map((v,k)=>v-data.positions[node*3+k])):Infinity;};if(!data.free[ia]&&!data.free[ib]&&Math.max(moved(ia),moved(ib))<.08)continue;}
     line(a,b,inspection&&data.plastic[e/2]>1e-5?warm:cold);seen=true;if(isRoof)roofSegments++;
    }
   }else if(inspection){for(let i=1;i<bar.points.length;i++)line(bar.points[i-1],bar.points[i],cold);seen=true;if(isRoof)roofSegments+=bar.points.length-1;}
   if(seen)count++;
  }
  if(lines.length>capacity){capacity=Math.max(1024,Math.ceil(lines.length*1.3/6)*6);geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(capacity),3));geometry.setAttribute('color',new THREE.BufferAttribute(new Float32Array(capacity),3));}
  if(lines.length){geometry.attributes.position.array.set(lines);geometry.attributes.color.array.set(colors);geometry.attributes.position.needsUpdate=true;geometry.attributes.color.needsUpdate=true;}vertices=lines.length/3;geometry.setDrawRange(0,vertices);mesh.visible=enabled;
 }
 return {frame(frame,showRoof=true){last=frame;roof=showRoof;update();},mode(value,inspect=false){enabled=value;inspection=inspect;material.depthTest=!inspect;mesh.renderOrder=inspect?10:0;update();},stats:()=>({enabled,inspection,bars:layout.bars.length,bundles:plan.bars.length,visibleBars:count,vertices,roofSegments,local:true})};
}
