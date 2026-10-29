"""Real elastic column: analytical stiffness, mass, strain and absolute frequency."""
import importlib
import math
import pytest


def module():
    try:
        return importlib.import_module('lsprepost_mcp.architecture.cpu_response.column')
    except ModuleNotFoundError:
        pytest.fail('fiber column builder is missing')


def test_column_static_reference_mass_and_fiber_stress():
    column = module()
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    case = make_benchmark('rc-column-v1','medium')
    model = column.build_column(ops,case)
    column.run_static(ops,model,10000)
    sample = column.read_column_sample(ops,model,ops.getTime())
    area_s = 4*math.pi*0.016**2/4
    mass = ((0.09-area_s)*2500+area_s*7850)*3
    ei = 30e9*0.3**4/12 + (200e9-30e9)*area_s*0.102**2
    expected = 3000*3**4/(8*ei)
    assert model['mass_kg'] == pytest.approx(mass,rel=1e-12)
    assert sum(model['node_masses_kg']) == pytest.approx(mass,rel=1e-12)
    assert sample['displacements_m'][-1][0] == pytest.approx(expected,rel=0.02)
    assert sample['support_reaction'][0] == pytest.approx(-9000,abs=1e-6)
    assert sample['support_reaction'][4] == pytest.approx(-13500,abs=1e-6)
    assert sample['steel_stress_pa']
    for stress,strain in zip(sample['steel_stress_pa'],sample['steel_strain']):
        assert stress == pytest.approx(200e9*strain,abs=1)
    assert min(sample['steel_stress_pa'])<0<max(sample['steel_stress_pa'])
    ops.wipe()


def test_column_absolute_first_frequency_uses_physical_mass():
    column=module()
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    model=column.build_column(ops,make_benchmark('rc-column-v1','fine'))
    eig=ops.eigen(3)
    ref=1.8751040687**2*math.sqrt(model['ei_nm2']/(model['mass_kg']/3*3**4))
    assert math.sqrt(eig[0])==pytest.approx(ref,rel=0.02)
    ops.wipe()


def test_reversing_pressure_reverses_fiber_tension_and_compression():
    column=module()
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    results=[]
    for sign in (1,-1):
        case=make_benchmark('rc-column-v1')
        case['loads']['direction']=[sign,0,0]
        model=column.build_column(ops,case);column.run_static(ops,model,10000)
        results.append(column.read_column_sample(ops,model,1)['steel_stress_pa'])
    assert results[1]==pytest.approx([-v for v in results[0]],abs=1)
    ops.wipe()


def test_pure_end_moment_checks_known_curvature_and_orthogonal_direction():
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    from test_cpu_response_references import column_reference
    column=module();ref=column_reference();rotated=[]
    for dof,coordinate,sign in [(5,0,-1),(4,1,1)]:
        model=column.build_column(ops,make_benchmark('rc-column-v1','medium'))
        ops.timeSeries('Linear',1);ops.pattern('Plain',1,1)
        f=[0]*6;f[dof-1]=1000;ops.load(len(model['nodes']),*f)
        column.configure_static(ops);assert ops.analyze(1)==0
        value=column.read_column_sample(ops,model,1)
        for loc,stress in zip(model['steel_samples'],value['steel_stress_pa']):
            expected=sign*loc['position_m'][coordinate]*1000/ref['ei_nm2']*200e9
            assert stress==pytest.approx(expected,rel=0.02)
        rotated.append(sorted(abs(v) for v in value['steel_stress_pa']))
    assert rotated[0]==pytest.approx(rotated[1],rel=1e-9)
    ops.wipe()
