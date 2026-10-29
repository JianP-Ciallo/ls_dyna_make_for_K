import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
const $=id=>document.getElementById(id),names={whole:'整栋外观',floor:'楼层内部',plan:'俯视平面',front:'正立面'};
const faces=[[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]];
const colors={concrete:'#b9b7ab',plaster:'#e4dfd2',masonry:'#ddd4c3',steel:'#637780',metal:'#637780',glass:'#8eafb7',wood:'#ad9373'};
let sceneData=null,renderer,world,camera,controls,animation,mode='whole',level=0,selected=null;
const meshes=[],labels=[],plane=new THREE.Plane(new THREE.Vector3(0,0,-1),1.3),viewport=$('viewport');
function node(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
function rooms(){return sceneData.rooms.filter(r=>r.level===level&&r.kind!=='shaft');}
function floorZ(){const selected=rooms();return selected.length?Math.min(...selected.map(r=>r.bounds_m[2])):level*3.1;}
function buildMesh(c){
 const positions=[];for(const f of faces)for(const i of [f[0],f[1],f[2],f[0],f[2],f[3]])positions.push(...c.vertices_m[i]);
 const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.computeVertexNormals();
 const glass=c.role==='glass',ground=c.role==='ground';
 const material=new THREE.MeshStandardMaterial({color:ground?'#b9bcb3':colors[c.material]||colors.concrete,roughness:glass?.2:.85,metalness:c.material==='steel'?.35:0,transparent:glass,opacity:glass?.25:1,depthWrite:!glass,side:THREE.DoubleSide,clippingPlanes:[],clipShadows:true});
 const mesh=new THREE.Mesh(geometry,material);mesh.userData=c;mesh.castShadow=!glass&&!ground;mesh.receiveShadow=true;
 if(!ground){const edge=new THREE.LineSegments(new THREE.EdgesGeometry(geometry,25),new THREE.LineBasicMaterial({color:'#526c70',transparent:true,opacity:.2,clippingPlanes:[]}));mesh.add(edge);}
 world.add(mesh);meshes.push(mesh);
}
function roomList(){
 $('roomList').replaceChildren();for(const r of rooms()){const b=node('button',(r.unit==='west'?'西户 · ':r.unit==='east'?'东户 · ':'')+(r.label||r.id));b.dataset.room=r.id;b.classList.toggle('selected',r.id===selected);b.onclick=()=>selectRoom(r.id);$('roomList').append(b);}
}
function selectRoom(id){
 const r=sceneData.rooms.find(r=>r.id===id);if(!r)return;selected=id;const b=r.bounds_m;
 $('selection').replaceChildren(node('h3',r.label||r.id),node('p',`${r.level+1} 层 · ${r.unit==='west'?'西侧住户':r.unit==='east'?'东侧住户':'公共空间'}`),node('p',`平面尺寸 ${(b[3]-b[0]).toFixed(2)} × ${(b[4]-b[1]).toFixed(2)} m`),node('p',`投影面积 ${(r.area_m2??(b[3]-b[0])*(b[4]-b[1])).toFixed(2)} m²`),node('p','空间与构件来自同一固定模板，不表示门洞净空或结构连接验收。'));
 roomList();for(const l of labels)l.element.classList.toggle('selected',l.room.id===id);
}
function rebuildLabels(){
 $('roomLabels').replaceChildren();labels.length=0;if(!['floor','plan'].includes(mode)||!$('showLabels').checked)return;
 for(const r of rooms().filter(r=>!['corridor','entry','stairwell','lobby'].includes(r.kind))){const b=node('button',r.label||r.id);b.className='room-tag';b.classList.toggle('selected',r.id===selected);b.onclick=()=>selectRoom(r.id);$('roomLabels').append(b);labels.push({element:b,room:r});}
}
function visibility(){
 if(!sceneData)return;const interior=['floor','plan'].includes(mode);plane.constant=floorZ()+Number($('section').value);
 for(const m of meshes){const c=m.userData;let visible=!interior||c.level===level;
  if(c.role==='ground')visible=!interior&&$('showGround').checked;
  if(['roof','canopy'].includes(c.role)&&(interior||!$('showRoof').checked))visible=false;
  if(['glass','window_frame','door'].includes(c.role)&&!$('showWindows').checked)visible=false;
  if(['stair','landing','shaft'].includes(c.role)&&!$('showStairs').checked)visible=false;
  m.visible=visible;const clipping=interior?[plane]:[];m.material.clippingPlanes=clipping;for(const edge of m.children)edge.material.clippingPlanes=clipping;
 }
 rebuildLabels();roomList();$('viewState').textContent=names[mode]+(interior?' · '+(level+1)+' 层':'');
}
function fit(){
 if(!sceneData)return;const box=new THREE.Box3();for(const m of meshes)if(m.visible&&m.userData.role!=='ground'){const b=m.userData.bounds_m;box.expandByPoint(new THREE.Vector3(...b.slice(0,3)));box.expandByPoint(new THREE.Vector3(...b.slice(3)));}if(box.isEmpty())return;
 const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()),extent=Math.max(size.x,size.y,size.z,4);
 if(['floor','plan'].includes(mode))center.z=floorZ()+.35;
 controls.target.copy(center);camera.up.set(0,0,1);controls.enableRotate=mode!=='plan';
 if(mode==='plan'){camera.position.copy(center).add(new THREE.Vector3(0,0,extent*3));camera.up.set(0,1,0);}
 else if(mode==='front')camera.position.copy(center).add(new THREE.Vector3(0,-extent*3,0));
 else camera.position.copy(center).add(new THREE.Vector3(extent*.95,-extent*1.2,extent*(mode==='floor'?1.55:.85)));
 camera.lookAt(center);camera.zoom=1;camera.updateMatrixWorld();
 const projected=[];for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z])projected.push(new THREE.Vector3(x,y,z).applyMatrix4(camera.matrixWorldInverse));
 const width=Math.max(...projected.map(p=>p.x))-Math.min(...projected.map(p=>p.x)),height=Math.max(...projected.map(p=>p.y))-Math.min(...projected.map(p=>p.y)),aspect=Math.max(viewport.clientWidth/viewport.clientHeight,.2),frame=Math.max(height,width/aspect)*.62;
 camera.left=-frame*aspect;camera.right=frame*aspect;camera.top=frame;camera.bottom=-frame;camera.updateProjectionMatrix();controls.update();
}
function setMode(next){mode=next;for(const b of document.querySelectorAll('[data-view]'))b.classList.toggle('active',b.dataset.view===mode);visibility();fit();}
function frame(){
 animation=requestAnimationFrame(frame);controls.update();renderer.render(world,camera);
 for(const label of labels){const b=label.room.bounds_m,position=new THREE.Vector3((b[0]+b[3])/2,(b[1]+b[4])/2,floorZ()+.35).project(camera);label.element.style.left=((position.x*.5+.5)*viewport.clientWidth)+'px';label.element.style.top=((-position.y*.5+.5)*viewport.clientHeight)+'px';label.element.hidden=Math.abs(position.x)>1||Math.abs(position.y)>1||position.z>1;}
}
async function boot(){
 try{
  const response=await fetch('/api/architecture/pressure/preview-scene'),data=await response.json();if(!response.ok)throw Error(data.error||'固定建筑预览未配置');sceneData=data;
  renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));renderer.setClearColor(getComputedStyle(viewport).getPropertyValue('--wb-viewport').trim()||'#eef3ef');renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.25;renderer.localClippingEnabled=true;renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;viewport.append(renderer.domElement);
  world=new THREE.Scene();camera=new THREE.OrthographicCamera(-20,20,20,-20,.1,1000);camera.up.set(0,0,1);controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.12;controls.minZoom=.2;controls.maxZoom=10;
  world.add(new THREE.HemisphereLight('#ffffff','#c6c2b5',2.2));const light=new THREE.DirectionalLight('#fff5e7',3.1);light.position.set(-18,-25,45);light.castShadow=true;light.shadow.mapSize.set(2048,2048);light.shadow.camera.left=-45;light.shadow.camera.right=45;light.shadow.camera.top=45;light.shadow.camera.bottom=-45;light.shadow.camera.far=130;light.shadow.bias=-.0007;world.add(light);
  for(const c of [...data.components,data.ground])buildMesh(c);for(const l of data.levels){const option=node('option',(l+1)+' 层');option.value=l;$('level').append(option);}level=data.levels[0];
  const ground=data.ground.bounds_m;$('templateIdentity').textContent=data.template_id+' · 固定模板';$('templateIdentity').title=data.template_fingerprint;
  $('templateSummary').textContent=`${data.levels.length} 层住宅\n${data.components.length} 个结构构件\n${data.rooms.length} 个房间与公共空间\n${(ground[3]-ground[0]).toFixed(1)} × ${(ground[4]-ground[1]).toFixed(1)} m 场地`;
  $('componentCount').textContent=data.components.length+' 个构件';$('roomCount').textContent=data.rooms.length+' 个空间';$('groundSummary').textContent='混凝土地面 '+(ground[5]-ground[2]).toFixed(1)+' m 厚';
  const resize=()=>{renderer.setSize(viewport.clientWidth,viewport.clientHeight);fit();};const observer=new ResizeObserver(resize);observer.observe(viewport);resize();visibility();fit();frame();status('固定建筑已载入；显示操作不生成网格或启动求解');
  await registerBuildingNavigation();
  window.addEventListener('pagehide',()=>{cancelAnimationFrame(animation);observer.disconnect();controls.dispose();for(const mesh of meshes)mesh.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});renderer.dispose();},{once:true});
 }catch(error){$('loadFailure').hidden=false;$('loadFailure').textContent=error.message;status(error.message,true);for(const b of document.querySelectorAll('[data-view],#fitView,#level'))b.disabled=true;}
}
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>setMode(b.dataset.view);
$('fitView').onclick=fit;$('level').onchange=()=>{level=Number($('level').value);selected=null;visibility();fit();};
for(const id of ['showRoof','showWindows','showStairs','showGround','showLabels'])$(id).onchange=visibility;
$('section').oninput=()=>{$('sectionValue').textContent=Number($('section').value).toFixed(2)+' m';visibility();};
boot();

async function registerBuildingNavigation(){
 const n=window.WorkbenchNavigation;if(!n)return;
 await n.register('building',{
  restoreIdentity:()=>new URL(location.href).searchParams.get('scene_id')||'template',
  context:()=>({identity:new URL(location.href).searchParams.get('scene_id')||'template',revision:sceneData.template_fingerprint,label:'三层固定建筑',url:location.pathname+location.search}),
  capture:()=>({fields:n.captureFields(document.body),mode,level,selected}),
  restore:s=>{n.restoreFields(document.body,s.fields);level=Number($('level').value);setMode(Object.hasOwn(names,s.mode)?s.mode:'whole');if(s.selected&&rooms().some(r=>r.id===s.selected))selectRoom(s.selected);$('sectionValue').textContent=Number($('section').value).toFixed(2)+' m';},
 });
}
