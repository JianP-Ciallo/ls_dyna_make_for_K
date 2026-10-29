"""Closed CPU case schema. JSON only, SI internally, bounded small reference cases."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

CaseSource = CaseSpec = ModelMap = StepSample = CaseResult = LoadMap = dict


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()


def closed(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + ': unknown or missing fields')


def adapter_identity() -> str:
    root=Path(__file__).parent
    return fingerprint({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))})


def finite(value, lo, hi, label):
    if isinstance(value, bool) or not isinstance(value, (float,int)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(label + ': invalid finite value')
    return value


def normalize_case(payload: dict) -> CaseSpec:
    from .benchmarks import make_benchmark
    from .loads import validate_curve
    closed(payload, ('source','geometry','reinforcement','materials','mesh','loads','analysis','budget','assumptions'), 'case')
    case = deepcopy(payload)
    source = case['source']
    closed(source, ('kind','id','revision','fingerprint'), 'source')
    if source['kind'] != 'benchmark':
        raise ValueError('building computation is not enabled at this stage')
    base = make_benchmark(source['id'])
    if source != base['source']:
        raise ValueError('benchmark definition identity mismatch')
    for name in ('geometry','reinforcement','materials','assumptions'):
        if case[name] != base[name]:
            raise ValueError(name + ': only the verified reference definition is enabled')
    closed(case['mesh'], base['mesh'], 'mesh')
    n = case['mesh']['n']
    if type(n) is not int or n not in (4,8,16,32):
        raise ValueError('reference mesh must be 4, 8, 16 or 32')
    if 'fibers' in case['mesh']:
        if type(case['mesh']['fibers']) is not int or case['mesh']['fibers'] not in (10,20):
            raise ValueError('fiber refinement must be 10 or 20')
        if case['mesh']['integration_points'] != 3:
            raise ValueError('only the verified three-point integration is enabled')
    closed(case['analysis'], ('kind','dt_s','duration_s','damping'), 'analysis')
    a = case['analysis']
    if a['kind'] not in ('static','dynamic'):
        raise ValueError('unknown analysis')
    finite(a['dt_s'], 1e-6, 0.001, 'dt_s')
    finite(a['duration_s'], 0.001, 1, 'duration_s')
    if a['damping'] != 0:
        raise ValueError('reference cases use zero damping')
    closed(case['budget'], base['budget'], 'budget')
    for key, ceiling in base['budget'].items():
        finite(case['budget'][key], 1, ceiling, key)
        if key != 'wall_s' and type(case['budget'][key]) is not int:
            raise ValueError('integer resource budget required')
    if math.ceil(a['duration_s']/a['dt_s']) + 4 > case['budget']['max_steps']:
        raise ValueError('integration step budget exceeded')
    closed(case['loads'], ('curve_si','static_pressure_pa','direction'), 'loads')
    validate_curve(case['loads']['curve_si'])
    if case['loads']['curve_si'][-1][0] > a['duration_s']:
        raise ValueError('load extends past analysis duration')
    if case['budget']['frames']<4 or case['budget']['samples']<len({0,a['duration_s'],*[t for t,_ in case['loads']['curve_si']]}):
        raise ValueError('sample budget must retain endpoints and pressure knots')
    finite(case['loads']['static_pressure_pa'], 0, 100000, 'static pressure')
    if any(p > 100000 for _,p in case['loads']['curve_si']):
        raise ValueError('reference pressure budget exceeded')
    direction = case['loads']['direction']
    allowed = ([1,0,0],[-1,0,0],[0,1,0],[0,-1,0]) if case['geometry']['kind']=='column' else ([0,0,1],[0,0,-1])
    if direction not in allowed:
        raise ValueError('unsupported pressure direction')
    return case
