"""CPython regressions of single materials, precision scope and one tiny plate."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).parents[1]
HERE=ROOT/'artifacts/native-host-precision-guard-20261024-01'

@pytest.mark.parametrize('mode',['point','acceptance','reject','guard','increment','plate'])
def test_python_host_precision_and_restoration(mode,tmp_path):
    runtime=Path(os.environ.get('NATIVE_HOST_RUNTIME',HERE/'runtime'))
    bridge=Path(os.environ.get('NATIVE_HOST_BRIDGE',HERE/'bin/MaterialHostGuardProbe.dll'))
    result=subprocess.run([str(runtime/'python.exe'),'-B','-X','utf8',str(ROOT/'scripts/probe_native_host_precision.py'),
        '--bridge',str(bridge),'--mode',mode,'--output',str(tmp_path/'probe')],cwd=ROOT,capture_output=True,timeout=30,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (tmp_path/'stdout.txt').write_bytes(result.stdout);(tmp_path/'stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0,result.stderr.decode('utf8','replace')[-4000:]
    data=json.loads((tmp_path/'probe/result.json').read_text())
    assert data['structure_assembled'] is (mode=='plate')
    assert data['whole_building_assembled'] is False
    if mode=='point':
        assert len(data['rows'])==6
        assert all(r['host_low_bit']==(0. if r['bits']==53 else 2.**-60) for r in data['rows'])
