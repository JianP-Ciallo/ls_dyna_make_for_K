const NS='http://www.w3.org/2000/svg';
function node(tag,attrs,text){const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs||{}))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
export class ResponseCharts{
  constructor(svg){this.svg=svg;this.result=null;this.quantity='displacement';this.cursor=0;this.draw();}
  setResult(result){this.result=result;this.draw();}
  setQuantity(quantity){this.quantity=quantity;this.draw();}
  setCursor(timeS){this.cursor=timeS;if(this.cursorLine){const end=this.result.curves.at(-1).time_s||1;const x=64+timeS/end*910;this.cursorLine.setAttribute('x1',x);this.cursorLine.setAttribute('x2',x);}}
  draw(){
    const svg=this.svg;svg.replaceChildren();const rows=this.result?.curves||[];
    const axis=this.result?.mesh.kind==='column'?0:2;
    const spec={displacement:['monitor_displacement_m',1000,'mm'],velocity:['monitor_velocity_m_s',1,'m/s'],acceleration:['monitor_acceleration_m_s2',1,'m/s²'],steel:['steel_max_pa',1e-6,'MPa'],energy:['energy_j',1,'J']}[this.quantity];
    const series=rows.map(r=>this.quantity==='steel'?[r.steel_max_pa*1e-6,r.steel_min_pa*1e-6]:[(Array.isArray(r[spec[0]])?r[spec[0]][axis]:r[spec[0]])*spec[1]]);
    const values=series.flat();let min=Math.min(0,...values),max=Math.max(0,...values);if(max-min<1e-12){max=1;min=0;}
    const pad=(max-min)*.08;min-=pad;max+=pad;
    const end=rows.at(-1)?.time_s||.15,x=t=>64+t/end*910,y=v=>158-(v-min)/(max-min)*135;
    for(let i=0;i<4;i++){const value=min+(max-min)*i/3,py=y(value);svg.append(node('line',{x1:64,x2:974,y1:py,y2:py,stroke:'#e6eeee'}),node('text',{x:54,y:py+4,'text-anchor':'end',fill:'#81999e','font-size':11},value.toPrecision(3)));}
    for(let i=0;i<4;i++){const t=end*i/3;svg.append(node('text',{x:x(t),y:184,'text-anchor':'middle',fill:'#81999e','font-size':11},(t*1000).toFixed(0)+' ms'));}
    if(rows.length){for(let s=0;s<(this.quantity==='steel'?2:1);s++){svg.append(node('path',{d:rows.map((r,i)=>(i?'L':'M')+x(r.time_s).toFixed(2)+','+y(series[i][s]).toFixed(2)).join(' '),fill:'none',stroke:s?'#cb8f62':'#08898d','stroke-width':1.7}));}}
    else svg.append(node('text',{x:520,y:90,'text-anchor':'middle',fill:'#a0b2b5','font-size':13},'计算后显示实际响应曲线'));
    svg.append(node('text',{x:15,y:15,fill:'#83999f','font-size':10},spec[2]));
    this.cursorLine=node('line',{x1:x(this.cursor),x2:x(this.cursor),y1:20,y2:160,stroke:'#d7985e','stroke-width':1,'stroke-dasharray':'3 3'});svg.append(this.cursorLine);
  }
}
