"""Immutable artifacts are verified, never promoted from partial/native failure output."""
import importlib
import json
import pytest


def module():
    try:return importlib.import_module('lsprepost_mcp.architecture.cpu_response.results')
    except ModuleNotFoundError:pytest.fail('CPU result artifacts are missing')


def fixture_result():
    return dict(schema_version='cpu-response.result@1',source={'kind':'benchmark','id':'x','revision':1,'fingerprint':'a'*64},
                input_fingerprint='b'*64,mesh={'nodes':[[0,0,0]],'elements':[],'steel_samples':[]},
                frames=[{'time_s':0,'displacements_m':[[0,0,0]],'rotations_rad':[[0,0,0]],'steel_stress_pa':[],'steel_strain':[]}],
                curves=[{'time_s':0,'monitor_displacement_m':[0,0,0]}],peaks={'displacement_m':0,'steel_abs_pa':0},diagnostics={},provenance={})


def test_artifact_integrity_detects_later_modification(tmp_path):
    results=module();value=fixture_result()
    index=results.write_artifacts(value,tmp_path)
    assert index['result.json']['sha256']
    assert results.load_result(tmp_path)['input_fingerprint']=='b'*64
    (tmp_path/'result.json').write_text('{}')
    with pytest.raises(ValueError):results.load_result(tmp_path)


def test_nonfinite_or_unordered_partial_results_are_rejected(tmp_path):
    results=module();value=fixture_result();value['peaks']['displacement_m']=float('nan')
    with pytest.raises(ValueError):results.write_artifacts(value,tmp_path)
    assert not (tmp_path/'manifest.json').exists()
