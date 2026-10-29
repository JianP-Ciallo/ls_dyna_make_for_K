"""Single saved material point; no building or thirteen-element assembly."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).parents[1]
HERE=ROOT/'artifacts/native-plate-precision-20261024-01'
SOURCE=ROOT/'artifacts/native-first-failure-capture-20261024-01/execution-01/worker/native-first-failure.jsonl'


def test_saved_real_material_point_meets_original_sigma33_with_state_and_tangent_checks(tmp_path):
    exe=Path(os.environ.get('NATIVE_PRECISION_EXE',HERE/'bin/NativeMaterialRegression.exe'))
    runtime=Path(os.environ.get('NATIVE_PRECISION_RUNTIME',HERE/'runtime'))
    env=os.environ.copy();env.pop('OPENSEES_NATIVE_FAILURE_LOG',None)
    env['PATH']=f'{runtime};{runtime}/Lib/site-packages/openseespywin;D:/mingw64/bin;'+env['PATH']
    result=subprocess.run([str(exe),'point-acceptance',str(SOURCE)],cwd=ROOT,env=env,capture_output=True,timeout=20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (tmp_path/'stdout.txt').write_bytes(result.stdout);(tmp_path/'stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0,result.stderr.decode('utf8','replace')[-3000:]
    row=next(r for r in map(json.loads,(x for x in result.stdout.decode('utf8').splitlines() if x.startswith('{'))) if r['kind']=='acceptance')
    assert abs(row['sigma33'])<=1.e-8
    assert row['external_strain_unchanged'] and row['copy_commit_revert_serialization']
    assert row['tangent_directions']==20


def test_precise_thickness_survives_zero_inplane_increment_and_history(tmp_path):
    exe=Path(os.environ.get('NATIVE_PRECISION_EXE',HERE/'bin/NativeMaterialRegression.exe'))
    runtime=Path(os.environ.get('NATIVE_PRECISION_RUNTIME',HERE/'runtime'))
    env=os.environ.copy();env.pop('OPENSEES_NATIVE_FAILURE_LOG',None)
    env['PATH']=f'{runtime};{runtime}/Lib/site-packages/openseespywin;D:/mingw64/bin;'+env['PATH']
    result=subprocess.run([str(exe),'point-increment',str(SOURCE)],cwd=ROOT,env=env,capture_output=True,timeout=20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (tmp_path/'stdout.txt').write_bytes(result.stdout);(tmp_path/'stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0,result.stderr.decode('utf8','replace')[-3000:]
    row=json.loads(next(x for x in result.stdout.decode('utf8').splitlines() if x.startswith('{')))
    assert row['tail_lifecycle'] is True


def test_unsupported_multiple_parallel_children_reject_precision_without_mutation(tmp_path):
    exe=Path(os.environ.get('NATIVE_PRECISION_EXE',HERE/'bin/NativeMaterialRegression.exe'))
    runtime=Path(os.environ.get('NATIVE_PRECISION_RUNTIME',HERE/'runtime'))
    env=os.environ.copy();env.pop('OPENSEES_NATIVE_FAILURE_LOG',None)
    env['PATH']=f'{runtime};{runtime}/Lib/site-packages/openseespywin;D:/mingw64/bin;'+env['PATH']
    result=subprocess.run([str(exe),'point-multi',str(SOURCE)],cwd=ROOT,env=env,capture_output=True,timeout=20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (tmp_path/'stdout.txt').write_bytes(result.stdout);(tmp_path/'stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0,result.stderr.decode('utf8','replace')[-3000:]
