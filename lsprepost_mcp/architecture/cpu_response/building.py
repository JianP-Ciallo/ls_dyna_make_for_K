"""Read-only semantic inventory. Never creates a solver model from display bounds."""
from collections import Counter
from copy import deepcopy
from itertools import product
import math
from .contracts import fingerprint


def inventory_template(sealed):
    payload=sealed['payload']
    if fingerprint(payload)!=sealed['template_fingerprint']:raise ValueError('template semantic checksum mismatch')
    groups=dict(columns=[],plates=[],infill=[],other=[]);components={};roles=Counter()
    for cid,c in sorted(payload['components'].items()):
        role,material=c['role'],c['material'];roles[role]+=1
        group=('columns' if role=='column' and material=='concrete' else
               'plates' if role in ('slab','roof') and material=='concrete' else
               'infill' if role in ('wall','partition','shaft','roof') and material=='plaster' else 'other')
        groups[group].append(cid)
        vertices=c.get('vertices_m',[])
        valid=len(vertices)==8 and all(len(v)==3 and all(isinstance(x,(float,int)) and math.isfinite(x) for x in v) for v in vertices)
        axes=[sorted({v[d] for v in vertices}) for d in range(3)] if valid else []
        box=valid and all(len(a)==2 for a in axes) and set(map(tuple,vertices))==set(product(*axes))
        bounds=([a[0] for a in axes]+[a[-1] for a in axes]) if valid else None
        native=c.get('native_bounds_m')
        differs=bool(bounds and native and any(abs(a-b)>1e-8 for a,b in zip(bounds,native)))
        components[cid]=dict(role=role,material=material,level=c.get('level'),part_id=c.get('part_id'),group=group,
                            vertices_m=deepcopy(vertices),semantic_bounds_m=bounds,native_bounds_m=deepcopy(native),
                            native_bounds_differ=differs,geometry_status='semantic_prism_native_unverified' if box else 'requires_native_geometry')
    return dict(schema_version='cpu-response.building-inventory@1',template_id=sealed['template_id'],
                template_fingerprint=sealed['template_fingerprint'],structural_system='column_slab_with_infill_load_and_mass',
                groups=groups,role_counts=dict(roles),components=components,ready_to_solve=False,
                unverified=['native_connectivity_and_offsets','reinforcement_geometry_and_material_profile',
                            'infill_support_edges_and_load_transfer','foundation_boundary','mass_overlap_and_nonstructural_mass'],
                scope='semantic_inventory_only_no_native_mesh_or_solver',
                assumptions=['infill_no_bearing_stiffness','no_invented_beams','no_global_rigid_floor',
                             'reference_parameters_are_not_building_calibration'])
