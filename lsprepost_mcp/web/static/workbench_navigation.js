/* One navigation bar; registered controllers own snapshot/restore semantics. */
(() => {
  const S=window.WorkbenchSession;
  if(!S||window.WorkbenchNavigation)return;
  let storage;try{storage=window.sessionStorage;}catch{}
  const store=S.createStore(storage),labels={modeling:'建模工作台',refined:'精细化爆炸',building:'建筑预览',pressure:'压力与 K 文件',response:'CPU 开发验证',blast:'CPU 响应',assessment:'评估演示'};
  const fixedPages=['building','pressure'];
  let adapter=null,workspace=null,ready=false,timer=null,leaving=false,lastDurable=false,pendingRecovery=null,durableIdentity=null;
  const header=document.createElement('header');header.className='workbench-global-header';header.dataset.workbenchHeader='';
  const brand=document.createElement('a');brand.className='workbench-global-brand';brand.href='/';brand.dataset.workbenchDestination='modeling';brand.textContent='lsprepost-mcp';brand.setAttribute('aria-label','建模工作台');
  const nav=document.createElement('nav');nav.setAttribute('aria-label','工作台切换');
  const context=document.createElement('div');context.className='workbench-global-context';
  const project=document.createElement('strong'),status=document.createElement('span');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const recover=document.createElement('button');recover.type='button';recover.textContent='下载保留草稿';recover.hidden=true;
  const embedded=window.top!==window;
  context.append(project,status,recover);header.append(brand,nav,context);document.body.prepend(header);
  if(embedded)header.hidden=true;else document.body.classList.add('has-workbench-navigation');
  for(const [id,label]of [['modeling',labels.modeling],['refined',labels.refined],['fixed-building','固定建筑压力分析'],['blast',labels.blast],['assessment',labels.assessment]]){
    const a=document.createElement('a');a.textContent=label;
    if(id==='fixed-building')a.dataset.workbenchGroup=id;
    a.dataset.workbenchDestination=id==='fixed-building'?'building':id;a.href=S.ROUTES[a.dataset.workbenchDestination];nav.append(a);
  }
  const subnavigation=document.createElement('div');subnavigation.className='workbench-subnavigation';
  const subnav=document.createElement('nav');subnav.setAttribute('aria-label','固定建筑压力分析子页');
  for(const id of fixedPages){const a=document.createElement('a');a.href=S.ROUTES[id];a.dataset.workbenchDestination=id;a.textContent=labels[id];subnav.append(a);}
  subnavigation.append(subnav);header.append(subnavigation);
  function activeRoute(){return Object.entries(S.ROUTES).find(([,path])=>path===(location.pathname.replace(/\/$/,'')||'/'))?.[0]||'modeling';}
  function fixedDestination(){const active=workspace||activeRoute();return fixedPages.includes(active)?active:store.list().filter(r=>fixedPages.includes(r.workspace)).at(-1)?.workspace||'building';}
  function info(){return adapter?.context?.()||{identity:'new',label:labels[activeRoute()],url:location.pathname+location.search};}
  function urlFor(id){
    let url=store.read(id)?.url||S.ROUTES[id];
    if(id==='blast'){
      const target=new URL(url,location.origin),current=new URL(info().url,location.origin),active=workspace||activeRoute();
      target.searchParams.delete('legacy');
      if(['building','pressure','response'].includes(active)){
        target.searchParams.set('source','fixed_three_storey');target.searchParams.set('building','residence-3');target.searchParams.delete('project_name');target.searchParams.delete('run_id');
        for(const key of ['scene_id','tnt_scene_id']){const value=current.searchParams.get(key);if(value)target.searchParams.set(key,value);else target.searchParams.delete(key);}
      }else if(active==='modeling'&&current.searchParams.has('project_name')){
        const projectName=current.searchParams.get('project_name');if(target.searchParams.get('project_name')!==projectName){for(const key of ['building','source','run_id','scene_id','tnt_scene_id'])target.searchParams.delete(key);}target.searchParams.set('project_name',projectName);
      }
      try{return S.canonicalUrl(id,target.pathname+target.search);}catch{return S.ROUTES[id];}
    }
    const family=['building','pressure','response'];
    if(family.includes(id)){
      const latest=store.list().filter(r=>family.includes(r.workspace)).at(-1);
      const current=(family.includes(workspace||activeRoute())||((workspace||activeRoute())==='blast'&&new URL(info().url,location.origin).searchParams.has('scene_id')))?info().url:latest?.url;
      const scene=new URL(current||S.ROUTES[id],location.origin).searchParams.get('scene_id');
      const matching=store.list(id).filter(r=>new URL(r.url,location.origin).searchParams.get('scene_id')===scene).at(-1);
      const target=new URL(matching?.url||S.ROUTES[id],location.origin);
      if(scene)target.searchParams.set('scene_id',scene);else target.searchParams.delete('scene_id');
      url=target.pathname+target.search;
    }
    try{return S.canonicalUrl(id,url);}catch{return S.ROUTES[id];}
  }
  function refresh(){
    const active=workspace||activeRoute();
    for(const a of nav.children){
      if(a.dataset.workbenchGroup)a.dataset.workbenchDestination=fixedDestination();
      a.href=urlFor(a.dataset.workbenchDestination);
      if(a.dataset.workbenchGroup&&fixedPages.includes(active))a.setAttribute('aria-current','true');
      else if(!a.dataset.workbenchGroup&&(a.dataset.workbenchDestination===active||(active==='response'&&a.dataset.workbenchDestination==='blast')))a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
    }
    subnavigation.hidden=embedded||!fixedPages.includes(active);
    for(const a of subnav.children){a.href=urlFor(a.dataset.workbenchDestination);if(a.dataset.workbenchDestination===active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
    project.textContent=info().label||labels[active];project.title=project.textContent;
    document.body.dataset.activeWorkbench=active;document.body.dataset.activeWorkbenchGroup=fixedPages.includes(active)?'fixed-building':active;
  }
  function message(text,error=false){status.textContent=text;status.dataset.error=String(error);}
  function checkpoint(){
    if(!ready||!adapter)return false;
    if(pendingRecovery&&String(pendingRecovery.revision)===String(info().revision??''))throw Error('原草稿仍保留，请先下载草稿备份后切换。');
    const meta=info(),saved=store.write(workspace,{...meta,snapshot:adapter.capture()});
    if(activeRoute()===workspace&&location.pathname+location.search!==saved.url)window.history.replaceState(window.history.state,'',saved.url);
    lastDurable=true;durableIdentity=meta.identity;refresh();
    message(pendingRecovery?'旧版草稿另行保留，可下载查看':'参数已保留在本标签页',!!pendingRecovery);return true;
  }
  async function register(id,next){
    if(!Object.hasOwn(labels,id))throw Error('Unknown workspace');
    adapter=next;workspace=id;ready=false;lastDurable=false;pendingRecovery=null;durableIdentity=null;refresh();
    const key=next.restoreIdentity?.()??null,meta=info();
    const saved=store.read(id,key,meta.revision===undefined?null:String(meta.revision));
    const older=!saved&&key!==null?store.read(id,key):null;
    try{
      if(saved)await next.restore(saved.snapshot,saved);
      else if(older){pendingRecovery=older;message('项目版本已变化，旧草稿已保留；未覆盖当前版本。',true);}
    }catch(error){pendingRecovery=saved;message('草稿未应用：'+error.message,true);}
    ready=true;recover.hidden=!pendingRecovery;
    // Failed restore must remain available; revisions are separate store records.
    if(pendingRecovery&&String(pendingRecovery.revision)===String(info().revision??'')){lastDurable=false;refresh();return;}
    try{checkpoint();}catch(error){message(error.message,true);}
  }
  async function navigate(id){
    if(leaving||!Object.hasOwn(labels,id))return;
    if(id===workspace&&!(id==='blast'&&new URL(location.href).searchParams.get('legacy')==='1'))return;
    if(!ready){message('参数正在载入，请稍后切换。',true);return;}
    leaving=true;
    try{
      if(pendingRecovery&&String(pendingRecovery.revision)===String(info().revision??''))throw Error('原草稿仍保留，请先下载草稿备份后切换。');
      await adapter.beforeLeave?.();
      if(!checkpoint())throw Error('草稿尚未就绪，已取消切换。');
      location.assign(urlFor(id));
    }catch(error){leaving=false;lastDurable=false;message(error.message,true);}
  }
  recover.addEventListener('click',()=>{
    if(!pendingRecovery)return;
    const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(pendingRecovery,null,2)],{type:'application/json'}));
    a.href=url;a.download='workbench-draft-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    pendingRecovery=null;recover.hidden=true;try{checkpoint();}catch(error){message(error.message,true);}
  });
  document.addEventListener('click',event=>{
    const target=event.target.closest?.('[data-workbench-destination],#openRefinedBlastWorkbench,#openFixedBuildingWorkspace,[data-refined-back],#backPressure,#openCpuResponse');
    if(!target)return;
    const id=target.dataset.workbenchDestination||({openRefinedBlastWorkbench:'refined',openFixedBuildingWorkspace:'building',backPressure:'pressure',openCpuResponse:'blast'}[target.id])||'modeling';
    if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||event.button!==0){try{checkpoint();}catch(error){event.preventDefault();message(error.message,true);}return;}
    event.preventDefault();event.stopImmediatePropagation();navigate(id);
  },true);
  for(const type of ['input','change'])document.addEventListener(type,()=>{
    lastDurable=false;if(!ready)return;clearTimeout(timer);
    // Reload chooses its URL before beforeunload: persist identity changes now.
    if(info().identity!==durableIdentity){try{checkpoint();}catch(error){message(error.message,true);}return;}
    timer=setTimeout(()=>{try{checkpoint();}catch(error){message(error.message,true);}},150);
  });
  window.addEventListener('beforeunload',event=>{
    if(!ready)return;
    try{if(!checkpoint())throw Error('not ready');}
    catch(error){lastDurable=false;message(error.message,true);event.preventDefault();event.returnValue='';}
  });
  window.addEventListener('pagehide',()=>{try{checkpoint();}catch{}});
  window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
  window.addEventListener('popstate',refresh);
  const resize=()=>document.documentElement.style.setProperty('--wb-navigation-height',header.getBoundingClientRect().height+'px');
  new ResizeObserver(resize).observe(header);resize();refresh();message('正在恢复当前工作台…');
  // Existing local task commands stay accessible after the old cross-page bars hide.
  const savedButton=document.getElementById('openSaved'),localContext=document.querySelector('.context');
  if(savedButton&&localContext)localContext.append(savedButton);
  window.WorkbenchNavigation={register,navigate,checkpoint,refresh,read:(id,key=null,rev=null)=>store.read(id,key,rev),captureFields:S.captureFields,restoreFields:S.restoreFields,
    canLeaveWithoutLoss:()=>lastDurable};
})();
