"""Independent fixed-building preview/pressure adapter for the main Web App.

The template archive contains structural inputs and display metadata only.
Initialization is lazy so the legacy/refined workbench remains independent.
"""
import json
import mimetypes
import os
from pathlib import Path
import shutil
import threading
from uuid import uuid4
import zipfile

from ..architecture.pressure_api import PREFIX, handle_pressure_request
from ..architecture.cpu_response.api import PREFIX as CPU_PREFIX, handle_cpu_response_request
from ..architecture.cpu_response.service import CpuResponseService
from ..architecture.scene_blast.api import PREFIX as SCENE_CPU_PREFIX, handle_request as handle_scene_request

ASSETS=Path(__file__).resolve().parent/'static'
RESOURCE=Path(__file__).resolve().parents[2]/'resources'/'fixed_building_pressure'/'three-storey-structural.zip'
STATIC_NAMES=frozenset({'fixed_building_preview.html','fixed_building_preview.css','fixed_building_preview.js',
                        'fixed_building_entry.css','structural_pressure.html','structural_pressure.css',
                        'structural_pressure.js','structural_pressure_view.js',
                        'fixed_building_response.html','fixed_building_response.css','fixed_building_response.js',
                        'fixed_building_response_view.js','fixed_building_response_charts.js',
                        'fixed_building_tnt.html','fixed_building_tnt.css','fixed_building_tnt.js','fixed_building_tnt_view.js',
                        'cpu_blast.html','cpu_blast.css','cpu_blast.js','blast_demo_cache.js',
                        'blast_demo.js','blast_demo_model.js','blast_demo_view.js','blast_demo_presentation.js','blast_demo_worker.js','blast_original_scenes.js',
                        'blast_panel_fracture.js','blast_fracture_view.js','blast_rebar_catalog.js','blast_rebar_layout.js',
                        'blast_rebar_bundles.js','blast_rebar_coupling.js','blast_rebar_view.js',
                        'blast_local_rebar.js','blast_local_rebar_view.js','blast_damage_fields.js',
                        'blast_powder.js','blast_powder_view.js'})


