"""Bounded single-bay elastic connection verification; not a building solver.

Four fiber columns support one flexible layered plate. Short rigid links model
only the slab half-thickness eccentricity. Infill transfers uniform pressure and
mass by simply supported vertical strips; no infill stiffness/local response.
"""
import math
import numpy as np
from .benchmarks import make_benchmark
from .column import define_column_section
from .panel import define_panel_section


def strip_wall_transfer(points,thickness_m,density,direction,*,bottom_segments=1,top_segments=1):
    p=np.asarray(points,dtype=float);d=np.asarray(direction,dtype=float)
    if p.shape!=(4,3) or d.shape!=(3,) or not np.isfinite(p).all() or not np.isfinite(d).all():raise ValueError('wall geometry')
    if not math.isfinite(thickness_m) or not math.isfinite(density) or thickness_m<=0 or density<=0:raise ValueError('wall mass')
    a,b=p[1]-p[0],p[3]-p[0];cross=np.cross(a,b);area=float(np.linalg.norm(cross))
    if area<=0 or abs(np.dot(a,b))>1e-10*np.linalg.norm(a)*np.linalg.norm(b) or not np.allclose(p[2],p[0]+a+b,rtol=0,atol=1e-10):raise ValueError('rectangular support patch required')
    if not np.allclose(a[2],0,atol=1e-10) or not np.allclose(b[:2],0,atol=1e-10) or b[2]<=0:raise ValueError('vertical spanning strip required')
    if not math.isclose(float(np.linalg.norm(d)),1,abs_tol=1e-12) or abs(float(np.dot(d,cross)/area))<1-1e-10:raise ValueError('pressure must be unit wall normal')
    if any(isinstance(n,bool) or not isinstance(n,int) or not 1<=n<=128 for n in (bottom_segments,top_segments)):raise ValueError('edge segment count')
    # Each vertical strip sends half its force/mass to each support EDGE.
    # Integrate the linear edge shape functions, preserving local virtual work
    # for flexible edges as well as resultant force and rigid-body moment.
    support=[];weights=[]
    for first,last,n in ((p[0],p[1],bottom_segments),(p[2],p[3],top_segments)):
        for i in range(n+1):
            support.append((first+(last-first)*i/n).tolist())
            weights.append(area/(2*n)*(.5 if i in (0,n) else 1))
    return dict(area_m2=area,support_points_m=support,nodal_vectors_per_pa=[[*list(d*w),0,0,0] for w in weights],
                nodal_mass_kg=[w*thickness_m*density for w in weights],method='uniform_vertical_strip_edge_transfer')


