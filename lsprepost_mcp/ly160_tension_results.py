"""Extract the added paper specimens from preserved native solver histories."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from .ly160_nr45_results import align_histories, force_history, gauge_history
from .ly160_tension import PAPER, build_keyword, build_mesh


def file_hash(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def energy_audit(path: Path):
    states, current = [], None
    for line in path.open(encoding="ascii", errors="replace"):
        match = re.match(r"\s*([a-z /]+?)\s*\.+\s+([-+0-9.Ee]+)", line)
        if not match:
            continue
        key, value = match[1].strip(), float(match[2])
        if key == "time":
            current = {key: value}
            states.append(current)
        elif current is not None:
            current[key] = value
    if not states:
        raise ValueError("Missing GLSTAT energy states")
    final = states[-1]
    peak_internal = max(abs(s["internal energy"]) for s in states)
    return {"final_per_model": final,
            "max_hourglass_over_peak_internal_percent": 100*max(abs(s["hourglass energy"]) for s in states)/peak_internal,
            "max_kinetic_energy": max(abs(s["kinetic energy"]) for s in states),
            "max_added_mass": max(abs(s.get("added mass", 0)) for s in states),
            "final_work_balance_percent": 100*(final["internal energy"]+final["hourglass energy"]-final["external work"])/final["external work"]}


def extract(run: Path):
    record = json.loads((run/"run.json").read_text(encoding="utf-8"))
    if not record.get("solver_evaluation", {}).get("parsed", {}).get("terminated_normally"):
        raise ValueError("Normally terminated native run required")
    digest = hashlib.sha256((run/"model.k").read_bytes()).hexdigest()
    if digest != record["input_sha256"]:
        raise ValueError("Input hash mismatch")
    spec = json.loads((run/"model.json").read_text(encoding="utf-8"))["spec"]
    _, metadata = build_keyword(spec)
    mesh = build_mesh(spec)
    bottom, top = set(mesh["sets"][102]), set(mesh["sets"][103])
    gauge = np.asarray(gauge_history(run/"nodout", bottom, top))
    support = np.asarray(force_history(run/"spcforc", bottom, "spcforc"))
    applied = np.asarray(force_history(run/"bndout", top, "bndout"))
    for data in (gauge, support, applied):
        if data.ndim != 2 or len(data) < 3 or not np.isfinite(data).all() or np.any(np.diff(data[:, 0]) <= 0):
            raise ValueError("Invalid native history")
    counts = {"nodout": len(gauge), "spcforc": len(support), "bndout": len(applied)}
    gauge, support, applied = align_histories(gauge, support, applied)
    factor = metadata["force_to_full_specimen"]
    load, upper_load = -support[:,1]*factor/1000, applied[:,1]*factor/1000
    extension = gauge[:,1]*1000
    target = spec["analysis"]["final_extension_m"]
    if abs(extension[-1]/1000-target) > 1e-8 or abs(gauge[-1,0]-target/1e-5) > .001:
        raise ValueError("Incomplete gauge motion")
    if load.max() <= 0 or np.any(np.diff(extension) < -1e-7):
        raise ValueError("Invalid tensile motion or force")
    balance = float(np.max(abs(load-upper_load))/load.max())
    if balance > .01:
        raise ValueError("End reaction imbalance exceeds 1% of peak")
    peak = int(np.argmax(load))
    p = PAPER[spec["specimen"]]
    metrics = {"specimen": spec["specimen"], "run_dir": str(run.resolve()), "run_id": record["run_id"],
               "input_sha256": digest, "solver_duration_s": record["duration_s"], "raw_history_counts": counts,
               "history_samples": len(gauge), "end_time_s": float(gauge[-1,0]), "final_extension_mm": float(extension[-1]),
               "force_to_full_specimen": factor, "peak_load_kN": float(load[peak]), "peak_extension_mm": float(extension[peak]),
               "final_load_kN": float(load[-1]), "peak_error_vs_table1_percent": float(100*(load[peak]/p["peak_kN"]-1)),
               "final_error_vs_table1_percent": float(100*(load[-1]/p["cutoff_kN"]-1)),
               "max_end_imbalance_over_peak_percent": balance*100, "energy": energy_audit(run/"glstat"),
               "reference_table1": p, "assumptions": metadata["assumptions"],
               "columns": ["time_s", "gauge_extension_mm", "bottom_load_kN", "top_load_kN"],
               "sources": {name: {"sha256": file_hash(run/name),
                                   "bytes": (run/name).stat().st_size} for name in ("model.k", "nodout", "spcforc", "bndout", "elout", "glstat", "d3hsp")}}
    return np.column_stack((gauge[:,0], extension, load, upper_load)), metrics


def write_results(run: Path, output: Path):
    rows, metrics = extract(run)
    output.mkdir(parents=True, exist_ok=False)
    with (output/"lsdyna_load_displacement.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(metrics["columns"])
        writer.writerows(rows)
    (output/"metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    m = write_results(args.run, args.output)
    print(json.dumps({k:m[k] for k in ("specimen", "peak_load_kN", "final_load_kN", "peak_error_vs_table1_percent", "energy")}, indent=2))


if __name__ == "__main__":
    main()
