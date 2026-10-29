"""Independent TNT scenes, lightweight estimates and explicitly requested K exports."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import re
import threading
from uuid import uuid4
import zipfile

from .tnt_resource import TntResource, digest
from .tnt_native.architecture_blast_contracts import build_blast_schema, normalize_blast_config, resolve_blast_cylinder, fingerprint

ID = re.compile(r'^[a-f0-9]{32}$')


def checked_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('invalid scene/job ID')
    return value


def write_record(path, record):
    if path.is_symlink():
        raise ValueError('不允许链接记录')
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True), encoding='utf8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def read_record(path):
    if path.is_symlink():
        raise ValueError('不允许链接记录')
    return json.loads(path.read_text(encoding='utf8'))


class TntService:
    def __init__(self, root, *, archive=None):
        self.root = Path(root).resolve()
        self.resource = TntResource(archive)
        self.metadata = self.resource.metadata()
        for name in ('scenes', 'jobs', 'exports'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='tnt-k-export')
        self.active = None; self.closed = False
        for path in (self.root / 'jobs').glob('*.json'):
            r = read_record(path)
            if r.get('status') in ('queued', 'running'):
                r.update(status='interrupted', error='服务重启，先前导出未完成'); write_record(path, r)

    def schema(self):
        result = build_blast_schema(self.metadata)
        p = self.resource.payload
        result.update(analysis_type='tnt_air_fsi', geometry=dict(p['geometry_metadata'],
                      components=list(deepcopy(p['components']).values())),
                      reference_pressure_pa=101325., coupling_nquad=2, tnt_density_kg_m3=self.metadata['tnt_density_kg_m3'],
                      placement_policy=dict(scenarios=['outdoor'], exclusion='building_outer_envelope', tolerance_m=1e-9),
                      mesh_generated=False, solver_started=False)
        return result

    def _outdoor_placement(self, c):
        if c['scenario'] != 'outdoor':
            raise ValueError('当前仅允许室外TNT工况，必须放在建筑外；历史室内工况保留只读')
        cylinder = resolve_blast_cylinder(c['cylinder'], self.metadata['tnt_density_kg_m3'])
        g = self.resource.payload['geometry_metadata']; b = g['building_bounds_m']
        x, y = c['location']['xy_m']; r = cylinder['diameter_m']/2
        bottom = g['grade_m'] + c['location']['bottom_clearance_m']; top = bottom+cylinder['height_m']
        dx = max(b[0]-x, 0., x-b[3]); dy = max(b[1]-y, 0., y-b[4])
        if top >= b[2]-1e-9 and bottom <= b[5]+1e-9 and math.hypot(dx,dy) <= r+1e-9:
            raise ValueError('TNT整个圆柱必须位于建筑外，不得进入建筑内部或接触建筑外包络')
        return dict(cylinder, center_m=[x,y,(bottom+top)/2], bounds_m=[x-r,y-r,bottom,x+r,y+r,top],
                    bottom_elevation_m=bottom, floor_elevation_m=g['grade_m'])

    def _revision(self, record, revision):
        if type(revision) is not int or revision != record['revision']:
            raise ValueError('工况版本 revision 已变化，请重新载入')

    def save(self, config, *, scene_id=None, revision=None):
        c = normalize_blast_config(config, self.metadata)
        self._outdoor_placement(c)
        with self.lock:
            if self.closed:
                raise ValueError('服务已关闭')
            sid = checked_id(scene_id) if scene_id is not None else uuid4().hex
            if scene_id is not None:
                existing = self.load(sid); self._revision(existing, revision)
                if existing['config']['scenario'] != 'outdoor':
                    raise ValueError('历史室内工况仅保留只读，请新建室外工况')
            elif revision is not None:
                raise ValueError('revision without scene ID')
            record = dict(scene_id=sid, revision=revision + 1 if scene_id else 1, config=c,
                          analysis_type='tnt_air_fsi', updated_at=datetime.now(timezone.utc).isoformat())
            write_record(self.root / 'scenes' / (sid + '.json'), record)
            return deepcopy(record)

    def load(self, sid):
        return read_record(self.root / 'scenes' / (checked_id(sid) + '.json'))

    def list_scenes(self):
        rows = [read_record(p) for p in (self.root / 'scenes').glob('*.json')]
        return [dict(scene_id=r['scene_id'], revision=r['revision'], name=r['config']['name'], scenario=r['config']['scenario'], updated_at=r['updated_at'])
                for r in sorted(rows, key=lambda r:r['updated_at'], reverse=True)]

    def estimate(self, config):
        """Axis planning and conservative exterior check; no FE arrays or mesh allocation."""
        from .tnt_native.architecture_blast_placement import _axis
        c = normalize_blast_config(config, self.metadata)
        placement = self._outdoor_placement(c)
        g = self.resource.payload['geometry_metadata']; b = g['building_bounds_m']
        bounds = placement['bounds_m']
        mesh = c['mesh']; m = mesh['margins_m']
        air = [b[0]-m['xmin'], b[1]-m['ymin'], g['grade_m'], b[3]+m['xmax'], b[4]+m['ymax'], b[5]+m['top']]
        ground = g['ground_bounds_m']
        if any(air[i]<ground[i]-1e-9 or air[i+3]>ground[i+3]+1e-9 for i in (0,1)):
            raise ValueError('空气范围超出固定混凝土地面，请减小外扩距离')
        h = mesh['charge_cell_m']
        if any(bounds[i]<air[i] or bounds[i+3]>air[i+3] for i in range(3)):
            raise ValueError('TNT必须位于空气域内部')
        if any(bounds[i]-h<=air[i]+1e-9 or bounds[i+3]+h>=air[i+3]-1e-9 for i in range(3)):
            grade_touch=abs(bounds[2]-g['grade_m'])<1e-9 and all(air[i]<bounds[i]-h<bounds[i+3]+h<air[i+3] for i in (0,1)) and bounds[5]+h<air[5]
            if not grade_touch:raise ValueError('TNT及其加密缓冲区域必须被空气域包围')
        regions = [[(max(air[i], bounds[i]-h), min(air[i+3], bounds[i+3]+h), h)] for i in range(3)]
        axes = [_axis(air[i], air[i+3], mesh['background_cell_m'], regions[i]) for i in range(3)]
        axes[2] = g['buffer_z'] + axes[2]
        cells = math.prod(len(a)-1 for a in axes); nodes = math.prod(len(a) for a in axes)
        if cells>200000 or nodes>250000:
            raise ValueError(f'ALE grid预算超限：{cells}单元、{nodes}节点')
        return dict(config=c, placement=placement, grid=dict(element_count=cells, node_count=nodes, bounds_m=air),
                    mesh_generated=False, solver_started=False, exact_geometry_verified=False,
                    warnings=['轻量预估；实际实体干涉、材料体积分数和耦合面在生成时核验。'], exportable=True)

    def preview(self, sid, revision):
        self.resource.verify()
        with self.lock:
            r = self.load(sid); self._revision(r, revision)
            p = self.estimate(r['config'])
            p.update(scene_id=sid, revision=revision,
                     scene_fingerprint=fingerprint(dict(config=p['config'], resource=self.resource.archive_sha256)))
            return p

    def start_export(self, sid, revision, scene_fingerprint, *, scope_accepted=False):
        if scope_accepted is not True:
            raise ValueError('请先确认 scope：生成范围、预计耗时和资源预算')
        with self.lock:
            p = self.preview(sid, revision)
            if p['scene_fingerprint'] != scene_fingerprint:
                raise ValueError('预览已过期，请更新预览')
            if self.active:
                old = self.export_status(self.active)
                if old['scene_id']==sid and old['revision']==revision and old['scene_fingerprint']==scene_fingerprint:
                    return old
                raise ValueError('已有TNT导出正在执行')
            jid = uuid4().hex
            job = dict(job_id=jid, scene_id=sid, revision=revision, scene_fingerprint=scene_fingerprint,
                       status='queued', grid=p['grid'], config=p['config'], solver_started=False)
            write_record(self.root/'jobs'/(jid+'.json'), job); self.active=jid
            self.executor.submit(self._export, jid, deepcopy(p))
            return deepcopy(job)

    def _export(self, jid, preview):
        path = self.root/'jobs'/(jid+'.json'); job=read_record(path)
        job['status']='running'; write_record(path, job)
        try:
            from .tnt_native.architecture_blast_template import load_blast_template
            from .tnt_native.architecture_blast_export import prepare_blast_scene, export_blast_scene
            template = load_blast_template(self.resource.unpack(self.root/'templates'))
            prepared = prepare_blast_scene(template, preview['config'])
            result = export_blast_scene(self.root/'exports'/jid, template, prepared)
            directory=self.root/'exports'/jid
            package_names=[*result['k_sha256'],'scene-config.json','change-map.json','blast-scene-manifest.json',
                           *['template/'+name for name in [*result['k_sha256'],'blast-template.json']]]
            job.update(status='exported', result=result, entry=result['main_k'],
                       package_sha256={name:digest(directory/name) for name in package_names},
                       download_url='/api/architecture/tnt/exports/'+jid+'/download')
        except Exception as exc:
            job.update(status='failed', error=str(exc))
        finally:
            with self.lock:
                write_record(path, job); self.active=None

    def export_status(self, jid):
        return read_record(self.root/'jobs'/(checked_id(jid)+'.json'))

    def list_exports(self, sid):
        self.load(sid)
        return [r for p in sorted((self.root/'jobs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                if (r:=read_record(p))['scene_id']==sid]

    def export_directory(self, jid):
        job=self.export_status(jid)
        if job['status']!='exported': raise ValueError('K包尚未成功导出')
        path=self.root/'exports'/checked_id(jid)
        if path.is_symlink() or path.resolve().parent != (self.root/'exports').resolve():
            raise ValueError('不安全的导出路径')
        return path, job

    def download(self, jid):
        path, job = self.export_directory(jid)
        manifest=read_record(path/'blast-scene-manifest.json')
        if manifest!=job['result'] or not job.get('package_sha256'):
            raise ValueError('导出清单身份不匹配或缺少封存校验值')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
            names=[*job['result']['k_sha256'],'scene-config.json','change-map.json','blast-scene-manifest.json',
                   *['template/'+name for name in [*job['result']['k_sha256'],'blast-template.json']]]
            for name in names:
                p=path/name
                if p.is_symlink(): raise ValueError('导出包包含链接')
                if digest(p)!=job['package_sha256'].get(name):raise ValueError('导出文件校验失败：'+name)
                z.write(p,name)
        return output.getvalue()

    def attach_results(self, jid, directory):
        """Called only after explicit local folder selection, with matching native K hashes."""
        path,job=self.export_directory(jid); source=Path(directory).resolve()
        if not source.is_dir():raise ValueError('结果文件夹不存在')
        for name,sha in job['result']['k_sha256'].items():
            if (source/name).is_symlink() or digest(source/name)!=sha:
                raise ValueError('结果输入与此工况导出不一致：'+name)
        from .tnt_results import read_native_pressure, native_binout_files
        curves=read_native_pressure(source,job['result']['summary']['monitor_bindings'])
        record=dict(status='available',job_id=jid,scene_id=job['scene_id'],revision=job['revision'],
                    scene_fingerprint=job['scene_fingerprint'],native_scene_fingerprint=job['result']['scene_fingerprint'],
                    source_directory=str(source),source_sha256={p.name:digest(p) for p in native_binout_files(source)},
                    curves=curves,solver_started=False,engineering_validated=False)
        record['result_fingerprint']=fingerprint(record)
        write_record(path/'pressure-results.json',record)
        return record

    def results(self,jid):
        path,job=self.export_directory(jid)
        file=path/'pressure-results.json'
        if not file.exists():return dict(status='unavailable',curves=[],job_id=jid)
        record=read_record(file); body={k:v for k,v in record.items() if k!='result_fingerprint'}
        if fingerprint(body)!=record['result_fingerprint'] or record['scene_fingerprint']!=job['scene_fingerprint'] or record['job_id']!=jid:
            raise ValueError('压力结果身份或校验值不匹配')
        return record

    def close(self):
        with self.lock: self.closed=True
        self.executor.shutdown(wait=True)
