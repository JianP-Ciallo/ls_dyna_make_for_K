"""Frozen one-point regressions; no building generation, gravity solve or TNT."""
import json
from pathlib import Path

import numpy as np
import pytest

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/scene_blast/native-material-history.json').read_text(encoding='utf8'))


def set_strain(ops, tag, values):
    # Upstream NDTest discards setTrialStrain's return code. Verify the actual
    # state rather than interpreting a completed Python call as acceptance.
    ops.NDTest('SetStrain', tag, *values)
    np.testing.assert_array_equal(ops.NDTest('GetStrain', tag), values)


def material(ops, *, replay=True, tag=910001):
    from lsprepost_mcp.architecture.scene_blast.native_materials import concrete_laws
    profile = FIXTURE['profile']
    law = concrete_laws(profile['E'], profile['length'])
    args = []
    for key in ('Te', 'Ts', 'Td', 'Ce', 'Cs', 'Cd'):
        args.extend(['-' + key, *law[key]])
    ops.nDMaterial('ASDConcrete3D', tag, profile['E'], profile['nu'], *args, '-tangent')
    if replay:
        for step in FIXTURE['accepted_history']:
            set_strain(ops, tag, step['strain'])
            np.testing.assert_allclose(ops.NDTest('GetStress', tag), step['stress'], rtol=1e-11, atol=1e-6)
            ops.NDTest('CommitState', tag)
    return tag


@pytest.fixture
def ops():
    import openseespy.opensees as native
    native.wipe()
    yield native
    native.wipe()


@pytest.mark.parametrize('index', range(4))
def test_frozen_root_tangent_stays_on_local_constitutive_branch(ops, index):
    tag = material(ops)
    x = np.array(FIXTURE['targets'][index]['strain'])
    x[2] = FIXTURE['targets'][index]['root']
    set_strain(ops, tag, x)
    base = np.array(ops.NDTest('GetStress', tag))
    tangent = np.array(ops.NDTest('GetTangentStiffness', tag)).reshape(6, 6)
    assert abs(base[2]) <= 1e-8
    # Independent prior two-sided diagnosis: D3333 is about 29.2 GPa,
    # whereas the stock perturbation crosses a branch and gives 0.158 GPa.
    assert 29.0e9 < tangent[2, 2] < 29.4e9
    for j in range(6):
        h = 1e-13
        delta = np.zeros(6)
        delta[j] = h
        set_strain(ops, tag, x + delta)
        plus = np.array(ops.NDTest('GetStress', tag))
        set_strain(ops, tag, x - delta)
        minus = np.array(ops.NDTest('GetStress', tag))
        # Both directions must agree; averaging slopes across a kink would hide it.
        scale = max(np.linalg.norm(tangent[:, j]), 1.)
        assert np.linalg.norm((plus - base) / h - tangent[:, j]) / scale < 2e-4
        assert np.linalg.norm((base - minus) / h - tangent[:, j]) / scale < 2e-4
    set_strain(ops, tag, x)
    np.testing.assert_array_equal(ops.NDTest('GetStress', tag), base)


@pytest.mark.parametrize('x', [
    [1e-5, 2e-6, -3e-6, 3e-6, -2e-6, 1e-6],
    [1.3e-4, 1e-5, -4e-5, 2e-5, 0., 0.],
    [-1e-3, -3e-4, -2e-4, 2e-5, 1e-5, -3e-5],
    [-3e-3, -1e-3, -5e-4, 8e-5, 2e-5, -4e-5],
])
def test_loading_and_unloading_full_three_dimensional_directional_derivative(ops, x):
    tag = material(ops, replay=False)
    for load in (1., .7):
        strain = np.array(x) * load
        set_strain(ops, tag, strain)
        base = np.array(ops.NDTest('GetStress', tag))
        tangent = np.array(ops.NDTest('GetTangentStiffness', tag)).reshape(6, 6)
        for direction in (np.array([1., -.3, .2, .15, -.2, .1]), np.array([.1, .2, -.4, .5, .3, -.2])):
            h = 1e-10
            prediction = tangent @ direction
            for sign in (-1, 1):
                set_strain(ops, tag, strain + sign * h * direction)
                stress = np.array(ops.NDTest('GetStress', tag))
                error = np.linalg.norm((stress - base) / (sign * h) - prediction)
                assert error / max(np.linalg.norm(prediction), 1.) < 1e-4
        set_strain(ops, tag, strain)
        ops.NDTest('CommitState', tag)
