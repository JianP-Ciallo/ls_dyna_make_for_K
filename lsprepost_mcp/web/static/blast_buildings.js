import {SCENE_PRESETS,BUILDING_PRESETS,buildBuilding} from './blast_demo_model.js';
import {createDemoView} from './blast_demo_view.js';
const cards=document.getElementById('buildingCards');
for(const [i,p] of SCENE_PRESETS.entries()){
 const model=buildBuilding({building:p.id}),card=document.createElement('article');card.className='card';card.dataset.buildingId=p.id;
 card.innerHTML=`<div class="preview" aria-label="${p.name}模型预览"></div><div class="card-content"><div class="card-heading"><h2>${p.name}</h2><span class="tag">${i?'原设计场景':'我的三层建筑'}</span></div><p class="facts">${p.summary||'三层住宅 · 双侧阳台'}<br>${model.bodies.length} 个实体构件 · ${p.detail||'保留原三层外观'}</p><a class="open" href="/cpu-blast?building=${p.id}" target="_blank" rel="noopener">独立打开并模拟 ↗</a></div>`;
 cards.append(card);
 await new Promise(requestAnimationFrame);
 const host=card.querySelector('.preview'),view=createDemoView(host,model,()=>{});
 view.editable(false);view.source(p.source);view.charge(0);view.frame(undefined);view.fit();
 const image=new Image();image.alt=p.name+'的独立实体构件模型';image.src=view.capture();
 view.dispose();host.append(image);
}
const extras=document.getElementById('extraExamples');if(extras)extras.innerHTML=BUILDING_PRESETS.slice(1).map(p=>`<a href="./blast_demo.html?building=${p.id}" target="_blank" rel="noopener">${p.name} ↗</a>`).join(' · ');
document.body.dataset.catalogReady='true';
