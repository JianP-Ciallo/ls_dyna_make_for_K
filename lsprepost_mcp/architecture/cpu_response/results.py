"""Finite validated result bundles with atomic manifest publication."""
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
from uuid import uuid4

ArtifactIndex=dict
MAX_RESULT_BYTES=32_000_000


def json_write(path: Path,value):
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf8')
    if len(raw)>MAX_RESULT_BYTES:raise ValueError('result artifact size budget exceeded')
    temp=path.with_name('.'+path.name+'-'+uuid4().hex)
    temp.write_bytes(raw);os.replace(temp,path)


def validate_result(result):
    if not isinstance(result,dict) or result.get('schema_version')!='cpu-response.result@1':
        raise ValueError('unknown CPU result schema')
    def finite_tree(v):
        if isinstance(v,float) and not math.isfinite(v):raise ValueError('nonfinite CPU result')
        if isinstance(v,dict):
            for x in v.values():finite_tree(x)
        if isinstance(v,list):
            for x in v:finite_tree(x)
    finite_tree(result)
    for key in ('source','input_fingerprint','mesh','frames','curves','peaks','diagnostics','provenance'):
        if key not in result:raise ValueError('incomplete result: '+key)
    mesh=result['mesh'];nn=len(mesh['nodes']);ns=len(mesh['steel_samples'])
    if not result['frames'] or len(result['frames'])>500 or len(result['curves'])>5000:
        raise ValueError('invalid result samples')
    for collection in ('frames','curves'):
        times=[r['time_s'] for r in result[collection]]
        if any(b<=a for a,b in zip(times,times[1:])):raise ValueError('result time is not increasing')
    for frame in result['frames']:
        if len(frame['displacements_m'])!=nn or len(frame['steel_stress_pa'])!=ns or len(frame['steel_strain'])!=ns:
            raise ValueError('result field shape mismatch')


def write_artifacts(result: dict,result_dir: Path) -> ArtifactIndex:
    validate_result(result)
    root=Path(result_dir);root.mkdir(parents=True,exist_ok=True)
    json_write(root/'result.json',result)
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['time_s','pressure_pa','ux_m','uy_m','uz_m','steel_max_pa','steel_min_pa','energy_j'])
    for row in result['curves']:
        writer.writerow([row['time_s'],row.get('pressure_pa',0),*row['monitor_displacement_m'],row.get('steel_max_pa',0),row.get('steel_min_pa',0),row.get('energy_j',0)])
    (root/'curves.csv').write_text(stream.getvalue(),encoding='utf-8-sig',newline='')
    index={}
    for name,mime in (('result.json','application/json'),('curves.csv','text/csv; charset=utf-8')):
        raw=(root/name).read_bytes();index[name]=dict(sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),mime=mime)
    json_write(root/'manifest.json',index)
    return index


def load_result(result_dir: Path) -> dict:
    root=Path(result_dir)
    index=json.loads((root/'manifest.json').read_text(encoding='utf8'))
    if set(index)!= {'result.json','curves.csv'}:raise ValueError('unexpected result artifacts')
    for name,meta in index.items():
        path=root/name
        if path.is_symlink() or path.stat().st_size>MAX_RESULT_BYTES:raise ValueError('unsafe result artifact')
        raw=path.read_bytes()
        if len(raw)!=meta['size_bytes'] or hashlib.sha256(raw).hexdigest()!=meta['sha256']:
            raise ValueError('result integrity mismatch')
    result=json.loads((root/'result.json').read_text(encoding='utf8'));validate_result(result)
    return result
