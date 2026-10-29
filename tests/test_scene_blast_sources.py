"""Scene contracts and bounded geometry preparation; no structural solves."""
import pytest
from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input, fingerprint
from lsprepost_mcp.architecture.scene_blast.sources import catalog, shell_model


def test_five_sources_and_independent_contract():
    assert {x['id'] for x in catalog()} == {'commercial_supermarket','residential_community','subway_entrance','city_street','fixed_three_storey'}
    v = normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[10,-8,0],'mass_kg':10}})
    assert v['schema_version'] == 'scene-blast-input@1'
    assert fingerprint(v) == fingerprint(normalize_input(v))
    for bad in [{'pressureScale':2}, {'source':{'kind':'unknown'}}, {'source':{'kind':'subway_entrance','project_name':'../../x'}}, {'source':{'kind':'city_street'},'tnt':{'position_m':[0,0,2],'mass_kg':1}}]:
        with pytest.raises(ValueError):normalize_input(bad)


def test_shared_edge_springs_have_thickness_lever_arms_and_supported_graph():
    nodes=[(1,0,0,0),(2,1,0,0),(3,1,0,1),(4,0,0,1),(5,2,0,0),(6,2,0,1)]
    model=shell_model('tiny',nodes,[(1,1,1,2,3,4),(2,1,2,5,6,3)],.2)
    assert len(model['bodies']) == 2
    assert sum(b['mass_kg'] for b in model['bodies']) == pytest.approx(960)
    assert len(model['springs']) >= 4
    assert len({round(s['point_m'][1],8) for s in model['springs']}) == 2
    assert model['checks']['supported']


def test_five_bounded_previews_preserve_fixed_mass_and_distributed_display():
    import numpy as np
    from lsprepost_mcp.architecture.scene_blast.sources import prepare
    for item in catalog():
        m=prepare(normalize_input({'source':{'kind':item['id']}}))
        assert m['checks']['supported'] and m['envelopes']
        assert m['budget']['bodies']<=m['budget']['limits']['max_bodies']
        if item['id']=='fixed_three_storey':
            assert m['mass_ledger']['relative_error']<1e-12
            assert m['mass_ledger']['fixed_relative_error']<1e-12
            structural=[d for d in m['display'] if d.get('response')=='structural']
            assert len(structural)==len(m['bodies'])
            for s in m['surfaces']:
                points=s['application_points_m'];weights=s['weights'];p=np.array(s['point_m']);force=-np.array(s['normal'])*s['area_m2']
                assert sum(w for _,w in weights)==pytest.approx(1.)
                moment=sum((w*np.cross(q,force) for (_,w),q in zip(weights,points)),np.zeros(3))
                assert np.linalg.norm(moment-np.cross(p,force))<1e-7
            # Loaded parent faces must reach independent macro DOFs along their extent.
            upward={};wall_groups={}
            for s in m['surfaces']:
                if s['normal'][2]>.9:upward.setdefault(s['component_id'],set()).update(i for i,w in s['weights'] if w>0)
                if abs(s['normal'][2])<.1:
                    key=(s['component_id'],tuple(np.round(s['normal'],6)));wall_groups.setdefault(key,set()).update(i for i,w in s['weights'] if w>0)
            assert any(len(v)>=4 for v in upward.values())
            assert any(len(v)>2 for v in wall_groups.values())


def test_surface_partition_preserves_local_tile_loads_not_just_global_resultants():
    import numpy as np
    from lsprepost_mcp.architecture.scene_blast.sources import face_patches
    patches=list(face_patches([[0,0,1],[2,0,1],[2,1,1],[0,1,1]],[np.array([0,1,2]),np.array([0,1]),np.array([0,1])]))
    left=sum(area for point,normal,area in patches if point[0]<1);right=sum(area for point,normal,area in patches if point[0]>1)
    assert left==pytest.approx(1.) and right==pytest.approx(1.)
