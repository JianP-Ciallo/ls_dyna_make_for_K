"""Analytic block meshes and bounded-memory extrusion for the B120 source.

Only scalar geometry and subdivision parameters are accepted. No source node
or element table is read. Rectangular topology uses the existing Phase15 core.
"""
from __future__ import annotations

from collections import Counter
import math

from .phase15 import compile_axisymmetric_quad_mesh

GEOMETRY = {'axis': [0, 0, 1], 'body_radius': 1.05, 'concrete_z': [-.54, .86],
            'bore_radius': .049, 'bore_z': [0, .86], 'C5_z': [-1.04, -.54],
            'RC40_z': [-1.54, -1.04], 'steel_inner_radius': 1.05,
            'steel_outer_radius': 1.066, 'steel_z': [-1.54, .86],
            'steel_band_outer_radius': 1.086, 'steel_bands_z': [[-.42, -.26], [.7, .86]],
            'coordinate_fit_tolerance': 2e-6}
DEFAULT_MESH = {'core_divisions': 8, 'core_radial_layers': 3, 'bore_transition_layers': 4,
                'outer_extension_cells': 21, 'outer_radial_layers': 25, 'axial_step_m': .02}
Z_BREAKS = (-1.54, -1.04, -.54, -.42, -.26, 0., .56, .7, .86)
NODE_START = ELEMENT_START = 2000001
SALE_NODE_START = SALE_ELEMENT_START = 9000001


def _axial_counts(step):
    return [max(1, math.ceil(round((b-a)/step, 10))) for a, b in zip(Z_BREAKS, Z_BREAKS[1:])]


def validate_mesh_parameters(raw):
    if not isinstance(raw, dict) or set(raw) != set(DEFAULT_MESH):
        raise ValueError('mesh requires exactly the documented scalar subdivision fields')
    for name in set(DEFAULT_MESH)-{'axial_step_m'}:
        v = raw[name]
        if type(v) is not int or not 1 <= v <= 64:
            raise ValueError(f'{name} must be an integer from 1 to 64')
    if raw['core_divisions'] % 2:
        raise ValueError('core_divisions must be even for matching square boundaries')
    step = raw['axial_step_m']
    if isinstance(step, bool) or not isinstance(step, (float, int)) or not math.isfinite(step) or not .001 <= step <= .5:
        raise ValueError('axial_step_m must be finite and between .001 and .5')
    if _estimate(raw)['elements'] > 1500000:
        raise ValueError('requested mesh exceeds the controlled 1500000-element budget')
    return dict(raw)


def _estimate(p):
    n, e = p['core_divisions'], p['outer_extension_cells']
    circumference = 4*(n+2*e)
    fill = n*n+4*n*p['core_radial_layers']
    full = fill+4*n*p['bore_transition_layers']+4*e*(n+e)+circumference*p['outer_radial_layers']
    annular = full-fill
    full_nodes = full+circumference//2+1
    annular_nodes = annular+(circumference+4*n)//2
    c = _axial_counts(p['axial_step_m'])
    concrete_lower, concrete_upper = sum(c[2:5]), sum(c[5:])
    steel = circumference*(sum(c)+c[3]+c[7])
    by_part = {2: concrete_lower*full+concrete_upper*annular, 4: c[1]*full, 5: c[0]*full, 6: steel}
    nodes = (c[0]+c[1]+1)*full_nodes+(concrete_lower+1)*full_nodes+concrete_upper*annular_nodes
    nodes += (sum(c)+1)*2*circumference+(c[3]+c[7]+2)*circumference
    return {'nodes': nodes, 'elements': sum(by_part.values()), 'elements_by_part': {str(k): v for k, v in by_part.items()},
            'full_section_nodes': full_nodes, 'annular_section_nodes': annular_nodes,
            'full_section_quads': full, 'annular_section_quads': annular,
            'outer_circumference_cells': circumference, 'bore_circumference_cells': 4*n,
            'bottom_nodes': full_nodes+2*circumference, 'bottom_segments': full+circumference,
            'sale_nodes': 275706, 'sale_elements': 262500}


def estimate_mesh(raw):
    return _estimate(validate_mesh_parameters(raw))


def _levels(step):
    points = [Z_BREAKS[0]]
    for a, b, count in zip(Z_BREAKS, Z_BREAKS[1:], _axial_counts(step)):
        points.extend(round(a+(b-a)*i/count, 12) for i in range(1, count+1))
    return points


