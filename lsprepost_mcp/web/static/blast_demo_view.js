import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {TransformControls} from 'three/addons/controls/TransformControls.js';
import {createFractureView} from './blast_fracture_view.js';
import {scenePresentation,cameraForBounds} from './blast_demo_presentation.js';
import {createRebarView} from './blast_rebar_view.js';
import {createPowderView} from './blast_powder_view.js';

export function createDemoView(host,model,onMove) {
 const presentation=scenePresentation(model,[4,-10,.8]);let focusedBounds=null,focusedId=null;
 const span=Math.max(model.width,model.depth,model.height),scene=new THREE.Scene();scene.background=new THREE.Color('#e9eeee');scene.fog=new THREE.Fog('#e9eeee',Math.max(65,span*3),Math.max(145,span*8));
 const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
 renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
 renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.2;
 host.prepend(renderer.domElement);renderer.domElement.setAttribute('aria-label',`${model.name||'三层住宅'}实体建筑与爆炸响应三维视图`);
 const camera=new THREE.PerspectiveCamera(38,1,.1,Math.max(200,span*12));camera.up.set(0,0,1);
 const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,0,4);controls.maxPolarAngle=Math.PI*.49;controls.minDistance=4;controls.maxDistance=Math.max(160,span*5);controls.enableDamping=false;
 const light=new THREE.DirectionalLight('#fff4df',3.2);light.position.set(-20,-25,Math.max(40,model.height*2));light.castShadow=true;
 const shadowSpan=Math.max(30,span*.75);Object.assign(light.shadow.camera,{left:-shadowSpan,right:shadowSpan,top:shadowSpan,bottom:-shadowSpan,near:1,far:Math.max(150,span*5)});light.shadow.mapSize.set(2048,2048);light.shadow.bias=-.0002;
 scene.add(light,new THREE.HemisphereLight('#eaf3ff','#9a9686',2.1));
 const ground=new THREE.Mesh(new THREE.PlaneGeometry(180,180),new THREE.MeshStandardMaterial({color:'#cbd2d0',roughness:1}));ground.position.z=-.23;ground.receiveShadow=true;scene.add(ground);
 const pad=new THREE.Mesh(new THREE.BoxGeometry(Math.max(30,model.width+10),Math.max(25,model.depth+12),.22),new THREE.MeshStandardMaterial({color:'#c8c9bc',roughness:.95}));pad.position.set(0,-1,-.12);pad.receiveShadow=true;scene.add(pad);
 const grid=new THREE.GridHelper(150,75,'#b7c5c5','#c5cecd');grid.rotation.x=Math.PI/2;grid.position.z=-.22;grid.material.transparent=true;grid.material.opacity=.4;scene.add(grid);
 const cutawayPatches=[];
 if(model.groundCutout){const [x0,y0,x1,y1]=model.groundCutout;for(const [x,y,w,h] of [[(-90+x0)/2,0,x0+90,180],[(x1+90)/2,0,90-x1,180],[(x0+x1)/2,(-90+y0)/2,x1-x0,y0+90],[(x0+x1)/2,(y1+90)/2,x1-x0,90-y1]]){const patch=new THREE.Mesh(new THREE.BoxGeometry(w,h,.15),new THREE.MeshStandardMaterial({color:'#c8c9bc',roughness:1}));patch.position.set(x,y,-.075);patch.receiveShadow=true;scene.add(patch);cutawayPatches.push(patch);}}
 const geometry=new THREE.BoxGeometry(1,1,1),material=new THREE.MeshStandardMaterial({color:'#ffffff',roughness:.86});
 const mesh=new THREE.InstancedMesh(geometry,material,model.bodies.length);mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);mesh.castShadow=true;mesh.receiveShadow=true;mesh.frustumCulled=false;scene.add(mesh);
 const transparentIndices=model.bodies.flatMap((b,i)=>b.transparent?[i]:[]),transparentMap=new Map(transparentIndices.map((i,j)=>[i,j]));
 const glassMesh=transparentIndices.length?new THREE.InstancedMesh(geometry,new THREE.MeshStandardMaterial({color:'#a9ced5',roughness:.25,transparent:true,opacity:.32,depthWrite:false,side:THREE.DoubleSide}),transparentIndices.length):null;
 if(glassMesh){glassMesh.frustumCulled=false;scene.add(glassMesh);}
 const dummy=new THREE.Object3D(),baseColors=model.bodies.map(b=>new THREE.Color(b.color)),damageColor=new THREE.Color();
 let latest=null,damageMode=false,roof=true,dust=true,cutaway=!!model.cutaway,sourceMass=160,source=[4,-10,.8],allEvents=[],smokeEvents=[],time=0;
 const fractureView=createFractureView(scene,model);
 const rebarView=createRebarView(scene,model);
 const powderView=createPowderView(scene);
 const sourceMesh=new THREE.Mesh(new THREE.CylinderGeometry(.28,.28,.62,24),new THREE.MeshStandardMaterial({color:'#c77342',roughness:.6,metalness:.08}));sourceMesh.rotation.x=Math.PI/2;sourceMesh.castShadow=true;scene.add(sourceMesh);
 const gizmo=new TransformControls(camera,renderer.domElement);gizmo.setMode('translate');gizmo.setSize(.75);gizmo.showZ=false;gizmo.attach(sourceMesh);scene.add(gizmo.getHelper());
 gizmo.addEventListener('dragging-changed',e=>{controls.enabled=!e.value;});
 gizmo.addEventListener('objectChange',()=>{source=sourceMesh.position.toArray();onMove(source);render();});
 const flash=new THREE.Mesh(new THREE.SphereGeometry(1,24,16),new THREE.MeshBasicMaterial({color:'#ffbb64',transparent:true,depthWrite:false}));scene.add(flash);
 const ring=new THREE.Mesh(new THREE.RingGeometry(.94,1,96),new THREE.MeshBasicMaterial({color:'#fff9e7',transparent:true,side:THREE.DoubleSide,depthWrite:false}));ring.position.z=.025;scene.add(ring);
 const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;const ctx=canvas.getContext('2d'),gradient=ctx.createRadialGradient(64,64,5,64,64,62);
 gradient.addColorStop(0,'rgba(255,255,255,.75)');gradient.addColorStop(.4,'rgba(255,255,255,.42)');gradient.addColorStop(1,'rgba(255,255,255,0)');ctx.fillStyle=gradient;ctx.fillRect(0,0,128,128);
 const texture=new THREE.CanvasTexture(canvas),smoke=[];
 for(let i=0;i<200;i++) {
  const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,color:i%3?'#887b69':'#b8ac96',transparent:true,opacity:0,depthWrite:false}));sprite.visible=false;scene.add(sprite);smoke.push(sprite);
 }
 const random=i=>{const a=Math.sin(i*91.7+17.1)*12345.678;return a-Math.floor(a);};
 const signLabels=(model.labels||[]).map(label=>{const c=document.createElement('canvas');c.width=1024;c.height=128;const context=c.getContext('2d');context.font='bold 76px Microsoft YaHei, sans-serif';context.textAlign='center';context.textBaseline='middle';context.fillStyle=label.color||'#fff';context.fillText(label.text,512,64,980);const b=model.bodies[label.body],w=Math.max(b.size[0],b.size[1])*.9,thinX=b.size[0]<b.size[1];const sprite=new THREE.Mesh(new THREE.PlaneGeometry(w,Math.min(.65,b.size[2]*.8)),new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(c),transparent:true,depthWrite:false,side:THREE.DoubleSide}));const basis=new THREE.Matrix4().makeBasis(new THREE.Vector3(...(thinX?[0,-1,0]:[1,0,0])),new THREE.Vector3(0,0,1),new THREE.Vector3(...(thinX?[-1,0,0]:[0,-1,0]))),orientation=new THREE.Quaternion().setFromRotationMatrix(basis),offset=new THREE.Vector3(...(thinX?[-b.size[0]/2-.01,0,0]:[0,-b.size[1]/2-.01,0]));scene.add(sprite);return {...label,sprite,orientation,offset};});
 function updateInstances(){
  fractureView.frame(latest?.fracture,damageMode,roof,cutaway);
  rebarView.frame(latest,roof);
  ground.visible=!cutaway;pad.visible=!model.layout&&!model.groundCutout;grid.visible=!model.groundCutout;for(const patch of cutawayPatches)patch.visible=cutaway;
  for(let i=0;i<model.bodies.length;i++) {
   const b=model.bodies[i];dummy.position.fromArray(latest?.poses||b.center,latest?i*7:0);latest?dummy.quaternion.fromArray(latest.poses,i*7+3):dummy.quaternion.fromArray(b.rotation||[0,0,0,1]);
   dummy.scale.fromArray(b.size);if(fractureView.contains(i)||(!roof&&(b.isRoof??b.floor>=model.storeys))||(cutaway&&b.cutawayHidden))dummy.scale.setScalar(0);
   dummy.updateMatrix();if(transparentMap.has(i)){glassMesh.setMatrixAt(transparentMap.get(i),dummy.matrix);dummy.scale.setScalar(0);dummy.updateMatrix();}mesh.setMatrixAt(i,dummy.matrix);
   if(damageMode){const d=latest?.damage[i]||0;damageColor.setHSL(.55*(1-d),.6,.56);mesh.setColorAt(i,damageColor);}else mesh.setColorAt(i,baseColors[i]);
  }
  if(glassMesh)glassMesh.instanceMatrix.needsUpdate=true;
  for(const label of signLabels){const b=model.bodies[label.body],q=new THREE.Quaternion().fromArray(latest?.poses||b.rotation||[0,0,0,1],latest?label.body*7+3:0);label.sprite.position.fromArray(latest?.poses||b.center,latest?label.body*7:0).add(label.offset.clone().applyQuaternion(q));label.sprite.quaternion.copy(q).multiply(label.orientation);label.sprite.visible=(roof||!b.isRoof)&&!fractureView.contains(b.id)&&!(cutaway&&b.cutawayHidden);}
  mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;
 }
 function effects(){
  powderView.frame(allEvents,time,dust,renderer.domElement.height/(2*Math.tan(camera.fov*Math.PI/360)));
  const age=time-.15;flash.visible=sourceMass>0&&age>=0&&age<.35;flash.position.fromArray(source);flash.scale.setScalar(.1+Math.max(0,age)*7);flash.material.opacity=Math.max(0,1-age/.35)*.85;
  ring.visible=sourceMass>0&&age>0&&age<1.5;ring.position.x=source[0];ring.position.y=source[1];ring.scale.setScalar(Math.max(.01,age*20));ring.material.opacity=Math.max(0,.55-age*.4);
  for(let i=0;i<smoke.length;i++) {
   const sprite=smoke[i],event=i<35?{time:.15,position:source}:smokeEvents[(i-35)*7%Math.max(1,smokeEvents.length)],a=event?time-event.time:-1;
   sprite.visible=i<presentation.smokeLimit&&sourceMass>0&&dust&&a>0&&a<6;if(!sprite.visible)continue;
   const dx=(random(i*3)-.5),dy=(random(i*3+1)-.5),lift=random(i*3+2);
   const spread=i<35?2.2:1.2;
   const pit=model.groundCutout,floor=pit&&event.position[0]>pit[0]&&event.position[0]<pit[2]&&event.position[1]>pit[1]&&event.position[1]<pit[3]?model.contactFloorZ:0;
   sprite.position.set(event.position[0]+dx*a*spread,event.position[1]+dy*a*spread,Math.max(floor+.3,event.position[2]+a*(.5+lift)-.06*a*a));
   const radius=.2+a*(.5+lift*.35);sprite.scale.set(radius*2,radius*2,1);sprite.material.opacity=presentation.smokeOpacity*(i<35?.65:.45)*(1-Math.exp(-a*7))*Math.exp(-a*.55);
  }
 }
 function render(){
  camera.updateMatrixWorld();const p=sourceMesh.position.clone().add(new THREE.Vector3(0,0,.7)).project(camera),tag=host.querySelector('#sourceTag');
  if(tag){tag.style.left=(p.x*.5+.5)*host.clientWidth+'px';tag.style.top=(-p.y*.5+.5)*host.clientHeight+'px';tag.hidden=p.z>1||p.z<0;}
  renderer.render(scene,camera);
 }
 function fit(){
  focusedBounds=null;focusedId=null;host.dataset.viewMode='overview';delete host.dataset.focusId;
  if(!model.buildingId||model.buildingId==='residence-3'){camera.position.set(26,-36,23);controls.target.set(0,-.8,4.2);}
  else {const radius=Math.hypot(model.width,model.depth+2,model.height)/2,distance=radius/Math.sin(camera.fov*Math.PI/360)*1.12*Math.max(1,1/camera.aspect);if(model.bounds){controls.target.fromArray(model.bounds.min.map((v,i)=>(v+model.bounds.max[i])/2));}else controls.target.set(0,-.8,model.height*.45);camera.position.copy(controls.target).add(new THREE.Vector3(...(model.viewDirection||[26,-36,23])).normalize().multiplyScalar(distance));}
  controls.update();render();
 }
 function focus(bounds,id,direction=model.viewDirection){focusedBounds=bounds;focusedId=id;const frame=cameraForBounds(bounds,camera.aspect,direction,source);controls.maxDistance=Math.max(160,span*5,frame.distance*1.05);camera.position.fromArray(frame.position);controls.target.fromArray(frame.target);controls.update();host.dataset.viewMode='focus';host.dataset.focusId=id||'';render();}
 function resize(){const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h);camera.aspect=w/Math.max(1,h);camera.updateProjectionMatrix();if(focusedBounds)focus(focusedBounds,focusedId,camera.position.clone().sub(controls.target).toArray());else render();}
 const observer=new ResizeObserver(resize);controls.addEventListener('change',render);observer.observe(host);updateInstances();sourceMesh.position.fromArray(source);resize();fit();effects();
 return {
  frame(frame,events=[],t=frame?.time||0){latest=frame;allEvents=events;smokeEvents=events.filter(e=>e.kind!=='pulverized');time=t;updateInstances();effects();render();},
  source(value){source=[...value];sourceMesh.position.fromArray(source);effects();render();},
  charge(value){sourceMass=value;effects();render();},
  mode(value){damageMode=value;updateInstances();render();},
  roof(value){roof=value;updateInstances();render();},
  dust(value){dust=value;effects();render();},
  cutaway(value){cutaway=value;updateInstances();render();},
  editable(value){gizmo.enabled=value;gizmo.getHelper().visible=value;},
  reinforcement(value,inspection=false,revision='k-bundles@1'){const inspect=value&&inspection;material.transparent=inspect;material.opacity=inspect?.06:1;material.depthWrite=!inspect;material.needsUpdate=true;mesh.castShadow=!inspect;fractureView.inspection(inspect);powderView.inspection(inspect);rebarView.mode(value,inspect,revision);render();},
  reinforcementPlan:()=>rebarView.plan,
  reinforcementLayout:()=>rebarView.layout,
  fit,focus,
  framing:()=>({mode:focusedBounds?'focus':'overview',id:focusedId,position:camera.position.toArray(),target:controls.target.toArray(),aspect:camera.aspect,rebar:rebarView.stats(),powder:powderView.stats()}),
  capture(){render();return renderer.domElement.toDataURL('image/png');},
  dispose(){observer.disconnect();controls.dispose();gizmo.dispose();const geometries=new Set(),materials=new Set(),textures=new Set([texture]);scene.traverse(o=>{if(o.geometry)geometries.add(o.geometry);if(o.material)for(const m of Array.isArray(o.material)?o.material:[o.material]){materials.add(m);if(m.map)textures.add(m.map);}});for(const g of geometries)g.dispose();for(const m of materials)m.dispose();for(const t of textures)t.dispose();light.shadow.map?.dispose();renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();}
 };
}
