import * as THREE from 'three';
import {samplePowder} from './blast_powder.js';

export function createPowderView(scene){
 const geometry=new THREE.BufferGeometry(),material=new THREE.ShaderMaterial({transparent:true,depthWrite:false,depthTest:true,uniforms:{pixelScale:{value:900}},
  vertexShader:'attribute float pointSize;attribute float opacityValue;attribute float grainValue;uniform float pixelScale;varying float vOpacity;varying float vGrain;void main(){vec4 p=modelViewMatrix*vec4(position,1.0);gl_Position=projectionMatrix*p;gl_PointSize=clamp(pointSize*pixelScale/max(1.0,-p.z),1.0,180.0);vOpacity=opacityValue;vGrain=grainValue;}',
  fragmentShader:'varying float vOpacity;varying float vGrain;void main(){float r=length(gl_PointCoord-vec2(0.5))*2.0;float a=pow(max(0.0,1.0-r*r),2.0)*vOpacity;if(a<0.002)discard;gl_FragColor=vec4(mix(vec3(0.64,0.62,0.56),vec3(0.78,0.76,0.69),vGrain),a);}'
 }),mesh=new THREE.Points(geometry,material);mesh.name='Pulverized concrete dust';mesh.frustumCulled=false;mesh.renderOrder=4;mesh.visible=false;geometry.setDrawRange(0,0);scene.add(mesh);let capacity=0,inspect=false,enabled=true,last={count:0,clouds:0,representedMass:0,positions:new Float32Array()};
 function frame(events,time,show=true,pixelScale=900){enabled=show;last=samplePowder(events,time,show);if(last.count>capacity){capacity=Math.max(256,last.count);for(const [key,n]of [['position',3],['pointSize',1],['opacityValue',1],['grainValue',1]])geometry.setAttribute(key,new THREE.BufferAttribute(new Float32Array(capacity*n),n));}
  if(last.count)for(const [key,array]of [['position',last.positions],['pointSize',last.sizes],['opacityValue',last.opacities],['grainValue',last.grains]]){geometry.attributes[key].array.set(array);geometry.attributes[key].needsUpdate=true;}
  geometry.setDrawRange(0,last.count);material.uniforms.pixelScale.value=pixelScale;mesh.visible=enabled&&!inspect&&last.count>0;
 }
 return {frame,inspection(value){inspect=value;mesh.visible=enabled&&!inspect&&last.count>0;},stats:()=>({particles:last.count,visibleParticles:mesh.visible?last.count:0,clouds:last.clouds,representedMass:last.representedMass,firstPosition:Array.from(last.positions.slice(0,3))})};
}
