/* Actual shipped controller: diagnostic retrieval, stale reply protection, legacy records. No server or solver. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let source=fs.readFileSync('lsprepost_mcp/web/static/scene_blast.js','utf8').replace(/^import[^\n]*\n/,'');source=source.slice(0,source.lastIndexOf('init().catch'));
const fields=new Map(),element=id=>{if(!fields.has(id))fields.set(id,{value:'',textContent:'',hidden:false,disabled:false,dataset:{}});return fields.get(id);};
const saved=[],diagnostic={input_fingerprint:'input',model_fingerprint:'model',method:{name:'fixture',fingerprint:'method'},status:'failed',accepted_load_factor:.75,wall_s:1.2,reason:'fixture only',restored_to_accepted_state:true,
 final:{scaled_relative_residual:.25,force_residual_n:123.,moment_residual_nm:4.,worst_body:{body_id:'column-2'},connections:{cracked_concrete:2,compression_plastic:1,shear_plastic:0,steel_plastic:1},worst_connection:{spring_index:7,a_body_id:'column-2',b_body_id:'slab-1',kind:'concrete'}}};
const job={run_id:'fixture-run',input_fingerprint:'input',model_fingerprint:'model',method:diagnostic.method,gravity_sha256:'sealed-fixture'};
let resolve;const routes=[];
const context=vm.createContext({document:{getElementById:element},URL,location:{href:'http://local/cpu-blast'},setTimeout,clearTimeout,console,
 fixtureApi:route=>{routes.push(route);return new Promise(r=>resolve=r);},saveFixture:(...args)=>saved.push(args)});
vm.runInContext(source+`\napi=fixtureApi;download=saveFixture;globalThis.hooks={showGravity,state};`,context);
(async()=>{
 const h=context.hooks;
 let pending=h.showGravity(job);resolve(diagnostic);await pending;
 assert(element('gravityFacts').textContent.includes('123'));assert(element('gravityFacts').textContent.includes('column-2'));
 assert(element('gravityFacts').textContent.includes('75.0%'));assert(!element('downloadGravity').disabled);assert(!element('gravityPanel').hidden);
 const good=element('gravityFacts').textContent;
 for(const [status,expected] of [['positive_definite','正定验证已通过'],['non_positive','未满足正定阈值'],['unresolved','数值判定未完成']]){
  pending=h.showGravity(job);resolve({...diagnostic,last_stability:{status,reason_code:'fixture_only',matrix_dofs:128,blocks:[]}});await pending;
  assert(element('gravityFacts').textContent.includes(expected));
  if(status==='unresolved')assert(element('gravityFacts').textContent.includes('不能据此判定建筑失稳'));
 }
 pending=h.showGravity(job);h.state.epoch++;element('gravityFacts').textContent='new input';resolve(diagnostic);await pending;
 assert.equal(element('gravityFacts').textContent,'new input');
 await h.showGravity({...job,gravity_sha256:null});assert(element('downloadGravity').disabled);assert(element('gravityFacts').textContent.includes('未保存'));
 pending=h.showGravity(job);resolve({...diagnostic,input_fingerprint:'wrong'});await pending;
 assert(element('gravityFacts').textContent.includes('校验'));assert(element('downloadGravity').disabled);
 assert(routes.every(p=>p==='runs/fixture-run/gravity'));assert(good.includes('回滚'));
 console.log('PASS 7 gravity UI checks: diagnostics, three stability states, stale replies, legacy records, identity mismatch; zero computation');
})().catch(e=>{console.error(e);process.exitCode=1;});
