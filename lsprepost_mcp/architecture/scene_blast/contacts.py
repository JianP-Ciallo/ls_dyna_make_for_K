"""Conservative contact classification around existing bonded junctions.

No contact force, support, or material adjustment is introduced here. Small
proxy overlap is admissible only through a local, still load-carrying junction
within a bounded constitutive/kinematic range. All other collisions stop the
experimental solver. There is no initial-overlap or component-name whitelist.
"""
from collections import deque

import numpy as np
from scipy.spatial import cKDTree, ConvexHull

from .contact_geometry import intersection_vertices

EPS = 1e-6  # Same geometric resolution as the original SAT detector, metres.
REFERENCE_EPS = 1e-7


def box_axes(vertices):
    edges = vertices[..., [1, 3, 4], :] - vertices[..., :1, :]
    return edges / np.linalg.norm(edges, axis=-1, keepdims=True)


def box_contacts(a, b):
    """Vectorized 15-axis SAT: signed minimum translation depth and A->B axis."""
    aa, bb = box_axes(a), box_axes(b)
    axes = np.concatenate([aa, bb, np.cross(aa[:, :, None], bb[:, None, :]).reshape(-1, 9, 3)], axis=1)
    length = np.linalg.norm(axes, axis=2)
    axes = np.divide(axes, length[:, :, None], out=np.zeros_like(axes), where=length[:, :, None] > 1e-10)
    pa = np.einsum('nvi,nki->nkv', a, axes); pb = np.einsum('nvi,nki->nkv', b, axes)
    depth = np.minimum(pa.max(2)-pb.min(2), pb.max(2)-pa.min(2))
    depth[length <= 1e-10] = np.inf
    index = depth.argmin(1); rows = np.arange(len(a)); normal = axes[rows, index].copy()
    normal *= np.where(np.sum((b.mean(1)-a.mean(1))*normal, axis=1) < 0, -1., 1.)[:, None]
    return depth[rows, index], normal


def candidates(vertices, tolerance):
    lo, hi = vertices.min(1), vertices.max(1)
    radius = np.linalg.norm(hi-lo, axis=1).max()/2
    pairs = cKDTree((lo+hi)/2).query_pairs(2*radius+tolerance, output_type='ndarray')
    if len(pairs):
        a, b = pairs.T
        pairs = pairs[np.all(hi[a] >= lo[b]-tolerance, axis=1) & np.all(hi[b] >= lo[a]-tolerance, axis=1)]
    return pairs


