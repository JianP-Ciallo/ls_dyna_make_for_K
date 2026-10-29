"""Read-only evidence from one earlier building trial; never a solver entry."""
import json
from pathlib import Path
from .results import load_result, MAX_RESULT_BYTES

DEFAULT_TRIAL=Path(__file__).resolve().parents[3]/'artifacts'/'cpu-response-building-trial-20261022-01'
FILES={'result.json':('result.json','application/json; charset=utf-8'),
       'curves.csv':('curves.csv','text/csv; charset=utf-8'),
       'report.md':('analysis/report.md','text/markdown; charset=utf-8'),
       'deformation-and-steel.png':('analysis/deformation-and-steel.png','image/png'),
       'response-curves.png':('analysis/response-curves.png','image/png')}


class SavedBuildingTrial:
    def __init__(self,root=None):self.root=Path(root) if root is not None else DEFAULT_TRIAL

    def _path(self,relative):
        path=self.root/relative
        if self.root.is_symlink() or any(p.is_symlink() for p in [path,*path.parents] if p!=self.root.parent and p.is_relative_to(self.root)):
            raise ValueError('saved building symlink rejected')
        if path.stat().st_size>MAX_RESULT_BYTES:raise ValueError('saved building artifact is too large')
        return path

    def _load(self):
        self._path('manifest.json');self._path('parent-process.json')
        value=load_result(self.root);process=json.loads((self.root/'parent-process.json').read_text(encoding='utf8'))
        if value['source'].get('kind')!='regularized_building_reference' or value['source'].get('id')!='three-storey-structural-reference' or value['mesh'].get('kind')!='building_reference' or process.get('status')!='completed':
            raise ValueError('saved building trial identity mismatch')
        return value,process

    def status(self):
        base=dict(solver_enabled=False,convergence_verified=False,trial=None,
                  remaining=['整栋网格收敛验证','整栋时间步长收敛验证','验收后开放整栋计算与三维回放'])
        try:
            value,process=self._load();case=value['provenance']['case'];loads=case['loads']
            artifacts={}
            for name,(relative,_) in FILES.items():
                try:self._path(relative)
                except FileNotFoundError:continue
                artifacts[name]='/api/architecture/pressure/cpu-response/building-trial/artifacts/'+name
            return dict(base,status='saved_trial',trial=dict(input_fingerprint=value['input_fingerprint'],
                source=value['source'],duration_ms=case['analysis']['duration_s']*1000,dt_ms=case['analysis']['dt_s']*1000,
                peak_pressure_kpa=max(row[1] for row in loads['curve_si'])/1000,target=loads['target_component_id'],
                wall_s=process.get('wall_s'),nodes=len(value['mesh']['nodes']),elements=len(value['mesh']['elements']),
                checks=case.get('checks',{}),peaks=value['peaks'],artifacts=artifacts))
        except (OSError,ValueError,TypeError,KeyError) as exc:
            return dict(base,status='unavailable',reason='已有整栋首试资料不可用：'+str(exc))

    def artifact(self,name):
        if name not in FILES:raise FileNotFoundError(name)
        self._load()  # Integrity/identity must still hold when opening a download.
        relative,mime=FILES[name];return self._path(relative).read_bytes(),mime
