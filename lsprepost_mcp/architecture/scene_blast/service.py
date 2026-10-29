"""Immutable scene jobs, scoped history and one owned subprocess at a time."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import threading
import time
from uuid import uuid4

from .contracts import LIMITS, MATERIAL, fingerprint, method_identity, normalize_input, snapshot
from .sources import catalog, prepare as prepare_model


def stamp():return datetime.now(timezone.utc).isoformat()


class ProcessStopped(ValueError):
    def __init__(self,status,message):
        if status not in {'timed_out','cancelled'}:raise ValueError('invalid termination status')
        self.status=status;super().__init__(message)


class WorkerFailure(ValueError):
    def __init__(self,value):
        self.status=value.get('status','failed')
        if self.status not in {'failed','cancelled','timed_out'}:self.status='failed'
        super().__init__(value['error'])


def write_json(path,value):
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf8')
    if len(raw)>64_000_000:raise ValueError('场景记录超过 64 MB 预算')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.'+uuid4().hex+'.tmp');tmp.write_bytes(raw)
    # Windows readers can briefly deny FILE_SHARE_DELETE. Keep the original
    # intact and retry this SAME atomic replacement, never truncate in place.
    for attempt in range(20):
        try:tmp.replace(path);break
        except PermissionError:
            if attempt==19:raise
            time.sleep(.005)


def read_json(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>64_000_000:raise ValueError('记录大小或路径无效')
    return json.loads(path.read_text(encoding='utf8'))


class SceneBlastService:
    def __init__(self,root,*,prepare=prepare_model,runner=None):
        self.root=Path(root).resolve();(self.root/'runs').mkdir(parents=True,exist_ok=True)
        self.prepare_model=prepare;self.runner=runner or self._process;self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='scene-cpu-blast')
        self.lock=threading.RLock();self.events={};self.futures={};self.cache={};self.records={};self.requests={};self.closed=False
        for path in (self.root/'runs').glob('*/job.json'):
            if not re.fullmatch('[a-f0-9]{32}',path.parent.name):continue
            record=read_json(path);rid=path.parent.name
            if record.get('run_id')!=rid:continue
            if record['status'] in {'running','queued'}:
                record.update(status='interrupted',error='服务重启，原任务未自动重跑',finished_at=stamp());write_json(path,record)
            self.records[rid]=record;self.requests[record['request_id']]=rid

    def capabilities(self):
        return dict(sources=catalog(),projects=self.projects(),method=method_identity(),material=MATERIAL,limits=LIMITS,
            available=all(importlib.util.find_spec(name) is not None for name in ('numpy','scipy')),
            engineering_validated=False,performance_validated=False,scope='outdoor_single_surface_tnt',
            note='实验实施版：真实整栋尚未试算验收；单 TNT 贴地、开阔场地，无城市遮挡/绕射/多重反射')

    def projects(self):
        from ...config import PROJECTS_DIR, LEGACY_PROJECTS_DIR
        rows={}
        for root in (PROJECTS_DIR,LEGACY_PROJECTS_DIR):
            if not root.is_dir():continue
            for directory in list(root.iterdir())[:300]:
                path=directory/'model.json'
                if directory.is_symlink() or not path.is_file() or path.is_symlink() or path.stat().st_size>4_000_000:continue
                try:
                    spec=read_json(path)['spec'];kinds={c.get('template') for c in spec.get('components',[])}
                    kind='city_street' if spec.get('model_type')=='city_street_blast_scene' else next(iter(kinds)) if len(kinds)==1 else None
                    if kind in {r['id'] for r in catalog()} and directory.name not in rows:rows[directory.name]=dict(project_name=directory.name,kind=kind)
                except (ValueError,KeyError,OSError,TypeError):continue
        return list(rows.values())

    def prepare(self,value):
        config=normalize_input(value)
        # Re-read project definition on prepare/start; stale projects must not reuse a cache.
        model=self.prepare_model(config);identity=fingerprint(model)
        with self.lock:
            if self.closed:raise ValueError('服务已关闭')
            self.cache[identity]=model
            while len(self.cache)>4:self.cache.pop(next(iter(self.cache)))
        return dict(config=config,model=model,model_fingerprint=identity,material=MATERIAL,method=method_identity())

    def _directory(self,rid):
        if not isinstance(rid,str) or not re.fullmatch('[a-f0-9]{32}',rid):raise ValueError('任务标识无效')
        directory=self.root/'runs'/rid
        if directory.is_symlink() or directory.resolve().parent!=(self.root/'runs').resolve():raise ValueError('任务路径无效')
        return directory

    def _save(self,rid):write_json(self._directory(rid)/'job.json',self.records[rid])

    def submit(self,payload):
        if not isinstance(payload,dict) or set(payload)!={'input','model_fingerprint','request_id'}:raise ValueError('开始模拟需要输入、模型身份和请求标识')
        request=payload['request_id']
        if not isinstance(request,str) or not re.fullmatch('[a-f0-9]{32}',request):raise ValueError('请求标识无效')
        config=normalize_input(payload['input']);key=fingerprint(dict(input=config,model_fingerprint=payload['model_fingerprint']))
        with self.lock:
            if request in self.requests:
                record=self.records[self.requests[request]]
                if record['request_fingerprint']!=key:raise ValueError('同一请求标识不能用于不同输入')
                return deepcopy(record)
            if any(j['status'] in {'queued','running'} for j in self.records.values()):raise ValueError('已有 CPU 场景任务在运行，请先停止或等待')
        prepared=self.prepare(config);model=prepared['model']
        if prepared['model_fingerprint']!=payload['model_fingerprint']:raise ValueError('模型已变化，请重新载入场景后再开始')
        if not model['checks']['supported']:raise ValueError('模型连接未通过基础承载路径检查，请查看未支承构件')
        xyz=config['tnt']['position_m']
        for envelope in model['envelopes']:
            if all(envelope['min_m'][i]-.05<=xyz[i]<=envelope['max_m'][i]+.05 for i in (0,1)):
                raise ValueError('TNT 位于建筑包络内部或过近，首版仅支持室外开阔位置')
            separation=sum(max(envelope['min_m'][i]-xyz[i],0,xyz[i]-envelope['max_m'][i])**2 for i in range(3))**.5
            if separation/config['tnt']['mass_kg']**(1/3)<.2:raise ValueError('爆源到建筑包络的最近缩尺距离小于 0.2，超出首版经验荷载范围')
        from .loads import surface_parameters
        parameters=surface_parameters(config,model)  # Validate every receiver's empirical domain before queuing.
        if not parameters or min(p['arrival_s'] for p in parameters)>=config['analysis']['duration_s']:raise ValueError('模拟时长内爆压尚未到达模型，请增加时长或调整工况')
        frozen=snapshot(config,model);rid=uuid4().hex;directory=self._directory(rid)
        with self.lock:
            if any(j['status'] in {'queued','running'} for j in self.records.values()):raise ValueError('已有 CPU 场景任务在运行')
            directory.mkdir(exist_ok=False);write_json(directory/'input.json',frozen)
            record=dict(run_id=rid,request_id=request,request_fingerprint=key,input_fingerprint=frozen['input_fingerprint'],model_fingerprint=frozen['model_fingerprint'],method=frozen['method'],
                source=model['source'],config=config,status='queued',created_at=stamp(),deleted_at=None,input_sha256=hashlib.sha256((directory/'input.json').read_bytes()).hexdigest())
            self.records[rid]=record;self.requests[request]=rid;self._save(rid);event=threading.Event();self.events[rid]=event
            self.futures[rid]=self.pool.submit(self._execute,rid,frozen,event)
            return deepcopy(record)

    def _execute(self,rid,frozen,event):
        directory=self._directory(rid)
        with self.lock:
            if event.is_set():return
            self.records[rid].update(status='running',started_at=stamp());self._save(rid)
        outcome={}
        try:
            value=self.runner(frozen,directory,event)
            if value.get('status') not in {'completed','partial','cancelled','timed_out'}:raise ValueError('运行器返回了无效状态')
            if any(value.get(k)!=frozen[k] for k in ('input_fingerprint','model_fingerprint','method')):raise ValueError('计算结果与冻结输入校验不符')
            if value.get('schema_version')!='scene-blast-result@1' or not value.get('frames'):raise ValueError('计算结果缺少有效帧')
            write_json(directory/'result.json',value);digest=hashlib.sha256((directory/'result.json').read_bytes()).hexdigest()
            outcome.update(status=value['status'],result_sha256=digest,termination_reason=value.get('termination_reason'),metrics=value.get('metrics'))
        except Exception as exc:
            outcome.update(status='cancelled' if event.is_set() else exc.status if isinstance(exc,(ProcessStopped,WorkerFailure)) else 'failed',error=str(exc)[:2000])
        finally:
            with self.lock:
                diagnostic=directory/'gravity.json'
                if diagnostic.is_file():
                    try:
                        value=read_json(diagnostic)
                        if any(value.get(k)!=frozen[k] for k in ('input_fingerprint','model_fingerprint','method')):raise ValueError('自重诊断与冻结输入身份不符')
                        if value.get('status')=='running':
                            # Keep the worker's exact last snapshot. Native termination
                            # cannot execute Python rollback or final diagnostic code.
                            original=hashlib.sha256(diagnostic.read_bytes()).hexdigest()
                            value=dict(value,status=outcome['status'],reason_code='worker_'+outcome['status'],
                                reason=outcome.get('error','worker 已结束，未完成自重状态确认'),
                                restored_to_accepted_state=False,raw_progress_sha256=original,
                                terminal_observation=dict(worker_status=outcome['status'],observed_at=stamp(),
                                    state='last recorded trial only; worker rollback not confirmed'))
                            diagnostic=directory/'gravity-terminal.json';write_json(diagnostic,value)
                        self.records[rid]['gravity_sha256']=hashlib.sha256(diagnostic.read_bytes()).hexdigest()
                        self.records[rid]['gravity_file']=diagnostic.name
                        self.records[rid]['gravity_summary']={k:value.get(k) for k in ('status','reason_code','accepted_load_factor','wall_s','blast_applied','final')}
                    except (OSError,ValueError,KeyError) as exc:
                        self.records[rid]['gravity_diagnostics_error']=str(exc)
                self.records[rid].update(outcome,finished_at=stamp());self._save(rid)

    def _process(self,frozen,directory,event):
        from ..cpu_response.runtime import run_process
        process=run_process([sys.executable,'-m','lsprepost_mcp.architecture.scene_blast.worker',str(directory/'input.json')],
            timeout_s=min(180,frozen['limits']['wall_s']+10),log_dir=directory/'logs',cancel=event)
        write_json(directory/'process.json',process)
        if process['status'] in {'timeout','cancelled'}:raise ProcessStopped('timed_out' if process['status']=='timeout' else 'cancelled','CPU 进程'+{'timeout':'超时','cancelled':'已停止'}[process['status']]+'；输入和日志已保留')
        if process['status']!='completed':raise ValueError('CPU 进程失败；输入和日志已保留')
        if (directory/'failure.json').is_file():raise WorkerFailure(read_json(directory/'failure.json'))
        return read_json(directory/'result.json')

    def job(self,rid):
        self._directory(rid)
        with self.lock:
            if rid not in self.records:raise FileNotFoundError(rid)
            value=deepcopy(self.records[rid])
        progress=self._directory(rid)/'progress.json'
        if value['status']=='running' and progress.is_file():
            try:value['progress']=read_json(progress)
            except (OSError,ValueError):pass
        return value

    def history(self,include_deleted=False):
        with self.lock:return deepcopy(sorted([r for r in self.records.values() if bool(r.get('deleted_at'))==include_deleted],key=lambda r:r['created_at'],reverse=True)[:200])

    def input(self,rid):
        j=self.job(rid);path=self._directory(rid)/'input.json'
        if not j.get('input_sha256') or hashlib.sha256(path.read_bytes()).hexdigest()!=j['input_sha256']:raise ValueError('完整输入快照校验失败')
        value=read_json(path)
        if fingerprint(value['config'])!=j['input_fingerprint'] or fingerprint(value['model'])!=j['model_fingerprint']:raise ValueError('输入记录校验失败')
        return value

    def result(self,rid):
        j=self.job(rid);path=self._directory(rid)/'result.json'
        if not j.get('result_sha256') or hashlib.sha256(path.read_bytes()).hexdigest()!=j['result_sha256']:raise ValueError('结果记录校验失败')
        value=read_json(path)
        if any(value.get(k)!=j[k] for k in ('input_fingerprint','model_fingerprint','method')):raise ValueError('结果身份校验失败')
        return value

    def gravity(self,rid):
        j=self.job(rid);filename=j.get('gravity_file','gravity.json')
        if filename not in {'gravity.json','gravity-terminal.json'}:raise ValueError('自重诊断路径无效')
        path=self._directory(rid)/filename
        if not j.get('gravity_sha256'):raise FileNotFoundError('此记录没有已保存的自重诊断')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=j['gravity_sha256']:raise ValueError('自重诊断记录校验失败')
        value=read_json(path)
        if any(value.get(k)!=j[k] for k in ('input_fingerprint','model_fingerprint','method')):raise ValueError('自重诊断身份校验失败')
        return value

    def cancel(self,rid):
        with self.lock:
            j=self.job(rid)
            if j['status'] not in {'queued','running'}:return j
            self.events[rid].set()
            if self.futures[rid].cancel():self.records[rid].update(status='cancelled',finished_at=stamp());self._save(rid)
        return self.job(rid)

    def delete(self,rid):
        with self.lock:
            j=self.job(rid)
            if j['status'] in {'queued','running'}:raise ValueError('运行中的任务不能删除，请先停止')
            self.records[rid]['deleted_at']=stamp();self._save(rid)
        return self.job(rid)

    def restore(self,rid):
        with self.lock:self.job(rid);self.records[rid]['deleted_at']=None;self._save(rid)
        return self.job(rid)

    def close(self):
        with self.lock:
            self.closed=True
            for event in self.events.values():event.set()
        self.pool.shutdown(wait=True,cancel_futures=True)
