/* Exercise the shipped refined adapter against a delayed save; no HTTP or solve. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('lsprepost_mcp/web/static/refined_blast_workbench.js','utf8');
const start=source.indexOf('async function registerRefinedNavigation('),end=source.indexOf('\nfunction statusText(',start);
assert(start>=0&&end>start);
(async()=>{
 let raw='invalid-uncommitted',adapter,release;
 const listeners=new Map(),root={addEventListener:(t,fn)=>listeners.set(t,fn),removeEventListener:t=>listeners.delete(t)};
 const session={timer:null,queued:true,actionInFlight:false,inFlight:new Promise(r=>release=r)};
 const navigation={register:async(id,a)=>{assert.equal(id,'refined');adapter=a;},captureFields:()=>[{value:raw}],restoreFields:(_,fields)=>{raw=fields[0].value;}};
 const context=vm.createContext({window:{WorkbenchNavigation:navigation},sessionIsActive:()=>true,clearTimeout,structuredClone});
 vm.runInContext(source.slice(start,end),context);await context.registerRefinedNavigation(root,session);
 const leaving=adapter.beforeLeave();
 raw='';listeners.get('input')(); // User keeps editing while the earlier save is pending.
 raw='server-rendered-old-value';release();await leaving;
 assert.equal(raw,'','leave must preserve the latest raw field over a delayed save rerender');
 assert.equal(session.queued,false);assert.equal(listeners.size,0);
 console.log('1 delayed autosave navigation check passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
