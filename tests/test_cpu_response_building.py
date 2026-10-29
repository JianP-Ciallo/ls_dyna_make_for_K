"""Small semantic fixtures only: no actual building mesh generation or solve."""
import pytest
from lsprepost_mcp.architecture.cpu_response.contracts import fingerprint


def prism(role,material,z=0):
    return dict(role=role,material=material,level=0,part_id=1,
                vertices_m=[[x,y,v] for v in (z,z+.2) for y in (0,1) for x in (0,2)],
                native_bounds_m=[0,0,z,2,1,z+.2])


def sealed():
    cs={k:prism(*v) for k,v in dict(c=('column','concrete'),s=('slab','concrete'),
        r=('roof','concrete'),p=('roof','plaster'),w=('wall','plaster'),q=('shaft','plaster')).items()}
    cs['c']['native_bounds_m'][5]=.18
    p=dict(components=cs,files={},geometry_metadata={},rooms={},schema_version=1)
    return dict(payload=p,template_id='micro',template_fingerprint=fingerprint(p))


def test_semantic_mapping_distinguishes_structural_plates_from_plaster_and_keeps_gaps():
    from lsprepost_mcp.architecture.cpu_response.building import inventory_template
    report=inventory_template(sealed())
    assert report['groups']==dict(columns=['c'],plates=['r','s'],infill=['p','q','w'],other=[])
    assert report['structural_system']=='column_slab_with_infill_load_and_mass'
    assert report['components']['c']['native_bounds_differ']
    assert not report['ready_to_solve']
    assert 'native_connectivity_and_offsets' in report['unverified']
    altered=sealed();altered['payload']['components']['w']['material']='concrete'
    with pytest.raises(ValueError,match='checksum'):inventory_template(altered)


def test_unrecognized_geometry_is_reported_never_promoted_to_a_box():
    from lsprepost_mcp.architecture.cpu_response.building import inventory_template
    value=sealed();value['payload']['components']['s']['vertices_m'][0][0]=.03
    value['template_fingerprint']=fingerprint(value['payload'])
    report=inventory_template(value)
    assert report['components']['s']['geometry_status']=='requires_native_geometry'
    assert not report['ready_to_solve']


def test_strip_wall_transfer_preserves_force_moment_and_mass_without_wall_stiffness():
    import numpy as np
    from lsprepost_mcp.architecture.cpu_response.assembly import strip_wall_transfer
    # Front wall: width 4, height 3, t=.2; pressure normal to it.
    points=[[0,0,0],[4,0,0],[4,0,3],[0,0,3]]
    value=strip_wall_transfer(points,thickness_m=.2,density=1800,direction=[0,1,0])
    f=np.asarray(value['nodal_vectors_per_pa'])[:,:3];x=np.asarray(points)
    np.testing.assert_allclose(f.sum(axis=0),[0,12,0])
    np.testing.assert_allclose(np.cross(x,f).sum(axis=0),[-18,0,24])
    assert sum(value['nodal_mass_kg'])==pytest.approx(4320)
    # Force virtual work equals rigid translation/rotation work at area centroid.
    v=np.array([.2,.3,.1]);omega=np.array([.01,.02,.03])
    assert np.sum(f*(v+np.cross(omega,x)))==pytest.approx(np.dot([0,12,0],v+np.cross(omega,[2,0,1.5])))
    with pytest.raises(ValueError):strip_wall_transfer(points,.2,1800,[1,0,0])
    refined=strip_wall_transfer(points,.2,1800,[0,1,0],top_segments=4)
    np.testing.assert_allclose(np.array(refined['nodal_vectors_per_pa'])[2:,1],[.75,1.5,1.5,1.5,.75])
    # A displacement at the top edge midpoint must receive nonzero wall work.
    assert refined['nodal_vectors_per_pa'][4][1]==pytest.approx(1.5)