class JunctionContacts:
    def __init__(self, system):
        self.s = system; self.original = system.vertex_array+system.x0[:system.count, None, :]
        self.axes = box_axes(self.original); self.centers = self.original.mean(1)
        self.half = np.linalg.norm(self.original[:, [1,3,4]]-self.original[:, :1], axis=2)/2
        self.skin = np.array([b.get('thickness_m',2*self.half[i].min())
            for i,b in enumerate(system.model['bodies'])])
        self.facets = []; groups = {}
        for k, spring in enumerate(system.model['springs']):
            if spring['kind'] != 'concrete': continue
            a, b = system.pairs[k]; n = system.n[k].copy()
            if n[np.argmax(abs(n))] < 0: n = -n
            key = (min(a,b), max(a,b), *np.round(n,7), round(float(np.array(spring['point_m'])@n),7))
            groups.setdefault(key, []).append(k)
        for indices in groups.values():
            points = np.array([system.model['springs'][k]['point_m'] for k in indices]); p = points.mean(0)
            # add_interface supplies four Gauss samples of an actual rectangle.
            # Extrapolate its support, not an arbitrary spatial search radius.
            if len(indices) != 4: continue
            _, _, basis = np.linalg.svd(points-p, full_matrices=False)
            uv = (points-p)@basis[:2].T*np.sqrt(3.)
            hull = ConvexHull(uv); a, b = system.pairs[indices[0]]; n = system.n[indices[0]]
            # The normal reach is half the THIN section dimension, never half
            # a slab's metre-long in-plane span. It represents skin/joint proxy
            # overlap, and cannot cover arbitrary solid interpenetration.
            skin = [self.skin[i] for i in (a,b) if i < system.count]
            corners = p+np.sqrt(3.)*(points-p)
            radius = max(np.linalg.norm(self.original[i]-p,axis=1).max() for i in (a,b) if i < system.count)
            self.facets.append(dict(a=int(a),b=int(b),indices=indices,point=p,basis=basis[:2],
                hull=hull.equations,normal=n,normal_reach=min(skin)/2,
                radius=radius,corners=corners,length=float(system.length[indices].min())))
        self.adjacency = [[] for _ in system.x]
        for k, f in enumerate(self.facets):
            self.adjacency[f['a']].append((f['b'],k)); self.adjacency[f['b']].append((f['a'],k))
        self.reference = {}; self._metrics = []
        self.facet_indices = np.array([f['indices'] for f in self.facets],int).reshape(-1,4)
        self.facet_pairs = np.array([[f['a'],f['b']] for f in self.facets],int).reshape(-1,2)
        self.facet_radii = np.array([f['radius'] for f in self.facets])
        self.facet_corners = np.array([f['corners'] for f in self.facets]).reshape(-1,4,3)
        self.cell_offsets = np.array([np.vstack([f['corners']-f['point']+f['normal']*f['normal_reach'],
            f['corners']-f['point']-f['normal']*f['normal_reach']]) for f in self.facets]).reshape(-1,8,3)
        L = np.array([f['length'] for f in self.facets]); mat = system.mat
        G = mat['e_pa']/(2*(1+mat['nu']))
        self.compression_limit = mat['fc_pa']/mat['e_pa']*L+EPS
        self.shear_limit = (mat['ft_pa']+.5*mat['fc_pa'])/G*L+EPS
        self.opening_limit = 2*mat['gf_n_m']/mat['ft_pa']+mat['steel_fy_pa']/mat['steel_e_pa']*L+EPS

    def contains(self, point):
        local = np.einsum('nij,nj->ni', self.axes, point-self.centers)
        return np.all(abs(local) <= self.half+REFERENCE_EPS, axis=1)

    def local_graph(self, a, b):
        key = (a,b)
        if key in self.reference: return self.reference[key]
        va, vb = self.original[[a,b]]; depth, _ = box_contacts(va[None],vb[None])
        if depth[0] < -REFERENCE_EPS:
            self.reference[key] = None; return None
        lo = np.maximum(va.min(0), vb.min(0)); hi = np.minimum(va.max(0), vb.max(0))
        # At a balcony/column corner the contact centroid can be outside the
        # connecting interior slab. Check the actual intersection endpoints too.
        intersection_corners = [np.where(bits,hi,lo) for bits in np.ndindex(2,2,2)]
        options = [(lo+hi)/2, *intersection_corners, *va, *vb]
        fallback = None
        for p in options:
            inside = self.contains(p)
            if not (inside[a] and inside[b]): continue
            value = self.graph_at_point(p)
            value['depth'] = float(max(0.,depth[0]))
            value['region_corners'] = np.array(intersection_corners)
            value['depth_limit_m'] = float(min(self.skin[a],self.skin[b])/2)
            if fallback is None: fallback = value
            if self.path(value['graph'],a,b,[],False) is not None:
                self.reference[key] = value; return value
        self.reference[key] = fallback
        return fallback

    def graph_at_point(self, point):
        inside = self.contains(point); graph = {}; edges = set()
        for i in np.flatnonzero(inside):
            for j,k in self.adjacency[i]:
                if j < self.s.count and not inside[j]: continue
                f = self.facets[k]; offset = point-f['point']; uv = offset@f['basis'].T
                if abs(offset@f['normal']) > f['normal_reach']+REFERENCE_EPS: continue
                if np.any(f['hull'][:,:2]@uv+f['hull'][:,2] > REFERENCE_EPS): continue
                graph.setdefault(int(i),[]).append((j,k)); edges.add(k)
        # The dummy foundation has no finite geometry. Only fixed bodies at THIS
        # junction can stand in for it, and only local real foundation facets lead to it.
        ground = self.s.count
        for i in np.flatnonzero(inside & self.s.fixed[:ground]):
            graph.setdefault(int(i),[]).append((ground,None))
            graph.setdefault(ground,[]).append((int(i),None))
        for k in edges:
            f = self.facets[k]
            if f['b'] == ground: graph.setdefault(ground,[]).append((f['a'],k))
            if f['a'] == ground: graph.setdefault(ground,[]).append((f['b'],k))
        return dict(point=point,graph=graph)

    def reference_region_supported(self, reference, path):
        """A local corner path must never grandfather a remote/deep overlap.

        Require the complete bounding region to fit ONE physical facet's convex
        support cell. Covering only selected corners with a union of cells could
        hide uncovered gaps. For rotated reference boxes the bounding region is
        conservative: an unrepresented intersection stops rather than passes.
        """
        if reference['depth'] > reference['depth_limit_m']+REFERENCE_EPS: return False
        for _,_,k in path:
            if k is None: continue
            f = self.facets[k]; offset = reference['region_corners']-f['point']
            uv = offset@f['basis'].T
            if (np.all(abs(offset@f['normal']) <= f['normal_reach']+REFERENCE_EPS) and
                np.all(uv@f['hull'][:,:2].T+f['hull'][:,2] <= REFERENCE_EPS)):
                return True
        return False

    def metrics(self):
        """Check existing facets without committing history or applying forces."""
        s = self.s
        ids = self.facet_indices; a,b = self.facet_pairs.T
        # The physical rectangle corners bound its affine gap; Gauss samples
        # alone can miss the most compressed/open corner during rotation.
        pa=s.x[a,None,:]+np.einsum('nij,nkj->nki',s.R[a],self.facet_corners-s.x0[a,None,:])
        pb=s.x[b,None,:]+np.einsum('nij,nkj->nki',s.R[b],self.facet_corners-s.x0[b,None,:])
        n=np.einsum('nij,nj->ni',s.R[a],s.n[ids[:,0]])
        gap=pb-pa;dn=np.sum(gap*n[:,None,:],axis=2)
        shear=np.linalg.norm(gap-dn[:,:,None]*n[:,None,:],axis=2)
        # Measure actual relative rotation at the local support cell, rather
        # than multiplying by the remote roof edge distance. Current overlap
        # containment below independently guards collisions outside this cell.
        relative=s.R[a]-s.R[b]
        turn=np.linalg.norm(np.einsum('nij,nkj->nki',relative,self.cell_offsets),axis=2).max(1)
        proxy_turn=np.linalg.norm(relative,axis=(1,2))/np.sqrt(2.)*self.facet_radii
        budget = self.compression_limit+self.shear_limit+self.opening_limit
        closure = np.maximum(0.,np.max(-dn,axis=1)); opening = np.maximum(0.,np.max(dn,axis=1))
        slide = np.max(shear,axis=1); damage = np.max(s.damage[ids],axis=1)
        ratio = np.maximum.reduce([closure/self.compression_limit,opening/self.opening_limit,
            slide/self.shear_limit,turn/budget])
        alive = damage < 1-1e-10
        self.current_cells={}
        return dict(compatible=alive & (ratio<=1.),alive=alive,kinematic_ratio=ratio,budget_m=budget,
            max_damage=damage,normal_closure_m=closure,opening_m=opening,shear_m=slide,
            rotation_sweep_m=turn,proxy_rotation_sweep_m=proxy_turn,compression_limit_m=self.compression_limit,
            shear_limit_m=self.shear_limit,opening_limit_m=self.opening_limit)

    def current_cell(self,k,side):
        key=(k,side)
        if key not in self.current_cells:
            f=self.facets[k];s=self.s
            # Hull rows are unit outward normals in the 2-D facet basis.
            normals=np.vstack([f['hull'][:,:2]@f['basis'],f['normal'],-f['normal']])
            bounds=np.r_[-f['hull'][:,2]+self.shear_limit[k],
                [f['normal_reach']+self.compression_limit[k]]*2]
            world_normals=normals@s.R[side].T
            center=s.x[side]+s.R[side]@(f['point']-s.x0[side])
            self.current_cells[key]=(world_normals,bounds,center)
        return self.current_cells[key]

    def current_region_supported(self,path,va,vb):
        """Prove the WHOLE current convex intersection fits one convex cell.

        Projection bounds can certify containment cheaply. If inconclusive,
        clipping finds the actual intersection vertices; testing all vertices
        against all six planes certifies the complete convex polytope. Never
        infer containment from SAT depth or selected sample points alone.
        """
        cells=[]
        for _,_,k in path:
            if k is None:continue
            for side in (self.facets[k]['a'],self.facets[k]['b']):
                normals,bounds,center=self.current_cell(k,side)
                upper=np.minimum(((va-center)@normals.T).max(0),((vb-center)@normals.T).max(0))
                outside=float(np.max(upper-bounds))
                if outside<=EPS:
                    return dict(contained=True,method='box_projection_bound',facet_index=k,
                        carrier_index=side,max_outside_m=outside)
                cells.append((k,side,normals,bounds,center))
        points=intersection_vertices(va,vb)
        if len(points)<4:
            return dict(contained=False,method='intersection_unresolved',vertex_count=len(points),outside_point_m=None)
        best=None
        for k,side,normals,bounds,center in cells:
            violation=(points-center)@normals.T-bounds
            outside=float(violation.max())
            report=dict(contained=outside<=EPS,method='exact_box_intersection',facet_index=k,
                carrier_index=side,max_outside_m=outside,vertex_count=len(points))
            if outside<=EPS:return report
            report['outside_point_m']=points[np.unravel_index(violation.argmax(),violation.shape)[0]].tolist()
            if best is None or outside<best['max_outside_m']:best=report
        return best or dict(contained=False,method='no_support_cell',outside_point_m=None)

    @staticmethod
    def path(graph, a, b, metrics, require_compatible=True):
        queue = deque([(a,[])]); seen = {a}
        while queue:
            i, path = queue.popleft()
            if i == b:
                # Shared fixed status alone is not evidence of a real interface.
                if any(k is not None for _,_,k in path): return path
                continue
            for j,k in graph.get(i,[]):
                if j in seen or (require_compatible and k is not None and not metrics['compatible'][k]): continue
                seen.add(j); queue.append((j,path+[(i,j,k)]))
        return None

    def inspect(self, detailed=True):
        s = self.s; vertices = np.einsum('nij,nkj->nki',s.R[:s.count],s.vertex_array)+s.x[:s.count,None,:]
        pairs = candidates(vertices, -EPS); records = []; unsupported = set(); metrics = None; overlaps = 0
        if len(pairs):
            # Bound SAT workspace even when many AABBs overlap.
            batches = []
            for offset in range(0,len(pairs),1024):
                batch = pairs[offset:offset+1024]
                depths,normals = box_contacts(vertices[batch[:,0]],vertices[batch[:,1]])
                keep = depths>EPS
                if keep.any(): batches.append((batch[keep],depths[keep],normals[keep]))
            if not batches: pairs = np.empty((0,2),int)
            else: pairs,depths,normals = (np.concatenate([batch[i] for batch in batches]) for i in range(3))
            overlaps = len(pairs)
            if len(pairs): metrics = self.metrics()
            for (a,b),depth,normal in zip(pairs,depths,normals):
                a,b = int(a),int(b); ref = self.local_graph(a,b); path = None; reference_path = None; reason = 'no_local_load_path';current_support=None
                if ref is not None:
                    reference_path = self.path(ref['graph'],a,b,metrics,False)
                    path = self.path(ref['graph'],a,b,metrics)
                    if path is None and reference_path is not None:
                        reason = ('released_local_junction' if any(k is not None and not metrics['alive'][k]
                            for _,_,k in reference_path) else 'joint_kinematics_exceeded')
                    if path is not None:
                        budget = sum(metrics['budget_m'][k] for _,_,k in path if k is not None)
                        if not self.reference_region_supported(ref,path):
                            path = None; reason = 'reference_overlap_outside_junction'
                        elif depth > ref['depth']+budget+EPS: path = None; reason = 'joint_kinematics_exceeded'
                        else:
                            current_support=self.current_region_supported(path,vertices[a],vertices[b])
                            if not current_support['contained']:
                                path=None;reason='current_overlap_outside_junction'
                valid = path is not None
                if not valid: unsupported.add((a,b))
                if not detailed: continue
                record = dict(body_indices=[a,b],body_ids=[s.model['bodies'][i]['id'] for i in (a,b)],
                    classification='connected_junction' if valid else 'unsupported_collision',
                    reason_code='local_compatible_load_path' if valid else reason,
                    penetration_m=float(depth),normal=normal.tolist(),
                    reference_penetration_m=None if ref is None else ref['depth'],
                    reference_depth_limit_m=None if ref is None else ref['depth_limit_m'],
                    current_support=current_support,
                    junction_point_m=None if ref is None else ref['point'].tolist(),path=[])
                for i,j,k in (path if valid else reference_path) or []:
                    record['path'].append(dict(a=int(i),b=int(j),kind='fixed_support' if k is None else 'bonded_facet',
                        spring_indices=[] if k is None else self.facets[k]['indices'],
                        state=None if k is None else {name:value[k].item() for name,value in metrics.items()}))
                if not valid:
                    record['poses']=[dict(body_id=s.model['bodies'][i]['id'],center_m=s.x[i].tolist(),
                        rotation=s.R[i].tolist(),vertices_m=vertices[i].tolist()) for i in (a,b)]
                records.append(record)
        s.contact_diagnostics = dict(schema_version='scene-blast-contacts@1',geometric_tolerance_m=EPS,
            kinematics_measure='physical_facet_corners_and_local_support_cell_rotation',
            geometric_overlap_pairs=overlaps,connected_junction_pairs=overlaps-len(unsupported),
            unsupported_pairs=len(unsupported),detailed=detailed,records=records)
        return unsupported
