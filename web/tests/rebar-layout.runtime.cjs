const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),load=require('./blast-demo-modules.cjs');
const root=path.resolve(__dirname,'../../lsprepost_mcp/web/static');
(async()=>{
 const file=path.join(root,'blast_rebar_layout.js');assert(fs.existsSync(file),'K reinforcement layout is missing');
 const api=await load(file),core=await load(path.join(root,'blast_demo_model.js')),model=core.buildBuilding(),before=JSON.stringify(model),layout=api.buildRebarLayout(model);
 assert.equal(JSON.stringify(model),before,'reinforcement mapping must not change the concrete model');
 assert.equal(layout.schema,'k-rebar-layout@1');assert(layout.bars.length>1000);assert(layout.members.length>30);assert(layout.source.reinforcementSha256==='736e1e9d96f134ddad6cdf9d77f9d81c6ae7eafce44841d5abd808341c27bafd');
 for(const kind of ['column','slab','wall','balcony','stairs','roof'])assert(layout.members.some(m=>m.kind===kind),'missing mapped '+kind);
 assert.equal(layout.members.filter(m=>m.kind==='parapet').length,4,'all four K-defined roof parapet edges must be mapped');
 for(const member of layout.members.filter(m=>m.kind==='stairs')){const bars=layout.bars.filter(b=>b.member===member.id);assert(bars.some(b=>b.kind==='stair_transverse'),'K transverse stair bars must exist on every mapped flight');assert(new Set(bars.filter(b=>b.kind==='stair_longitudinal').map(b=>b.layer)).size>=2,'retain the K longitudinal stair layers');for(const bar of bars)for(const p of bar.points)assert(member.bodyIds.some(id=>model.bodies[id].size.every((s,k)=>Math.abs(p[k]-model.bodies[id].center[k])<=s/2+1e-6)),'mapped stair nodes must lie inside actual treads');}
 assert(layout.members.every(m=>m.sourceComponent&&m.sourceParts.length));
 for(const bar of layout.bars){assert(bar.diameter>0&&bar.points.length>=2&&bar.points.flat().every(Number.isFinite));assert(bar.points.every(p=>p[0]>=-8.55&&p[0]<=8.55&&p[1]>=-7.85&&p[1]<=6.2&&p[2]>=-.05&&p[2]<=10.8));}
 for(const member of layout.members.filter(m=>m.kind==='column')){const bars=layout.bars.filter(b=>b.member===member.id&&b.kind==='column_longitudinal');assert.equal(bars.length,4);assert(bars.every(b=>Math.abs(b.diameter-.016)<1e-10));assert(member.bodyIds.length===3,'a column must span the three display pieces');assert(bars.every(b=>Math.abs(b.points.at(-1)[2]-b.points[0][2])>2.7));}
 assert(!layout.members.some(m=>m.bodyIds.some(id=>model.bodies[id].interior)),'unreinforced lightweight partitions must not gain steel');
 const wall=layout.members.find(m=>m.kind==='wall'&&m.floor===0&&m.bounds.min[1]<-5.8);for(const bar of layout.bars.filter(b=>b.member===wall.id)){const mid=bar.points[0].map((v,k)=>(v+bar.points.at(-1)[k])/2);assert(!(mid[0]>-6.5&&mid[0]<-4.8&&mid[2]>.4&&mid[2]<2.2),'a bar must not close a real door opening');}
 const floor=layout.members.find(m=>m.kind==='slab'&&m.floor===1);assert(floor.bodyIds.length===48);assert(layout.bars.some(b=>b.member===floor.id&&Math.hypot(...b.points.at(-1).map((v,k)=>v-b.points[0][k]))>10),'steel must span display tile boundaries');
 for(const id of ['commercial_supermarket','residential_community','subway_entrance','city_street'])assert.equal(api.buildRebarLayout(core.buildBuilding({building:id})).bars.length,0,'other scene must be unchanged');
 assert.deepEqual(api.buildRebarLayout(model),layout);console.log(JSON.stringify({status:'passed',checks:10,bars:layout.bars.length,members:layout.members.length,source:layout.source}));
})().catch(e=>{console.error(e);process.exitCode=1;});
