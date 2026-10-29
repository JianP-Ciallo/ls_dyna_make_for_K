"""Immutable local benchmark profiles and snapshot-bound CPU jobs."""
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import threading
from uuid import uuid4
from .benchmarks import IDS,make_benchmark
from .contracts import closed,finite,normalize_case,fingerprint,adapter_identity
from .jobs import CpuJobQueue
from .results import json_write,load_result
from .runtime import DEFAULT_PYTHON,run_process,runtime_identity


class CpuConflict(ValueError):pass


def checked_id(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise ValueError('invalid CPU record ID')
    return value


def now():return datetime.now(timezone.utc).isoformat()


class CpuResponseService:
    def __init__(self,root,*,python_executable=None,capability_path=None,runner=run_process,building_trial_dir=None):
        self.root=Path(root);self.python=Path(python_executable or DEFAULT_PYTHON)
        self.capability_path=Path(capability_path) if capability_path else self.python.parent/'capabilities.json'
        self.runner=runner;self.jobs=CpuJobQueue();self.lock=threading.RLock();self.closed=False;self.requests={}
        from .saved_building import SavedBuildingTrial
        self.saved_building=SavedBuildingTrial(building_trial_dir)
        # Startup recovery only; constructing this service never launches a native worker.
        runs=self.root/'runs'
        if runs.exists():
            for path in runs.glob('*/job.json'):
                if not re.fullmatch('[a-f0-9]{32}',path.parent.name):continue
                record=json.loads(path.read_text(encoding='utf8'))
                if record['status'] in ('queued','running'):
                    record.update(status='interrupted',finished_at=now(),error='service restarted before completion')
                    json_write(path,record)
                self.requests[record['client_request_id']]=record['run_id']

    def capabilities(self):
        value=dict(available=False,verified=False,reason='CPU runtime has not been verified')
        try:
            saved=json.loads(self.capability_path.read_text(encoding='utf8'))
            if self.python.is_file() and saved.get('verified') and saved.get('available') and Path(saved['runtime']['executable']).resolve()==self.python.resolve() and saved.get('runtime_identity')==runtime_identity(self.python):
                value=saved
        except (OSError,ValueError,KeyError,TypeError):pass
        return dict(value,scope='elastic_reference_benchmarks',building_enabled=False,nonlinear_enabled=False,
                    budget=make_benchmark(IDS[0])['budget'],
                    fields=['surface_pressure_pa','displacement_m','steel_axial_stress_pa'])

    def benchmarks(self):
        return [dict(source=make_benchmark(cid)['source'],label='单柱 · 纤维截面' if cid==IDS[0] else '单板 · 分层配筋壳',
                     defaults=make_benchmark(cid)) for cid in IDS]

    def create_profile(self,payload):
        allowed={'benchmark_id','mesh_n','dt_s','pressure_scale'}
        if not isinstance(payload,dict) or set(payload)-allowed or 'benchmark_id' not in payload:raise ValueError('unknown or missing CPU profile fields')
        case=make_benchmark(payload['benchmark_id'])
        if 'mesh_n' in payload:case['mesh']['n']=payload['mesh_n']
        if 'dt_s' in payload:case['analysis']['dt_s']=payload['dt_s']
        if 'pressure_scale' in payload:
            scale=finite(payload['pressure_scale'],0,10,'pressure scale')
            case['loads']['curve_si']=[[t,p*scale] for t,p in case['loads']['curve_si']]
            case['loads']['static_pressure_pa']*=scale
        case=normalize_case(case)
        profile=dict(profile_id=uuid4().hex,source=case['source'],case=case,input_fingerprint=fingerprint(case),adapter_identity=adapter_identity(),created_at=now())
        with self.lock:
            directory=self.root/'profiles';directory.mkdir(parents=True,exist_ok=True)
            json_write(directory/(profile['profile_id']+'.json'),profile)
        return profile

    def get_profile(self,profile_id):
        path=self.root/'profiles'/(checked_id(profile_id)+'.json')
        if path.is_symlink():raise ValueError('symlink record rejected')
        value=json.loads(path.read_text(encoding='utf8'))
        if value['input_fingerprint']!=fingerprint(normalize_case(value['case'])):raise ValueError('CPU profile integrity mismatch')
        return value

    def preflight(self,source,profile_id):
        profile=self.get_profile(profile_id)
        if source!=profile['source']:raise CpuConflict('source identity changed')
        if profile.get('adapter_identity')!=adapter_identity():raise CpuConflict('CPU adapter changed; create a new profile')
        caps=self.capabilities()
        if not caps['available'] or not caps['verified']:raise ValueError(caps.get('reason','CPU runtime unavailable'))
        key='column_fiber_stress' if source['id']==IDS[0] else 'panel_rebar_stress'
        if not caps.get(key):raise ValueError('required native steel response has not been verified')
        return dict(source=source,profile_id=profile_id,input_fingerprint=profile['input_fingerprint'],
                    model=profile['case']['geometry']['kind'],mesh=profile['case']['mesh'],
                    budget=profile['case']['budget'],assumptions=profile['case']['assumptions'],ready=True)

    def get_run(self,run_id):
        path=self.root/'runs'/checked_id(run_id)/'job.json'
        if path.is_symlink() or path.parent.is_symlink():raise ValueError('symlink record rejected')
        with self.lock:
            return json.loads(path.read_text(encoding='utf8'))

    def start_run(self,source,profile_id,input_fingerprint,client_request_id):
        if not isinstance(client_request_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',client_request_id):raise ValueError('invalid client submission ID')
        with self.lock:
            if self.closed:raise ValueError('CPU service is closed')
            check=self.preflight(source,profile_id)
            if input_fingerprint!=check['input_fingerprint']:raise CpuConflict('CPU input fingerprint is stale')
            if client_request_id in self.requests:
                prior=self.get_run(self.requests[client_request_id])
                if (prior['source'],prior['profile_id'],prior['input_fingerprint'])!=(source,profile_id,input_fingerprint):raise CpuConflict('submission ID already belongs to another input')
                return prior
            profile=self.get_profile(profile_id);run_id=uuid4().hex
            directory=self.root/'runs'/run_id;directory.mkdir(parents=True)
            snapshot=dict(operation='solve',case=profile['case'],input_fingerprint=input_fingerprint,
                          source=source,profile_id=profile_id,run_id=run_id,runtime=self.capabilities(),adapter_identity=profile['adapter_identity'])
            json_write(directory/'input.json',snapshot)
            record=dict(run_id=run_id,source=source,profile_id=profile_id,input_fingerprint=input_fingerprint,
                        adapter_identity=profile['adapter_identity'],client_request_id=client_request_id,status='queued',created_at=now())
            json_write(directory/'job.json',record);self.requests[client_request_id]=run_id
            self.jobs.submit(run_id,lambda cancel:self._execute(run_id,cancel))
            return record

    def _execute(self,run_id,cancel):
        directory=self.root/'runs'/run_id
        with self.lock:
            record=self.get_run(run_id)
            if cancel.is_set() or record['status']=='cancelled':return
            record.update(status='running',started_at=now());json_write(directory/'job.json',record)
        try:
            snapshot=json.loads((directory/'input.json').read_text(encoding='utf8'))
            outcome=self.runner([str(self.python),'-m','lsprepost_mcp.architecture.cpu_response.worker',
                                 '--input',str((directory/'input.json').resolve()),'--output',str(directory.resolve())],
                                timeout_s=snapshot['case']['budget']['wall_s'],log_dir=directory,cancel=cancel)
            status={'timeout':'failed'}.get(outcome['status'],outcome['status'])
            if status=='completed':
                result=load_result(directory)
                if result['source']!=record['source'] or result['input_fingerprint']!=record['input_fingerprint']:raise ValueError('worker result identity mismatch')
                if result['provenance'].get('adapter_identity')!=record['adapter_identity']:raise ValueError('worker adapter identity mismatch')
            error=None if status=='completed' else 'CPU worker '+outcome['status']
        except Exception as exc:
            outcome={};status='failed';error=str(exc)
        with self.lock:
            current=self.get_run(run_id)
            if cancel.is_set() or current['status']=='cancelled':status='cancelled'
            current.update(status=status,finished_at=now(),process=outcome)
            if error:current['error']=error[:2000]
            json_write(directory/'job.json',current)

    def cancel(self,run_id):
        with self.lock:
            value=self.get_run(run_id)
            if value['status'] in ('queued','running'):
                self.jobs.cancel(run_id);value.update(status='cancelled',finished_at=now())
                json_write(self.root/'runs'/run_id/'job.json',value)
            return value

    def get_results(self,run_id):
        record=self.get_run(run_id)
        if record.get('deleted_at'):raise CpuConflict('记录已删除，请先从已删除记录中恢复。')
        if record['status']!='completed':raise CpuConflict('CPU result is not completed')
        result=load_result(self.root/'runs'/run_id)
        if result['input_fingerprint']!=record['input_fingerprint'] or result['source']!=record['source']:raise ValueError('result belongs to a different input')
        if record.get('adapter_identity') and result['provenance'].get('adapter_identity')!=record['adapter_identity']:raise ValueError('result belongs to a different adapter')
        return dict(result,run_id=run_id)

    def delete_run(self,run_id):
        with self.lock:
            record=self.get_run(run_id)
            if record['status'] in ('queued','running'):raise CpuConflict('任务仍在进行，请先停止任务后再删除记录。')
            if not record.get('deleted_at'):
                record['deleted_at']=now();json_write(self.root/'runs'/run_id/'job.json',record)
            return record

    def restore_run(self,run_id):
        with self.lock:
            record=self.get_run(run_id)
            if record.pop('deleted_at',None):json_write(self.root/'runs'/run_id/'job.json',record)
            return record

    def building_trial(self):
        return self.saved_building.status()

    def history(self,kind,source_id,*,deleted=False):
        if kind!='benchmark' or source_id not in IDS:raise ValueError('unsupported CPU source')
        with self.lock:
            values=[self.get_run(rid) for rid in set(self.requests.values())]
        return sorted((r for r in values if r['source']['kind']==kind and r['source']['id']==source_id and bool(r.get('deleted_at'))==deleted),key=lambda r:r['created_at'],reverse=True)

    def close(self):
        self.closed=True;self.jobs.close()
