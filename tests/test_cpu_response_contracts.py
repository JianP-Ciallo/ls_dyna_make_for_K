"""Input integrity and bounded, reproducible reference cases."""
import importlib
import math
import pytest


def api():
    try:
        return importlib.import_module('lsprepost_mcp.architecture.cpu_response.benchmarks')
    except ModuleNotFoundError:
        pytest.fail('CPU benchmark definitions are missing')


def test_reference_identity_is_stable_while_profile_changes_input_identity():
    from lsprepost_mcp.architecture.cpu_response import contracts
    case = api().make_benchmark('rc-column-v1')
    original = contracts.fingerprint(contracts.normalize_case(case))
    case['analysis']['dt_s'] = 0.00005
    changed = contracts.normalize_case(case)
    assert changed['source'] == api().make_benchmark('rc-column-v1')['source']
    assert contracts.fingerprint(changed) != original


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 0, True])
def test_invalid_step_is_rejected(value):
    case = api().make_benchmark('rc-panel-v1')
    case['analysis']['dt_s'] = value
    from lsprepost_mcp.architecture.cpu_response.contracts import normalize_case
    with pytest.raises(ValueError):
        normalize_case(case)


def test_unknown_fields_and_unbudgeted_refinement_are_rejected():
    from lsprepost_mcp.architecture.cpu_response.contracts import normalize_case
    case = api().make_benchmark('rc-panel-v1')
    case['mesh']['n'] = 10000
    with pytest.raises(ValueError):
        normalize_case(case)
    case = api().make_benchmark('rc-column-v1')
    case['python_path'] = 'arbitrary'
    with pytest.raises(ValueError):
        normalize_case(case)


def test_benchmark_source_cannot_be_impersonated_or_geometry_silently_changed():
    from lsprepost_mcp.architecture.cpu_response.contracts import normalize_case
    case = api().make_benchmark('rc-column-v1')
    case['source']['fingerprint'] = '0' * 64
    with pytest.raises(ValueError):
        normalize_case(case)
    case = api().make_benchmark('rc-panel-v1')
    case['reinforcement']['cover_m'] = 1
    with pytest.raises(ValueError):
        normalize_case(case)


@pytest.mark.parametrize('name',['column','panel'])
def test_published_reference_inputs_are_frozen_at_revision_one(name):
    import json
    from pathlib import Path
    expected=json.loads((Path(__file__).parent/'fixtures/cpu_response'/(name+'-v1.json')).read_text())
    assert api().make_benchmark('rc-'+name+'-v1')==expected


def test_refinement_to_32_preserves_resource_limits_and_rejects_larger_mesh():
    from lsprepost_mcp.architecture.cpu_response.contracts import normalize_case
    case=api().make_benchmark('rc-panel-v1');original=case['budget'].copy();case['mesh']['n']=32
    assert normalize_case(case)['budget']==original
    case['mesh']['n']=64
    with pytest.raises(ValueError):normalize_case(case)
