/* Protocol/export micro-regression only. No browser, model or solver. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),inspector=require('node:inspector'),zlib=require('node:zlib');
const target=path.resolve(__dirname,'../../scripts/edge_saved_capture.cjs'),out=path.resolve(process.argv[2]);
(async()=>{
 assert(fs.existsSync(target),'bounded saved-result capture utility is missing');
 const {evaluateVoid,evaluateText,evaluateJson,streamCase,profileArgumentPattern}=require(target),session=new inspector.Session();session.connect();
 const call=(method,params)=>new Promise((resolve,reject)=>session.post(method,params,(error,result)=>error?reject(error):resolve(result)));
 try{
  await call('Runtime.evaluate',{expression:'globalThis.__large={schema:"fixture",frames:[{time:0,a:new Float32Array([1,2,3])},{time:1,a:new Float32Array([4,5,6])}]};globalThis.__cycle={};globalThis.__cycle.self=globalThis.__cycle;void 0',returnByValue:false});
  await evaluateVoid(call,'globalThis.__captured=globalThis.__cycle');
  assert.deepEqual(await evaluateJson(call,'({same:globalThis.__captured===globalThis.__cycle})'),{same:true});
  await assert.rejects(evaluateText(call,'"x".repeat(100)',32),/bounded capture/);
  await evaluateVoid(call,'globalThis.__captured=globalThis.__large');
  const meta=await evaluateText(call,'JSON.stringify({schema:globalThis.__captured.schema})'),requests=[];
  fs.mkdirSync(out,{recursive:true});
  await streamCase(path.join(out,'fixture.json.gz'),meta,2,async i=>{requests.push(i);return evaluateText(call,`JSON.stringify(globalThis.__captured.frames[${i}],(_k,v)=>ArrayBuffer.isView(v)?Array.from(v):v)`);});
  const result=JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(out,'fixture.json.gz'))));assert.deepEqual(requests,[0,1]);assert.deepEqual(result,{schema:'fixture',frames:[{time:0,a:[1,2,3]},{time:1,a:[4,5,6]}]});
  const stopped=[];await assert.rejects(streamCase(path.join(out,'first-error.json.gz'),meta,3,async i=>{stopped.push(i);if(i===1)throw Error('expected fixture stop');return '{"time":0}';}),/expected fixture stop/);assert.deepEqual(stopped,[0,1]);assert(!fs.existsSync(path.join(out,'first-error.json.gz')));
  const profile=path.resolve(out,'edge-profile'),match=new RegExp(profileArgumentPattern(profile),'i');for(const arg of ['--user-data-dir='+profile,'--user-data-dir="'+profile+'"','"--user-data-dir='+profile+'"'])assert(match.test('msedge.exe '+arg+' --type=renderer'));for(const arg of ['--user-data-dir='+profile+'2','--user-data-dir='+profile+'\\nested','--note='+profile])assert(!match.test('msedge.exe '+arg));
  console.log(JSON.stringify({status:'passed',checks:6,wholeObjectNotReturned:true,framesStreamedInOrder:true,firstErrorStops:true,exactProfileArgument:true,solverStarted:false}));
 }finally{session.disconnect();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
