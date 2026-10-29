/* Interactive semantic geometry only; native meshes and exports stay on the server. */
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
const NS='http://www.w3.org/2000/svg';
function element(tag,attrs={},content){const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(content!==undefined)n.textContent=content;return n;}
function corners(b){return [[b[0],b[1],b[2]],[b[3],b[1],b[2]],[b[3],b[4],b[2]],[b[0],b[4],b[2]],[b[0],b[1],b[5]],[b[3],b[1],b[5]],[b[3],b[4],b[5]],[b[0],b[4],b[5]]];}
const faces=[[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]];
const colors={concrete:'#b9b7ab',plaster:'#e4dfd2',masonry:'#ddd4c3',steel:'#637780',metal:'#637780',glass:'#8eafb7',wood:'#ad9373'};
function clearGroup(group){group.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});group.clear();}
function semanticMesh(c){
  const vertices=c.vertices_m||corners(c.bounds_m),positions=[];
  for(const f of faces)for(const i of [f[0],f[1],f[2],f[0],f[2],f[3]])positions.push(...vertices[i]);
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.computeVertexNormals();
  const glass=c.role==='glass',material=new THREE.MeshStandardMaterial({color:c.role==='ground'?'#b9bcb3':colors[c.material]||'#b9b7ab',roughness:.85,transparent:glass,opacity:glass?.3:1,depthWrite:!glass,side:THREE.DoubleSide});
  const mesh=new THREE.Mesh(geometry,material);
  if(!glass)mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry,25),new THREE.LineBasicMaterial({color:'#526c70',transparent:true,opacity:.2})));
  return mesh;
}