def _ring_at(z):
    return any(a-1e-10 <= z <= b+1e-10 for a, b in GEOMETRY['steel_bands_z'])


def _area(xy):
    return .5*sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(xy, xy[1:]+xy[:1]))


def _quad_jacobians(xy):
    signs = ((-1, -1), (1, -1), (1, 1), (-1, 1))
    for xi in (-1/math.sqrt(3), 1/math.sqrt(3)):
        for eta in (-1/math.sqrt(3), 1/math.sqrt(3)):
            dx = [sum(p[a]*s[0]*(1+s[1]*eta)/4 for p, s in zip(xy, signs)) for a in (0, 1)]
            dy = [sum(p[a]*s[1]*(1+s[0]*xi)/4 for p, s in zip(xy, signs)) for a in (0, 1)]
            yield dx[0]*dy[1]-dx[1]*dy[0]


def _planar(p):
    n, e = p['core_divisions'], p['outer_extension_cells']
    xy, quads, fill, lookup = [], [], [], {}

    def block(nx, ny, mapping, is_fill=False):
        grid = compile_axisymmetric_quad_mesh(float(nx), float(ny), 1.)
        ids = {}
        for local, u, v, _ in grid['nodes']:
            point = tuple(round(w, 12) for w in mapping(u/nx, v/ny))
            if point not in lookup:
                lookup[point] = len(xy); xy.append(point)
            ids[local] = lookup[point]
        for row in grid['elements']:
            q = tuple(ids[v] for v in row[2:6])
            if _area([xy[i] for i in q]) < 0: q = q[::-1]
            quads.append(q); fill.append(is_fill)

    def square(s, u, a):
        v = -a+2*a*u
        return ((a, v), (-v, a), (-a, -v), (v, -a))[s]

    def circle(s, u, r):
        theta = -math.pi/4+(s+u)*math.pi/2
        return r*math.cos(theta), r*math.sin(theta)

    def blend(a, b, v):
        return (1-v)*a[0]+v*b[0], (1-v)*a[1]+v*b[1]

    block(n, n, lambda u, v: (-.0245+.049*u, -.0245+.049*v), True)
    for s in range(4):
        block(n, p['core_radial_layers'], lambda u, v, s=s: blend(square(s, u, .0245), circle(s, u, .049), v), True)
        block(n, p['bore_transition_layers'], lambda u, v, s=s: blend(circle(s, u, .049), square(s, u, .08), v))

    # Piecewise axes keep all interfaces conforming even in reduced test meshes.
    def axis(t):
        i = t*(n+2*e)
        if i <= e: return -.5+.42*i/e
        if i <= e+n: return -.08+.16*(i-e)/n
        return .08+.42*(i-e-n)/e

    block(e, n, lambda u, v: (.08+.42*u, -.08+.16*v))
    block(e, n, lambda u, v: (-.5+.42*u, -.08+.16*v))
    block(n+2*e, e, lambda u, v: (axis(u), .08+.42*v))
    block(n+2*e, e, lambda u, v: (axis(u), -.5+.42*v))
    for s in range(4):
        def outer(u, v, s=s):
            t = axis(u)
            sq = ((.5, t), (-t, .5), (-.5, -t), (t, -.5))[s]
            return blend(sq, circle(s, u, 1.05), v)
        block(n+2*e, p['outer_radial_layers'], outer)
    return xy, quads, fill


