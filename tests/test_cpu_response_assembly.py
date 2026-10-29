"""Native single-bay connection verification, not a real building case."""
import numpy as np
import pytest


def test_column_slab_offsets_equilibrium_local_bending_and_positive_modes():
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.assembly import build_bay,read_bay_sample
    from lsprepost_mcp.architecture.cpu_response.column import configure_static
    model=build_bay(ops)
    try:
        assert model['wall_area_m2']==pytest.approx(2*(3-.15))  # Physical clear height, excluding slab.
        edge=sorted(model['wall_top_tags'],key=lambda t:model['nodes'][t][0])
        assert len(edge)==5
        loads_y=[model['wall_nodal_loads_per_pa'].get(t,[0,0])[1] for t in edge]
        np.testing.assert_allclose(loads_y,np.array([.5,1,1,1,.5])*model['wall_area_m2']/8)
        ops.timeSeries('Linear',1);ops.pattern('Plain',1,1)
        loads=model['plate_nodal_loads_per_pa']
        for node,force in loads.items():ops.load(node,*[1000*x for x in force])
        configure_static(ops)
        assert ops.analyze(1)==0
        sample=read_bay_sample(ops,model,1)
        total=sum(v[2] for v in loads.values())*1000
        assert sample['support_reaction'][2]==pytest.approx(-total,rel=1e-9)
        for master,slave,offset in model['connections']:
            u=np.array(ops.nodeDisp(master));v=np.array(ops.nodeDisp(slave))
            np.testing.assert_allclose(v[:3],u[:3]+np.cross(u[3:],offset),atol=1e-12)
            np.testing.assert_allclose(v[3:],u[3:],atol=1e-12)
        masters={m for m,s,r in model['connections']};slaves={s for m,s,r in model['connections']}
        assert not masters&slaves  # Transformation handler must have no constraint chains.
        corners=[ops.nodeDisp(slave,3) for _,slave,_ in model['connections'][:4]]
        center=ops.nodeDisp(model['center_tag'],3)
        assert center<sum(corners)/4-1e-8  # Local plate bending was not tied away.
        assert max(abs(v) for v in sample['column_steel_pa'])>1
        assert max(abs(v) for v in sample['plate_steel_pa'])>1
        eigen=ops.eigen(6)
        assert len(eigen)==6 and min(eigen)>0
        # Lateral infill force also reaches the column foundations with no wall stiffness.
        ops.loadConst('-time',0);ops.timeSeries('Linear',2);ops.pattern('Plain',2,2)
        for tag,force in model['wall_nodal_loads_per_pa'].items():ops.load(tag,*[100*x for x in force])
        configure_static(ops);assert ops.analyze(1)==0
        ops.reactions()
        assert sum(ops.nodeReaction(t,2) for t in model['base_tags'])==pytest.approx(-100*model['wall_area_m2'],rel=1e-8)
        applied=np.zeros(3);reaction=np.zeros(3)
        for tag,force in loads.items():applied+=np.cross(model['nodes'][tag],np.asarray(force[:3])*1000)
        for tag,force in model['wall_nodal_loads_per_pa'].items():applied+=np.cross(model['nodes'][tag],np.asarray(force[:3])*100)
        for tag in model['base_tags']:
            r=np.asarray(ops.nodeReaction(tag));reaction+=r[3:]+np.cross(model['nodes'][tag],r[:3])
        np.testing.assert_allclose(reaction+applied,0,atol=1e-7)
        assert sum(model['wall_mass_by_tag'].values())==pytest.approx(model['wall_mass_kg'])
        assert len(model['plate_elements'])==16
    finally:ops.wipe()
