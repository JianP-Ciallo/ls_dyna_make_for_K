import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {TransformControls} from 'three/addons/controls/TransformControls.js';

const FACES=[[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]];
export function createSceneView(host,{onSelect,onMove}) {
  const scene=new THREE.Scene();scene.background=new THREE.Color('#f3f6f8');
  const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.9;
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));host.append(renderer.domElement);
  const tntLabel=document.createElement('span');tntLabel.className='scene-tnt-label';tntLabel.textContent='TNT';host.append(tntLabel);
  const camera=new THREE.PerspectiveCamera(40,1,.05,5000);camera.up.set(0,0,1);
  const orbit=new OrbitControls(camera,renderer.domElement);orbit.screenSpacePanning=true;
  scene.add(new THREE.HemisphereLight(0xffffff,0xa6b9bf,1.5));
  const light=new THREE.DirectionalLight(0xffffff,2.0);light.position.set(20,-30,45);scene.add(light);
  const root=new THREE.Group(),context=new THREE.Group();scene.add(root,context);
  const grid=new THREE.GridHelper(150,60,0xcbd8dd,0xe0e8eb);grid.rotation.x=Math.PI/2;grid.position.z=-.25;scene.add(grid);
  const ground=new THREE.Mesh(new THREE.PlaneGeometry(180,180),new THREE.MeshBasicMaterial({color:0xeaf0f3,transparent:true,opacity:.55,depthWrite:false}));ground.position.z=-.28;scene.add(ground);
  const tnt=new THREE.Group();scene.add(tnt);
  const cylinder=new THREE.Mesh(new THREE.CylinderGeometry(.3,.3,.65,24),new THREE.MeshStandardMaterial({color:0xf17d48,roughness:.7}));cylinder.rotation.x=Math.PI/2;cylinder.position.z=.325;tnt.add(cylinder);
  const ring=new THREE.Mesh(new THREE.RingGeometry(.48,.53,48),new THREE.MeshBasicMaterial({color:0xeb8d65,side:THREE.DoubleSide}));ring.position.z=.012;tnt.add(ring);
  const transform=new TransformControls(camera,renderer.domElement);transform.setMode('translate');transform.showZ=false;transform.setSize(.7);transform.attach(tnt);scene.add(transform.getHelper());
  let moving=false,syncing=false,model=null,meshes=[],selected=null,queued=false,down=null;
  function render(){if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;renderer.render(scene,camera);const p=tnt.position.clone().project(camera);tntLabel.style.left=(p.x+1)*host.clientWidth/2+'px';tntLabel.style.top=(1-p.y)*host.clientHeight/2+'px';tntLabel.hidden=Math.abs(p.x)>1||Math.abs(p.y)>1||p.z>1;tntLabel.title=tnt.position.toArray().map(v=>v.toFixed(3)).join(', ')+' m';});}
  orbit.addEventListener('change',render);transform.addEventListener('change',render);
  transform.addEventListener('dragging-changed',e=>{moving=e.value;orbit.enabled=!e.value;});
  transform.addEventListener('objectChange',()=>{if(syncing)return;tnt.position.z=0;onMove([tnt.position.x,tnt.position.y,0]);render();});
  function geometry(vertices,center=[0,0,0]) {
    const values=[];
    for(const face of FACES)for(const i of [face[0],face[1],face[2],face[0],face[2],face[3]])values.push(...vertices[i].map((v,k)=>v-center[k]));
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(values,3));g.computeVertexNormals();return g;
  }
  function clear(group){for(const child of [...group.children]){group.remove(child);child.traverse(o=>{o.geometry?.dispose();if(o.material)for(const m of [o.material].flat())m.dispose();});}}
  function fit(){
    if(!model)return;const b=model.bounds_m,center=new THREE.Vector3((b[0]+b[3])/2,(b[1]+b[4])/2,(b[2]+b[5])/2);
    const radius=Math.max(Math.hypot(b[3]-b[0],b[4]-b[1],b[5]-b[2])/2,3),v=camera.fov*Math.PI/180,h=2*Math.atan(Math.tan(v/2)*camera.aspect),distance=radius/Math.sin(Math.min(v,h)/2)*1.08;
    camera.position.copy(center).add(new THREE.Vector3(.95,-1.35,.9).normalize().multiplyScalar(distance));orbit.target.copy(center);camera.far=Math.max(1000,radius*25);camera.updateProjectionMatrix();orbit.update();render();
  }
  function load(value){
    model=value;clear(root);clear(context);selected=null;
    meshes=value.display.map((item,index)=>{
      const body=value.bodies[item.body];const glass=['glass','window'].includes(item.role),color=glass?0xb3d0d8:item.role==='window_frame'?0x819ba5:0xdce2e2;
      const mesh=new THREE.Mesh(geometry(item.vertices_m,body.center_m),new THREE.MeshStandardMaterial({color,roughness:.85,metalness:0,side:THREE.DoubleSide,transparent:glass,opacity:glass?.55:1}));
      mesh.position.fromArray(body.center_m);mesh.userData={index,body:item.body,baseColor:color,item};
      const edges=new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry,25),new THREE.LineBasicMaterial({color:0x8c9fa8,transparent:true,opacity:.26}));mesh.add(edges);root.add(mesh);return mesh;
    });
    for(const item of value.context||[]){
      if(item.role==='non_structural_visual_guide'||item.id.startsWith('tnt_entity'))continue;
      const g=item.geometry,t=item.transform||{},p=t.translate_m||[0,0,0];let dims;
      if(item.template==='parked_vehicle')dims=[g.length_m,g.width_m,g.body_height_m+g.cabin_height_m];
      else if(item.template==='parking_lot'||item.template==='shell_plate')dims=[g.length_m,g.width_m,.025];
      else if(item.template==='traffic_light')dims=[.15,.15,g.pole_height_m];else continue;
      const mesh=new THREE.Mesh(new THREE.BoxGeometry(...dims),new THREE.MeshStandardMaterial({color:item.template==='parked_vehicle'?0x9baab5:0xd9e3e7,roughness:1}));mesh.position.set(p[0]+dims[0]/2,p[1]+dims[1]/2,p[2]+dims[2]/2-.02);mesh.rotation.z=(t.rotate_deg?.[2]||0)*Math.PI/180;context.add(mesh);
    }
    host.dataset.loadedBodies=String(value.bodies.length);fit();render();
  }
  function frame(value,first,field='appearance',scale=1,max=1){
    const color=new THREE.Color();
    for(const mesh of meshes){
      const idx=mesh.userData.body,body=model.bodies[idx];mesh.position.fromArray(body.center_m);mesh.quaternion.identity();
      if(value){const base=first?.translation_m[idx]||[0,0,0],u=value.translation_m[idx];mesh.position.add(new THREE.Vector3(...u.map((v,k)=>base[k]+(v-base[k])*scale)));mesh.quaternion.fromArray(value.rotation_xyzw[idx]);}
      if(field==='appearance'||!value)mesh.material.color.setHex(mesh.userData.baseColor);
      else{const ratio=Math.max(0,Math.min(1,(value[field]?.[idx]||0)/(max||1)));color.setHSL((1-ratio)*.66,.8,.52);mesh.material.color.copy(color);}
      mesh.material.emissive.setHex(mesh===selected?0x284f57:0x000000);mesh.material.emissiveIntensity=mesh===selected?.35:0;
    }
    render();
  }
  const ray=new THREE.Raycaster();
  renderer.domElement.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY];});
  renderer.domElement.addEventListener('pointerup',e=>{
    if(moving||transform.axis||!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>4)return;
    const r=renderer.domElement.getBoundingClientRect();ray.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);
    const hit=ray.intersectObjects(meshes,false)[0];if(!hit)return;selected=hit.object;onSelect(selected.userData.item,selected.userData.body);render();
  });
  const observer=new ResizeObserver(()=>{const w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);const v=camera.fov*Math.PI/180,previous=Math.min(v,2*Math.atan(Math.tan(v/2)*camera.aspect));camera.aspect=w/h;const next=Math.min(v,2*Math.atan(Math.tan(v/2)*camera.aspect));if(model)camera.position.sub(orbit.target).multiplyScalar(Math.sin(previous/2)/Math.sin(next/2)).add(orbit.target);camera.updateProjectionMatrix();render();});observer.observe(host);
  return {load,frame,fit,setTnt(xyz){syncing=true;tnt.position.fromArray(xyz);syncing=false;render();},
    image(){renderer.render(scene,camera);return renderer.domElement.toDataURL('image/png');},
    dispose(){observer.disconnect();orbit.dispose();transform.dispose();renderer.dispose();clear(root);clear(context);}};
}