def build_bay(ops):
    """Frozen 2x2m / 3m single-bay numerical reference; all dimensions in SI."""
    column=make_benchmark('rc-column-v1');panel=make_benchmark('rc-panel-v1')
    ops.wipe();ops.model('basic','-ndm',3,'-ndf',6)
    cs=define_column_section(ops,column);ps=define_panel_section(ops,panel,tag=10,material_offset=10)
    a=b=2.;height=3.;h=.15;n=4;nc=2;under=height-h;z=height-h/2
    ops.geomTransf('Linear',1,0,1,0);ops.beamIntegration('Lobatto',1,1,3)
    xyz={};masses={};bases=[];tops=[];column_elements=[];eid=0
    def node(x):
        tag=len(xyz)+1;xyz[tag]=x;masses[tag]=0.;ops.node(tag,*x);return tag
    for x,y in ((0,0),(a,0),(a,b),(0,b)):
        tags=[node([x,y,under*i/nc]) for i in range(nc+1)]
        bases.append(tags[0]);tops.append(tags[-1]);ops.fix(tags[0],1,1,1,1,1,1)
        for i in range(nc):
            eid+=1;ops.element('dispBeamColumn',eid,tags[i],tags[i+1],1,1);column_elements.append(eid)
            for tag in tags[i:i+2]:masses[tag]+=cs['mu']*under/nc/2
    plate_tags=[node([a*i/n,b*j/n,z]) for j in range(n+1) for i in range(n+1)]
    plate_elements=[];plate_loads={tag:[0.]*6 for tag in plate_tags}
    for j in range(n):
        for i in range(n):
            k=j*(n+1)+i;tags=[plate_tags[q] for q in (k,k+1,k+n+2,k+n+1)]
            eid+=1;ops.element('ShellMITC4',eid,*tags,10);plate_elements.append(eid)
            for tag in tags:
                masses[tag]+=ps['area_mass_kg_m2']*a*b/n**2/4
                plate_loads[tag][2]-=a*b/n**2/4
    corners=[plate_tags[q] for q in (0,n,n*(n+1)+n,n*(n+1))]
    connections=[]
    for master,slave in zip(tops,corners):
        offset=[0,0,h/2];ops.rigidLink('beam',master,slave);connections.append((master,slave,offset))
    # Physical wall ends at the slab underside, not its middle surface. Give
    # interior wall-edge forces AND masses the same eccentric kinematics. At
    # corners use the existing column-end master to avoid chained MP constraints.
    wall_top=[tops[0]]
    for i in range(1,n):
        slave=node([a*i/n,0,under]);master=plate_tags[i]
        ops.rigidLink('beam',master,slave);connections.append((master,slave,[0,0,-h/2]));wall_top.append(slave)
    wall_top.append(tops[1])
    wall_corners=[bases[0],bases[1],wall_top[-1],wall_top[0]]
    wall_tags=[bases[0],bases[1],*reversed(wall_top)]
    wall=strip_wall_transfer([xyz[t] for t in wall_corners],.2,1800,[0,1,0],top_segments=n)
    if not np.allclose([xyz[t] for t in wall_tags],wall['support_points_m'],rtol=0,atol=1e-12):raise RuntimeError('wall edge mapping mismatch')
    wall_mass=dict(zip(wall_tags,wall['nodal_mass_kg']))
    for tag,mass in wall_mass.items():masses[tag]+=mass
    for tag,mass in masses.items():ops.mass(tag,mass,mass,mass,0,0,0)
    return dict(nodes=xyz,node_masses_kg=masses,base_tags=bases,connections=connections,
                column_elements=column_elements,plate_elements=plate_elements,column_bars=cs['bars'],plate_layers=ps['layers'],
                center_tag=plate_tags[(n//2)*(n+1)+n//2],plate_nodal_loads_per_pa=plate_loads,
                wall_nodal_loads_per_pa=dict(zip(wall_tags,wall['nodal_vectors_per_pa'])),wall_top_tags=wall_top,
                wall_mass_by_tag=wall_mass,wall_mass_kg=sum(wall_mass.values()),wall_area_m2=wall['area_m2'],
                source='single_bay_elastic_reference_not_actual_building',
                assumptions=['local_rigid_offsets_only','flexible_floor','infill_strip_force_and_mass_no_stiffness',
                             'benchmark_materials_and_reinforcement_not_building_calibration'])


def read_bay_sample(ops,model,time_s):
    ops.reactions('-dynamic');column=[];plate=[]
    for e in model['column_elements']:
        for ip in (1,2,3):
            for bar in model['column_bars']:
                v=ops.eleResponse(e,'section',ip,'fiber',bar['y'],bar['z'],2,'stressStrain')
                if len(v)!=2:raise RuntimeError('missing assembly column steel')
                column.append(v[0])
    for e in model['plate_elements']:
        for ip in (1,2,3,4):
            for li,layer in enumerate(model['plate_layers'],1):
                if layer['kind']!='steel':continue
                v=ops.eleResponse(e,'material',ip,'fiber',li,'stress')
                if len(v)!=5:raise RuntimeError('missing assembly plate steel')
                plate.append(v[0 if layer['axis']=='X' else 1])
    return dict(time_s=time_s,column_steel_pa=column,plate_steel_pa=plate,
                support_reaction=[sum(ops.nodeReaction(tag,d) for tag in model['base_tags']) for d in range(1,7)])
