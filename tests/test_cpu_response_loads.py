"""Forces, moments and impulse are invariant under display/mesh refinement."""
import importlib
import pytest


def loads():
    try:
        return importlib.import_module('lsprepost_mcp.architecture.cpu_response.loads')
    except ModuleNotFoundError:
        pytest.fail('CPU pressure mapping is missing')


def test_pressure_units_and_impulse_are_physical():
    curve = loads().curve_to_si([[0, 0], [1, 10], [10, 0], [150, 0]])
    assert curve[1] == [0.001, 10000]
    assert loads().curve_impulse(curve) == pytest.approx(50.0)


@pytest.mark.parametrize('curve', [[[0, 0], [1, -2]], [[0, 0], [1, 1], [1, 0]], [[1, 1], [2, 0]]])
def test_invalid_external_pressure_is_not_silently_clipped(curve):
    with pytest.raises(ValueError):
        loads().curve_to_si(curve)


def test_column_consistent_load_has_correct_resultant_and_moment():
    model = dict(kind='column', nodes=[[0, 0, 0], [0, 0, 3]],
                 elements=[[0, 1]], width_m=0.3)
    mapped = loads().map_pressure(model, dict(direction=[1, 0, 0]))
    vectors = mapped['nodal_vectors_per_pa']
    assert sum(v[0] for v in vectors) == pytest.approx(0.9)
    assert vectors[0][4] == pytest.approx(0.225)
    moment = sum(model['nodes'][i][2] * v[0] + v[4] for i, v in enumerate(vectors))
    assert moment == pytest.approx(1.35)


def test_panel_load_and_rotational_moment_do_not_depend_on_nodal_count():
    model = dict(kind='panel', nodes=[[0,0,0],[2,0,0],[2,2,0],[0,2,0]], elements=[[0,1,2,3]])
    vectors = loads().map_pressure(model, dict(direction=[0, 0, -1]))['nodal_vectors_per_pa']
    assert sum(v[2] for v in vectors) == pytest.approx(-4)
    assert sum(model['nodes'][i][0]*v[2] for i,v in enumerate(vectors)) == pytest.approx(-4)
