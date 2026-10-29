"""Elastic RC fiber column with an explicit physical mass ledger."""
import math
from .loads import map_pressure


def define_column_section(ops,case):
    """Define section/material tags 1/2 in an already initialized 3D model."""
    g,r,m=case['geometry'],case['reinforcement'],case['materials']
    nf=case['mesh']['fibers']
    b,h=g['width_m'],g['depth_m']
    ec,es=m['concrete_e_pa'],m['steel_e_pa']
    area=math.pi*r['diameter_m']**2/4
    py=b/2-r['cover_m']-r['diameter_m']/2
    pz=h/2-r['cover_m']-r['diameter_m']/2
    bars=[dict(id=f'bar-{i+1}',y=y,z=z,area_m2=area) for i,(y,z) in enumerate(((-py,-pz),(-py,pz),(py,-pz),(py,pz)))]
    ops.uniaxialMaterial('Elastic',1,ec);ops.uniaxialMaterial('Elastic',2,es)
    ops.section('Fiber',1,'-GJ',ec/(2*(1+m['concrete_nu']))*0.1406*b*h**3)
    # Equal-area square voids replace the four circular bar footprints. Concrete
    # quadrature is refined independently; actual steel fibers remain at bar centers.
    side=math.sqrt(area)
    ys=sorted([-b/2,b/2,-py-side/2,-py+side/2,py-side/2,py+side/2])
    zs=sorted([-h/2,h/2,-pz-side/2,-pz+side/2,pz-side/2,pz+side/2])
    concrete=[]
    for ya,yb in zip(ys,ys[1:]):
        for za,zb in zip(zs,zs[1:]):
            if any(abs((ya+yb)/2-v['y'])<side/2-1e-12 and abs((za+zb)/2-v['z'])<side/2-1e-12 for v in bars):
                continue
            ny=max(1,math.ceil((yb-ya)/b*nf));nz=max(1,math.ceil((zb-za)/h*nf))
            da=(yb-ya)*(zb-za)/(ny*nz)
            for iy in range(ny):
                for iz in range(nz):
                    y=ya+(iy+0.5)*(yb-ya)/ny;z=za+(iz+0.5)*(zb-za)/nz
                    ops.fiber(y,z,da,1);concrete.append((y,z,da))
    for bar in bars:ops.fiber(bar['y'],bar['z'],area,2)
    mu=m['concrete_density']*(b*h-4*area)+m['steel_density']*4*area
    return dict(mu=mu,bars=bars,concrete_fiber_count=len(concrete),
                ei_nm2=sum(ec*a*y*y for y,z,a in concrete)+sum(es*area*v['y']**2 for v in bars))


def build_column(ops, case: dict) -> dict:
    ops.wipe();ops.model('basic','-ndm',3,'-ndf',6)
    section=define_column_section(ops,case)
    mu,bars=section['mu'],section['bars']
    length,b,n=case['geometry']['length_m'],case['geometry']['width_m'],case['mesh']['n']
    nodes=[[0,0,length*i/n] for i in range(n+1)]
    masses=[mu*length/n*(0.5 if i in (0,n) else 1) for i in range(n+1)]
    for i,xyz in enumerate(nodes):
        ops.node(i+1,*xyz);ops.mass(i+1,masses[i],masses[i],masses[i],0,0,0)
    ops.fix(1,1,1,1,1,1,1)
    ops.geomTransf('Linear',1,0,1,0);ops.beamIntegration('Lobatto',1,1,3)
    elements=[[i,i+1] for i in range(n)]
    samples=[]
    for i,(a,c) in enumerate(elements):
        ops.element('dispBeamColumn',i+1,a+1,c+1,1,1)
        for ip,xi in enumerate((0,0.5,1),1):
            for bar in bars:
                samples.append(dict(id=f'e{i+1}-ip{ip}-{bar["id"]}',element=i+1,ip=ip,
                                    bar_id=bar['id'],y=bar['y'],z=bar['z'],
                                    position_m=[bar['y'],bar['z'],length*(i+xi)/n],
                                    local_axis=[0,0,1],scope='longitudinal_fiber'))
    model=dict(kind='column',nodes=nodes,elements=elements,width_m=b,steel_samples=samples,
               monitor_node=n,node_masses_kg=masses,mass_kg=mu*length,support_nodes=[0],
               ei_nm2=section['ei_nm2'],
               concrete_fiber_count=section['concrete_fiber_count'],bars=bars,
               section_geometry_approximation='equal_area_square_bar_voids')
    model['load_map']=map_pressure(model,case['loads'])
    return model


def configure_static(ops):
    ops.wipeAnalysis();ops.constraints('Transformation');ops.numberer('RCM');ops.system('UmfPack')
    ops.test('NormDispIncr',1e-11,30);ops.algorithm('Newton')
    ops.integrator('LoadControl',1);ops.analysis('Static')


def run_static(ops,model,pressure):
    ops.timeSeries('Linear',1);ops.pattern('Plain',1,1)
    for i,v in enumerate(model['load_map']['nodal_vectors_per_pa']):ops.load(i+1,*[pressure*x for x in v])
    configure_static(ops)
    if ops.analyze(1)!=0:raise RuntimeError('static solve did not converge')


def node_sample(ops,model,time_s):
    ops.reactions('-dynamic')
    dofs=[list(ops.nodeDisp(i+1)) for i in range(len(model['nodes']))]
    return dict(time_s=time_s,displacements_m=[v[:3] for v in dofs],rotations_rad=[v[3:] for v in dofs],
                velocities_m_s=[list(ops.nodeVel(i+1))[:3] for i in range(len(dofs))],
                accelerations_m_s2=[list(ops.nodeAccel(i+1))[:3] for i in range(len(dofs))],
                support_reaction=[sum(ops.nodeReaction(i+1,k+1) for i in model['support_nodes']) for k in range(6)])


def read_column_sample(ops,model,time_s):
    sample=node_sample(ops,model,time_s)
    stress=[];strain=[]
    for s in model['steel_samples']:
        value=ops.eleResponse(s['element'],'section',s['ip'],'fiber',s['y'],s['z'],2,'stressStrain')
        if len(value)!=2:raise RuntimeError('missing native steel fiber stress/strain')
        stress.append(value[0]);strain.append(value[1])
    sample.update(steel_stress_pa=stress,steel_strain=strain)
    return sample
