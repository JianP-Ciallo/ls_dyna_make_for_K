const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = path.resolve(__dirname, '../../lsprepost_mcp/web/static/workbench_session.js');
assert(fs.existsSync(source), 'shared navigation draft store is missing');
const { createStore, captureFields, restoreFields, canonicalUrl } = require(source);
const memory = () => { const data = new Map(); return { getItem: k => data.get(k) ?? null, setItem: (k,v) => data.set(k,v) }; };
let tests = 0;
function test(name, fn) { fn(); tests++; console.log('PASS', name); }
test('raw invalid pressure text and project identities survive a fresh store', () => {
  const storage = memory(), store = createStore(storage);
  const value = { identity:'scene-A',revision:'3',url:'/structural-pressure?scene_id=aaaa',label:'A',snapshot:{ curve:'0,0\nunfinished,pressure', monitor:['','1','2'], checked:false } };
  store.write('pressure', value);
  value.snapshot.curve='changed';
  const restored = createStore(storage).read('pressure','scene-A','3');
  assert.equal(restored.snapshot.curve,'0,0\nunfinished,pressure');
  assert.deepEqual(restored.snapshot.monitor,['','1','2']);
  assert.equal(store.read('pressure','scene-B'),null);
  assert.equal(store.read('refined','scene-A'),null);
});
test('base revisions remain separate and older drafts are never silently overwritten', () => {
  const store=createStore(memory());
  for(const revision of ['1','2'])store.write('refined',{identity:'project-A',revision,url:'/refined-building-blast?project_id=project-A',label:'A',snapshot:{ revision }});
  assert.equal(store.read('refined','project-A','1').snapshot.revision,'1');
  assert.equal(store.read('refined','project-A','2').snapshot.revision,'2');
  assert.equal(store.read('refined','project-A','3'),null);
});
test('quota/unavailable storage blocks a durable checkpoint instead of claiming saved', () => {
  const storage=memory(), store=createStore(storage);
  store.write('modeling',{identity:'A',url:'/',snapshot:{name:'original'}});
  storage.setItem=()=>{throw Error('quota');};
  assert.throws(()=>store.write('modeling',{identity:'A',url:'/',snapshot:{name:'changed'}}),/草稿|storage/i);
  assert.equal(store.read('modeling','A').snapshot.name,'original');
  assert.throws(()=>createStore(null).write('modeling',{identity:'A',url:'/',snapshot:{}}),/草稿|storage/i);
});
test('capacity rejects a new draft without evicting an existing unsaved project', () => {
  const store=createStore(memory(),{maxRecords:1});
  store.write('modeling',{identity:'A',url:'/',snapshot:{name:'keep'}});
  assert.throws(()=>store.write('pressure',{identity:'B',url:'/structural-pressure',snapshot:{}}),/草稿|capacity/i);
  assert.equal(store.read('modeling','A').snapshot.name,'keep');
});
test('corrupt/unknown storage is ignored and routes cannot escape the local workspaces', () => {
  for(const text of ['{','{"schema_version":"wrong","records":[]}'])assert.equal(createStore({getItem:()=>text}).read('pressure','A'),null);
  assert.equal(canonicalUrl('response','/fixed-building-pressure/response?scene_id=abc&run_id=def&external=https://x'),'/fixed-building-pressure/response?scene_id=abc&run_id=def');
  assert.throws(()=>canonicalUrl('pressure','https://evil.example/structural-pressure'));
  assert.throws(()=>canonicalUrl('pressure','/fixed-building-pressure'));
});
test('field restore retains raw strings/checkboxes without events or file/password values', () => {
  const fields=[
    {id:'curveText',tagName:'TEXTAREA',type:'textarea',value:'invalid CSV',dataset:{}},
    {id:'reviewed',tagName:'INPUT',type:'checkbox',checked:false,value:'on',dataset:{}},
    {id:'secret',tagName:'INPUT',type:'password',value:'never-store',dataset:{}},
    {id:'upload',tagName:'INPUT',type:'file',value:'private-file',dataset:{}},
  ];
  fields.forEach(f=>{f.dispatchEvent=()=>{throw Error('restore must not dispatch an action');};});
  const root={querySelectorAll:()=>fields}, saved=captureFields(root);
  assert(!JSON.stringify(saved).includes('never-store'));assert(!JSON.stringify(saved).includes('private-file'));
  fields[0].value='';fields[1].checked=true;restoreFields(root,saved);
  assert.equal(fields[0].value,'invalid CSV');assert.equal(fields[1].checked,false);
});
console.log(`${tests} navigation state tests passed`);
