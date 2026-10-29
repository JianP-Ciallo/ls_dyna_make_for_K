"""CPython checks of frozen material points, scopes or one synthetic 1m plate."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'artifacts/native-host-precision-guard-20261024-01'
CAPSULES={
    'old':ROOT/'artifacts/native-first-failure-capture-20261024-01/execution-01/worker/native-first-failure.jsonl',
    'new':ROOT/'artifacts/native-whole-gravity-precision-20261024-01/execution-01/worker/native-first-failure.jsonl',
}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bridge',type=Path,default=HERE/'bin/MaterialHostGuardProbe.dll')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=('point','acceptance','reject','guard','increment','plate'),default='point')
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    os.environ['OPENSEES_NATIVE_FAILURE_LOG']=str(a.output/'native-event.jsonl')
    runtime=Path(sys.executable).resolve().parent
    handles=[os.add_dll_directory(str(d)) for d in (Path('D:/mingw64/bin'),runtime/'Lib/site-packages/openseespywin')]
    import numpy
    import openseespywin.opensees as native
    bridge=ctypes.PyDLL(str(a.bridge.resolve()))
    bridge.read_x87.restype=ctypes.c_uint
    bridge.read_mxcsr.restype=ctypes.c_uint
    bridge.write_x87.argtypes=[ctypes.c_uint]
    bridge.effective_low_bit.restype=ctypes.c_double
    rows=[];initial=bridge.read_x87()
    try:
        if a.mode=='plate':
            sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,str(ROOT))
            from test_scene_blast_native_failure_diagnostics import minimal_plate_probe
            before=bridge.read_x87()
            assert (before & 0x300)==0x200,'actual pyd plate regression requires the PC53 Python host'
            value=minimal_plate_probe()
            assert bridge.read_x87()==before,'actual pyd plate solve changed caller precision'
            value.update(passed=True,cw_before=before,cw_after=bridge.read_x87())
            rows.append(value)
        elif a.mode in ('guard','increment'):
            fn=getattr(bridge,'guard_checks' if a.mode=='guard' else 'increment_checks')
            fn.restype=ctypes.c_char_p
            rows.append(json.loads(fn()))
        else:
            fn=bridge.material_host_probe
            fn.argtypes=[ctypes.c_char_p,ctypes.c_int];fn.restype=ctypes.c_char_p
            for name,capsule in CAPSULES.items():
                for bits in (53,64,53):
                    expected=(initial&~0x300)|(0x200 if bits==53 else 0x300)
                    bridge.write_x87(expected)
                    low_bit=bridge.effective_low_bit()
                    value=json.loads(fn(str(capsule).encode('utf8'),{'point':0,'acceptance':1,'reject':2}[a.mode]))
                    assert 'bridge_error' not in value,value
                    value.update(capsule=name,bits=bits,host_low_bit=low_bit,cw_after_return=bridge.read_x87(),capsule_sha256=hashlib.sha256(capsule.read_bytes()).hexdigest())
                    assert value['cw_after_return']==expected,value
                    assert value['cw_before']==value['cw_after']==expected,value
                    # Arithmetic can set sticky exception flags, but never MXCSR controls.
                    assert value['mxcsr_before']&~0x3f==value['mxcsr_after']&~0x3f,value
                    assert value['five_strain_change']==0,value
                    rows.append(value)
        result=dict(runtime=str(sys.executable),pyd=str(native.__file__),pyd_sha256=hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),bridge_sha256=hashlib.sha256(a.bridge.read_bytes()).hexdigest(),mode=a.mode,rows=rows,
                    structure_assembled=a.mode=='plate',whole_building_assembled=False,
                    fixture='synthetic_1m_plate_original_F2_section' if a.mode=='plate' else 'single_material_or_precision_scope')
        (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print(json.dumps(result))
        if a.mode in ('point','acceptance'):
            assert all(r['native_code']==0 and abs(r['sigma33'])<=1.e-8 for r in rows),rows
        elif a.mode=='reject':
            assert all(r['native_code']<0 and r['rejected_stress_change']==0 for r in rows),rows
        else:assert all(r.get('passed') for r in rows),rows
    finally:
        bridge.write_x87(initial)
        assert bridge.read_x87()==initial

if __name__=='__main__':main()
