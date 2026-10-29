const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../lsprepost_mcp/web/static');
(async()=>{
 const panel=await require('./blast-demo-modules.cjs')(path.join(root,'blast_panel_fracture.js'));
 const body={id:1,role:'rail',center:[4,-6,1.5],size:[1.24,.12,.92],capacity:.18,supports:[0],normal:[0,-1,0],fixed:false};
 assert(panel.isPanel(body),'solid balcony parapet was excluded from progressive damage');
 assert(!panel.isPanel({...body,size:[3,.06,.08]}),'slender handrail must not become a concrete plate');
 assert(!panel.isPanel({...body,fixed:true}),'fixed references must remain fixed');
 const patch=panel.panelPatch(body);for(const t of patch.triangles)for(let k=0;k<3;k++)if(t.anchors[k])assert(Math.abs(t.vertices[k*3+2]-(1.5-.92/2))<1e-8,'parapet attachments must be at its lower edge');
 const foundation={id:0,role:'slab',center:[4,-6,.1],size:[4,2,.2],capacity:1,supports:[],fixed:true};
 const run=mass=>{const s=panel.createPanelSystem({bodies:[foundation,body]},{mass,source:[4,-10,.8]},1/180);s.activate(1,0);for(let i=1;i<=360;i++)s.step(i/180,new Uint8Array(2));return s.sample();};
 const rest=run(0),impact=run(600);assert.equal(rest.maxDisplacement,0);assert.equal(rest.detached,0);assert(impact.cracked>0&&impact.detached>0,'solid parapet must crack and fragment under impact');assert(impact.vertices.every(Number.isFinite));
 const api=await require('./blast-demo-modules.cjs')(path.join(root,'blast_demo_model.js')),model=api.buildBuilding(),rails=model.bodies.filter(b=>b.role==='rail');assert.equal(rails.length,36);assert(rails.every(panel.isPanel));
 const result=await api.simulate(model,{mass:160,duration:1,response:'fracture'}),last=result.frames.at(-1),ids=new Set(last.fracture.ids),active=rails.filter(b=>ids.has(b.id));assert(active.length>0);assert(rails.filter(b=>last.damage[b.id]===1).every(b=>ids.has(b.id)),'detached solid parapets must use network geometry');
 assert.equal(result.method,'progressive-panel-fracture@5');assert.equal(result.method,panel.PANEL_FRACTURE_METHOD);
 console.log(JSON.stringify({status:'passed',checks:8,eligibleRails:rails.length,activeRails:active.length,fixture:{cracks:impact.cracked,detached:impact.detached},method:result.method}));
})().catch(e=>{console.error(e);process.exitCode=1;});
