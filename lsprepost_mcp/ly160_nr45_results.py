"""Read the actual NR45 nodout/SPCFORC/BNDOUT histories; no force fitting."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np

FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"


def _float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def force_history(path: Path, ids: set[int], kind: str) -> list[tuple[float, float]]:
    if kind == "spcforc":
        time_re = re.compile(r"output at time\s*=\s*(" + FLOAT + ")")
        node_re = re.compile(r"node=\s*(\d+)\s+local x,y,z forces\s*=\s*(" + FLOAT + r")\s*(" + FLOAT + r")\s*(" + FLOAT + ")")
    elif kind == "bndout":
        time_re = re.compile(r"o u t p u t\s+t=\s*(" + FLOAT + ")")
        node_re = re.compile(r"nd#\s*(\d+)\s+xforce=\s*(" + FLOAT + r")\s+yforce=\s*(" + FLOAT + r")\s+zforce=\s*(" + FLOAT + ")")
    else:
        raise ValueError("Unknown force history")
    rows, values, time = [], {}, None

    def finish():
        if time is not None:
            if set(values) != ids:
                raise ValueError(f"{kind}: incomplete node set at t={time}")
            rows.append((time, sum(values.values())))

    with path.open(encoding="ascii", errors="replace") as stream:
        for line in stream:
            match = time_re.search(line)
            if match:
                finish()
                time, values = _float(match[1]), {}
            match = node_re.search(line)
            if match and int(match[1]) in ids:
                nid = int(match[1])
                if nid in values:
                    raise ValueError(f"{kind}: duplicate node {nid}")
                values[nid] = _float(match[3])
    finish()
    return rows


def gauge_history(path: Path, bottom: set[int], top: set[int]) -> list[tuple[float, float]]:
    time_re = re.compile(r"at time\s+(" + FLOAT + ")")
    rows, values, time, active = [], {}, None, False

    def finish():
        if values:
            if set(values) != bottom | top:
                raise ValueError(f"nodout: incomplete end displacements at t={time}")
            u = sum(values[i] for i in top)/len(top)-sum(values[i] for i in bottom)/len(bottom)
            rows.append((time, u))

    with path.open(encoding="ascii", errors="replace") as stream:
        for line in stream:
            match = time_re.search(line)
            if match:
                finish()
                time, values, active = _float(match[1]), {}, False
            elif "nodal point" in line:
                active = "x-disp" in line and "y-disp" in line
            elif active and re.match(r"\s*\d+\s", line):
                items = re.findall(FLOAT, line)
                nid = int(items[0])
                if nid in bottom | top:
                    if nid in values:
                        raise ValueError(f"nodout: duplicate node {nid}")
                    values[nid] = _float(items[2])
    finish()
    return rows


def align_histories(gauge: np.ndarray, support: np.ndarray, applied: np.ndarray):
    """Use only common recorded states, allowing ASCII time rounding, no interpolation."""
    indices = []
    histories = (gauge, support, applied)
    # LS-DYNA may omit an early frame in any of these ASCII databases. Require
    # all samples of the shortest history to exist in every other history.
    # This retains only actual common states while still rejecting shifted grids.
    pivot = min(histories, key=len)
    for reference in histories:
        selected = []
        for time in pivot[:, 0]:
            i = int(np.argmin(np.abs(reference[:, 0]-time)))
            if not np.isclose(reference[i, 0], time, rtol=5e-6, atol=1e-7):
                raise ValueError("Force/displacement time mismatch beyond ASCII rounding")
            selected.append(i)
        if len(set(selected)) != len(selected) or len(selected) < .95*len(reference):
            raise ValueError("Incomplete or ambiguous time history alignment")
        if selected[0] != 0 or selected[-1] != len(reference)-1:
            raise ValueError("History endpoints missing")
        indices.append(selected)
    return tuple(data[index] for data, index in zip(histories, indices))


def extract(run: Path) -> tuple[np.ndarray, dict]:
    from .ly160_nr45 import build_mesh
    record = json.loads((run/"run.json").read_text(encoding="utf-8"))
    if not record.get("solver_evaluation", {}).get("parsed", {}).get("terminated_normally"):
        raise ValueError("A normally terminated run is required")
    digest = hashlib.sha256((run/"model.k").read_bytes()).hexdigest()
    if digest != record["input_sha256"]:
        raise ValueError("Solver input snapshot hash mismatch")
    spec = json.loads((run/"model.json").read_text(encoding="utf-8"))["spec"]
    sets = build_mesh(spec)["sets"]
    bottom, top = set(sets[102]), set(sets[103])
    gauge = np.asarray(gauge_history(run/"nodout", bottom, top))
    support = np.asarray(force_history(run/"spcforc", bottom, "spcforc"))
    applied = np.asarray(force_history(run/"bndout", top, "bndout"))
    for data in (gauge, support, applied):
        if data.ndim != 2 or len(data) < 3 or not np.all(np.isfinite(data)) or np.any(np.diff(data[:, 0]) <= 0):
            raise ValueError("Missing, nonfinite or unordered history")
    raw_counts = {"nodout": len(gauge), "spcforc": len(support), "bndout": len(applied)}
    gauge, support, applied = align_histories(gauge, support, applied)
    force_bottom = -support[:, 1]*2*math.pi/1000
    force_top = applied[:, 1]*2*math.pi/1000
    u = gauge[:, 1]*1000
    if abs(gauge[-1, 0]-387) > 1e-6 or abs(u[-1]-3.87) > 1e-6:
        raise ValueError("Run did not reach 387 s and 3.87 mm")
    if np.any(np.diff(u) < -1e-8) or force_bottom.max() <= 0:
        raise ValueError("Invalid tensile response")
    peak = int(np.argmax(force_bottom))
    imbalance = np.abs(force_bottom-force_top)
    normalized_balance = float(imbalance.max()/force_bottom.max())
    if normalized_balance > .01:
        raise ValueError("End forces differ by more than 1% of peak")
    cutoff = .85*force_bottom[peak]
    crossing = None
    for i in range(peak+1, len(u)):
        if force_bottom[i] <= cutoff < force_bottom[i-1]:
            crossing = float(u[i-1]+(u[i]-u[i-1])*(cutoff-force_bottom[i-1])/(force_bottom[i]-force_bottom[i-1]))
            break
    report = {
        "run_dir": str(run.resolve()), "run_id": record["run_id"],
        "input_sha256": digest, "solver_duration_s": record["duration_s"],
        "history_samples": len(gauge), "raw_history_counts": raw_counts,
        "alignment": "common recorded states only; no force interpolation; ASCII time rounding tolerated",
        "end_time_s": float(gauge[-1, 0]),
        "gauge_length_mm": 62.5, "final_gauge_extension_mm": float(u[-1]),
        "peak_load_kN": float(force_bottom[peak]), "peak_extension_mm": float(u[peak]),
        "final_load_kN": float(force_bottom[-1]),
        "nominal_85percent_peak_extension_mm": crossing,
        "peak_error_vs_table1_percent": float((force_bottom[peak]/6.36-1)*100),
        "final_load_error_vs_table1_percent": float((force_bottom[-1]/5.41-1)*100),
        "max_end_force_difference_kN": float(imbalance.max()),
        "max_end_force_difference_over_peak": normalized_balance,
        "force_convention": "-sum(bottom SPCFORC Fy)*2*pi/1000, kN; top BNDOUT only for balance",
        "displacement_convention": "mean(top nodout Uy)-mean(bottom nodout Uy), multiplied by 1000 for mm",
        "reference_table1": {"peak_kN": 6.36, "nominal_cutoff_kN": 5.41, "nominal_cutoff_mm": 3.87},
        "sources": {name: {"sha256": hashlib.sha256((run/name).read_bytes()).hexdigest(), "bytes": (run/name).stat().st_size}
                    for name in ("nodout", "spcforc", "bndout", "glstat", "elout", "d3hsp")},
    }
    return np.column_stack((gauge[:, 0], u, force_bottom, force_top)), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows, report = extract(args.run)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output/"lsdyna_load_displacement.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("time_s", "gauge_extension_mm", "bottom_load_kN", "top_load_kN"))
        writer.writerows(rows)
    (args.output/"metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "sources"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
