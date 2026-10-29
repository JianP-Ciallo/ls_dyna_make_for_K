"""Small explicit three-storey fixture, no actual building generation or solve."""
import math
import numpy as np
import pytest
from lsprepost_mcp.architecture.cpu_response.contracts import fingerprint


def box_record(bounds,role,material,level,pid,rebar=None):
    lo=np.array(bounds[:3]);hi=np.array(bounds[3:]);center=(lo+hi)/2;volume=float(np.prod(hi-lo))
    return dict(role=role,material=material,level=level,part_id=pid,native_bounds_m=bounds,
                cell_bounds_m=[bounds],non_box_cells=0,non_box_indices=[],solid_volume_m3=volume,
                solid_centroid_m=center.tolist(),solid_second_m2=(np.outer(center,center)+np.diag((hi-lo)**2/12)).tolist(),
                host_density_kg_m3=2400 if material=='concrete' else 1800,rebar=rebar or {},box_volume_m3=volume)


def steel(d,length,axis,coords,low,high):
    center=np.zeros(3);other=[i for i in range(3) if i!=axis];center[other]=coords;center[axis]=(low+high)/2
    cov=np.zeros((3,3));cov[axis,axis]=(high-low)**2/12
    return dict(diameter_m=d,length_m=length,volume_m3=math.pi*d*d/4*length,material_id=9001,
                centroid_m=center.tolist(),second_m2=(np.outer(center,center)+cov).tolist(),oblique_segments=0,
                lines=[dict(axis=axis,coordinates_m=coords,length_m=length,min_m=low,max_m=high)])


def three_storey_fixture():
    cs={};sem={};pid=0
    for level in range(4):
        top=3.1*level;pid+=1;cid=f'floor{level}'
        r=box_record([0,0,top-.18,2,2,top],'slab' if level<3 else 'roof','concrete',level,pid)
        # Four layers intentionally asymmetric about the middle surface.
        mid=top-.09;lines=[]
        for axis,z in [(0,mid-.042),(1,mid-.026),(1,mid-.010),(0,mid+.006)]:
            lines.append(dict(axis=axis,coordinates_m=[1,z],length_m=20.,min_m=0,max_m=2))
        group=steel(.016,80,0,[1,mid-.018],0,2);group['lines']=lines;r['rebar']={'slab_rebar':group}
        cs[cid]=r
    for level in range(3):
        for i,(x,y) in enumerate(((0,0),(2,0),(2,2),(0,2))):
            pid+=1;cid=f'c{level}-{i}';low=level*3.1;high=(level+1)*3.1
            r=box_record([x-.15,y-.15,low,x+.15,y+.15,high],'column','concrete',level,pid)
            group=steel(.016,4*3.1,2,[x,y],low,high)
            group['lines']=[dict(axis=2,coordinates_m=[x+dx,y+dy],length_m=3.1,min_m=low,max_m=high) for dx,dy in ((-.094,-.094),(-.094,.094),(.094,-.094),(.094,.094))]
            # Exact mean of four actual longitudinal bar axes.
            group['second_m2']=(np.array(group['second_m2'])+np.diag([.094**2,.094**2,0])).tolist()
            r['rebar']={'column_longitudinal':group};cs[cid]=r
    pid+=1;cs['wall']=box_record([.2,-.1,0,1.8,.1,2.92],'wall','plaster',0,pid)
    for cid,c in cs.items():
        b=c['native_bounds_m'];sem[cid]=dict(role=c['role'],material=c['material'],level=c['level'],part_id=c['part_id'],native_bounds_m=b,
            vertices_m=[[x,y,z] for z in (b[2],b[5]) for y in (b[1],b[4]) for x in (b[0],b[3])])
    payload=dict(components=sem,files={'fixture':'verified-tiny'},geometry_metadata=dict(grade_m=0),rooms={},schema_version='architecture.structural-template@1')
    sealed=dict(template_id='micro-three-storey',template_fingerprint=fingerprint(payload),payload=payload)
    audit=dict(template_id=sealed['template_id'],template_fingerprint=sealed['template_fingerprint'],files=payload['files'],
               native_files_verified=True,components=cs,assembly_rebar={},materials={9001:dict(density=7850,elastic_e_pa=210e9)})
    return audit,sealed


def test_column_priority_removes_wall_overlap_and_records_mass_change():
    from lsprepost_mcp.architecture.cpu_response.building_mapping import subtract_boxes,box_moments
    boxes=np.array([[0,0,0,2,1,3]],dtype=float)
    remaining=subtract_boxes(boxes,[0,0,0,1,1,3])
    v,first,second=box_moments(remaining)
    assert sum(v)==pytest.approx(3)
    np.testing.assert_allclose(first.sum(axis=0),[4.5,1.5,4.5])
    assert remaining.tolist()==[[1,0,0,2,1,3]]


