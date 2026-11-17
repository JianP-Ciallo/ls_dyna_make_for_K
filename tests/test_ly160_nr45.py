"""Paper reconstruction checks: material/geometry contracts, no solver execution."""
from bisect import bisect_right
import importlib
import importlib.util
import math
from pathlib import Path

import pytest


def api():
    name = "lsprepost_mcp.ly160_nr45"
    assert importlib.util.find_spec(name) is not None, "L-NR45 compiler is not implemented"
    return importlib.import_module(name)


def blocks(keyword):
    result = {}
    current = None
    for line in keyword.splitlines():
        if line.startswith("*"):
            current = []
            result.setdefault(line, []).append(current)
        elif line.strip() and not line.startswith("$") and current is not None:
            current.append(line)
    return result


def test_mat024_curve_reproduces_paper_voce_not_bilinear_or_total_strain():
    module = api()
    spec = module.default_spec()
    keyword, metadata = module.build_keyword(spec)
    deck = blocks(keyword)
    mat = deck["*MAT_PIECEWISE_LINEAR_PLASTICITY"][0]
    first = [float(x) for x in mat[0].split(",")]
    assert first[:6] == pytest.approx([1, 7850, 202.57e9, .3, 185.69e6, 0])
    curve_id = int(mat[1].split(",")[2])
    curve = next(c for c in deck["*DEFINE_CURVE"] if int(c[0].split(",")[0]) == curve_id)
    points = [[float(x) for x in row.split(",")] for row in curve[1:]]
    assert points[0] == pytest.approx([0, 185.69e6])
    assert points[-1] == pytest.approx([3, 1136.03e6])
    xs = [x for x, _ in points]
    assert all(b > a for a, b in zip(xs, xs[1:]))
    for i in range(6001):
        eps = 3 * i / 6000
        j = min(len(points)-2, max(0, bisect_right(xs, eps)-1))
        a, fa = points[j]
        b, fb = points[j+1]
        actual = fa + (fb-fa)*(eps-a)/(b-a)
        # Independent published equation, evaluated on a grid not used by the compiler.
        expected = 185.69e6 + 135.15e6*(1-math.exp(-11.24*eps)) + 271.73e6*eps
        assert abs(actual-expected) <= 10000.1
    assert metadata["material_curve"]["interpolation_error_bound_pa"] <= 10000
    assert "*MAT_ADD_EROSION" not in deck


def test_mesh_has_paper_gauge_root_radius_and_positive_axisymmetric_cells():
    module = api()
    mesh = module.build_mesh(module.default_spec())
    nodes = {row[0]: row[1:] for row in mesh["nodes"]}
    assert min(p[1] for p in nodes.values()) == pytest.approx(-.03125)
    assert max(p[1] for p in nodes.values()) == pytest.approx(.03125)
    root = [p[0] for p in nodes.values() if abs(p[1]) < 1e-14]
    assert max(root) == pytest.approx(.0025)
    assert sorted(root) == pytest.approx([i*.00025 for i in range(11)])
    assert max(p[0] for p in nodes.values()) == pytest.approx(.0045)
    assert all(p[0] >= 0 and p[2] == 0 for p in nodes.values())
    for row in mesh["elements"]:
        coords = [nodes[n] for n in row[2:]]
        assert len(set(row[2:])) == 4
        assert sum(coords[i][0]*coords[(i+1)%4][1] - coords[(i+1)%4][0]*coords[i][1] for i in range(4)) > 0
    # At axial +/-10 mm the circular notch has r = 47.5 - sqrt(1925) mm.
    assert module.radius_at(.010) == pytest.approx(.003625178063039389, rel=1e-9)
    assert module.radius_at(-.010) == module.radius_at(.010)


def test_r12_free_fields_fit_declared_long_format_and_auto_cards():
    module = api()
    keyword, _ = module.build_keyword(module.default_spec())
    assert keyword.splitlines()[0].upper() == "*KEYWORD LONG=Y"
    # R12 still enforces field width in comma-delimited input.
    for line in keyword.splitlines():
        if not line.startswith(("$", "*")) and "," in line:
            assert all(len(field.strip()) <= 20 for field in line.split(","))
    auto = blocks(keyword)["*CONTROL_IMPLICIT_AUTO"][0]
    assert len(auto[0].split(",")) == 6


