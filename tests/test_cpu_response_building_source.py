"""Tiny retained K source audit: geometry and rebar must come from native data."""
import hashlib
import json
import zipfile
import pytest
from lsprepost_mcp.architecture.cpu_response.contracts import fingerprint


def tiny_archive(path,*,bad_hash=False,grouped=False):
    vertices=[[x,y,z] for z in (0,3) for y in (-.15,.15) for x in (-.15,.15)]
    order=[0,1,3,2,4,5,7,6]
    solid='*NODE+\n'+''.join(f'{i+1},{x},{y},{z}\n' for i,(x,y,z) in enumerate(vertices))
    solid+='*ELEMENT_SOLID\n1,1,'+','.join(str(i+1) for i in order)+'\n'
    rebar='*NODE+\n11,-.094,-.094,.05\n12,-.094,-.094,2.95\n*ELEMENT_BEAM\n1,91,11,12,0\n*PART\nc.rebar.column_longitudinal\n91,92,9001\n*SECTION_BEAM\n92,1,1,2,1,0,0\n.016,.016,0,0,0,0\n'
    files={'solids-solver.k':solid,'reinforcement.k':rebar,
           'solid-properties.k':'*PART\nc\n1,11,9002\n',
           'materials-solver.k':'*MAT_CONCRETE_DAMAGE_REL3_TITLE+\nreference\n9002,2400,.2\n*MAT_PLASTIC_KINEMATIC_TITLE+\nsteel\n9001,7850,210000000000,.3,400000000\n',
           'installation.k':'$ no attached accessories\n','ground-solver.k':'$ fixed support reference\n'}
    hashes={n:hashlib.sha256(t.encode()).hexdigest() for n,t in files.items()}
    payload=dict(components={'c.step0' if grouped else 'c':dict(role='stair' if grouped else 'column',material='concrete',level=0,part_id=1,vertices_m=vertices,native_bounds_m=[-.15,-.15,0,.15,.15,3])},
                 files=hashes,geometry_metadata={},rooms={},schema_version='architecture.structural-template@1')
    sealed=dict(payload=payload,template_id='tiny-native',template_fingerprint=fingerprint(payload))
    if bad_hash:files['reinforcement.k']+='\n$ replaced\n'
    with zipfile.ZipFile(path,'w') as z:
        for n,t in files.items():z.writestr(n,t)
        z.writestr('structural-template.json',json.dumps(sealed))
    return path


def test_native_audit_uses_connectivity_volume_and_original_rebar_position(tmp_path):
    from lsprepost_mcp.architecture.cpu_response.building_source import audit_archive
    report=audit_archive(tiny_archive(tmp_path/'native.zip'))
    c=report['components']['c']
    assert report['native_files_verified']
    assert c['solid_volume_m3']==pytest.approx(.27)
    steel=.016**2*3.141592653589793/4*2.9
    assert c['steel_volume_m3']==pytest.approx(steel)
    assert c['mass_kg']==pytest.approx(2400*(.27-steel)+7850*steel)
    bars=c['rebar']['column_longitudinal']
    assert bars['diameter_m']==.016
    assert bars['lines'][0]['coordinates_m']==[-.094,-.094]
    assert bars['length_m']==pytest.approx(2.9)
    assert c['mesh_node_count']==8


def test_replaced_source_fails_before_mapping(tmp_path):
    from lsprepost_mcp.architecture.cpu_response.building_source import audit_archive
    with pytest.raises(ValueError,match='checksum'):
        audit_archive(tiny_archive(tmp_path/'changed.zip',bad_hash=True))


def test_fixed_width_native_element_columns_keep_leading_spaces():
    from lsprepost_mcp.architecture.cpu_response.building_source import parse_mesh
    text='*ELEMENT_BEAM\n  308329 9300001  443375  443376 6002856\n'
    assert parse_mesh(text,'BEAM')[1]==[(308329,9300001,443375,443376)]


def test_native_stair_assembly_rebar_is_preserved_with_explicit_host_members(tmp_path):
    from lsprepost_mcp.architecture.cpu_response.building_source import audit_archive
    report=audit_archive(tiny_archive(tmp_path/'stairs.zip',grouped=True))
    group=report['assembly_rebar']['c']
    assert group['members']==['c.step0']
    assert group['rebar']['column_longitudinal']['length_m']==pytest.approx(2.9)
    assert report['mass_total_kg']>report['components']['c.step0']['mass_kg']


def test_stair_rebar_host_excludes_attached_glass_railing():
    from lsprepost_mcp.architecture.cpu_response.building_source import stair_hosts
    members={'f.step0':dict(role='stair',material='concrete'),'f.rail':dict(role='railing',material='glass')}
    assert stair_hosts('f',members)==['f.step0']


def test_rotated_native_hex8_keeps_volume_centroid_and_inertia():
    import numpy as np
    from lsprepost_mcp.architecture.cpu_response.building_source import measure_hexes
    p=np.array([[0,0,0],[2,0,0],[2,1,0],[0,1,0],[0,0,.5],[2,0,.5],[2,1,.5],[0,1,.5]],dtype=float)
    angle=.43;c,s=np.cos(angle),np.sin(angle);r=np.array([[c,-s,0],[s,c,0],[0,0,1]])
    v,first,second=measure_hexes((p@r.T+np.array([3,4,5]))[None,:,:])
    center=np.array([1,.5,.25])@r.T+np.array([3,4,5])
    assert v[0]==pytest.approx(1)
    np.testing.assert_allclose(first[0],center,atol=1e-12)
    np.testing.assert_allclose(second[0]-np.outer(center,center),r@np.diag([4/12,1/12,.25/12])@r.T,atol=1e-12)
    with pytest.raises(ValueError,match='Jacobian'):measure_hexes(p[[1,0,3,2,5,4,7,6]][None,:,:])
