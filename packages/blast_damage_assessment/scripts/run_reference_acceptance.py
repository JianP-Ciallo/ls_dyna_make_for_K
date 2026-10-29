"""Acceptance harness for the three current Phase 18 reference cases."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _PACKAGE_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from blast_damage_assessment import assess, capabilities
from blast_damage_assessment.canonical import sha256_json
from blast_damage_assessment.contracts import GateState
from blast_damage_assessment.adapters.contracts import (
    AdapterProbe,
    ArrayField,
    EntityKind,
    FieldAvailability,
    GeometryIndex,
    SolverQuality,
    StateChunk,
)
from blast_damage_assessment.errors import ContractError
from blast_damage_assessment.reporting import render_building_csv, render_ground_csv, render_html_report
from blast_damage_assessment.source_evidence import continuous_d3plot_series


GIB = 1024**3
MAX_RSS_BYTES = 2 * GIB
TIMEOUT_SECONDS = 300.0
ARTIFACT_NAMES = {
    "assessment_request.json",
    "assessment_result.json",
    "assessment_snapshot.json",
    "evidence_index.json",
    "rule_snapshot.json",
    "damage_report.html",
    "building_components.csv",
    "ground_regions.csv",
}
OWNERSHIP_MARKER = ".blast-damage-acceptance-owned"


class AcceptanceFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessOutcome:
    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float
    peak_rss_bytes: int
    timed_out: bool
    memory_exceeded: bool


def _windows_peak_rss(pid: int) -> int:
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    query_limited = 0x1000
    vm_read = 0x0010
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    handle = kernel32.OpenProcess(query_limited | vm_read, False, pid)
    if not handle:
        return 0
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return 0
        return int(counters.PeakWorkingSetSize)
    finally:
        kernel32.CloseHandle(handle)

def descendant_process_ids(root_pid: int, parents: Mapping[int, int]) -> set[int]:
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for process_id, parent_id in parents.items():
            if parent_id in descendants and process_id not in descendants:
                descendants.add(process_id)
                changed = True
    return descendants


def aggregate_process_tree_rss(
    root_pid: int,
    parents: Mapping[int, int],
    rss_reader: Callable[[int], int],
) -> int:
    return sum(max(0, int(rss_reader(process_id))) for process_id in descendant_process_ids(root_pid, parents))


def _windows_process_parents() -> dict[int, int]:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return {}
    parents: dict[int, int] = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        available = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while available:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            available = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def _linux_process_parents() -> dict[int, int]:
    parents: dict[int, int] = {}
    for status in Path("/proc").glob("[0-9]*/status"):
        try:
            process_id = int(status.parent.name)
            parent_line = next(line for line in status.read_text(encoding="ascii").splitlines() if line.startswith("PPid:"))
            parents[process_id] = int(parent_line.split()[1])
        except (OSError, StopIteration, ValueError):
            continue
    return parents



def _linux_peak_rss(pid: int) -> int:
    try:
        text = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    except OSError:
        return 0
    values: dict[str, int] = {}
    for line in text.splitlines():
        if line.startswith(("VmHWM:", "VmRSS:")):
            name, raw, *_ = line.split()
            values[name.rstrip(":")] = int(raw) * 1024
    return values.get("VmHWM", values.get("VmRSS", 0))


def peak_rss_bytes(pid: int) -> int:
    if os.name == "nt":
        parents = _windows_process_parents()
        return aggregate_process_tree_rss(pid, parents, _windows_peak_rss)
    if sys.platform.startswith("linux"):
        parents = _linux_process_parents()
        return aggregate_process_tree_rss(pid, parents, _linux_peak_rss)
    return 0


def process_tree_termination_order(
    root_pid: int,
    parents: Mapping[int, int],
) -> tuple[int, ...]:
    descendants = descendant_process_ids(root_pid, parents)
    depths = {root_pid: 0}
    changed = True
    while changed:
        changed = False
        for process_id in descendants:
            parent_id = parents.get(process_id)
            if process_id not in depths and parent_id in depths:
                depths[process_id] = depths[parent_id] + 1
                changed = True
    return tuple(
        sorted(
            (process_id for process_id in descendants if process_id != root_pid),
            key=lambda process_id: (-depths.get(process_id, 0), process_id),
        )
    )


def _terminate(process: object) -> None:
    parents = (
        _windows_process_parents()
        if os.name == "nt"
        else _linux_process_parents()
        if sys.platform.startswith("linux")
        else {}
    )
    for process_id in process_tree_termination_order(process.pid, parents):  # type: ignore[attr-defined]
        try:
            os.kill(process_id, signal.SIGTERM)
        except OSError:
            pass
    process.terminate()  # type: ignore[attr-defined]
    try:
        process.wait(timeout=5.0)  # type: ignore[attr-defined]
    except Exception:
        process.kill()  # type: ignore[attr-defined]
        process.wait(timeout=5.0)  # type: ignore[attr-defined]


def run_monitored(
    command: Sequence[str],
    *,
    timeout_s: float = TIMEOUT_SECONDS,
    max_rss_bytes: int = MAX_RSS_BYTES,
    popen_factory: Callable[..., object] = subprocess.Popen,
    rss_reader: Callable[[int], int] = peak_rss_bytes,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval: float = 0.05,
) -> ProcessOutcome:
    started = monotonic()
    process = popen_factory(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    peak = 0
    timed_out = False
    memory_exceeded = False
    while process.poll() is None:  # type: ignore[attr-defined]
        peak = max(peak, int(rss_reader(process.pid)))  # type: ignore[attr-defined]
        elapsed = monotonic() - started
        if peak > max_rss_bytes:
            memory_exceeded = True
            _terminate(process)
            break
        if elapsed > timeout_s:
            timed_out = True
            _terminate(process)
            break
        sleep(poll_interval)
    stdout, stderr = process.communicate()  # type: ignore[attr-defined]
    elapsed = monotonic() - started
    return ProcessOutcome(
        int(process.returncode),  # type: ignore[attr-defined]
        stdout,
        stderr,
        elapsed,
        peak,
        timed_out,
        memory_exceeded,
    )


def validate_process_outcome(outcome: ProcessOutcome) -> None:
    if outcome.timed_out:
        raise AcceptanceFailure(f"process timeout after {outcome.elapsed_seconds:.3f} s")
    if outcome.memory_exceeded:
        raise AcceptanceFailure(f"process peak RSS exceeded limit: {outcome.peak_rss_bytes} bytes")
    if outcome.returncode != 0:
        detail = outcome.stderr.decode("utf-8", errors="replace").strip()
        raise AcceptanceFailure(f"process exit code {outcome.returncode}: {detail}")
    if outcome.peak_rss_bytes <= 0:
        raise AcceptanceFailure("process peak RSS could not be measured")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def case_source_hashes(result_dir: Path, manifest: Path) -> dict[str, str]:
    files = [
        result_dir / name
        for name in ("model.k", "model.json", "run.json", "d3hsp", "glstat", "matsum", "dbfsi")
        if (result_dir / name).is_file()
    ]
    files.extend(continuous_d3plot_series(result_dir))
    files.append(manifest)
    return {
        ("manifest:" + path.name if path == manifest else path.name): _sha256_file(path)
        for path in files
    }


def compare_source_hashes(before: Mapping[str, str], after: Mapping[str, str]) -> None:
    if dict(before) != dict(after):
        raise AcceptanceFailure("source hash set changed during acceptance")


def ensure_nonformal(snapshot: Mapping[str, object]) -> None:
    for name in ("overall", "building", "ground"):
        subject = snapshot.get(name)
        if not isinstance(subject, Mapping):
            raise AcceptanceFailure(f"snapshot lacks {name} result")
        if subject.get("gate") == "formal":
            raise AcceptanceFailure(f"formal result is forbidden for current reference case: {name}")


def validate_artifact_references(output_dir: Path) -> None:
    envelope_path = output_dir / "assessment_result.json"
    try:
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceFailure(f"invalid assessment result envelope: {exc}") from exc
    artifacts = envelope.get("artifacts")
    if not isinstance(artifacts, dict):
        raise AcceptanceFailure("assessment result has no artifact references")
    for name, record in artifacts.items():
        if not isinstance(name, str) or not isinstance(record, dict):
            raise AcceptanceFailure("invalid artifact reference")
        path = output_dir / name
        if not path.is_file():
            raise AcceptanceFailure(f"referenced artifact is missing: {name}")
        if path.stat().st_size != record.get("size_bytes"):
            raise AcceptanceFailure(f"artifact size mismatch: {name}")
        if _sha256_file(path) != record.get("sha256"):
            raise AcceptanceFailure(f"artifact hash mismatch: {name}")


def cleanup_owned_output_root(output_root: Path, allowed_parent: Path) -> None:
    parent = allowed_parent.resolve(strict=True)
    root = output_root.resolve(strict=True)
    if root.parent != parent:
        raise AcceptanceFailure("output cleanup target is outside the allowed parent")
    if not (root / OWNERSHIP_MARKER).is_file():
        raise AcceptanceFailure("output cleanup ownership marker is missing")
    shutil.rmtree(root)
def _negative_geometry(*, missing_building: bool = False, missing_ground: bool = False) -> GeometryIndex:
    coordinates = np.asarray(
        [
            [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
            [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
            [2, 0, 0], [2, 0, 1], [2, 0, 2], [2, 0, 3], [2, 0, 4],
        ],
        dtype=float,
    )
    return GeometryIndex(
        np.arange(1, 14, dtype=np.int64),
        coordinates,
        {
            EntityKind.SOLID: np.array([100], dtype=np.int64),
            EntityKind.SHELL: np.array([], dtype=np.int64),
            EntityKind.BEAM: np.arange(200, 204, dtype=np.int64),
        },
        {
            EntityKind.SOLID: np.array([9999 if missing_ground else 8001], dtype=np.int64),
            EntityKind.SHELL: np.array([], dtype=np.int64),
            EntityKind.BEAM: np.full(4, 9999 if missing_building else 1001, dtype=np.int64),
        },
        {
            EntityKind.SOLID: np.array([[0, 1, 2, 3, 4, 5, 6, 7]], dtype=np.int64),
            EntityKind.SHELL: np.empty((0, 4), dtype=np.int64),
            EntityKind.BEAM: np.array(
                [[8, 9], [9, 10], [10, 11], [11, 12]], dtype=np.int64
            ),
        },
    )


def _negative_array_field(
    kind: EntityKind,
    entity_ids: np.ndarray,
    indexes: np.ndarray,
    values: np.ndarray,
    name: str,
    unit: str,
) -> ArrayField:
    data = np.asarray(values)
    return ArrayField(
        kind,
        entity_ids.copy(),
        indexes.copy(),
        data.copy(),
        unit,
        data.copy(),
        unit,
        "units.identity@1",
        name,
        name,
    )


class _NegativeAdapter:
    adapter_id = "negative_fixture"
    adapter_version = "1-test"

    def __init__(
        self,
        *,
        termination: str = "normal",
        final_time: float = 5.0,
        velocity_available: bool = True,
        unstable: bool = False,
        missing_building: bool = False,
        missing_ground: bool = False,
        mutate_source: bool = False,
    ):
        self.geometry = _negative_geometry(
            missing_building=missing_building,
            missing_ground=missing_ground,
        )
        self.termination = termination
        self.final_time = final_time
        self.velocity_available = velocity_available
        self.unstable = unstable
        self.mutate_source = mutate_source
        self._mutated = False
        self.times = np.arange(6.0)

    def probe(self, result_dir: Path) -> AdapterProbe:
        available = FieldAvailability(True, None)
        missing = FieldAvailability(False, "not emitted")
        return AdapterProbe(
            self.adapter_id,
            self.adapter_version,
            self.geometry,
            6,
            {
                "node_displacement": available,
                "node_velocity": available if self.velocity_available else missing,
                "solid_stress": missing,
                "solid_effective_plastic_strain": missing,
                "solid_history_variables": missing,
                "solid_is_alive": available,
                "shell_stress": missing,
                "shell_effective_plastic_strain": missing,
                "shell_history_variables": missing,
                "shell_is_alive": missing,
                "shell_strain": missing,
                "beam_axial_force": missing,
                "beam_shear_force": missing,
                "beam_is_alive": available,
            },
            SolverQuality(
                self.termination,
                5.0,
                5.0,
                self.final_time,
                0.0,
            ),
        )

    def iter_state_chunks(self, result_dir: Path, chunk_size: int):
        if self.mutate_source and not self._mutated:
            (result_dir / "model.k").write_text("*KEYWORD\n$ changed\n*END\n", encoding="utf-8")
            self._mutated = True
        displacement = np.zeros((6, self.geometry.node_ids.size, 3), dtype=float)
        velocity = np.ones_like(displacement) if self.unstable else np.zeros_like(displacement)
        solid_alive = np.ones((6, 1), dtype=bool)
        beam_alive = np.ones((6, 4), dtype=bool)
        for start in range(0, 6, chunk_size):
            stop = min(start + chunk_size, 6)
            indexes = np.arange(start, stop, dtype=np.int64)
            fields = {
                "node_displacement_m": _negative_array_field(
                    EntityKind.NODE,
                    self.geometry.node_ids,
                    indexes,
                    displacement[start:stop],
                    "node_displacement",
                    "m",
                ),
                "solid_is_alive": _negative_array_field(
                    EntityKind.SOLID,
                    self.geometry.element_ids[EntityKind.SOLID],
                    indexes,
                    solid_alive[start:stop],
                    "element_solid_is_alive",
                    "1",
                ),
                "beam_is_alive": _negative_array_field(
                    EntityKind.BEAM,
                    self.geometry.element_ids[EntityKind.BEAM],
                    indexes,
                    beam_alive[start:stop],
                    "element_beam_is_alive",
                    "1",
                ),
            }
            if self.velocity_available:
                fields["node_velocity_m_per_s"] = _negative_array_field(
                    EntityKind.NODE,
                    self.geometry.node_ids,
                    indexes,
                    velocity[start:stop],
                    "node_velocity",
                    "m/s",
                )
            yield StateChunk(self.times[start:stop].copy(), fields)


def _write_negative_case(
    fixture_root: Path,
    name: str,
    *,
    unit_system: str = "SI_m_s_kg_N_Pa",
) -> tuple[Path, dict[str, object]]:
    root = fixture_root / name
    result_dir = root / "result"
    result_dir.mkdir(parents=True)
    semantics = {
        "schema_version": "blast_damage.model_semantics@1",
        "unit_system": unit_system,
        "axes": {"vertical": "z", "horizontal": ["x", "y"]},
        "blast_center_m": [0.5, 0.5, 2.0],
        "engineering_validated": False,
        "requires_project_review": True,
        "building": {
            "zones": [],
            "components": [{
                "id": "column", "role": "column", "part_ids": [1001],
                "material_ids": [4], "importance_class": "primary",
                "primary_load_path": True,
            }],
        },
        "ground": {
            "part_ids": [8001], "material_ids": [7],
            "surface": {"axis": "z", "direction": "max"},
        },
        "materials": [
            {"material_id": 4, "model": "elastic", "engineering_validated": False},
            {"material_id": 7, "model": "elastic", "engineering_validated": False},
        ],
    }
    manifest = result_dir / "assessment_semantics.json"
    manifest.write_text(json.dumps(semantics), encoding="utf-8")
    for filename, payload in {
        "model.k": "*KEYWORD\n*END\n",
        "model.json": "{}",
        "run.json": '{"status":"completed"}',
        "d3hsp": "normal termination\nproblem time = 5.0\ntermination time.... 5.0\n",
        "d3plot": "generated negative fixture",
    }.items():
        (result_dir / filename).write_text(payload, encoding="utf-8")
    return result_dir, _request(result_dir, manifest, root / "output", name, 2)




def _record_negative(name: str, check: Callable[[], None]) -> dict[str, object]:
    try:
        check()
    except Exception as exc:
        return {"passed": False, "detail": str(exc)}
    return {"passed": True}


def _require_issue(decision, state: GateState, code: str) -> None:
    if decision.state is not state or not any(issue.code == code for issue in decision.issues):
        raise AcceptanceFailure(f"expected {state.value}/{code}, got {decision.state.value}")


def run_negative_checks(acceptance_root: Path) -> dict[str, dict[str, object]]:
    fixture_root = acceptance_root / "negative-fixtures"
    fixture_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, object]] = {}

    def require_result_issue(
        name: str,
        adapter: _NegativeAdapter,
        state: GateState,
        code: str,
        *,
        unit_system: str = "SI_m_s_kg_N_Pa",
    ) -> None:
        _, request = _write_negative_case(
            fixture_root, name, unit_system=unit_system
        )
        result = assess(request, adapter=adapter)
        issues = (*result.blockers, *result.review_items)
        if result.gate is not state or not any(issue.code == code for issue in issues):
            raise AcceptanceFailure(
                f"expected full API result {state.value}/{code}, got {result.gate.value}"
            )

    def d3plot_gap() -> None:
        result_dir, request = _write_negative_case(fixture_root, "d3plot-gap")
        (result_dir / "d3plot02").write_bytes(b"gap")
        try:
            assess(request, adapter=_NegativeAdapter())
        except ContractError as exc:
            if "gap" in str(exc):
                return
            raise
        raise AcceptanceFailure("d3plot gap was accepted by the public API")

    results["d3plot_gap"] = _record_negative("d3plot_gap", d3plot_gap)

    def changed_hash() -> None:
        _, request = _write_negative_case(fixture_root, "changed-hash")
        try:
            assess(request, adapter=_NegativeAdapter(mutate_source=True))
        except Exception as exc:
            if "changed" in str(exc).lower() or "hash" in str(exc).lower():
                return
            raise
        raise AcceptanceFailure("changed source hash was accepted by the public API")

    results["changed_hash"] = _record_negative("changed_hash", changed_hash)
    results["abnormal_termination"] = _record_negative(
        "abnormal_termination",
        lambda: require_result_issue(
            "abnormal-termination",
            _NegativeAdapter(termination="abnormal"),
            GateState.BLOCKED,
            "solver.termination",
        ),
    )
    results["insufficient_final_time"] = _record_negative(
        "insufficient_final_time",
        lambda: require_result_issue(
            "insufficient-final-time",
            _NegativeAdapter(final_time=4.0),
            GateState.BLOCKED,
            "solver.coverage",
        ),
    )
    results["missing_units"] = _record_negative(
        "missing_units",
        lambda: require_result_issue(
            "missing-units",
            _NegativeAdapter(),
            GateState.BLOCKED,
            "semantics.units",
            unit_system="unknown",
        ),
    )
    results["missing_building_identity"] = _record_negative(
        "missing_building_identity",
        lambda: require_result_issue(
            "missing-building-identity",
            _NegativeAdapter(missing_building=True),
            GateState.BLOCKED,
            "building.identity",
        ),
    )
    results["missing_ground_identity"] = _record_negative(
        "missing_ground_identity",
        lambda: require_result_issue(
            "missing-ground-identity",
            _NegativeAdapter(missing_ground=True),
            GateState.BLOCKED,
            "ground.identity",
        ),
    )

    def unsupported_schema() -> None:
        _, request = _write_negative_case(fixture_root, "unsupported-schema")
        request["schema_version"] = "blast_damage.assessment_request@2"
        try:
            assess(request, adapter=_NegativeAdapter())
        except ContractError as exc:
            if "unsupported" in str(exc):
                return
            raise
        raise AcceptanceFailure("unsupported request major was accepted by the public API")

    results["unsupported_request_major"] = _record_negative("unsupported_request_major", unsupported_schema)
    results["missing_velocity"] = _record_negative(
        "missing_velocity",
        lambda: require_result_issue(
            "missing-velocity",
            _NegativeAdapter(velocity_available=False),
            GateState.PROVISIONAL,
            "ground.velocity_missing",
        ),
    )

    def unstable_surface() -> None:
        _, request = _write_negative_case(fixture_root, "unstable-surface")
        result = assess(request, adapter=_NegativeAdapter(unstable=True))
        snapshot = json.loads(
            (
                Path(request["output_dir"])
                / "assessment_snapshot.json"
            ).read_text(encoding="utf-8")
        )
        stability = snapshot["ground"]["stability"]
        if (
            result.gate is GateState.BLOCKED
            or stability["stable"]
            or stability["shape_term"] != "instantaneous_final_shape"
            or "tail_speed" not in stability["failed_criteria"]
        ):
            raise AcceptanceFailure("non-stabilized surface passed the full API as residual")

    results["non_stabilized_surface"] = _record_negative("non_stabilized_surface", unstable_surface)
    return results


def _request(
    result_dir: Path,
    manifest: Path,
    output_dir: Path,
    case_id: str,
    chunk_size: int,
) -> dict[str, object]:
    return {
        "schema_version": "blast_damage.assessment_request@1",
        "project_id": "phase18-reference-acceptance",
        "case_id": case_id,
        "result_dir": str(result_dir),
        "semantic_manifest": {
            "path": str(manifest),
            "sha256": _sha256_file(manifest),
        },
        "building_rule_pack": "building_research_reference@1",
        "ground_rule_pack": "ground_research_reference@1",
        "output_dir": str(output_dir),
        "state_chunk_size": chunk_size,
    }


def _load_snapshot(output_dir: Path) -> dict[str, object]:
    if {path.name for path in output_dir.iterdir() if path.is_file()} != ARTIFACT_NAMES:
        raise AcceptanceFailure(f"unexpected artifact set in {output_dir}")
    validate_artifact_references(output_dir)
    snapshot = json.loads((output_dir / "assessment_snapshot.json").read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        raise AcceptanceFailure("assessment snapshot root is not an object")
    fingerprint = snapshot.get("assessment_fingerprint")
    base = {key: value for key, value in snapshot.items() if key != "assessment_fingerprint"}
    if fingerprint != sha256_json(base):
        raise AcceptanceFailure("assessment snapshot fingerprint mismatch")
    ensure_nonformal(snapshot)
    if any(snapshot[name].get("gate") != "provisional" for name in ("overall", "building", "ground")):  # type: ignore[union-attr]
        raise AcceptanceFailure("current reference subjects must all be provisional")
    evidence = json.loads((output_dir / "evidence_index.json").read_text(encoding="utf-8"))
    nodes = {node["id"] for node in evidence.get("nodes", [])}
    if not nodes or any(not set(node.get("dependencies", ())) <= nodes for node in evidence.get("nodes", [])):
        raise AcceptanceFailure("evidence graph is not closed")
    return snapshot


def _validate_report_consistency(output_dir: Path, snapshot: Mapping[str, object]) -> None:
    if (output_dir / "building_components.csv").read_bytes() != render_building_csv(snapshot):
        raise AcceptanceFailure("building CSV severity or fields disagree with snapshot")
    if (output_dir / "ground_regions.csv").read_bytes() != render_ground_csv(snapshot):
        raise AcceptanceFailure("ground CSV severity or fields disagree with snapshot")
    expected_html = render_html_report(snapshot).encode("utf-8")
    if (output_dir / "damage_report.html").read_bytes() != expected_html:
        raise AcceptanceFailure("HTML report disagrees with snapshot")


    building = snapshot["building"]
    ground = snapshot["ground"]
    with (output_dir / "building_components.csv").open("r", encoding="utf-8-sig", newline="") as stream:
        building_rows = list(csv.DictReader(stream))
    with (output_dir / "ground_regions.csv").open("r", encoding="utf-8-sig", newline="") as stream:
        ground_rows = list(csv.DictReader(stream))
    if len(building_rows) != len(building["components"]):  # type: ignore[index]
        raise AcceptanceFailure("building CSV row count disagrees with snapshot")
    if len(ground_rows) != len(ground["subratings"]):  # type: ignore[index]
        raise AcceptanceFailure("ground CSV row count disagrees with snapshot")
    html = (output_dir / "damage_report.html").read_text(encoding="utf-8")
    if str(snapshot["overall"]["gate"]) not in html:  # type: ignore[index]
        raise AcceptanceFailure("HTML gate disagrees with snapshot")
    stability = ground.get("stability")  # type: ignore[union-attr]
    if isinstance(stability, dict) and not stability.get("stable"):
        if "瞬时末态" not in html or "残余爆坑" in html or "最终沉降" in html:
            raise AcceptanceFailure("unstable ground uses forbidden residual wording")


def validate_solver_times(final_time: float, problem_time: float, target: float) -> None:
    if not all(math.isfinite(value) for value in (final_time, problem_time, target)):
        raise AcceptanceFailure("solver times must be finite")
    if problem_time <= 0:
        raise AcceptanceFailure("d3hsp problem time must be positive")
    tolerance = max(1e-12, 5e-5 * abs(problem_time))
    if abs(final_time - problem_time) > tolerance:
        raise AcceptanceFailure("final d3plot time differs from d3hsp problem time")
    if target <= 0 or final_time / target < 0.99:
        raise AcceptanceFailure("final d3plot time does not cover run termination target")

def _validate_case_snapshot(
    snapshot: Mapping[str, object],
    manifest_payload: Mapping[str, object],
    run_payload: Mapping[str, object],
) -> None:
    adapter = snapshot["adapter"]
    geometry = adapter["geometry"]  # type: ignore[index]
    if geometry["node_count"] != manifest_payload.get("total_node_count"):  # type: ignore[index]
        raise AcceptanceFailure("manifest and d3plot node counts differ")
    if geometry["element_count"] != manifest_payload.get("total_element_count"):  # type: ignore[index]
        raise AcceptanceFailure("manifest and d3plot element counts differ")
    part_rows = manifest_payload.get("part_ids")
    if not isinstance(part_rows, list):
        raise AcceptanceFailure("manifest Part identity list is unavailable")
    valid_part_rows = [
        row
        for row in part_rows
        if isinstance(row, list)
        and len(row) == 2
        and isinstance(row[0], str)
        and isinstance(row[1], int)
    ]
    if len(valid_part_rows) != len(part_rows):
        raise AcceptanceFailure("manifest Part identity list is malformed")
    manifest_part_ids = {row[1] for row in valid_part_rows}
    implicit_volume_part_ids = {
        row[1] for row in valid_part_rows if row[0] == "tnt_high_explosive"
    }
    result_part_rows = geometry.get("part_ids")  # type: ignore[union-attr]
    if not isinstance(result_part_rows, list) or any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in result_part_rows
    ):
        raise AcceptanceFailure("d3plot Part identity list is unavailable")
    result_part_ids = set(result_part_rows)
    if len(result_part_ids) != len(result_part_rows) or geometry["part_count"] != len(result_part_ids):  # type: ignore[index]
        raise AcceptanceFailure("d3plot Part count or identity list is inconsistent")
    if result_part_ids - manifest_part_ids:
        raise AcceptanceFailure("d3plot contains an undeclared Part identity")
    if (manifest_part_ids - result_part_ids) - implicit_volume_part_ids:
        raise AcceptanceFailure("manifest finite-element Part is absent from d3plot")
    quality = adapter["solver_quality"]  # type: ignore[index]
    final_time = float(quality["final_state_time"])  # type: ignore[index]
    problem_time = float(quality["problem_time"])  # type: ignore[index]
    static = run_payload.get("static_validation", {})
    target = float(static.get("termination_time_s", 0.0)) if isinstance(static, dict) else 0.0
    validate_solver_times(final_time, problem_time, target)
    missing = set(snapshot.get("missing_fields", []))
    fields = adapter.get("fields", {})  # type: ignore[union-attr]
    expected_missing = {name for name, available in fields.items() if not available}
    if missing != expected_missing:
        raise AcceptanceFailure("missing fields are not represented as unavailable")


def _run_cli(request_path: Path) -> tuple[ProcessOutcome, dict[str, object]]:
    outcome = run_monitored(
        [sys.executable, "-m", "blast_damage_assessment", "evaluate", "--request", str(request_path)],
    )
    validate_process_outcome(outcome)
    try:
        envelope = json.loads(outcome.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceFailure(f"CLI returned invalid JSON: {exc}") from exc
    return outcome, envelope


_API_RUNNER = (
    "import json,sys;"
    "from pathlib import Path;"
    "from blast_damage_assessment import assess;"
    "request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));"
    "result=assess(request);"
    "print(json.dumps({"
    "'assessment_id':result.assessment_id,"
    "'assessment_fingerprint':result.assessment_fingerprint,"
    "'gate':result.gate.value,"
    "'severity':result.severity"
    "},sort_keys=True))"
)


def _run_api(request_path: Path) -> tuple[ProcessOutcome, dict[str, object]]:
    outcome = run_monitored(
        [sys.executable, "-c", _API_RUNNER, str(request_path)],
    )
    validate_process_outcome(outcome)
    try:
        envelope = json.loads(outcome.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceFailure(f"API runner returned invalid JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise AcceptanceFailure("API runner envelope is not an object")
    return outcome, envelope


def prepare_output_parent(output: Path) -> None:
    if output.exists():
        raise AcceptanceFailure(f"assessment output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)


def run_reference_case(
    label: str,
    result_dir: Path,
    manifest_name: str,
    output_root: Path,
) -> dict[str, object]:
    result_dir = result_dir.resolve(strict=True)
    manifest = (result_dir.parents[1] / manifest_name).resolve(strict=True)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    run_payload = json.loads((result_dir / "run.json").read_text(encoding="utf-8"))
    before = case_source_hashes(result_dir, manifest)
    fingerprints: dict[str, str] = {}
    process_records: dict[str, object] = {}
    snapshots: dict[str, dict[str, object]] = {}
    for chunk_size in (1, 8):
        output = output_root / label / f"chunk-{chunk_size}"
        prepare_output_parent(output)
        request = _request(result_dir, manifest, output, label, chunk_size)
        request_path = output_root / "requests" / f"{label}-chunk-{chunk_size}.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        outcome, envelope = _run_cli(request_path)
        snapshot = _load_snapshot(output)
        _validate_case_snapshot(snapshot, manifest_payload, run_payload)
        _validate_report_consistency(output, snapshot)
        fingerprints[f"chunk_{chunk_size}"] = str(envelope["assessment_fingerprint"])
        snapshots[f"chunk_{chunk_size}"] = snapshot
        process_records[f"chunk_{chunk_size}"] = {
            "runtime_seconds": outcome.elapsed_seconds,
            "peak_rss_bytes": outcome.peak_rss_bytes,
        }
    api_output = output_root / label / "api"
    prepare_output_parent(api_output)
    api_request = _request(result_dir, manifest, api_output, label, 8)
    api_request_path = output_root / "requests" / f"{label}-api.json"
    api_request_path.write_text(json.dumps(api_request, ensure_ascii=False, indent=2), encoding="utf-8")
    api_outcome, api_envelope = _run_api(api_request_path)
    api_snapshot = _load_snapshot(api_output)
    _validate_case_snapshot(api_snapshot, manifest_payload, run_payload)
    _validate_report_consistency(api_output, api_snapshot)
    fingerprints["api"] = str(api_envelope["assessment_fingerprint"])
    process_records["api"] = {
        "runtime_seconds": api_outcome.elapsed_seconds,
        "peak_rss_bytes": api_outcome.peak_rss_bytes,
    }
    if len(set(fingerprints.values())) != 1:
        raise AcceptanceFailure(f"chunk/API fingerprints differ for {label}: {fingerprints}")
    if snapshots["chunk_1"] != snapshots["chunk_8"] or snapshots["chunk_8"] != api_snapshot:
        raise AcceptanceFailure(f"deterministic snapshots differ for {label}")
    after = case_source_hashes(result_dir, manifest)
    compare_source_hashes(before, after)
    rule_payload = json.loads((api_output / "rule_snapshot.json").read_text(encoding="utf-8"))
    return {
        "result_dir": str(result_dir),
        "manifest": str(manifest),
        "source_hashes": before,
        "source_immutability_check": True,
        "fingerprint": fingerprints["api"],
        "gate": api_snapshot["overall"]["gate"],  # type: ignore[index]
        "severity": api_snapshot["overall"]["severity"],  # type: ignore[index]
        "building_gate": api_snapshot["building"]["gate"],  # type: ignore[index]
        "building_severity": api_snapshot["building"]["severity"],  # type: ignore[index]
        "ground_gate": api_snapshot["ground"]["gate"],  # type: ignore[index]
        "ground_severity": api_snapshot["ground"]["severity"],  # type: ignore[index]
        "missing_fields": api_snapshot["missing_fields"],
        "runtime_seconds": max(record["runtime_seconds"] for record in process_records.values()),  # type: ignore[index]
        "peak_rss_bytes": max(record["peak_rss_bytes"] for record in process_records.values()),  # type: ignore[index]
        "process_runs": process_records,
        "api_runtime_seconds": api_outcome.elapsed_seconds,
        "api_peak_rss_bytes": api_outcome.peak_rss_bytes,
        "rule_hashes": {item["subject"]: item["sha256"] for item in rule_payload["rule_packs"]},
        "checks": {
            "geometry_counts": True,
            "final_time": True,
            "unavailable_fields": True,
            "nonformal": True,
            "chunk_fingerprint": True,
            "api_cli_fingerprint": True,
            "report_consistency": True,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commercial", type=Path, required=True)
    parser.add_argument("--residential", type=Path, required=True)
    parser.add_argument("--subway", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest-name", default="manifest.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    output_root = arguments.output_root.absolute()
    if output_root.exists():
        raise AcceptanceFailure(f"acceptance output root already exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir()
    (output_root / OWNERSHIP_MARKER).write_text("created by blast damage acceptance harness\n", encoding="utf-8")
    started = time.monotonic()
    summary: dict[str, object] = {
        "schema_version": "blast_damage.reference_acceptance@1",
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "capabilities": capabilities(),
        "limits": {"timeout_seconds": TIMEOUT_SECONDS, "max_rss_bytes": MAX_RSS_BYTES},
        "cases": {},
    }
    try:
        for label, path in (
            ("commercial", arguments.commercial),
            ("residential", arguments.residential),
            ("subway", arguments.subway),
        ):
            summary["cases"][label] = run_reference_case(  # type: ignore[index]
                label, path, arguments.manifest_name, output_root
            )
        negative = run_negative_checks(output_root)
        if not all(item["passed"] for item in negative.values()):
            raise AcceptanceFailure("one or more negative acceptance checks failed")
        summary["negative_tests"] = negative
        summary["status"] = "passed"
    except Exception as exc:
        summary["status"] = "failed"
        summary["failure"] = str(exc)
        raise
    finally:
        summary["duration_seconds"] = time.monotonic() - started
        summary["completed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (output_root / "acceptance_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    print(json.dumps({"status": summary["status"], "summary": str(output_root / "acceptance_summary.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
