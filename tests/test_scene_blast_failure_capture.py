"""Lightweight stop-contract checks; never assemble the real building."""
import json
import sys
from pathlib import Path
import pytest


def test_first_native_failure_stops_without_refresh_or_backtracking(tmp_path, monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    model = n.build_nonlinear_reference(ops, single_column_case(), execution_scope='three_storey_prebalance')
    calls = []
    monkeypatch.setattr(ops, 'analyze', lambda *a: calls.append(a) or -3)
    monkeypatch.setattr(ops, 'reactions', lambda: pytest.fail('no native refresh after failure'))
    try:
        with pytest.raises(n.NativeGravityFailure) as caught:
            n.equilibrate_gravity(ops, model, checkpoint_dir=tmp_path, wall_s=5,
                                  stop_on_first_failure=True)
        assert calls == [(1,)]
        assert len(caught.value.diagnostics['attempts']) == 1
        assert caught.value.diagnostics['accepted_load_factor'] == 0
    finally:
        ops.wipe()


def test_material_event_stops_even_if_native_call_returns_success(tmp_path, monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    model = n.build_nonlinear_reference(ops, single_column_case(), execution_scope='three_storey_prebalance')
    original = ops.analyze
    calls = []
    def analyze(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(ops, 'analyze', analyze)
    try:
        with pytest.raises(n.NativeGravityFailure) as caught:
            n.equilibrate_gravity(ops, model, checkpoint_dir=tmp_path, wall_s=5,
                                  stop_on_first_failure=True, failure_probe=lambda: bool(calls))
        assert calls == [(1,)]
        assert 'native_failure_event' in caught.value.diagnostics['attempts'][0]['error']
    finally:
        ops.wipe()


def test_capture_worker_success_never_appends_subdomain(tmp_path, monkeypatch):
    from test_scene_blast_native_reference import single_column_case
    from lsprepost_mcp.architecture.scene_blast import native_failure_capture as c
    from lsprepost_mcp.architecture.scene_blast import native_subdomain
    monkeypatch.setattr(native_subdomain, 'extract_and_verify', lambda *a, **k: pytest.fail('no subdomain'))
    request = c.prepare_request(single_column_case(), sys.executable)
    result = c.run_worker(request, tmp_path / 'worker')
    assert result['status'] == 'completed'
    assert result['parent_load_factor'] == 1
    assert not list(tmp_path.rglob('*thirteen*'))


def test_capture_request_rejects_changed_scope_and_input():
    from test_scene_blast_native_reference import single_column_case
    from lsprepost_mcp.architecture.scene_blast import native_failure_capture as c
    request = c.prepare_request(single_column_case(), sys.executable)
    request['policy']['subdomain'] = True
    with pytest.raises(ValueError):
        c.validate_request(request)
    request = c.prepare_request(single_column_case(), sys.executable)
    request['case']['nodes'][0][0] += .1
    with pytest.raises(ValueError):
        c.validate_request(request)


def test_capture_deadline_stops_before_analyze(tmp_path, monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    from lsprepost_mcp.architecture.scene_blast import native_failure_capture as c
    from lsprepost_mcp.architecture.scene_blast import native_reference as n
    request = c.prepare_request(single_column_case(), sys.executable)
    original = n.build_nonlinear_reference
    clock = [0.]
    monkeypatch.setattr(c.time, 'monotonic', lambda: clock[0])
    def build(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 151.
        return result
    monkeypatch.setattr(n, 'build_nonlinear_reference', build)
    monkeypatch.setattr(ops, 'analyze', lambda *a: pytest.fail('deadline must stop before solve'))
    result = c.run_worker(request, tmp_path / 'worker')
    assert result['status'] == 'failed'
    assert 'deadline' in result['reason']


def test_event_during_force_read_stops_before_next_element_or_initialize(tmp_path, monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    case = single_column_case()
    case['elements'].append(dict(case['elements'][0]))
    model = n.build_nonlinear_reference(ops, case, execution_scope='three_storey_prebalance')
    original = ops.eleForce
    calls = []
    def force(tag):
        calls.append(tag)
        return original(tag)
    monkeypatch.setattr(ops, 'eleForce', force)
    monkeypatch.setattr(ops, 'initialize', lambda: pytest.fail('no initialization after force-read event'))
    try:
        with pytest.raises(n.NativeGravityFailure):
            n.equilibrate_gravity(ops, model, checkpoint_dir=tmp_path, wall_s=5,
                stop_on_first_failure=True, failure_probe=lambda: bool(calls))
        assert calls == [1]
    finally:
        ops.wipe()


def test_event_during_initialize_stops_before_matrix_read(tmp_path, monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    model = n.build_nonlinear_reference(ops, single_column_case(), execution_scope='three_storey_prebalance')
    original = ops.initialize
    calls = []
    def initialize():
        calls.append(1)
        return original()
    monkeypatch.setattr(ops, 'initialize', initialize)
    monkeypatch.setattr(ops, 'printA', lambda *a: pytest.fail('no matrix read after initialization event'))
    try:
        with pytest.raises(n.NativeGravityFailure):
            n.equilibrate_gravity(ops, model, checkpoint_dir=tmp_path, wall_s=5,
                stop_on_first_failure=True, failure_probe=lambda: bool(calls))
        assert calls == [1]
    finally:
        ops.wipe()


def test_analyze_returning_after_soft_deadline_does_not_start_refresh(tmp_path, monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    model = n.build_nonlinear_reference(ops, single_column_case(), execution_scope='three_storey_prebalance')
    original_analyze, original_integrator = ops.analyze, ops.integrator
    clock = [0.]
    monkeypatch.setattr(n.time, 'monotonic', lambda: clock[0])
    def analyze(*args):
        result = original_analyze(*args)
        clock[0] = 151.
        return result
    def integrator(*args):
        if clock[0]:
            pytest.fail('no refresh after soft deadline')
        return original_integrator(*args)
    monkeypatch.setattr(ops, 'analyze', analyze)
    monkeypatch.setattr(ops, 'integrator', integrator)
    try:
        with pytest.raises(n.NativeGravityFailure) as caught:
            n.equilibrate_gravity(ops, model, checkpoint_dir=tmp_path, wall_s=150,
                stop_on_first_failure=True, failure_probe=lambda: False)
        assert caught.value.diagnostics['reason_code'] == 'deadline'
    finally:
        ops.wipe()