class FixedBuildingWorkspace:
    def __init__(self,data_dir,*,template_dir=None,resource_archive=None,asset_dir=None):
        self.root=Path(data_dir).resolve();self.template_dir=Path(template_dir).resolve() if template_dir else None
        self.archive=Path(resource_archive).resolve() if resource_archive else RESOURCE
        self.assets=Path(asset_dir).resolve() if asset_dir else ASSETS
        self._service=None;self.lock=threading.Lock()
        self._tnt=None
        self.cpu=CpuResponseService(self.root/'cpu_response')
        self._scene_cpu=None

    def _unpack(self):
        from ..architecture.pressure_model import STRUCTURAL_FILES, file_sha, StructuralTemplate
        if not self.archive.is_file():raise ValueError('固定建筑结构资源未安装')
        identity=file_sha(self.archive);cache=self.root/'templates'/identity
        if cache.is_dir():return cache
        self.root.mkdir(parents=True,exist_ok=True);cache.parent.mkdir(parents=True,exist_ok=True)
        expected=set(STRUCTURAL_FILES)|{'structural-template.json'}
        with zipfile.ZipFile(self.archive) as z:
            infos=z.infolist();names=[i.filename for i in infos]
            if set(names)!=expected or len(names)!=len(expected) or any(i.is_dir() or i.file_size>60_000_000 for i in infos) or sum(i.file_size for i in infos)>200_000_000:
                raise ValueError('固定建筑资源包内容不匹配')
            stage=cache.parent/('.stage-'+uuid4().hex);stage.mkdir()
            try:
                for name in names:
                    with z.open(name) as source,(stage/name).open('xb') as target:
                        for chunk in iter(lambda:source.read(1024*1024),b''):target.write(chunk)
                StructuralTemplate(stage)
                os.replace(stage,cache)
            finally:
                if stage.exists():
                    resolved=stage.resolve()
                    if stage.is_symlink() or resolved.parent!=cache.parent.resolve() or not stage.name.startswith('.stage-'):
                        raise ValueError('unsafe template staging cleanup path')
                    shutil.rmtree(resolved)
        return cache

    def service(self):
        with self.lock:
            if self._service is None:
                from ..architecture.pressure_service import PressureService
                self._service=PressureService(self.template_dir or self._unpack(),self.root/'scenarios')
            return self._service

    def close(self):
        if self._service is not None:self._service.close()
        if self._tnt is not None:self._tnt.close()
        self.cpu.close()
        if self._scene_cpu is not None:self._scene_cpu.close()

    def tnt_service(self):
        with self.lock:
            if self._tnt is None:
                from ..architecture.tnt_service import TntService
                self._tnt=TntService(self.root/'tnt')
            return self._tnt

    def request(self,method,path,payload=None):
        if path.startswith(SCENE_CPU_PREFIX):
            with self.lock:
                if self._scene_cpu is None:
                    from ..architecture.scene_blast.service import SceneBlastService
                    self._scene_cpu=SceneBlastService(self.root/'scene_cpu')
            return handle_scene_request(self._scene_cpu,method,path,payload)
        if path.startswith(CPU_PREFIX):
            return handle_cpu_response_request(self.cpu,method,path,payload)
        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}
        if path.startswith('/api/architecture/tnt/'):
            from ..architecture.tnt_api import handle_tnt_request
            try:status,body=handle_tnt_request(self.tnt_service(),'GET' if method=='HEAD' else method,path,payload)
            except (ImportError,OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:
                status,body=503,dict(error='TNT资源不可用：'+str(exc))
            if isinstance(body,bytes):
                csv=path.endswith('/csv')
                headers.update({'Content-Type':'text/csv; charset=utf-8' if csv else 'application/zip',
                                'Content-Disposition':'attachment; filename="'+('tnt-pressure-results.csv' if csv else 'building-tnt-fsi.zip')+'"'})
                return status,headers,body
            headers['Content-Type']='application/json; charset=utf-8'
            return status,headers,json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf8')
        try:service=self.service()
        except (ImportError,OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:
            status,body=503,dict(error='固定建筑模板不可用：'+str(exc))
        else:status,body=handle_pressure_request(service,'GET' if method=='HEAD' else method,path,payload)
        if isinstance(body,bytes):
            headers.update({'Content-Type':'application/zip','Content-Disposition':'attachment; filename="structural-pressure.zip"'})
            return status,headers,body
        headers['Content-Type']='application/json; charset=utf-8'
        return status,headers,json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf8')

    def static_response(self,path,*,legacy=False):
        mapping={'/fixed-building-pressure':'fixed_building_preview.html','/fixed-building-pressure/':'fixed_building_preview.html',
                 '/cpu-blast':'scene_blast.html' if legacy else 'cpu_blast.html','/cpu-blast/':'scene_blast.html' if legacy else 'cpu_blast.html',
                 '/fixed-building-pressure/response':'fixed_building_response.html','/fixed-building-pressure/response/':'fixed_building_response.html',
                 '/structural-pressure':'structural_pressure.html' if legacy else 'fixed_building_tnt.html',
                 '/structural-pressure/':'structural_pressure.html' if legacy else 'fixed_building_tnt.html'}
        name=mapping.get(path)
        if name is None and path.startswith('/static/') and path[8:] in STATIC_NAMES:name=path[8:]
        if name is not None:target=self.assets/name
        elif path.startswith('/static/vendor/three/'):
            relative=Path(path[len('/static/'):]);target=(self.assets/relative).resolve()
            vendor=(self.assets/'vendor'/'three').resolve()
            if '..' in relative.parts or not target.is_relative_to(vendor) or target.suffix!='.js':return None
        else:return None
        if not target.is_file():return 404,{'Content-Type':'text/plain; charset=utf-8'},b'fixed-building asset missing'
        return 200,{'Content-Type':mimetypes.guess_type(target.name)[0] or 'application/octet-stream',
                    'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'},target.read_bytes()
