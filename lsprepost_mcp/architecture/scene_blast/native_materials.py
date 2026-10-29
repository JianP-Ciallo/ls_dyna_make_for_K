"""Nonlinear native reference materials, isolated from production macro solver.

Strengths/Gf follow scene_blast; elastic moduli and bar geometry follow the
audited beam/layered-shell reference. No viscosity, IMPL-EX, residual tensile
strength or artificial stiffness. Compression softening is an explicit untested
modelling assumption, not calibration or verified actual detailing.
"""
import math
import numpy as np
from .contracts import MATERIAL

ASSUMPTIONS=[
    'ideal_monolithic_section_fully_anchored_rebar_actual_anchorage_unverified',
    'reference_Ec_Es_and_original_rebar_layers_preserved',
    'fc30MPa_ft2MPa_fy400MPa_Gf200N_per_m_unchanged',
    'concrete_compression_peak_strain_0.002_zero_stress_at_0.006_unconfined_assumption',
    'steel_elastic_perfectly_plastic_no_hardening_no_bond_slip',
    'shell_crack_band_length_sqrt_area_not_yet_mesh_converged',
    'small_rotation_shell_MITC4_and_PDelta_columns_not_fragment_collision_solver',
    'not_validated_for_collapse_or_real_building_blast']


def concrete_laws(elastic,length):
    ft=MATERIAL['ft_pa'];fc=MATERIAL['fc_pa'];gf=MATERIAL['gf_n_m']
    if not math.isfinite(length) or length<=0 or elastic<=0:raise ValueError('invalid crack band length/modulus')
    peak=ft/elastic;end=2*gf/(ft*length)
    if end<=peak:raise ValueError('网格无法解析既定断裂能，必须细化，不能提高强度或断裂能')
    return dict(Te=[0.,peak,end],Ts=[0.,ft,0.],Td=[0.,0.,1.],
        Ce=[0.,.4*fc/elastic,.002,.006],Cs=[0.,.4*fc,fc,0.],Cd=[0.,0.,1-fc/(elastic*.002),1.],
        length_m=float(length),fracture_energy_n_m=gf)


def define_panel(ops,profile,tag,length):
    """PlateFiber wraps full nonlinear 3D concrete; steel layers use native state."""
    ec=profile['concrete_e_pa'];es=profile['steel_e_pa'];law=concrete_laws(ec,length)
    base=100000+tag*10
    args=[]
    for name in ('Te','Ts','Td','Ce','Cs','Cd'):args.extend(['-'+name,*law[name]])
    ops.nDMaterial('ASDConcrete3D',base,ec,profile['concrete_nu'],*args,'-tangent')
    # Unit-weight wrapper exposes the underlying six-component material state
    # through `material 1`; PlateFiber's own stress response hides sigma33.
    # There is one constitutive material, no added stiffness or secant copy.
    ops.nDMaterial('Parallel3D',base+6,base,'-weights',1.)
    ops.nDMaterial('PlateFiber',base+1,base+6)
    ops.uniaxialMaterial('Steel01',base+2,MATERIAL['steel_fy_pa'],es,0.)
    ops.uniaxialMaterial('MinMax',base+3,base+2,'-min',-MATERIAL['steel_rupture_strain'],'-max',MATERIAL['steel_rupture_strain'])
    ops.nDMaterial('PlateRebar',base+4,base+3,0.)
    ops.nDMaterial('PlateRebar',base+5,base+3,90.)
    layers=[]
    for layer in profile['layers']:
        material=base+1 if layer['kind']=='concrete' else base+4 if layer['axis']=='X' else base+5
        layers.extend([material,layer['t']])
    ops.section('LayeredShell',tag,len(profile['layers']),*layers)
    return dict(section_tag=tag,concrete_tag=base,steel_tag=base+3,steel_e_pa=es,law=law)


def define_column(ops,profile,tag,length):
    """One integration-point fiber section, keeping original asymmetric bar axes."""
    g=profile['geometry'];r=profile['reinforcement'];m=profile['materials']
    b,h=g['width_m'],g['depth_m'];ec=m['concrete_e_pa'];es=m['steel_e_pa']
    law=concrete_laws(ec,length);ft=MATERIAL['ft_pa'];fc=MATERIAL['fc_pa'];base=200000+tag*10
    ops.uniaxialMaterial('Concrete02',base,-fc,-2*fc/ec,0.,-.006,.1,ft,ft/(law['Te'][-1]-ft/ec))
    ops.uniaxialMaterial('Steel01',base+1,MATERIAL['steel_fy_pa'],es,0.)
    ops.uniaxialMaterial('MinMax',base+2,base+1,'-min',-MATERIAL['steel_rupture_strain'],'-max',MATERIAL['steel_rupture_strain'])
    ops.section('Fiber',tag,'-GJ',ec/(2*(1+m['concrete_nu']))*.1406*b*h**3,'-noCentroid')
    area=math.pi*r['diameter_m']**2/4;side=math.sqrt(area);bars=profile['original_bar_positions_m']
    ys=sorted({-b/2,b/2,*[y+s*side/2 for y,z in bars for s in (-1,1)]})
    zs=sorted({-h/2,h/2,*[z+s*side/2 for y,z in bars for s in (-1,1)]})
    concrete=[]
    for ya,yb in zip(ys,ys[1:]):
        for za,zb in zip(zs,zs[1:]):
            if any(abs((ya+yb)/2-y)<side/2-1e-12 and abs((za+zb)/2-z)<side/2-1e-12 for y,z in bars):continue
            ny=max(1,math.ceil((yb-ya)/b*profile['mesh']['fibers']));nz=max(1,math.ceil((zb-za)/h*profile['mesh']['fibers']))
            for i in range(ny):
                for j in range(nz):
                    y=ya+(i+.5)*(yb-ya)/ny;z=za+(j+.5)*(zb-za)/nz;a=(yb-ya)*(zb-za)/(ny*nz)
                    ops.fiber(y,z,a,base);concrete.append((y,z,a))
    for y,z in bars:ops.fiber(y,z,area,base+2)
    return dict(section_tag=tag,concrete_tag=base,steel_tag=base+2,law=law,concrete_fibers=concrete)
