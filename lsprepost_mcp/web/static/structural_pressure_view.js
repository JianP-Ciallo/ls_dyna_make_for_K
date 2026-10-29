/* Read-only semantic-envelope drawing; exported surfaces come from the server. */
const NS='http://www.w3.org/2000/svg';
function element(tag,attrs={},content){const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(content!==undefined)n.textContent=content;return n;}
function corners(b){return [[b[0],b[1],b[2]],[b[3],b[1],b[2]],[b[3],b[4],b[2]],[b[0],b[4],b[2]],[b[0],b[1],b[5]],[b[3],b[1],b[5]],[b[3],b[4],b[5]],[b[0],b[4],b[5]]];}
const sides={west:[0,3,7,4],east:[1,5,6,2],south:[0,4,5,1],north:[3,2,6,7],roof:[4,7,6,5]};
export function renderScene(svg,geometry,config,preview,view,onSelect){
  svg.replaceChildren();if(!geometry)return;
  const project=p=>view.plan?[p[0],-p[1]]:[p[0]*.82-p[1]*.58,-p[0]*.27-p[1]*.36-p[2]];
  const reference=view.layers.air&&geometry.air_bounds_m?geometry.air_bounds_m:geometry.ground_bounds_m;
  const ext=[...corners(reference),...corners(geometry.building_bounds_m)].map(project);
  const min=[Math.min(...ext.map(p=>p[0])),Math.min(...ext.map(p=>p[1]))],max=[Math.max(...ext.map(p=>p[0])),Math.max(...ext.map(p=>p[1]))];
  const scale=Math.min(860/Math.max(max[0]-min[0],1),540/Math.max(max[1]-min[1],1))*view.zoom;
  const screen=p=>{const q=project(p);return [500+(q[0]-(min[0]+max[0])/2)*scale,355+(q[1]-(min[1]+max[1])/2)*scale];};
  function polygon(points,attrs){return element('polygon',{points:points.map(p=>screen(p).join(',')).join(' '),...attrs});}
  function box(b,color,cid){
    const points=corners(b),group=element('g',cid?{'data-component':cid}:{});
    for(const [face,opacity]of(view.plan?[['roof',1]]:[['west',.72],['south',.9],['roof',1]])){
      group.append(polygon(sides[face].map(i=>points[i]),{fill:color,'fill-opacity':opacity,stroke:'#365d611f','stroke-width':.7}));
    }
    if(cid){group.addEventListener('click',()=>onSelect(cid));const title=element('title',{},cid);group.append(title);}
    return group;
  }
  if(view.layers.air&&geometry.air_bounds_m){
    const c=corners(geometry.air_bounds_m);for(const[a,b]of [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]]){
      const p=screen(c[a]),q=screen(c[b]);svg.append(element('line',{x1:p[0],y1:p[1],x2:q[0],y2:q[1],stroke:'#7b9fbb','stroke-width':1,'stroke-dasharray':'5 5'}));
    }
  }
  if(view.layers.ground)svg.append(box(geometry.ground_bounds_m,'#b5bdb9'));
  if(view.layers.building){
    const ordered=[...geometry.components].sort((a,b)=>{
      const depth=c=>-(c.bounds_m[0]+c.bounds_m[3])-(c.bounds_m[1]+c.bounds_m[4])+(c.bounds_m[2]+c.bounds_m[5])*.2;
      return depth(a)-depth(b);
    });
    for(const c of ordered){const color=c.id===config?.target.component_id?'#d7b080':(['glass','window_frame'].includes(c.role)?'#92b3bc':(['slab','roof','landing'].includes(c.role)?'#a2c2b6':'#55958a'));svg.append(box(c.bounds_m,color,c.id));}
    const selected=geometry.components.find(c=>c.id===config?.target.component_id);
    if(selected){const points=corners(selected.bounds_m);svg.append(polygon(sides[config.target.face].map(i=>points[i]),{fill:'#e89343','fill-opacity':.75,stroke:'#b5702f','stroke-width':2,'pointer-events':'none'}));}
    for(const points of preview?.segment_points_m||[])svg.append(polygon(points,{fill:'#f2aa53','fill-opacity':.75,stroke:'#a86e32','stroke-width':.8,'pointer-events':'none'}));
  }
  if(view.layers.monitors)for(const m of config?.monitors||[]){const p=screen(m.position_m);svg.append(element('circle',{cx:p[0],cy:p[1],r:5,fill:'#f6f9f8',stroke:'#236f77','stroke-width':2}));svg.append(element('text',{x:p[0]+9,y:p[1]-6,fill:'#296c73','font-size':13},m.id));}
  svg.append(element('text',{x:35,y:665,fill:'#7f9697','font-size':12},view.plan?'X →     Y ↑':'X / Y / Z · m'));
}

export function renderCurve(svg,rows){
  svg.replaceChildren();if(!rows.length){svg.append(element('text',{x:18,y:54,fill:'#99a9a9','font-size':11},'导入载荷后显示曲线'));return;}
  const end=Math.max(rows.at(-1)[0],1e-9),peak=Math.max(...rows.map(r=>r[1]),1e-9);
  svg.append(element('path',{d:'M25 10 V78 H265',fill:'none',stroke:'#d0dedd'}));
  svg.append(element('polyline',{points:rows.map(([t,p])=>`${25+235*t/end},${78-60*p/peak}`).join(' '),fill:'none',stroke:'#2a8b82','stroke-width':2}));
  svg.append(element('text',{x:27,y:96,fill:'#8c9c9d','font-size':9},`0 → ${end.toFixed(2)} ms`));
  svg.append(element('text',{x:150,y:96,fill:'#8c9c9d','font-size':9},`max ${peak.toFixed(3)} kPa`));
}
