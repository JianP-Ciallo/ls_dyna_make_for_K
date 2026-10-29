"""Opt-in native diagnostics, direct material probes only; no real building."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
OLD = ROOT / 'artifacts/native-runtime-20261023-01/resume-01'


def native(tmp_path, mode, *, enabled=True, extra=(), log_name='failure.jsonl'):
    exe = Path(os.environ.get('NATIVE_DIAGNOSTIC_EXE', OLD / 'build-opensees/NativeMaterialRegression.exe'))
    runtime = Path(os.environ.get('NATIVE_DIAGNOSTIC_RUNTIME', OLD / 'runtime'))
    env = os.environ.copy()
    env['PATH'] = f'{runtime};{runtime}/Lib/site-packages/openseespywin;D:/mingw64/bin;' + env['PATH']
    env.pop('OPENSEES_NATIVE_FAILURE_LOG', None)
    target = tmp_path / log_name
    if enabled:
        env['OPENSEES_NATIVE_FAILURE_LOG'] = str(target)
    result = subprocess.run([str(exe), mode, *map(str, extra)], env=env, cwd=ROOT,
                            capture_output=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr.decode('utf8', 'replace')[-3000:]
    return target


def event(path):
    assert path.is_file(), 'terminal native failure produced no diagnostic event'
    lines = path.read_text(encoding='utf8').splitlines()
    assert len(lines) == 1, 'only the first terminal failure may be emitted'
    return json.loads(lines[0])


def test_shell_failure_identifies_element_ip_layer_and_pre_revert_input(tmp_path):
    path = native(tmp_path, 'shell')
    d = event(path)
    assert d['schema'] == 'opensees-native-trial-failure@1'
    assert d['context']['element_tag'] == 1
    assert d['context']['integration_point'] == 1
    assert d['context']['section_tag'] == 4
    assert d['context']['layer'] == 1
    assert len(d['context']['nodal_trial']) == 4
    assert d['context']['nodal_trial'][1][0] is None  # rejected NaN, before native revert
    assert d['reason'] == 'nonfinite_input'
    assert d['checkpoint']['available'] is True
    assert d['checkpoint']['ids'] and d['checkpoint']['vectors']
    assert d['checkpoint']['strain'] == [0.] * 5
    native(tmp_path, 'replay-capsule', enabled=False, extra=(path,))


def test_asd_failure_saves_nonzero_committed_history_and_replays(tmp_path):
    path = native(tmp_path, 'state')
    d = event(path)
    assert d['source'] == 'ASDConcrete3D'
    assert d['reason'] == 'nonfinite_input'
    assert d['checkpoint']['available'] is True
    assert any(d['checkpoint']['strain'])
    native(tmp_path, 'replay-capsule', enabled=False, extra=(path,))


def test_finite_trial_names_the_guarded_branch_and_restores_checkpoint(tmp_path):
    path = native(tmp_path, 'finite-guard')
    d = event(path)
    assert d['source'] == 'ASDConcrete3D'
    assert d['reason'] == 'nonunique_principal_derivative'
    assert all(v is not None for v in d['trial_strain'])
    assert d['inner_error']['trial_strain'] == d['trial_strain']
    native(tmp_path, 'replay-capsule', enabled=False, extra=(path,))


def test_checkpoint_avoids_existing_child_database_tag_collision(tmp_path):
    path = native(tmp_path, 'tagged-checkpoint')
    d = event(path)
    assert d['checkpoint']['available'] is True
    assert len(d['checkpoint']['vectors']) == 2, 'root/child messages overwrote the same database tag'
    native(tmp_path, 'replay-capsule', enabled=False, extra=(path,))


@pytest.mark.parametrize(('mode', 'reason'), [('no-root', 'root_not_bracketed'),
                                            ('overflow', 'invalid_inverse_D3333')])
def test_root_failure_reason_is_not_reported_as_material_capacity(tmp_path, mode, reason):
    d = event(native(tmp_path, mode))
    assert d['source'] == 'PlateFiber'
    assert d['reason'] == reason
    assert d['root']['evaluations'] > 0
    assert d['checkpoint']['available'] is False  # test-only material has no serializer


@pytest.mark.parametrize('mode', ['root', 'bracket', 'recover-probe'])
def test_successful_or_recovered_search_produces_no_terminal_event(tmp_path, mode):
    assert not native(tmp_path, mode).exists()


def test_diagnostics_disabled_keeps_native_rejection_behavior(tmp_path):
    assert not native(tmp_path, 'shell', enabled=False).exists()


def test_log_io_failure_cannot_change_material_outcome(tmp_path):
    assert not native(tmp_path, 'shell', log_name='missing/failure.jsonl').exists()


def minimal_plate_probe():
    """One synthetic 1m cantilever plate; original F2 section/material inputs.

    Fixture fixities are not a change to the real building's supports.
    """
    import numpy as np
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.scene_blast.native_materials import define_panel
    case = json.loads((ROOT / 'artifacts/native-whole-gravity-20261024-01/request.json').read_text(encoding='utf8'))['case']
    profile = case['panel_sections'][18]
    densities = case['column_sections'][0]['materials']
    weight = 9.80665 * sum(layer['t'] * densities['concrete_density' if layer['kind'] == 'concrete' else 'steel_density']
                          for layer in profile['layers'])
    xyz = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]])
    loads = np.zeros((4, 6)); loads[:, 2] = -weight / 4
    ops.wipe(); ops.model('basic', '-ndm', 3, '-ndf', 6)
    try:
        for i, p in enumerate(xyz, 1): ops.node(i, *p)
        for i in (1, 4): ops.fix(i, 1, 1, 1, 1, 1, 1)
        define_panel(ops, profile, 100, 1.)
        ops.element('ShellMITC4', 1, 1, 2, 3, 4, 100)
        ops.timeSeries('Linear', 1); ops.pattern('Plain', 1, 1)
        for i, load in enumerate(loads, 1): ops.load(i, *load)
        def configure():
            ops.wipeAnalysis(); ops.constraints('Transformation'); ops.numberer('RCM'); ops.system('FullGeneral')
            ops.test('NormUnbalance', 1.e-6 * np.linalg.norm(loads[[1, 2], :3]), 40, 0)
            ops.algorithm('Newton'); ops.integrator('LoadControl', 1.); ops.analysis('Static')
        configure(); assert ops.analyze(1) == 0
        ops.integrator('LoadControl', 0.); assert ops.analyze(1) == 0
        internal = np.asarray(ops.eleForce(1)).reshape(4, 6)
        residual = internal - loads
        scaled = residual[[1, 2]].copy(); scaled[:, 3:] /= .5
        relative = float(np.linalg.norm(scaled) / np.linalg.norm(loads[[1, 2], :3]))
        ops.reactions(); reaction = np.asarray([ops.nodeReaction(i) for i in range(1, 5)])
        external = reaction + loads
        force = float(np.linalg.norm(external[:, :3].sum(0)) / weight)
        moment = float(np.linalg.norm((np.cross(xyz, external[:, :3]) + external[:, 3:]).sum(0)) / weight)
        n = ops.systemSize(); K = np.asarray(ops.printA('-ret')).reshape(n, n)
        diagonal = np.sqrt(np.diag(K)); normalized = K / diagonal[:, None] / diagonal[None, :]
        np.linalg.cholesky((normalized + normalized.T) / 2 - 1.e-9 * np.eye(n))
        sigma = 0.
        for ip in range(1, 5):
            for li, layer in enumerate(profile['layers'], 1):
                if layer['kind'] == 'concrete':
                    stress = ops.eleResponse(1, 'material', ip, 'fiber', li, 'material', 1, 'stress')
                    assert len(stress) == 6
                    sigma = max(sigma, abs(stress[2]))
        assert relative <= 1.e-5 and force <= 1.e-5 and moment <= 1.e-5
        assert sigma <= 1.e-8
        return dict(relative=relative, force_error=force, moment_error=moment, sigma33_pa=sigma,
                    max_displacement_m=float(np.max(np.abs([ops.nodeDisp(i, 3) for i in range(1, 5)]))),
                    dofs=n, tangent='positive_definite', load_factor=ops.getTime(), weight_n=weight)
    finally:
        ops.wipe()


def test_minimal_plate_gravity_identical_with_diagnostics_enabled_and_disabled(tmp_path):
    import sys
    runtime = Path(os.environ.get('NATIVE_DIAGNOSTIC_RUNTIME', OLD / 'runtime'))
    outputs = []
    for enabled in (False, True):
        env = os.environ.copy(); env.pop('OPENSEES_NATIVE_FAILURE_LOG', None)
        target = tmp_path / 'plate-failure.jsonl'
        if enabled: env['OPENSEES_NATIVE_FAILURE_LOG'] = str(target)
        result = subprocess.run([str(runtime / 'python.exe'), '-B', '-X', 'utf8', '-c',
            "import sys,json;sys.path.insert(0,'tests');from test_scene_blast_native_failure_diagnostics import minimal_plate_probe;print(json.dumps(minimal_plate_probe()))"],
            cwd=ROOT, env=env, capture_output=True, timeout=20,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert result.returncode == 0, result.stderr.decode('utf8', 'replace')[-3000:]
        outputs.append(json.loads(result.stdout.decode('utf8').strip().splitlines()[-1]))
        assert not target.exists()
    assert outputs[0] == outputs[1]
    assert outputs[0]['load_factor'] == 1. and outputs[0]['dofs'] == 12
    (tmp_path / 'plate-results.json').write_text(json.dumps(dict(
        fixture='synthetic_1m_plate_original_F2_section_not_real_building',
        diagnostics_disabled=outputs[0], diagnostics_enabled=outputs[1], identical=True), indent=2) + '\n', encoding='utf8')
