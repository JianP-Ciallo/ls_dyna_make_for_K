import numpy as np
import pytest

from lsprepost_mcp.ly160_nr45_results import align_histories, force_history, gauge_history


def test_nodout_uses_displacement_not_rotation_and_handles_adjacent_signs(tmp_path):
    path = tmp_path/"nodout"
    path.write_text("""
 n o d a l print ( at time 1.0000000E-01 )
 nodal point  x-disp y-disp z-disp
 1  0.00000E+00-1.00000E-05 0.00000E+00
 2 -2.00000E-06 3.00000E-05 0.00000E+00
 n o d a l print ( at time 1.0000000E-01 )
 nodal point  x-rot y-rot z-rot
 1 0.00000E+00 9.00000E+00 0.00000E+00
 2 0.00000E+00 8.00000E+00 0.00000E+00
""", encoding="ascii")
    assert np.asarray(gauge_history(path, {1}, {2})) == pytest.approx(np.array([[.1, 4e-5]]))


def test_spcforc_selects_bottom_nodes_and_rejects_missing_node(tmp_path):
    path = tmp_path/"spcforc"
    path.write_text("""
 output at time = 1.00000E+00
 node= 1 local x,y,z forces = 10.0 -20.0 30.0 setid=0
 node= 2 local x,y,z forces = 11.0 -21.0 31.0 setid=0
 node= 3 local x,y,z forces = 12.0 999.0 32.0 setid=0
""", encoding="ascii")
    assert force_history(path, {1, 2}, "spcforc") == [(1., -41.)]
    with pytest.raises(ValueError, match="incomplete"):
        force_history(path, {1, 4}, "spcforc")


def test_match_common_recorded_times_without_inventing_missing_spc_sample():
    times = np.arange(30, dtype=float)+.5387425
    times[0] = 0.
    gauge = np.column_stack((times, times*1e-5))
    force = np.column_stack(([float(format(t, '.6g')) for t in times], times*20))
    support = np.delete(force, 1, axis=0)
    g, s, a = align_histories(gauge, support, force)
    assert len(g) == 29
    assert .01 not in g[:, 1]
    assert g[1, 0] == times[2]
    assert s[:, 1] == pytest.approx(a[:, 1])


def test_alignment_rejects_physical_time_mismatch():
    gauge = np.column_stack((np.arange(30.), np.arange(30.)*1e-5))
    force = gauge.copy()
    force[10, 0] += .01
    with pytest.raises(ValueError, match="time"):
        align_histories(gauge, force, force)


def test_alignment_allows_a_missing_nodout_bndout_frame_without_interpolating():
    times = np.arange(30, dtype=float)+.5387425
    times[0] = 0.
    gauge = np.column_stack((times, times*1e-5))
    force = np.column_stack(([float(format(t, '.6g')) for t in times], times*20))
    g, s, a = align_histories(np.delete(gauge, 2, axis=0), force, np.delete(force, 2, axis=0))
    assert len(g) == len(s) == len(a) == 29
    assert g[2, 0] == times[3]
    assert s[:, 1] == pytest.approx(a[:, 1])
