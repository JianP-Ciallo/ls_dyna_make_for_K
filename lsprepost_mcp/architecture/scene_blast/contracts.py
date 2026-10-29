"""SI contracts deliberately separate from the old prescribed-pressure cases."""
from copy import deepcopy
import hashlib
import json
import math
import re

KINDS = ('commercial_supermarket', 'residential_community', 'subway_entrance', 'city_street', 'fixed_three_storey')
METHOD = 'rbsm-cohesive-ground-v1'
LIMITS = dict(max_bodies=2000, max_springs=40000, max_steps=30000, wall_s=90, max_frames=121)
MATERIAL = dict(e_pa=30e9, nu=.2, density_kg_m3=2400., ft_pa=2e6, fc_pa=30e6,
                gf_n_m=200., steel_e_pa=200e9, steel_fy_pa=400e6, steel_rupture_strain=.05,
                reference_steel_ratio=.005, damping_ratio=.02)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def number(value, lo, hi, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{name} 必须在 {lo:g}–{hi:g} 范围内')
    return float(value)


def normalize_input(value):
    if not isinstance(value, dict) or set(value)-{'schema_version','source','tnt','analysis'}:
        raise ValueError('仅接受建筑场景输入；旧压力倍率不是 TNT 当量')
    if value.get('schema_version','scene-blast-input@1') != 'scene-blast-input@1':raise ValueError('场景版本不支持')
    source=value.get('source',{})
    if not isinstance(source,dict) or set(source)-{'kind','project_name','scene_id','tnt_scene_id'} or source.get('kind') not in KINDS:raise ValueError('模型来源无效')
    name=source.get('project_name')
    if name is not None and (not isinstance(name,str) or not re.fullmatch(r'[\w\-\u4e00-\u9fff .]{1,100}',name) or name in {'.','..'}):raise ValueError('项目名称无效')
    scene=source.get('scene_id');tnt_scene=source.get('tnt_scene_id')
    for identity in (scene,tnt_scene):
        if identity is not None and (source['kind']!='fixed_three_storey' or not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',identity)):raise ValueError('固定建筑场景标识无效')
    if source['kind']=='fixed_three_storey' and name:raise ValueError('固定三层建筑使用其固定场景，不读取建模项目名称')
    tnt=value.get('tnt',{'position_m':[0,-10,0],'mass_kg':10})
    if not isinstance(tnt,dict) or set(tnt)-{'position_m','mass_kg'}:raise ValueError('TNT 参数无效')
    xyz=tnt.get('position_m')
    if not isinstance(xyz,list) or len(xyz)!=3:raise ValueError('TNT 坐标需要 XYZ')
    xyz=[number(v,-1000,1000,'TNT 坐标/m') for v in xyz]
    if abs(xyz[2])>1e-8:raise ValueError('首版荷载仅支持贴地爆炸，Z 必须为 0；不支持高架或室内爆源')
    a=value.get('analysis',{})
    if not isinstance(a,dict) or set(a)-{'duration_s','mesh_m'}:raise ValueError('模拟设置无效')
    fixed=source['kind']=='fixed_three_storey';mesh=number(a.get('mesh_m',2.5 if fixed else 2.0),1.,2.5,'宏单元尺寸/m')
    if fixed and mesh!=2.5:raise ValueError('固定三层首版采用已审计 2.5 m 规整参考，尺寸暂未开放修改')
    return dict(schema_version='scene-blast-input@1',source={'kind':source['kind'],'project_name':name,'scene_id':scene,'tnt_scene_id':tnt_scene},
                tnt={'position_m':xyz,'mass_kg':number(tnt.get('mass_kg'),.01,10000,'TNT 当量/kg')},
                analysis={'duration_s':number(a.get('duration_s',.25),.05,1.0,'时长/s'),
                          'mesh_m':mesh})


def method_identity():
    from pathlib import Path
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    return dict(name=METHOD, fingerprint=fingerprint({'files':files,'material':MATERIAL,'limits':LIMITS}))


def snapshot(config, model):
    return deepcopy(dict(config=config, model=model, input_fingerprint=fingerprint(config),
                         model_fingerprint=fingerprint(model), method=method_identity(), material=MATERIAL, limits=LIMITS))