export function createTntScene(container,onCameraChange,onCameraEnd,dragCallbacks={}){
  return new TntScene(container,onCameraChange,onCameraEnd,dragCallbacks);
}
class TntScene{
  constructor(container,onCameraChange,onCameraEnd,dragCallbacks){
    this.container=container;this.onCameraChange=onCameraChange;this.frame=25;this.pending=null;this.labels=[];this.initialized=false;
    this.renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));this.renderer.setClearColor('#f6f8fa');this.renderer.outputColorSpace=THREE.SRGBColorSpace;
    const canvas=this.renderer.domElement;canvas.setAttribute('aria-label','拖动旋转、右键平移、滚轮缩放的建筑与TNT模型');container.append(canvas);
    this.world=new THREE.Scene();this.camera=new THREE.OrthographicCamera(-25,25,25,-25,.05,2000);this.camera.up.set(0,0,1);
    this.controls=new OrbitControls(this.camera,container);this.controls.minZoom=.2;this.controls.maxZoom=20;this.controls.enableDamping=false;
    this.controls.addEventListener('change',()=>{if(!this.restoring)this.onCameraChange(this.snapshot());this.render();});
    this.controls.addEventListener('end',()=>onCameraEnd?.());
    this.world.add(new THREE.HemisphereLight('#ffffff','#bbc2b5',2.1));const light=new THREE.DirectionalLight('#fff5e7',2.8);light.position.set(-18,-25,45);this.world.add(light);
    for(const key of ['building','ground','air','tnt','monitors']){this[key]=new THREE.Group();this.world.add(this[key]);}
    this.marker=document.createElement('span');this.marker.className='tnt-marker';this.marker.dataset.tntCylinder='';this.marker.textContent='TNT';this.marker.title='拖动调整X/Y；使用旁边的高度手柄升降；Esc取消';this.marker.hidden=true;container.append(this.marker);
    this.heightHandle=document.createElement('span');this.heightHandle.className='tnt-height-handle';this.heightHandle.dataset.tntHeight='';this.heightHandle.title='向上拖升高，向下拖降低；X/Y保持不变；Esc取消';this.heightHandle.hidden=true;container.append(this.heightHandle);
    this.dragCallbacks=dragCallbacks;this.drag=null;this.raycaster=new THREE.Raycaster();
    this.dragDown=e=>this.startDrag(e);this.dragMove=e=>this.moveDrag(e);this.dragUp=e=>this.finishDrag(e,false);this.dragCancel=e=>this.finishDrag(e,true);
    this.dragKey=e=>{if(this.drag&&e.key==='Escape'){e.preventDefault();e.stopPropagation();this.finishDrag(null,true);}};
    this.dragBlur=()=>this.finishDrag(null,true);this.dragWheel=e=>{if(this.drag){e.preventDefault();e.stopImmediatePropagation();}};
    container.addEventListener('pointerdown',this.dragDown,true);container.addEventListener('pointermove',this.dragMove,true);container.addEventListener('pointerup',this.dragUp,true);container.addEventListener('pointercancel',this.dragCancel,true);container.addEventListener('lostpointercapture',this.dragCancel,true);container.addEventListener('wheel',this.dragWheel,{capture:true,passive:false});
    window.addEventListener('keydown',this.dragKey,true);window.addEventListener('blur',this.dragBlur);
    this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(container);this.resize();
  }
  pointerRay(e){
    const b=this.renderer.domElement.getBoundingClientRect();if(!b.width||!b.height)return null;
    this.camera.updateMatrixWorld();this.raycaster.setFromCamera(new THREE.Vector2((e.clientX-b.left)/b.width*2-1,-(e.clientY-b.top)/b.height*2+1),this.camera);return this.raycaster;
  }
  startDrag(e){
    if(this.drag||e.button!==0||!this.placement||!this.tnt.visible||!this.dragCallbacks.start)return;
    let details;
    if(this.heightHandle.contains(e.target)){
      if(!this.dragCallbacks.height)return;
      details={mode:'height',startY:e.clientY,startHeight:this.placement.bottom_elevation_m-this.geometry.grade_m,metresPerPixel:2*this.frame/(Math.max(this.container.clientHeight,1)*this.camera.zoom)};
    }else{
      const ray=this.pointerRay(e);if(!ray)return;this.tnt.updateMatrixWorld(true);
      if(!this.marker.contains(e.target)&&!ray.intersectObjects(this.tnt.children,true).length)return;
      const center=this.placement.center_m,plane=new THREE.Plane(new THREE.Vector3(0,0,1),-center[2]),hit=ray.ray.intersectPlane(plane,new THREE.Vector3());if(!hit)return;
      details={mode:'xy',plane,offset:[center[0]-hit.x,center[1]-hit.y]};
    }
    if(!this.dragCallbacks.start(details.mode))return;
    this.drag={...details,pointerId:e.pointerId,controlsEnabled:this.controls.enabled};this.controls.enabled=false;
    this.container.dataset.tntDragging='true';this.container.dataset.tntDragMode=details.mode;this.marker.dataset.dragBlocked='false';this.heightHandle.dataset.dragBlocked='false';this.container.setPointerCapture(e.pointerId);e.preventDefault();e.stopImmediatePropagation();
  }
  moveDrag(e){
    const drag=this.drag;if(!drag||e.pointerId!==drag.pointerId)return;e.preventDefault();e.stopImmediatePropagation();
    if(drag.mode==='height'){
      const accepted=this.dragCallbacks.height(drag.startHeight-(e.clientY-drag.startY)*drag.metresPerPixel);this.heightHandle.dataset.dragBlocked=String(!accepted);
    }else{
      const hit=this.pointerRay(e)?.ray.intersectPlane(drag.plane,new THREE.Vector3());if(!hit)return;
      const accepted=this.dragCallbacks.move?.([hit.x+drag.offset[0],hit.y+drag.offset[1]]);this.marker.dataset.dragBlocked=String(!accepted);
    }
  }
  finishDrag(e,cancelled){
    const drag=this.drag;if(!drag||(e&&e.pointerId!==drag.pointerId))return;
    this.drag=null;this.controls.enabled=drag.controlsEnabled;delete this.container.dataset.tntDragging;delete this.container.dataset.tntDragMode;delete this.marker.dataset.dragBlocked;delete this.heightHandle.dataset.dragBlocked;
    if(this.container.hasPointerCapture(drag.pointerId))this.container.releasePointerCapture(drag.pointerId);
    if(e){e.preventDefault();e.stopImmediatePropagation();}this.dragCallbacks.end?.({cancelled});
  }
  snapshot(){return {position:this.camera.position.toArray(),target:this.controls.target.toArray(),zoom:this.camera.zoom,frame:this.frame};}
  restoreCamera(s){
    if(!s||![s.position,s.target].every(v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite))||!Number.isFinite(s.zoom)||!Number.isFinite(s.frame)||s.frame<=0)return;
    this.restoring=true;this.camera.position.fromArray(s.position);this.controls.target.fromArray(s.target);this.camera.zoom=Math.max(.2,Math.min(20,s.zoom));this.frame=s.frame;this.resize();this.controls.update();this.restoring=false;this.onCameraChange(this.snapshot());this.render();
  }
  resize(){
    const w=Math.max(this.container.clientWidth,1),h=Math.max(this.container.clientHeight,1),aspect=w/h;
    this.renderer.setSize(w,h,false);this.camera.left=-this.frame*aspect;this.camera.right=this.frame*aspect;this.camera.top=this.frame;this.camera.bottom=-this.frame;this.camera.updateProjectionMatrix();this.render();
  }
  fit(preset){
    if(!this.geometry)return;const g=this.geometry,bounds=[g.building_bounds_m];
    if(this.ground.visible)bounds.push(g.ground_bounds_m);if(this.air.visible)bounds.push(g.air_bounds_m);
    if(this.placement)bounds.push(this.placement.bounds_m);
    const box=new THREE.Box3();for(const b of bounds)for(const p of corners(b))box.expandByPoint(new THREE.Vector3(...p));
    const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()),extent=Math.max(size.x,size.y,size.z,4);
    let direction=this.camera.position.clone().sub(this.controls.target).normalize();
    if(preset==='plan')direction.set(0,-.001,1).normalize();else if(preset==='3d'||!direction.lengthSq())direction.set(.95,-1.2,.85).normalize();
    this.controls.target.copy(center);this.camera.position.copy(center).addScaledVector(direction,extent*3);this.camera.zoom=1;this.camera.lookAt(center);this.camera.updateMatrixWorld();
    const p=corners([box.min.x,box.min.y,box.min.z,box.max.x,box.max.y,box.max.z]).map(p=>new THREE.Vector3(...p).applyMatrix4(this.camera.matrixWorldInverse));
    const width=Math.max(...p.map(p=>p.x))-Math.min(...p.map(p=>p.x)),height=Math.max(...p.map(p=>p.y))-Math.min(...p.map(p=>p.y));
    this.frame=Math.max(height,width/(Math.max(this.container.clientWidth,1)/Math.max(this.container.clientHeight,1)))*.6;this.resize();this.controls.update();this.onCameraChange(this.snapshot());this.render();
  }
  zoom(factor){this.camera.zoom=Math.max(.2,Math.min(20,this.camera.zoom*factor));this.camera.updateProjectionMatrix();this.controls.update();this.onCameraChange(this.snapshot());this.render();}
  update(geometry,config,placement,view){
    const requested=view.camera;this.geometry=geometry;this.placement=placement;
    if(this.components!==geometry.components){
      clearGroup(this.building);clearGroup(this.ground);for(const c of geometry.components)this.building.add(semanticMesh(c));this.ground.add(semanticMesh({bounds_m:geometry.ground_bounds_m,role:'ground'}));this.components=geometry.components;
    }
    if(JSON.stringify(this.airBounds)!==JSON.stringify(geometry.air_bounds_m)){
      clearGroup(this.air);const b=geometry.air_bounds_m,box=new THREE.BoxGeometry(b[3]-b[0],b[4]-b[1],b[5]-b[2]),edges=new THREE.EdgesGeometry(box);box.dispose();
      const lines=new THREE.LineSegments(edges,new THREE.LineDashedMaterial({color:'#7b9fbb',dashSize:.35,gapSize:.25,transparent:true,opacity:.65}));lines.position.set(...[0,1,2].map(i=>(b[i]+b[i+3])/2));lines.computeLineDistances();this.air.add(lines);this.airBounds=[...b];
    }
    clearGroup(this.tnt);this.marker.hidden=true;this.heightHandle.hidden=true;
    if(placement){const p=placement,mesh=new THREE.Mesh(new THREE.CylinderGeometry(p.diameter_m/2,p.diameter_m/2,p.height_m,32),new THREE.MeshStandardMaterial({color:'#ed913c',roughness:.65}));mesh.rotation.x=Math.PI/2;mesh.position.set(...p.center_m);this.tnt.add(mesh);this.markerPoint=new THREE.Vector3(...p.center_m);this.heightHandle.textContent='↕ '+(p.bottom_elevation_m-geometry.grade_m).toFixed(3)+' m';}
    clearGroup(this.monitors);for(const l of this.labels)l.element.remove();this.labels=[];
    for(const m of config.monitors||[]){const point=new THREE.Vector3(...m.position_m),mesh=new THREE.Mesh(new THREE.SphereGeometry(.075,10,8),new THREE.MeshBasicMaterial({color:'#236f77'}));mesh.position.copy(point);this.monitors.add(mesh);const label=document.createElement('span');label.className='tnt-marker monitor-marker';label.textContent=m.id;this.container.append(label);this.labels.push({element:label,point});}
    for(const key of ['building','ground','air','tnt','monitors'])this[key].visible=!!view.layers[key];
    if(!this.initialized){this.initialized=true;this.fit(view.plan?'plan':'3d');if(requested)this.restoreCamera(requested);}
    this.render();
  }
  render(){
    if(this.pending!==null)return;this.pending=requestAnimationFrame(()=>{this.pending=null;this.renderer.render(this.world,this.camera);
      const place=(label,point,visible)=>{if(!point){label.hidden=true;return;}const p=point.clone().project(this.camera);label.hidden=!visible||Math.abs(p.x)>1||Math.abs(p.y)>1||p.z>1||p.z< -1;label.style.left=(p.x*.5+.5)*this.container.clientWidth+'px';label.style.top=(-p.y*.5+.5)*this.container.clientHeight+'px';};
      place(this.marker,this.markerPoint,!!this.placement&&this.tnt.visible);place(this.heightHandle,this.markerPoint,!!this.placement&&this.tnt.visible&&!!this.dragCallbacks.height);this.heightHandle.style.top=Math.max(14,parseFloat(this.heightHandle.style.top)-34)+'px';for(const l of this.labels)place(l.element,l.point,this.monitors.visible);this.container.dataset.viewReady='true';
    });
  }
  dispose(){this.finishDrag(null,true);if(this.pending!==null)cancelAnimationFrame(this.pending);this.observer.disconnect();this.controls.dispose();
    const c=this.container;c.removeEventListener('pointerdown',this.dragDown,true);c.removeEventListener('pointermove',this.dragMove,true);c.removeEventListener('pointerup',this.dragUp,true);c.removeEventListener('pointercancel',this.dragCancel,true);c.removeEventListener('lostpointercapture',this.dragCancel,true);c.removeEventListener('wheel',this.dragWheel,true);window.removeEventListener('keydown',this.dragKey,true);window.removeEventListener('blur',this.dragBlur);
    this.world.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});this.renderer.dispose();}
}

