"""Only launched by an explicit scene Start action, never by catalog/preview."""
import sys
from pathlib import Path

from .contracts import fingerprint,method_identity,MATERIAL,LIMITS
from .service import read_json,write_json


def main():
    path=Path(sys.argv[1]).resolve();directory=path.parent
    try:
        value=read_json(path)
        if value['method']!=method_identity() or value['input_fingerprint']!=fingerprint(value['config']) or value['model_fingerprint']!=fingerprint(value['model']):raise ValueError('输入或求解方法在排队期间变化，未启动计算')
        if value['material']!=MATERIAL or value['limits']!=LIMITS:raise ValueError('冻结的参考材料或预算与当前方法不匹配')
        from .solver import solve
        def progress(p):
            try:write_json(directory/'progress.json',p)
            except OSError:pass  # Optional progress telemetry cannot invalidate physical results.
        def gravity_diagnostics(d):write_json(directory/'gravity.json',d)
        result=solve(value,progress=progress,gravity_diagnostics=gravity_diagnostics)
        write_json(directory/'result.json',result)
    except Exception as exc:
        failure=dict(error=str(exc),status=getattr(exc,'status','failed'))
        if hasattr(exc,'diagnostics'):
            failure.update(stage='gravity',blast_applied=False,diagnostics=exc.diagnostics)
        write_json(directory/'failure.json',failure)


if __name__=='__main__':main()