class MeshRecipe:
    def __init__(self, raw):
        self.parameters = validate_mesh_parameters(raw)
        self.estimate = _estimate(self.parameters)
        self.xy, self.quads, self.fill = _planar(self.parameters)
        self.annular = [q for q, fill in zip(self.quads, self.fill) if not fill]
        self.full_indices = tuple(range(len(self.xy)))
        self.annular_indices = tuple(sorted({i for q in self.annular for i in q}))
        self.full_positions = {i: i for i in self.full_indices}
        self.annular_positions = {v: i for i, v in enumerate(self.annular_indices)}
        zs = _levels(self.parameters['axial_step_m'])
        self.lower = [z for z in zs if z <= -.54]
        self.upper = [z for z in zs if z >= -.54]
        self.steel = zs
        self.nt = self.estimate['outer_circumference_cells']
        self.bases = {}; self.level_sizes = {}; offset = NODE_START
        for group, levels in [('lower', self.lower), ('upper', self.upper), ('steel', self.steel)]:
            bases, sizes = [], []
            for z in levels:
                size = (3 if _ring_at(z) else 2)*self.nt if group == 'steel' else len(self.annular_indices) if group == 'upper' and z > 0 else len(self.xy)
                bases.append(offset); sizes.append(size); offset += size
            self.bases[group] = bases; self.level_sizes[group] = sizes
        if offset-NODE_START != self.estimate['nodes']:
            raise ValueError('block interfaces did not produce the estimated node topology')
        self.quality = self._audit_sections()

    def _audit_sections(self):
        exp = self.estimate
        if len(self.xy) != exp['full_section_nodes'] or len(self.quads) != exp['full_section_quads'] or len(self.annular_indices) != exp['annular_section_nodes']:
            raise ValueError('planar topology does not match the closed disk/annulus contract')
        report = {}
        for name, rows, boundary in [('disk', self.quads, self.nt), ('annulus', self.annular, self.nt+4*self.parameters['core_divisions'])]:
            edges = Counter(tuple(sorted((a, b))) for q in rows for a, b in zip(q, q[1:]+q[:1]))
            minimum = min(v for q in rows for v in _quad_jacobians([self.xy[i] for i in q]))
            if minimum <= 0 or any(c not in (1, 2) for c in edges.values()) or sum(c == 1 for c in edges.values()) != boundary:
                raise ValueError('nonpositive or nonconforming planar cells')
            report[name] = {'area_m2': sum(_area([self.xy[i] for i in q]) for q in rows),
                            'minimum_2d_gauss_jacobian': minimum, 'boundary_edges': boundary}
        report['minimum_axial_spacing_m'] = min(b-a for a, b in zip(self.steel, self.steel[1:]))
        report['geometry_validation'] = 'positive mapped 2D Gauss determinants and straight positive-z extrusion'
        return report

    def _id(self, group, layer, index):
        pos = self.annular_positions if group == 'upper' and self.upper[layer] > 0 else self.full_positions
        return self.bases[group][layer]+pos[index]

    def iter_nodes(self):
        for group, levels in [('lower', self.lower), ('upper', self.upper)]:
            for layer, z in enumerate(levels):
                indices = self.annular_indices if group == 'upper' and z > 0 else self.full_indices
                for index in indices:
                    yield (self._id(group, layer, index), *self.xy[index], z)
        for layer, z in enumerate(self.steel):
            radii = (1.05, 1.066, 1.086) if _ring_at(z) else (1.05, 1.066)
            for radial, r in enumerate(radii):
                for i in range(self.nt):
                    theta = -math.pi/4+i*2*math.pi/self.nt
                    yield (self.bases['steel'][layer]+radial*self.nt+i, round(r*math.cos(theta), 12), round(r*math.sin(theta), 12), z)

    def _steel_quad(self, layer, radial, i):
        b = self.bases['steel'][layer]+radial*self.nt; j = (i+1) % self.nt
        return b+i, b+self.nt+i, b+self.nt+j, b+j

    def iter_elements(self):
        eid = ELEMENT_START
        for group, levels in [('lower', self.lower), ('upper', self.upper)]:
            for layer, (a, b) in enumerate(zip(levels, levels[1:])):
                pid = 2 if group == 'upper' else 5 if (a+b)/2 < -1.04 else 4
                quads = self.annular if group == 'upper' and a >= 0 else self.quads
                for q in quads:
                    yield (eid, pid, *(self._id(group, layer, i) for i in q), *(self._id(group, layer+1, i) for i in q))
                    eid += 1
        for layer, (a, b) in enumerate(zip(self.steel, self.steel[1:])):
            for radial in range(2 if _ring_at((a+b)/2) else 1):
                for i in range(self.nt):
                    yield (eid, 6, *self._steel_quad(layer, radial, i), *self._steel_quad(layer+1, radial, i))
                    eid += 1
        if eid-ELEMENT_START != self.estimate['elements']:
            raise ValueError('extruded element count does not match the recipe')

    def iter_bottom_nodes(self):
        yield from range(self.bases['lower'][0], self.bases['lower'][0]+len(self.xy))
        yield from range(self.bases['steel'][0], self.bases['steel'][0]+2*self.nt)

    def iter_bottom_segments(self):
        for q in self.quads:
            yield tuple(self._id('lower', 0, i) for i in q[::-1])
        for i in range(self.nt):
            yield self._steel_quad(0, 0, i)[::-1]


def build_recipe(raw):
    return MeshRecipe(raw)