def test_solver_uniform_rediscretization_keeps_the_voce_curve_accuracy():
    module = api()
    keyword, _ = module.build_keyword(module.default_spec())
    curve = next(c for c in blocks(keyword)["*DEFINE_CURVE"] if c[0].split(",")[0] == "1001")
    count = int(curve[0].split(",")[7]) or 100  # documented LS-DYNA default
    points = [[float(v) for v in line.split(",")] for line in curve[1:]]
    xs = [p[0] for p in points]

    def sample(x):
        j = min(len(points)-2, max(0, bisect_right(xs, x)-1))
        a, fa = points[j]
        b, fb = points[j+1]
        return fa+(fb-fa)*(x-a)/(b-a)

    # Emulate the documented two-stage interpolation on the emitted data.
    spacing = 3/(count-1)
    values = [sample(i*spacing) for i in range(count)]
    worst = 0.
    for i in range(1, count):
        p = (i-.5)*spacing
        expected = 185.69e6+135.15e6*(1-math.exp(-11.24*p))+271.73e6*p
        worst = max(worst, abs((values[i-1]+values[i])/2-expected))
    assert worst < 10000


def test_axis_constraints_load_curve_and_force_convention_are_consistent():
    module = api()
    keyword, metadata = module.build_keyword(module.default_spec())
    deck = blocks(keyword)
    section = deck["*SECTION_SHELL"][0][0].split(",")
    assert int(section[1]) == 15 and int(section[3]) == 4
    assert deck["*CONTROL_IMPLICIT_GENERAL"][0][0].split(",")[0] == "1"
    assert deck["*CONTROL_IMPLICIT_SOLUTION"][0][0].split(",")[0] == "12"
    # Independent-DOF line search must not scale prescribed end displacements.
    assert int(deck["*CONTROL_IMPLICIT_SOLUTION"][0][3].split(",")[1]) == 2
    motion = deck["*BOUNDARY_PRESCRIBED_MOTION_SET"][0][0].split(",")
    assert [int(v) for v in motion[:3]] == [103, 2, 2]
    sets = {int(c[1].split(",")[0]): [int(v) for row in c[2:] for v in row.split(",") if int(v)] for c in deck["*SET_NODE_LIST_TITLE"]}
    nodes = {int(c.split(",")[0]): [float(x) for x in c.split(",")[1:4]] for c in deck["*NODE"][0]}
    assert all(nodes[n][0] == 0 for n in sets[101])
    assert all(nodes[n][1] == -.03125 for n in sets[102])
    assert all(nodes[n][1] == .03125 for n in sets[103])
    load = next(c for c in deck["*DEFINE_CURVE"] if int(c[0].split(",")[0]) == int(motion[3]))
    assert [float(x) for x in load[-1].split(",")] == pytest.approx([387, .00387])
    assert "*DATABASE_SPCFORC" in deck and "*DATABASE_BNDOUT" in deck
    assert metadata["force_to_full_circumference"] == pytest.approx(2*math.pi)
    assert metadata["solver_launched"] is False


@pytest.mark.parametrize("field,value", [("radial_cells", True), ("radial_cells", 0), ("radial_cells", 100000), ("near_size_m", float("nan")), ("near_size_m", 1e-10)])
def test_invalid_mesh_inputs_are_rejected_before_allocation(field, value):
    module = api()
    spec = module.default_spec()
    spec["mesh"][field] = value
    with pytest.raises(ValueError):
        module.build_keyword(spec)


def test_paper_parameters_cannot_be_silently_replaced():
    module = api()
    spec = module.default_spec()
    spec["material"]["youngs_pa"] = 200.44e9  # L-CIR is not L-NR45.
    with pytest.raises(ValueError):
        module.build_keyword(spec)


def test_mat103_diagnostic_uses_identical_direct_curve_without_refitting_or_rate():
    module = api()
    base, _ = module.build_keyword(module.default_spec())
    spec = module.diagnostic_spec("mat103_direct", "nr45_mat103_unit")
    actual, metadata = module.build_keyword(spec)
    before, after = blocks(base), blocks(actual)
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    assert changed == {"*MAT_PIECEWISE_LINEAR_PLASTICITY", "*MAT_ANISOTROPIC_VISCOPLASTIC"}
    cards = after["*MAT_ANISOTROPIC_VISCOPLASTIC"][0]
    assert len(cards) == 6
    assert [float(v) for v in cards[0].split(",")] == pytest.approx(
        [1, 7850, 202.57e9, .3, 0, 2, 1001, 1])
    # FLAG=2 takes absolute stress from the same curve. Remaining zero fields
    # retain isotropic defaults (R=1 or F/G/H=.5, L/M/N=1.5), no rate or failure.
    assert all(float(v) == 0 for card in cards[1:] for v in card.split(","))
    assert metadata["constitutive_implementation"] == "MAT_103 FLAG=2 direct isotropic curve"
    for key in ("material", "geometry", "analysis", "curve", "mesh"):
        assert spec[key] == module.default_spec()[key]
    spec["material"]["q_pa"] *= 1.01
    with pytest.raises(ValueError):
        module.build_keyword(spec)


