/* Same-tab drafts only. No network, model generation or solver operations. */
(function (global) {
  const KEY = 'lsprepost.workbench.session@1';
  const ROUTES = {
    modeling: '/', refined: '/refined-building-blast', building: '/fixed-building-pressure',
    pressure: '/structural-pressure', response: '/fixed-building-pressure/response', blast:'/cpu-blast', assessment: '/damage_assessment_demo.html',
  };
  const QUERIES = {modeling:['project_name','viewer'],refined:['project_id'],building:['scene_id'],pressure:['scene_id','tnt_scene_id'],response:['scene_id','run_id'],blast:['building','source','project_name','scene_id','tnt_scene_id','run_id','legacy'],assessment:[]};
  const clone = value => JSON.parse(JSON.stringify(value));
  function canonicalUrl(workspace, value) {
    if (!Object.hasOwn(ROUTES,workspace)) throw Error('Unknown workspace');
    const url = new URL(value || ROUTES[workspace], 'http://workbench.local');
    if (url.origin !== 'http://workbench.local' || (url.pathname.replace(/\/$/,'') || '/') !== ROUTES[workspace]) throw Error('Invalid workspace route');
    const search = new URLSearchParams();
    for (const key of QUERIES[workspace]) if (url.searchParams.has(key)) search.set(key,url.searchParams.get(key));
    return ROUTES[workspace] + (search.size ? '?' + search : '');
  }
  function createStore(storage, {limit=4_000_000,maxRecords=32}={}) {
    function records() {
      try {
        const raw=storage?.getItem(KEY);if(!raw||raw.length>limit)return [];
        const data=JSON.parse(raw);
        if(data.schema_version!==KEY||!Array.isArray(data.records)||data.records.length>maxRecords)return [];
        return data.records.filter(r=>r&&Object.hasOwn(ROUTES,r.workspace)&&typeof r.identity==='string'&&typeof r.revision==='string'&&r.snapshot&&typeof r.snapshot==='object');
      } catch {return [];}
    }
    function read(workspace,identity=null,revision=null) {
      const r=records().filter(r=>r.workspace===workspace&&(identity===null||r.identity===identity)&&(revision===null||r.revision===String(revision))).at(-1);
      return r?clone(r):null;
    }
    function write(workspace,entry) {
      if(!storage?.setItem)throw Error('浏览器无法保存本标签页草稿，已取消切换。');
      if(typeof entry.identity!=='string'||entry.identity.length>500||!entry.snapshot||typeof entry.snapshot!=='object')throw Error('草稿身份无效，已取消切换。');
      const record=clone({workspace,identity:entry.identity,revision:String(entry.revision??''),url:canonicalUrl(workspace,entry.url),label:String(entry.label||'参数草稿').slice(0,200),snapshot:entry.snapshot});
      const next=records().filter(r=>!(r.workspace===workspace&&r.identity===record.identity&&r.revision===record.revision));
      next.push(record);
      if(next.length>maxRecords)throw Error('本标签页保留的草稿过多，已取消切换；请先保存已有草稿。');
      const raw=JSON.stringify({schema_version:KEY,records:next});
      if(raw.length>limit)throw Error('草稿超过本地缓存容量，已取消切换；当前参数仍在页面中。');
      try {storage.setItem(KEY,raw);if(storage.getItem(KEY)!==raw)throw Error('storage verification');}
      catch {throw Error('草稿未能保存在本标签页，已取消切换；请检查浏览器存储空间。');}
      return clone(record);
    }
    return {read,write,list:workspace=>clone(records().filter(r=>!workspace||r.workspace===workspace))};
  }
  function controls(root) {return Array.from(root.querySelectorAll('input,select,textarea'));}
  function fieldKey(el,index) {
    if(el.id)return 'id:'+el.id;
    if(el.dataset?.param)return 'param:'+el.dataset.param;
    if(el.dataset?.refinedDraftPath)return 'path:'+el.dataset.refinedDraftPath+(el.dataset.refinedVectorIndex??'');
    return 'index:'+index;
  }
  function captureFields(root) {
    return controls(root).flatMap((el,index)=>['file','password'].includes(el.type)||el.dataset?.workbenchEphemeral!==undefined?[]:[{
      key:fieldKey(el,index),tag:el.tagName,type:el.type||'',value:el.value??'',checked:!!el.checked,
    }]);
  }
  function restoreFields(root,saved=[]) {
    const map=new Map(controls(root).map((el,i)=>[fieldKey(el,i),el]));
    for(const f of saved) {
      const el=map.get(f.key);if(!el||el.tagName!==f.tag||['file','password'].includes(el.type)||el.type!==f.type||el.dataset?.workbenchEphemeral!==undefined)continue;
      if(typeof f.value==='string'&&(el.tagName!=='SELECT'||!el.options||Array.from(el.options).some(o=>o.value===f.value)))el.value=f.value;
      if(['checkbox','radio'].includes(el.type))el.checked=!!f.checked;
    }
  }
  const api={createStore,captureFields,restoreFields,canonicalUrl,ROUTES};
  global.WorkbenchSession=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