export function renderPressureChart(svg,curve){
  svg.replaceChildren();
  if(!curve){svg.append(element('text',{x:400,y:175,'text-anchor':'middle',fill:'#789298','font-size':16},'尚无该工况求解结果'));return;}
  const t=curve.time_s.map(v=>v*1000),p=curve.overpressure_pa.map(v=>v/1000);
  const lo=p.reduce((a,b)=>Math.min(a,b),0),hi=p.reduce((a,b)=>Math.max(a,b),.001),start=t[0],end=t.at(-1),range=Math.max(end-start,1e-12);
  const x=v=>70+690*(v-start)/range,y=v=>300-260*(v-lo)/(hi-lo);
  svg.append(element('path',{d:'M70 30 V300 H760',fill:'none',stroke:'#a5b9bc','stroke-width':1.2}));
  svg.append(element('line',{x1:70,x2:760,y1:y(0),y2:y(0),stroke:'#d0dfe0','stroke-dasharray':'4 4'}));
  svg.append(element('polyline',{points:t.map((v,i)=>`${x(v)},${y(p[i])}`).join(' '),fill:'none',stroke:'#227f88','stroke-width':2}));
  for(let i=0;i<=4;i++){const value=start+(end-start)*i/4;svg.append(element('text',{x:x(value),y:324,'text-anchor':'middle',fill:'#627e85','font-size':12},value.toPrecision(4)));}
  svg.append(element('text',{x:415,y:352,'text-anchor':'middle',fill:'#416d77','font-size':13},'实际输出时间 / ms'));
  svg.append(element('text',{x:70,y:18,fill:'#416d77','font-size':13},`超压 / kPa    ${lo.toPrecision(4)} ～ ${hi.toPrecision(4)}`));
}
