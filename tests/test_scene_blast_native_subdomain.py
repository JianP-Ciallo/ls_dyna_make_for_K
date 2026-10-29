"""Shared FE boundaries; real reference READ ONLY, native solves only micro case."""
import json
from pathlib import Path
import numpy as np
import pytest

ROOT=Path(__file__).parents[1]
REAL_INDICES=[154,183,190,191,197,198,199,208,212,420,421,466,467]


def test_real_thirteen_element_boundary_comes_from_parent_incidence_not_macro_faces():
    from lsprepost_mcp.architecture.scene_blast.native_subdomain import partition
    r=json.loads((ROOT/'resources/scene_blast/three-storey-reference.json').read_text(encoding='utf8'))
    p=partition(r,REAL_INDICES)
    assert len(p['nodes'])==23 and len(p['boundary_nodes'])==11
    assert p['boundary_nodes']==[187,195,230,231,238,240,248,249,257,528,571]
    assert p['interior_nodes']==[201,202,239,246,247,254,255,256,267,268,529,570]
    assert p['element_counts']==dict(panel=9,column=4)


def micro_indices(case):
    panels=[i for i,e in enumerate(case['elements']) if e['component_id']=='floor1']
    lower=[];upper=[];extra=[]
    for i,e in enumerate(case['elements']):
        if e['kind']!='column':continue
        z=[case['nodes'][n][2] for n in e['nodes']]
        if e['component_id'].startswith('c0-'):
            (lower if max(z)>3. else extra).append(i)
        if e['component_id'].startswith('c1-') and min(z)<3.1:upper.append(i)
    result=panels+lower+upper+[extra[0]]
    assert len(result)==13
    return result


def test_micro_parent_thirteen_elements_unique_boundary_force_moment_state_and_tangent(tmp_path):
    import openseespy.opensees as ops
    from test_cpu_response_building_solver import micro_case
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference,equilibrate_gravity
    from lsprepost_mcp.architecture.scene_blast.native_subdomain import extract_and_verify
    case=micro_case();m=build_nonlinear_reference(ops,case)
    try:
        parent=equilibrate_gravity(ops,m,checkpoint_dir=tmp_path,wall_s=10)
        try:result=extract_and_verify(ops,m,parent,micro_indices(case))
        except ValueError as exc:
            if hasattr(exc,'diagnostics'):
                (tmp_path/'failed-subdomain.json').write_text(json.dumps(exc.diagnostics,indent=2),encoding='utf8')
                print({k:exc.diagnostics[k] for k in ('actual_relative_residual','interface_relative_residual','force_balance_relative_error','moment_balance_relative_error','stability')})
            raise
        assert result['status']=='completed' and len(result['elements'])==13
        assert result['actual_relative_residual']<=1e-5
        assert result['interface_relative_residual']<=1e-5
        assert result['force_balance_relative_error']<=1e-5 and result['moment_balance_relative_error']<=1e-5
        assert result['stability']['status']=='positive_definite'
        assert result['boundary_owner']=='single_native_parent_node_no_averaging'
        for record in result['boundary']:
            assert record['dofs']==pytest.approx(ops.nodeDisp(record['parent_node']+1),abs=1e-14)
        assert result['material_state_source']=='same_live_native_parent_domain_no_history_reinitialization'
        assert result['material_states'] and not result['blast_applied']
        (tmp_path/'micro-thirteen-element-result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        changed=result['boundary'][0]['parent_node']+1
        ops.setNodeDisp(changed,1,ops.nodeDisp(changed,1)+1e-4,'-commit')
        with pytest.raises(ValueError,match='位姿已改变'):extract_and_verify(ops,m,parent,micro_indices(case))
    finally:ops.wipe()


def test_rejected_or_partial_parent_never_provides_accepted_boundary(tmp_path):
    from lsprepost_mcp.architecture.scene_blast.native_subdomain import require_equilibrated_parent
    for report in [dict(status='failed',accepted_load_factor=.8),dict(status='completed',accepted_load_factor=.8),
                   dict(status='completed',accepted_load_factor=1.,actual_relative_residual=.01,stability=dict(status='positive_definite'))]:
        with pytest.raises(ValueError,match='父模型'):require_equilibrated_parent(report)


def test_boundary_partition_rejects_empty_duplicate_or_disconnected_selection():
    from lsprepost_mcp.architecture.scene_blast.native_subdomain import partition
    from test_cpu_response_building_solver import micro_case
    case=micro_case()
    for selected in ([],[1,1],[-1],[0,15]):
        with pytest.raises(ValueError):partition(case,selected)
