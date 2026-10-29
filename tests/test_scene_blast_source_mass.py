"""Two cells/physical source packets; never generate a real building model."""
from copy import deepcopy
import numpy as np
import pytest

from lsprepost_mcp.architecture.scene_blast.sources import body_from_quad


def two_cells():
    return [body_from_quad('slab:0',[[0,0,1],[.15,0,1],[.15,.2,1],[0,.2,1]],.18),
            body_from_quad('slab:1',[[.15,0,1],[1.4,0,1],[1.4,.2,1],[.15,.2,1]],.18)]


def test_source_density_perturbation_stays_on_its_own_physical_cell():
    from lsprepost_mcp.architecture.scene_blast.source_mass import map_source_packets
    bodies=two_cells()
    packets=[dict(source_component='slab',bearing_component='slab',mass_kg=10.,position_m=[.075,.1,1.]),
             dict(source_component='slab',bearing_component='slab',mass_kg=100.,position_m=[.7,.1,1.])]
    a=map_source_packets(bodies,packets)
    changed=deepcopy(packets);changed[0]['mass_kg']*=2
    b=map_source_packets(bodies,changed)
    assert a['bodies'][0]['mass_kg']==10 and a['bodies'][1]['mass_kg']==100
    assert b['bodies'][0]['mass_kg']==20 and b['bodies'][1]['mass_kg']==100
    assert a['ledger']['source_components']['slab']['mass_kg']==110
    assert not a['bodies'][0]['inertia_positive']  # A true point mass isn't padded with fake inertia.


def test_packets_preserve_total_mass_first_second_moments_and_provenance():
    from lsprepost_mcp.architecture.scene_blast.source_mass import map_source_packets
    bodies=two_cells();packets=[]
    for i,x in enumerate((.075,.7)):
        for signs in np.ndindex(2,2,2):
            p=np.array([x,.1,1])+np.array([1 if v else -1 for v in signs])*[.01,.02,.03]
            packets.append(dict(source_component=f'source{i}',bearing_component='slab',mass_kg=12.5,position_m=p.tolist()))
    result=map_source_packets(bodies,packets)
    assert all(b['inertia_positive'] for b in result['bodies'])
    m=np.array([p['mass_kg'] for p in packets]);xyz=np.array([p['position_m'] for p in packets])
    assert result['ledger']['mass_kg']==pytest.approx(m.sum())
    assert result['ledger']['first_moment_kg_m']==pytest.approx((m[:,None]*xyz).sum(0))
    assert result['ledger']['second_moment_kg_m2']==pytest.approx(np.einsum('n,ni,nj->ij',m,xyz,xyz))
    assert set(result['bodies'][0]['source_components'])=={'source0'}
    assert set(result['bodies'][1]['source_components'])=={'source1'}


def test_unmapped_source_or_empty_cell_is_reported_not_silently_redistributed():
    from lsprepost_mcp.architecture.scene_blast.source_mass import map_source_packets
    b=two_cells()
    with pytest.raises(ValueError,match='承重构件'):
        map_source_packets(b,[dict(source_component='wall',bearing_component='unknown',mass_kg=100,position_m=[0,0,1])])
    result=map_source_packets(b,[dict(source_component='wall',bearing_component='slab',mass_kg=100,position_m=[.075,.1,2])])
    assert result['bodies'][1]['mass_kg']==0 and result['unsupported_massless_bodies']==['slab:1']
    assert result['bodies'][0]['center_m']==pytest.approx([.075,.1,2])


def test_rotated_adjacent_cells_use_local_geometry_not_overlapping_world_boxes():
    from lsprepost_mcp.architecture.scene_blast.source_mass import map_source_packets
    from lsprepost_mcp.architecture.scene_blast.mechanics import rotation
    R=rotation(np.array([0,0,np.pi/4]))
    bodies=[body_from_quad('slab:0',[[0,0,1],[1,0,1],[1,1,1],[0,1,1]],.18),
            body_from_quad('slab:1',[[1,0,1],[2,0,1],[2,1,1],[1,1,1]],.18)]
    for b in bodies:b['vertices_m']=(np.asarray(b['vertices_m'])@R.T).tolist()
    position=R@np.array([1.1,.5,1.])
    result=map_source_packets(bodies,[dict(source_component='slab',bearing_component='slab',mass_kg=100,position_m=position.tolist())])
    assert result['bodies'][0]['mass_kg']==0
    assert result['bodies'][1]['mass_kg']==100
