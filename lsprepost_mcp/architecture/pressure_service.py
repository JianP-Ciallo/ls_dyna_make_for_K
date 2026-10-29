"""Versioned structural-pressure drafts and portable, solver-free K exports."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import threading
from uuid import uuid4
import zipfile

from .pressure_model import (StructuralTemplate, STRUCTURAL_FILES, normalize,
                             fingerprint, file_sha, validate_structural_file)


class PressureConflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def json_write(path, value):
    temporary = path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def checked_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value): raise ValueError('invalid ID')
    return value


def read_record(path):
    if path.is_symlink(): raise ValueError('record symlink rejected')
    return json.loads(path.read_text(encoding='utf8'))


class PressureService:
    def __init__(self, template_dir, data_dir):
        self.template = StructuralTemplate(template_dir)
        self.root = Path(data_dir).resolve()
        self.scenes = self.root/'scenes'; self.jobs = self.root/'jobs'; self.outputs = self.root/'exports'
        for p in (self.scenes, self.jobs, self.outputs): p.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='structural-pressure-export')
        for path in self.jobs.glob('*.json'):
            job = read_record(path)
            if job.get('status') in ('queued', 'running'):
                job.update(status='interrupted', error='服务重启，导出未完成', updated_at=now()); json_write(path, job)

    def close(self):
        self.pool.shutdown(wait=True)

    def schema(self):
        return self.template.schema()

    def load(self, scene_id):
        record = read_record(self.scenes/(checked_id(scene_id)+'.json'))
        if record['template_fingerprint'] != self.template.identity: raise PressureConflict('固定模板已更改，请新建工况')
        return record

    def list_scenes(self):
        result = []
        with self.lock:
            for path in self.scenes.glob('*.json'):
                record = read_record(path)
                if record['template_fingerprint'] == self.template.identity:
                    result.append(dict(scene_id=record['scene_id'], revision=record['revision'],
                                       name=record['config']['name'], updated_at=record['updated_at']))
        return sorted(result, key=lambda r: r['updated_at'], reverse=True)

    def save(self, config, scene_id=None, revision=None):
        c = normalize(config, self.template)
        with self.lock:
            if scene_id is None:
                if revision is not None: raise ValueError('new scene must not supply a revision')
                sid = uuid4().hex; rev = 1
            else:
                old = self.load(scene_id)
                if type(revision) is not int or old['revision'] != revision: raise PressureConflict('工况已更新，请重新载入')
                sid = scene_id; rev = revision+1
            record = dict(scene_id=sid, revision=rev, config=c, template_fingerprint=self.template.identity, updated_at=now())
            json_write(self.scenes/(sid+'.json'), record)
            return record

    def _version(self, sid, revision):
        record = self.load(sid)
        if type(revision) is not int or record['revision'] != revision: raise PressureConflict('工况已更新，请重新载入')
        return record

    def preview(self, scene_id, revision):
        with self.lock:
            record = self._version(scene_id, revision)
            resolved = self.template.resolve(normalize(record['config'], self.template))
            resolved.update(scene_id=scene_id, revision=revision, template_fingerprint=self.template.identity,
                            scene_fingerprint=fingerprint(dict(config=record['config'], template=self.template.identity, revision=revision)))
            record['preview'] = resolved
            json_write(self.scenes/(scene_id+'.json'), record)
            return resolved

    def start_export(self, scene_id, revision, scene_fingerprint):
        with self.lock:
            record = self._version(scene_id, revision)
            preview = record.get('preview')
            if not preview or scene_fingerprint != preview['scene_fingerprint']: raise PressureConflict('需要重新校验当前工况')
            if not preview['exportable']: raise ValueError('review reference and attestation required before export')
            if any(read_record(p)['status'] in ('queued', 'running') for p in self.jobs.glob('*.json')):
                raise PressureConflict('已有导出进行中，请等待完成')
            jid = uuid4().hex
            job = dict(job_id=jid, scene_id=scene_id, revision=revision, status='queued', updated_at=now(), solver_started=False)
            json_write(self.jobs/(jid+'.json'), job)
            self.pool.submit(self._export, jid, record)
            return job

    def export_status(self, job_id):
        with self.lock: return read_record(self.jobs/(checked_id(job_id)+'.json'))

    def _job_update(self, jid, **values):
        with self.lock:
            path = self.jobs/(jid+'.json'); job = read_record(path)
            job.update(values, updated_at=now()); json_write(path, job)

    def _export(self, jid, record):
        try:
            self._job_update(jid, status='running')
            self.template.verify()
            out = self.outputs/jid
            out.mkdir(exist_ok=False)
            for name in STRUCTURAL_FILES:
                shutil.copyfile(self.template.root/name, out/name)
                if file_sha(out/name) != self.template.hashes[name]: raise ValueError('copied structural checksum mismatch')
                validate_structural_file(out/name)
            # Re-resolve from checked source rather than trusting stored preview geometry.
            config = normalize(record['config'], self.template)
            preview = self.template.resolve(config)
            self._write_load(out, preview)
            self._write_supports(out)
            self._write_controls(out, config, preview)
            includes = [*STRUCTURAL_FILES, 'pressure-load.k', 'supports.k', 'controls.k']
            (out/'structural-pressure.k').write_text('*KEYWORD\n*TITLE\nSupplied structural pressure history; SI m kg s Pa\n'+
                ''.join('*INCLUDE\n'+name+'\n' for name in includes)+'*END\n', encoding='utf8')
            json_write(out/'config.json', config); json_write(out/'preview.json', preview)
            files = {p.name: file_sha(p) for p in out.iterdir() if p.is_file()}
            manifest = dict(schema_version='architecture.structural-pressure-package@1', entry='structural-pressure.k',
                files=files, template_fingerprint=self.template.identity, scene_id=record['scene_id'], revision=record['revision'],
                solver_started=False, engineering_validated=False, scope='supplied_structural_pressure_only',
                assumptions=['Pressure is user-supplied, not predicted.', 'Review attestation is recorded user input, not independent certification.',
                             'Explicit component bounding-plane exposed faces only; whole-building visibility is not classified.',
                             'Building bottom and ground bottom independently fixed; no new building-ground contact.',
                             'No air mesh, fluid coupling, explosive, detonation or automatic solver execution.',
                             'Existing structural material calibration/contact limitations remain.'])
            json_write(out/'manifest.json', manifest)
            for name, sha in files.items():
                if file_sha(out/name) != sha: raise ValueError('output checksum mismatch')
            archive = out/'structural-pressure.zip'
            with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
                for name in [*files, 'manifest.json']: z.write(out/name, name)
            self._job_update(jid, status='exported', output_dir=str(out), entry='structural-pressure.k',
                             download_url='/api/architecture/pressure/exports/'+jid+'/download', archive_sha256=file_sha(archive))
        except Exception as exc:
            self._job_update(jid, status='failed', error=str(exc))

    def _write_load(self, out, preview):
        with (out/'pressure-load.k').open('w', encoding='utf8') as stream:
            stream.write('$ Positive pressure acts inward against preserved outward segment winding.\n*DEFINE_CURVE\n9899001,0,1,1,0,0,0,0\n')
            for t,p in preview['curve_si']: stream.write(format(t, '.17g')+','+format(p, '.17g')+'\n')
            stream.write('*SET_SEGMENT_TITLE\nExplicit selected structural surface\n9899002\n')
            for face in preview['segments']: stream.write(','.join(map(str, face))+'\n')
            stream.write('*LOAD_SEGMENT_SET\n9899002,9899001,1,0\n')

    def _write_supports(self, out):
        nodes, _, ground, _, _ = self.template.geometry()
        with (out/'supports.k').open('w', encoding='utf8') as stream:
            stream.write('$ Independent building and ground bottom restraints, no new contact.\n')
            for sid, xyz in ((9899003,nodes), (9899004,ground)):
                bottom = min(p[2] for p in xyz.values())
                ids = sorted(n for n,p in xyz.items() if abs(p[2]-bottom)<1e-8)
                stream.write('*SET_NODE_LIST\n'+str(sid)+'\n')
                for i in range(0, len(ids), 8): stream.write(','.join(map(str,ids[i:i+8]))+'\n')
                stream.write('*BOUNDARY_SPC_SET\n'+str(sid)+',0,1,1,1,0,0,0\n')

    def _write_controls(self, out, c, preview):
        controls = c['controls']
        with (out/'controls.k').open('w', encoding='utf8') as stream:
            stream.write('*CONTROL_TERMINATION\n'+format(controls['termination_ms']/1000,'.17g')+'\n')
            stream.write('*CONTROL_TIMESTEP\n0,0.67,0,0\n')
            for keyword, interval in (('D3PLOT','plot_ms'),('NODOUT','history_ms'),('ELOUT','history_ms'),('GLSTAT','history_ms')):
                stream.write('*DATABASE_'+('BINARY_' if keyword=='D3PLOT' else '')+keyword+'\n'+format(controls[interval]/1000,'.17g')+'\n')
            for key, keyword in (('node_id','NODE'),('element_id','SOLID')):
                ids = sorted({m[key] for m in preview['monitors'] if key in m})
                if ids:
                    stream.write('*DATABASE_HISTORY_'+keyword+'\n')
                    for i in range(0,len(ids),8): stream.write(','.join(map(str,ids[i:i+8]))+'\n')

    def download(self, job_id):
        job = self.export_status(job_id)
        if job['status'] != 'exported': raise PressureConflict('导出尚未完成')
        path = self.outputs/checked_id(job_id)/'structural-pressure.zip'
        if path.parent.is_symlink() or path.is_symlink() or file_sha(path) != job['archive_sha256']:
            raise ValueError('export archive checksum mismatch')
        return path.read_bytes()