def test_one_point_axisymmetric_diagnostic_uses_assumed_strain_stabilization():
    module = api()
    base, _ = module.build_keyword(module.default_spec())
    spec = module.diagnostic_spec("nip1_hg6", "nr45_nip1_unit")
    actual, metadata = module.build_keyword(spec)
    before, after = blocks(base), blocks(actual)
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    assert changed == {"*PART", "*SECTION_SHELL", "*HOURGLASS"}
    assert after["*SECTION_SHELL"][0][0].split(",")[1:4] == ["15", "0.833333", "1"]
    assert after["*PART"][0][1].split(",")[4] == "1"
    assert after["*HOURGLASS"][0][0].split(",")[:3] == ["1", "6", "0.1"]
    assert after["*CONTROL_ENERGY"][0][0].split(",")[0] == "2"
    assert metadata["integration_points"] == 1
    assert metadata["hourglass"] == {"type": 6, "coefficient": .1}
    assert not any("fully integrated" in a for a in metadata["assumptions"])
    assert before["*NODE"] == after["*NODE"]
    assert before["*ELEMENT_SHELL"] == after["*ELEMENT_SHELL"]


@pytest.mark.parametrize("case", ["time_step_10x", "top_radial_fixed"])
def test_diagnostic_changes_only_its_declared_numerical_or_boundary_setting(case):
    module = api()
    base, _ = module.build_keyword(module.default_spec())
    spec = module.diagnostic_spec(case, "nr45_diagnostic_unit")
    assert spec["model_type"] == "ly160_nr45_diagnostic"
    assert spec["material"] == module.default_spec()["material"]
    assert spec["geometry"] == module.default_spec()["geometry"]
    actual, metadata = module.build_keyword(spec)
    before, after = blocks(base), blocks(actual)
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    if case == "time_step_10x":
        assert changed == {"*CONTROL_IMPLICIT_GENERAL", "*CONTROL_IMPLICIT_AUTO"}
        assert float(after["*CONTROL_IMPLICIT_GENERAL"][0][0].split(",")[1]) == .01
        assert float(after["*CONTROL_IMPLICIT_AUTO"][0][0].split(",")[4]) == .1
    else:
        assert changed == {"*BOUNDARY_SPC_SET"}
        assert after["*BOUNDARY_SPC_SET"][0][-1] == "103,0,1,0,0,0,0,0"
    assert metadata["diagnostic_case"] == case
    spec["material"]["yield_strength_pa"] *= 1.05
    with pytest.raises(ValueError):
        module.build_keyword(spec)
    spec = module.default_spec()
    spec["unrecognized_solver_setting"] = True
    with pytest.raises(ValueError):
        module.build_keyword(spec)


@pytest.mark.parametrize("diagnostic", [None, "time_step_10x", "top_radial_fixed", "mat103_direct", "nip1_hg6"])
def test_project_round_trip_versioning_and_tamper_detection(tmp_path, monkeypatch, diagnostic):
    module = api()
    from lsprepost_mcp import project_store, paths
    from lsprepost_mcp.provenance import verify_generated_project
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "PROJECTS_DIR", tmp_path)
    spec = module.default_spec("nr45_unit") if diagnostic is None else module.diagnostic_spec(diagnostic, "nr45_unit")
    result = module.generate_project(spec)
    path = Path(result["project_dir"])
    assert project_store.validate_project_files(path)["ok"]
    assert verify_generated_project(path)["ok"]
    before = (path/"model.k").read_bytes()
    with pytest.raises(FileExistsError):
        module.generate_project(spec)
    assert (path/"model.k").read_bytes() == before
    versioned = module.generate_project(spec, if_exists="versioned")
    assert Path(versioned["project_dir"]) != path
    assert verify_generated_project(versioned["project_dir"])["ok"]
    altered = before.decode().replace("185690000", "138010000", 1)
    assert altered != before.decode()
    (path/"model.k").write_text(altered, encoding="utf-8")
    assert not project_store.validate_project_files(path)["ok"]
    assert not verify_generated_project(path)["ok"]
