"""Supplied structural pressure histories and checked retained structural meshes.

No load prediction, explosive definition, fluid mesh or solver invocation.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import threading

import numpy as np

from .pressure_mesh import read_nodes, read_solids, exterior_faces

STRUCTURAL_FILES = ('materials-solver.k', 'solids-solver.k', 'solid-properties.k',
                    'reinforcement.k', 'installation.k', 'ground-solver.k')
FACES = dict(west=(0, -1), east=(0, 1), south=(1, -1), north=(1, 1), roof=(2, 1))
RESERVED = (9899001, 9899002, 9899003, 9899004)
STRUCTURAL_KEYWORDS = frozenset({
    '*NODE', '*ELEMENT_SOLID', '*ELEMENT_BEAM', '*PART', '*SECTION_SOLID', '*SECTION_BEAM',
    '*MAT_ELASTIC', '*MAT_CONCRETE_DAMAGE_REL3', '*MAT_PLASTIC_KINEMATIC', '*MAT_ADD_EROSION',
    '*DEFINE_CURVE', '*SET_NODE_LIST', '*SET_PART_LIST', '*CONSTRAINED_INTERPOLATION',
    '*CONSTRAINED_BEAM_IN_SOLID', '*CONSTRAINED_BEAM_IN_SOLID_PENALTY',
    '*CONSTRAINED_JOINT_REVOLUTE', '*CONSTRAINED_NODAL_RIGID_BODY',
})


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode('utf8')).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
    return digest.hexdigest()


def closed(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + ': unknown or missing fields')


def number(value, label, lower=0, upper=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper or not math.isfinite(value):
        raise ValueError(label + ': finite value outside allowed range')
    return float(value)


def text(value, label, maximum=200):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ValueError(label + ': invalid text')
    return value.strip()


def default_config(template):
    cid = next((k for k, c in template.components.items() if c['role'] == 'wall'), next(iter(template.components)))
    return dict(name='外部压力结构工况', notes='', target=dict(component_id=cid, face='west'),
                curve_ms_kpa=[], source=dict(reference='', reviewer='', reviewed=False), monitors=[],
                controls=dict(termination_ms=100, plot_ms=1, history_ms=.1))


def normalize(config, template):
    closed(config, ('name', 'notes', 'target', 'curve_ms_kpa', 'source', 'monitors', 'controls'), 'config')
    c = deepcopy(config)
    c['name'] = text(c['name'], 'name', 120)
    if not c['name']: raise ValueError('name is required')
    c['notes'] = text(c['notes'], 'notes', 4000)
    closed(c['target'], ('component_id', 'face'), 'target')
    if c['target']['component_id'] not in template.components or c['target']['face'] not in FACES:
        raise ValueError('unknown target component or face')
    closed(c['source'], ('reference', 'reviewer', 'reviewed'), 'source')
    for k in ('reference', 'reviewer'): c['source'][k] = text(c['source'][k], k, 1000)
    if type(c['source']['reviewed']) is not bool: raise ValueError('reviewed must be boolean')
    closed(c['controls'], ('termination_ms', 'plot_ms', 'history_ms'), 'controls')
    for k in c['controls']: c['controls'][k] = number(c['controls'][k], k, 1e-6, 10000)
    end = c['controls']['termination_ms']
    if any(c['controls'][k] > end for k in ('plot_ms', 'history_ms')): raise ValueError('output interval exceeds termination')
    curve = c['curve_ms_kpa']
    if not isinstance(curve, list) or len(curve) > 10000: raise ValueError('curve requires at most 10000 rows')
    previous = -1
    for row in curve:
        if not isinstance(row, list) or len(row) != 2: raise ValueError('curve rows require time_ms,pressure_kpa')
        row[:] = [number(row[0], 'curve time', 0, end), number(row[1], 'curve pressure', 0, 1e6)]
        if row[0] <= previous: raise ValueError('curve times must strictly increase')
        previous = row[0]
    if curve and (len(curve) < 2 or curve[0] != [0, 0] or curve[-1][1] != 0):
        raise ValueError('curve must start at zero time/pressure and finish at zero pressure')
    monitors = c['monitors']
    if not isinstance(monitors, list) or len(monitors) > 128: raise ValueError('at most 128 monitors')
    ids = set()
    for monitor in monitors:
        closed(monitor, ('id', 'kind', 'position_m'), 'monitor')
        mid = monitor['id']
        if not isinstance(mid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', mid) or mid in ids:
            raise ValueError('unique monitor IDs required')
        ids.add(mid)
        if monitor['kind'] not in ('structure_node', 'ground_node', 'solid_stress'): raise ValueError('unsupported structural monitor')
        xyz = monitor['position_m']
        if not isinstance(xyz, list) or len(xyz) != 3: raise ValueError('monitor position requires XYZ')
        monitor['position_m'] = [number(v, 'monitor coordinate', -1e6, 1e6) for v in xyz]
    return c


class StructuralTemplate:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.index_name = 'structural-template.json' if (self.root/'structural-template.json').is_file() else 'blast-template.json'
        sealed = json.loads((self.root/self.index_name).read_text(encoding='utf8'))
        self.payload = sealed['payload']
        self.identity = sealed['template_fingerprint']
        if fingerprint(self.payload) != self.identity: raise ValueError('template semantic checksum mismatch')
        self.template_id = sealed['template_id']
        self.components = self.payload['components']
        if not self.components: raise ValueError('template has no components')
        self.bounds = self.payload['geometry_metadata']
        self.hashes = {n: self.payload['files'][n] for n in STRUCTURAL_FILES}
        self.lock = threading.Lock()
        self._geometry = None
        self.verify()

    def verify(self):
        index = self.root/self.index_name
        if index.is_symlink(): raise ValueError('template index symlink rejected')
        sealed = json.loads(index.read_text(encoding='utf8'))
        if fingerprint(sealed['payload']) != self.identity: raise ValueError('template semantic checksum mismatch')
        for name, sha in self.hashes.items():
            path = self.root/name
            if path.is_symlink() or file_sha(path) != sha: raise ValueError('template file checksum mismatch: '+name)

    def geometry(self):
        with self.lock:
            if self._geometry is None:
                self.verify()
                nodes = read_nodes(self.root/'solids-solver.k')
                elements = read_solids(self.root/'solids-solver.k')
                ground_nodes = read_nodes(self.root/'ground-solver.k')
                ground_elements = read_solids(self.root/'ground-solver.k')
                self._geometry = (nodes, elements, ground_nodes, ground_elements, exterior_faces(elements))
            return self._geometry

    def schema(self):
        return dict(template_id=self.template_id, template_fingerprint=self.identity,
                    default_config=default_config(self), faces=list(FACES),
                    geometry=dict(building_bounds_m=self.bounds['building_bounds_m'],
                                  ground_bounds_m=self.bounds['ground_bounds_m'],
                                  air_bounds_m=self.bounds.get('air_bounds_m'),
                                  components=[dict(id=cid, role=c['role'], level=c.get('level'), bounds_m=c['native_bounds_m'])
                                              for cid, c in self.components.items()]),
                    scope='supplied_structural_pressure_only', solver_started=False)

    def preview_scene(self):
        """Only immutable display metadata; never parse native nodes/elements here."""
        def corners(b):
            return [[b[0],b[1],b[2]],[b[3],b[1],b[2]],[b[3],b[4],b[2]],[b[0],b[4],b[2]],
                    [b[0],b[1],b[5]],[b[3],b[1],b[5]],[b[3],b[4],b[5]],[b[0],b[4],b[5]]]
        components=[]
        for cid,c in self.components.items():
            bounds=c['native_bounds_m'];vertices=c.get('vertices_m')
            if (not isinstance(vertices,list) or len(vertices)!=8 or
                any(len(v)!=3 for v in vertices) or
                any(abs(min(v[a] for v in vertices)-bounds[a])>1e-7 or
                    abs(max(v[a] for v in vertices)-bounds[a+3])>1e-7 for a in range(3))):
                vertices=corners(bounds)
            material=c.get('material',{'glass':'glass','window_frame':'metal','door':'wood','partition':'plaster'}.get(c['role'],'concrete'))
            components.append(dict(id=cid,role=c['role'],level=c.get('level'),material=material,
                                   bounds_m=bounds,vertices_m=vertices))
        rooms=[{k:r[k] for k in ('id','label','kind','bounds_m','level','unit','area_m2') if k in r}
               for r in self.payload.get('rooms',{}).values()]
        levels=sorted({r['level'] for r in rooms if isinstance(r.get('level'),int) and r['level']>=0})
        if not levels:levels=sorted({c['level'] for c in components if isinstance(c.get('level'),int) and c['level']>=0}) or [0]
        ground=self.bounds['ground_bounds_m']
        return dict(template_id=self.template_id,template_fingerprint=self.identity,components=components,rooms=rooms,
                    bounds_m=self.bounds['building_bounds_m'],levels=levels,ground=dict(id='concrete-ground',role='ground',
                    level=-1,material='concrete',bounds_m=ground,vertices_m=corners(ground)),
                    mesh_generated=False,solver_started=False,scope='immutable_fixed_building_display_only')

    def resolve(self, c):
        self.verify()
        if not c['curve_ms_kpa']: raise ValueError('pressure history is empty')
        nodes, elements, ground_nodes, ground_elements, exposed = self.geometry()
        component = self.components[c['target']['component_id']]
        selected = elements[elements[:, 1] == component['part_id']]
        if not len(selected): raise ValueError('target has no actual solid elements')
        candidates = exposed[np.isin(exposed, np.unique(selected[:, 2:])).all(axis=1)]
        own_faces = {tuple(sorted(map(int, face))) for face in exterior_faces(selected)}
        candidates = [face for face in candidates if tuple(sorted(map(int, face))) in own_faces]
        axis, sign = FACES[c['target']['face']]
        bound = component['native_bounds_m'][axis + (3 if sign > 0 else 0)]
        segments = []; points = []; area = 0
        for face in candidates:
            p = np.asarray([nodes[int(n)] for n in face])
            normal = np.cross(p[1]-p[0], p[2]-p[0])
            if not np.allclose(p[:, axis], bound, atol=1e-8, rtol=0) or normal[axis]*sign <= 0: continue
            if abs(normal @ (p[3]-p[0])) > 1e-8: raise ValueError('nonplanar target face')
            area += .5*(np.linalg.norm(normal)+np.linalg.norm(np.cross(p[2]-p[0], p[3]-p[0])))
            segments.append(list(map(int, face))); points.append(p.tolist())
        if not segments: raise ValueError('no exposed segments on selected component bounding plane')
        resolved = []
        for m in c['monitors']:
            xyz, els = (ground_nodes, ground_elements) if m['kind'] == 'ground_node' else (nodes, elements)
            if m['kind'] == 'solid_stress':
                ids = els[:, 0]; positions = np.asarray([[xyz[int(n)] for n in e[2:]] for e in els]).mean(axis=1)
                key = 'element_id'
            else:
                ids = np.unique(els[:, 2:]); positions = np.asarray([xyz[int(n)] for n in ids]); key = 'node_id'
            distances = np.linalg.norm(positions-np.asarray(m['position_m']), axis=1)
            i = int(np.argmin(distances))
            if distances[i] > 2: raise ValueError('no physical sampling candidate within 2 m: '+m['id'])
            resolved.append(dict(m, **{key: int(ids[i])}, sample_position_m=positions[i].tolist(), distance_m=float(distances[i])))
        ready = bool(c['source']['reviewed'] and c['source']['reference'] and c['source']['reviewer'])
        return dict(segment_count=len(segments), area_m2=float(area), segments=segments,
                    segment_points_m=points, curve_si=[[t/1000, p*1000] for t,p in c['curve_ms_kpa']],
                    monitors=resolved, exportable=ready, engineering_validated=False,
                    warnings=[] if ready else ['A supplied load reference, reviewer and review attestation are required before export.'])


def validate_structural_file(path):
    """Reject nested paths, incompatible fluid/loading cards and reserved ID collisions."""
    with Path(path).open(encoding='utf8') as stream:
        for line in stream:
            value = line.strip().upper()
            if value.startswith('*') and value.removesuffix('+').removesuffix('_TITLE') not in STRUCTURAL_KEYWORDS:
                raise ValueError('unsupported card in structural input: '+value)
            if not value or value.startswith(('*', '$')): continue
            tokens = value.split(',')[0].split()
            if not tokens: continue
            token = tokens[0]
            if token.isdigit() and int(token) in RESERVED: raise ValueError('reserved export ID collision')
