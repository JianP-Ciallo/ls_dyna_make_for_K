"""Trial preparation is read-only by default; CLI never auto-runs a solver."""
from test_cpu_response_building_mapping import three_storey_fixture


def test_trial_cli_default_only_inspects_prepared_micro_snapshot(tmp_path,capsys):
    from scripts.run_cpu_response_building import main
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    from lsprepost_mcp.architecture.cpu_response.results import json_write
    a,s=three_storey_fixture();case=prepare_reference(a,s,target_component_id='wall')
    path=tmp_path/'case.json';json_write(path,case);calls=[]
    assert main(['--case',str(path)],runner=lambda *args,**kwargs:calls.append((args,kwargs)))==0
    assert not calls
    assert 'prepared_only' in capsys.readouterr().out


def test_report_distinguishes_semantic_plaster_from_actual_K_material():
    from scripts.prepare_cpu_response_building import material_label_conflicts
    a=dict(components={'wall':dict(material='plaster',material_id=9002,host_density_kg_m3=2400)},
           materials={9002:dict(model='*MAT_CONCRETE_DAMAGE_REL3_TITLE+')})
    assert material_label_conflicts(a)[0]['native_material_id']==9002
    a['materials']={str(k):v for k,v in a['materials'].items()}
    assert material_label_conflicts(a)[0]['semantic_material']=='plaster'
