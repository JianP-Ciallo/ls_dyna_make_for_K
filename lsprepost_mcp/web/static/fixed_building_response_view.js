import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

export class ResponseView{
  constructor(container,onLegend){
    this.container=container;this.onLegend=onLegend;this.result=null;this.frame=0;this.field='displacement';this.filter='all';this.scale=300;
    this.scene=new THREE.Scene();this.scene.background=new THREE.Color(getComputedStyle(container).getPropertyValue('--wb-viewport').trim()||'#f3f8f8');
    this.camera=new THREE.PerspectiveCamera(38,1,.01,100);this.camera.up.set(0,0,1);
    this.renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});this.renderer.setPixelRatio(Math.min(devicePixelRatio,2));
    container.append(this.renderer.domElement);this.controls=new OrbitControls(this.camera,this.renderer.domElement);this.controls.enableDamping=false;
    this.controls.addEventListener('change',()=>this.render());
    this.scene.add(new THREE.HemisphereLight(0xffffff,0x8ba5a5,2.5));const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(4,-4,8);this.scene.add(light);
    this.root=new THREE.Group();this.scene.add(this.root);
    this.grid=new THREE.GridHelper(8,32,0xc6d5d7,0xe0e9e8);this.grid.rotation.x=Math.PI/2;this.grid.position.z=-.18;this.scene.add(this.grid);
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(container);this.resize();
    this.render();
  }
  render(){if(this.renderer&&this.camera&&this.scene)this.renderer.render(this.scene,this.camera);}
  resize(){const w=this.container.clientWidth,h=this.container.clientHeight;if(!w||!h)return;this.renderer.setSize(w,h);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();this.render();}
  clear(){for(const child of [...this.root.children]){child.geometry?.dispose();if(Array.isArray(child.material))child.material.forEach(m=>m.dispose());else child.material?.dispose();this.root.remove(child);}this.result=null;this.render();}
  setResult(result){
    this.clear();this.result=result;if(!result)return;
    this.vertices=[];this.barVertices=[];this.cellSteel=[];
    const model=result.mesh,kind=model.kind;
    if(kind==='column'){
      const b=result.provenance.case.geometry.width_m/2,h=result.provenance.case.geometry.depth_m/2;
      const corners=[[-b,-h],[b,-h],[b,h],[-b,h]];
      for(let e=0;e<model.elements.length;e++)for(let sub=0;sub<8;sub++)for(let side=0;side<4;side++){
        const next=(side+1)%4,t0=sub/8,t1=(sub+1)/8;
        for(const [t,c]of [[t0,side],[t0,next],[t1,next],[t0,side],[t1,next],[t1,side]])this.vertices.push({e,t,side,x:corners[c][0],y:corners[c][1]});
      }
      for(let bar=0;bar<4;bar++)for(let e=0;e<model.elements.length;e++)for(let sub=0;sub<8;sub++){
        const data=model.bars[bar];for(const t of [sub/8,(sub+1)/8])this.barVertices.push({e,t,x:data.y,y:data.z,bar});
      }
    }else{
      for(let e=0;e<model.elements.length;e++){
        for(const z of [-result.provenance.case.geometry.thickness_m/2,result.provenance.case.geometry.thickness_m/2])for(const corner of [0,1,2,0,2,3])this.vertices.push({e,node:model.elements[e][corner],z});
        const groups={};model.steel_samples.forEach((s,i)=>{if(s.element===e+1){const key=s.side+'-'+s.axis;(groups[key]??=[]).push(i);}});this.cellSteel.push(groups);
      }
    }
    this.bodyGeometry=this.geometry(this.vertices.length);
    this.body=new THREE.Mesh(this.bodyGeometry,new THREE.MeshStandardMaterial({vertexColors:true,side:THREE.DoubleSide,transparent:true,opacity:.84,roughness:.65}));this.root.add(this.body);
    if(this.barVertices.length){this.barGeometry=this.geometry(this.barVertices.length);this.bars=new THREE.LineSegments(this.barGeometry,new THREE.LineBasicMaterial({vertexColors:true}));this.root.add(this.bars);}
    this.setFrame(0);
    const outline=new THREE.LineSegments(new THREE.EdgesGeometry(this.bodyGeometry.clone()),new THREE.LineBasicMaterial({color:0x9bb3b7,transparent:true,opacity:.28}));this.root.add(outline);
    this.fit();
  }
  geometry(count){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(new Float32Array(count*3),3));g.setAttribute('color',new THREE.BufferAttribute(new Float32Array(count*3),3));return g;}
  fit(){const panel=this.result?.mesh.kind==='panel';this.controls.target.set(panel?1:0,panel?1:0,panel?0:1.5);this.camera.position.set(panel?4:4,panel?-4:-6,panel?3.5:3.3);this.controls.update();}
  setScale(factor){if(Number.isFinite(factor)&&factor>=1&&factor<=5000){this.scale=factor;this.setFrame(this.frame);}}
  setField(field,filter='all'){this.field=field;this.filter=filter;this.setFrame(this.frame);}
  color(value,max,signed){const c=new THREE.Color();if(signed){const t=Math.max(-1,Math.min(1,value/(max||1)));c.set(t<0?'#207bc8':'#d95b36');c.lerp(new THREE.Color('#f7f7f1'),1-Math.abs(t));}else c.setHSL((1-Math.max(0,Math.min(1,value/(max||1))))*.65,.85,.48);return c;}
  columnPoint(v,frame){
    const [a,b]=this.result.mesh.elements[v.e],p=this.result.mesh.nodes[a],q=this.result.mesh.nodes[b],l=q[2]-p[2],t=v.t;
    const ua=frame.displacements_m[a],ub=frame.displacements_m[b],ra=frame.rotations_rad[a],rb=frame.rotations_rad[b];
    const h1=1-3*t*t+2*t*t*t,h2=t-2*t*t+t*t*t,h3=3*t*t-2*t*t*t,h4=-t*t+t*t*t;
    const u=[h1*ua[0]+h2*l*ra[1]+h3*ub[0]+h4*l*rb[1],h1*ua[1]-h2*l*ra[0]+h3*ub[1]-h4*l*rb[0],ua[2]*(1-t)+ub[2]*t];
    const rx=ra[0]*(1-t)+rb[0]*t,ry=ra[1]*(1-t)+rb[1]*t;
    return {point:[v.x+u[0]*this.scale,v.y+u[1]*this.scale,p[2]+l*t+(u[2]+rx*v.y-ry*v.x)*this.scale],value:Math.hypot(...u)};
  }
  barStress(v,frame){const left=v.t<.5?0:1,f=(v.t-left*.5)*2;return frame.steel_stress_pa[v.e*12+left*4+v.bar]*(1-f)+frame.steel_stress_pa[v.e*12+(left+1)*4+v.bar]*f;}
  setFrame(index){
    if(!this.result)return;this.frame=Math.max(0,Math.min(this.result.frames.length-1,index));const frame=this.result.frames[this.frame],model=this.result.mesh;
    const signed=this.field==='steel';let max=signed?this.result.peaks.steel_abs_pa:this.result.peaks.displacement_m;
    const rows=this.result.provenance.case.loads.curve_si;const t=frame.time_s;let pressure=0;
    for(let i=1;i<rows.length;i++)if(t>=rows[i-1][0]&&t<=rows[i][0])pressure=rows[i-1][1]+(rows[i][1]-rows[i-1][1])*(t-rows[i-1][0])/(rows[i][0]-rows[i-1][0]);
    if(this.field==='pressure')max=Math.max(...rows.map(r=>r[1]));
    const positions=this.bodyGeometry.attributes.position,colors=this.bodyGeometry.attributes.color;
    for(let i=0;i<this.vertices.length;i++){
      const v=this.vertices[i];let point,value;
      if(model.kind==='column'){const out=this.columnPoint(v,frame);point=out.point;value=out.value;if(signed)value=0;}
      else{
        const p=model.nodes[v.node],u=frame.displacements_m[v.node],r=frame.rotations_rad[v.node];point=[p[0]+(u[0]+r[1]*v.z)*this.scale,p[1]+(u[1]-r[0]*v.z)*this.scale,v.z+u[2]*this.scale];value=Math.hypot(...u);
        if(signed){const ids=this.cellSteel[v.e][this.filter]||this.cellSteel[v.e]['top-X'];value=ids.reduce((s,k)=>s+frame.steel_stress_pa[k],0)/ids.length;}
      }
      if(this.field==='pressure'){
        const direction=this.result.provenance.case.loads.direction;
        const face=direction[0]>0?3:direction[0]<0?1:direction[1]>0?0:2;
        value=model.kind==='column'?(v.side===face?pressure:0):(v.z*direction[2]<0?pressure:0);
      }
      positions.setXYZ(i,...point);const color=this.color(value,max,signed);colors.setXYZ(i,color.r,color.g,color.b);
    }
    positions.needsUpdate=true;colors.needsUpdate=true;this.bodyGeometry.computeVertexNormals();
    this.body.material.opacity=model.kind==='column'&&signed?.2:.86;
    if(this.barGeometry){for(let i=0;i<this.barVertices.length;i++){
      const v=this.barVertices[i],out=this.columnPoint(v,frame),selected=this.filter==='all'||this.filter===`bar-${v.bar+1}`;
      const color=signed&&selected?this.color(this.barStress(v,frame),max,true):new THREE.Color(selected?'#49727b':'#c6d6d9');
      this.barGeometry.attributes.position.setXYZ(i,...out.point);this.barGeometry.attributes.color.setXYZ(i,color.r,color.g,color.b);
    }this.barGeometry.attributes.position.needsUpdate=true;this.barGeometry.attributes.color.needsUpdate=true;}
    const divisor=signed?1e6:this.field==='pressure'?1000:.001;
    this.onLegend({signed,min:signed?-max/divisor:0,max:max/divisor,label:signed?'钢筋轴向应力 / MPa':this.field==='pressure'?'施加压力 / kPa':'位移 / mm'});
    this.render();
  }
  png(){return this.renderer.domElement.toDataURL('image/png');}
}
