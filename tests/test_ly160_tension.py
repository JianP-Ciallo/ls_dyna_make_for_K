"""Specific physics and provenance regressions for the three added specimens."""
import json
from pathlib import Path

import numpy as np
import pytest

from lsprepost_mcp import ly160_tension as api


@pytest.mark.parametrize("name,values", [
    ("L-NR225", [201.70,203.99,114.,5.87,226.12]),
    ("L-GP", [199.42,133.75,162.84,10.66,246.81]),
    ("L-CIR", [200.44,138.01,157.16,13.70,272.38]),
])
def test_published_law_and_locked_parameters(name, values):
    E, s0, Q, b, L = values
    spec = api.default_spec(name)
    assert spec["material"]["E_GPa"] == E
    curve, bound = api.hardening_curve(name)
    curve = np.asarray(curve)
    ep = np.linspace(0, 3, 20001)
    expected = (s0+Q*(1-np.exp(-b*ep))+L*ep)*1e6
    assert np.max(abs(np.interp(ep, curve[:,0], curve[:,1])-expected)) <= bound <= 10000
    spec["material"]["Q_MPa"] *= 1.01
    with pytest.raises(ValueError):
        api.build_keyword(spec)


@pytest.mark.parametrize("name", list(api.PAPER))
def test_geometry_mesh_boundary_sets_and_load_scaling(name):
    spec = api.default_spec(name)
    mesh = api.build_mesh(spec)
    assert api.audit_mesh(mesh)["ok"]
    nodes = {n[0]:np.array(n[1:]) for n in mesh["nodes"]}
    assert all(abs(nodes[n][1]+.03125)<1e-12 for n in mesh["sets"][102])
    assert all(abs(nodes[n][1]-.03125)<1e-12 for n in mesh["sets"][103])
    assert all(nodes[n][0] == 0 for n in mesh["sets"][101])
    assert all(nodes[n][2] == 0 for n in mesh["sets"][104])
    root = np.array([p for p in nodes.values() if abs(p[1]) < 1e-12])
    keyword, metadata = api.build_keyword(spec)
    if name == "L-NR225":
        assert root[:,0].max() == pytest.approx(.00225)
        assert api.nr225_radius(0) == .00225
        assert api.nr225_radius(.00225) == .0045
        assert metadata["force_to_full_specimen"] == pytest.approx(2*np.pi)
    else:
        assert "*ELEMENT_SOLID" in keyword and "*HOURGLASS\n1,6,0.1" in keyword
        assert metadata["force_to_full_specimen"] == 4
        area = np.ptp(root[:,0])*np.ptp(root[:,2])*4
        assert area*1e6 == pytest.approx(120 if name == "L-GP" else 100)
    assert all(len(field)<=20 for line in keyword.splitlines() if "," in line and not line.startswith("$") for field in line.split(","))
    # The independent mesh audit must reject an inverted element.
    changed = dict(mesh)
    changed["elements"] = [row.copy() for row in mesh["elements"]]
    changed["elements"][0][2:4] = reversed(changed["elements"][0][2:4])
    with pytest.raises(ValueError):
        api.audit_mesh(changed)


@pytest.mark.parametrize("name", list(api.PAPER))
def test_normal_project_entry_points_and_tamper_detection(name, tmp_path, monkeypatch):
    from lsprepost_mcp import paths, project_store
    from lsprepost_mcp.provenance import verify_generated_project
    from lsprepost_mcp.lsdyna_runner import _result_mode
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "PROJECTS_DIR", tmp_path)
    spec = api.default_spec(name)
    result = api.generate_project(spec)
    project = Path(result["project_dir"])
    assert result["checks"]["ok"], result["checks"]
    assert verify_generated_project(project)["ok"]
    assert _result_mode(project) == "quasi_static"
    with pytest.raises(FileExistsError):
        api.generate_project(spec)
    versioned = Path(api.generate_project(spec, if_exists="versioned")["project_dir"])
    assert versioned != project and verify_generated_project(versioned)["ok"]
    model = json.loads((project/"model.json").read_text(encoding="utf-8"))
    model["spec"]["material"]["E_GPa"] *= 1.01
    (project/"model.json").write_text(json.dumps(model), encoding="utf-8")
    assert not project_store.validate_project_files(project)["ok"]
    assert not verify_generated_project(project)["ok"]