def test_three_storey_mapping_conserves_mass_center_inertia_and_load_moment():
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    audit,sealed=three_storey_fixture()
    case=prepare_reference(audit,sealed,target_component_id='wall',mesh_size_m=1.,column_segments=2)
    assert case['checks']['connected_to_fixed_base'] and case['checks']['column_stacks_complete']
    ledger=case['mass_ledger'];assert ledger['mass_relative_error']<1e-10
    assert ledger['first_moment_relative_error']<1e-10
    assert ledger['second_moment_relative_error']<1e-10
    assert len(case['column_sections'])==1 and len(case['panel_sections'])==4
    assert case['column_sections'][0]['reinforcement']['cover_m']==pytest.approx(.048)
    assert any(abs(p['b_norm_n'])>0 for p in case['panel_sections'])
    force=np.array(case['nodal_load_per_pa']);nodes=np.array(case['nodes'])
    np.testing.assert_allclose(force[:,:3].sum(axis=0),[0,1.6*2.92,0],atol=1e-12)
    moment=(np.cross(nodes,force[:,:3])+force[:,3:]).sum(axis=0)
    np.testing.assert_allclose(moment,np.cross([1,-.1,1.46],[0,1.6*2.92,0]),atol=1e-11)
    assert case['source']['kind']=='regularized_building_reference'
    assert case['checks']['ready_for_trial']
    assert len(case['mass_points'])>len(case['nodes'])


def test_missing_column_storey_or_changed_native_identity_blocks_trial():
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    audit,sealed=three_storey_fixture();audit['files']={'fixture':'changed'}
    with pytest.raises(ValueError,match='identity'):prepare_reference(audit,sealed,target_component_id='wall')
    audit,sealed=three_storey_fixture();del audit['components']['c1-0']
    with pytest.raises(ValueError,match='column'):prepare_reference(audit,sealed,target_component_id='wall')


def test_asymmetric_original_column_bar_positions_are_retained():
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    audit,sealed=three_storey_fixture()
    audit['components']['c0-0']['rebar']['column_longitudinal']['lines'][0]['coordinates_m'][0]=-.08
    case=prepare_reference(audit,sealed,target_component_id='wall')
    section=next(s for s in case['column_sections'] if [-.08,-.094] in s['original_bar_positions_m'])
    assert section['reinforcement']['count']==4


def test_reference_worker_contract_rejects_invalid_mass_and_connectivity():
    from copy import deepcopy
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    from lsprepost_mcp.architecture.cpu_response.building_solver import validate_reference
    a,s=three_storey_fixture();c=prepare_reference(a,s,target_component_id='wall')
    validate_reference(c)
    bad=deepcopy(c);bad['mass_points'][0]['mass_kg']=-1
    with pytest.raises(ValueError):validate_reference(bad)
    bad=deepcopy(c);bad['elements'][0]['nodes'][0]=len(c['nodes'])
    with pytest.raises(ValueError):validate_reference(bad)


def test_longitudinal_steel_mass_follows_its_column_chain_interior_nodes():
    from copy import deepcopy
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    a,s=three_storey_fixture();original=prepare_reference(a,s,target_component_id='wall',column_segments=2)
    b=deepcopy(a);b['components']['c0-0']['rebar']['column_longitudinal']['volume_m3']=0
    control=prepare_reference(b,s,target_component_id='wall',column_segments=2)
    interior={i for e in original['elements'] if e['component_id']=='c0-0' for i in e['nodes'] if 0<original['nodes'][i][2]<3.01-1e-8}
    def mass(c):return sum(p['mass_kg'] for p in c['mass_points'] if p['master'] in interior)
    assert mass(original)-mass(control)>1


def test_wall_strip_reactions_have_only_real_slab_thickness_offset_moments():
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    a,s=three_storey_fixture();c=prepare_reference(a,s,target_component_id='wall')
    q=np.array(c['nodal_load_per_pa']);nodes=np.array(c['nodes']);half=1.6*2.92/2
    for z,sign in [(-.09,-1),(3.01,1)]:
        edge=q[np.abs(nodes[:,2]-z)<1e-8]
        assert edge[:,1].sum()==pytest.approx(half)
        assert edge[:,3].sum()==pytest.approx(sign*.09*half)
    # Unit independent lower-floor rotation work uses only its actual eccentricity.
    assert q[np.abs(nodes[:,2]+.09)<1e-8,3].sum()==pytest.approx(-.09*half)


def test_plate_mass_and_local_kinetic_energy_stay_on_its_own_floor():
    from copy import deepcopy
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    a,s=three_storey_fixture();original=prepare_reference(a,s,target_component_id='wall')
    b=deepcopy(a);b['components']['floor1']['host_density_kg_m3']+=10
    heavier=prepare_reference(b,s,target_component_id='wall')
    def masses(c):
        m=np.zeros(len(c['nodes']))
        for p in c['mass_points']:m[p['master']]+=p['mass_kg']
        return m
    delta=masses(heavier)-masses(original);own=np.abs(np.array(original['nodes'])[:,2]-3.01)<1e-8
    np.testing.assert_allclose(delta[~own],0,atol=1e-8)
    assert delta[own].sum()>1
    # Only this floor translates at 1m/s: all added plate kinetic energy belongs here.
    assert .5*delta[own].sum()==pytest.approx(.5*(heavier['mass_ledger']['total_kg']-original['mass_ledger']['total_kg']),rel=1e-10)
