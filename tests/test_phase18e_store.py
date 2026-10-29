from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import multiprocessing
import subprocess
import stat
import threading
import time
from types import MappingProxyType

import pytest

from lsprepost_mcp.refined_blast.contracts import (
    RefinedBlastProject,
    ScenarioDraft,
    normalize_refined_blast_project,
)
from lsprepost_mcp.refined_blast.store import (
    DraftConflictError,
    RefinedBlastStore,
    derive_invalidation,
)
import lsprepost_mcp.refined_blast.store as store_module


def minimal_project() -> RefinedBlastProject:
    return normalize_refined_blast_project(
        {
            "schema_version": "refined_building_blast@1",
            "project_id": "project-1",
            "building_reference": {"asset_id": "building-1"},
            "building_artifact_fingerprint": "a" * 64,
            "preset_reference": "none",
            "preset_version": "1",
            "project_overrides": {},
            "expert_extensions": {},
            "scenario_set": [
                {
                    "scenario_id": "scenario-1",
                    "scenario_kind": "external",
                    "building_placement": {},
                    "support_and_ground": {},
                    "load_provider": {
                        "provider_id": "lbe_segment",
                        "provider_input": {
                            "schema_version": "lbe_segment@1", "unit_system": "SI_m_s_kg_N_Pa",
                            "source": {"schema_version": "lbe_segment.source@1", "source_id": "charge-1", "position_m": [-1.0, 3.0, 1.5], "direction_unit_vector": [1.0, 0.0, 0.0], "maximum_range_m": 20.0},
                            "selection": {"schema_version": "lbe_segment.selection@1", "surface_categories": ["exterior_surfaces"], "occlusion_policy": "none", "user_surface_ids": []},
                            "load": {"schema_version": "lbe_segment.load@1", "peak_pressure_pa": 250000.0, "positive_phase_duration_s": 0.02},
                            "budgets": {"schema_version": "lbe_segment.budgets@1", "max_surface_count": 10000, "max_total_area_m2": 100000.0},
                        },
                    },
                    "blast_source": {},
                    "fluid_domain": {},
                    "boundaries": {},
                    "interactions": {},
                    "solver_controls": {},
                    "output_requests": {},
                    "resource_versions": {},
                    "acknowledged_warning_ids": [],
                }
            ],
            "confirmation_records": [],
            "provenance": {},
            "created_at": "2026-08-11T00:00:00Z",
            "updated_at": "2026-08-11T00:00:00Z",
        }
    )


def changed_kind(project: RefinedBlastProject) -> ScenarioDraft:
    return replace(project.scenario_set[0], scenario_kind="internal")


def with_output_request(project: RefinedBlastProject) -> RefinedBlastProject:
    """Model an already-normalized future output contract without changing Task 1."""

    draft = replace(
        project.scenario_set[0],
        output_requests=MappingProxyType({"history": "nodout"}),
    )
    return replace(project, scenario_set=(draft,))


def with_provider(project: RefinedBlastProject) -> RefinedBlastProject:
    provider = store_module._json_value(project.scenario_set[0].load_provider)
    assert isinstance(provider, dict)
    provider_input = provider["provider_input"]
    assert isinstance(provider_input, dict)
    load = provider_input["load"]
    assert isinstance(load, dict)
    load["peak_pressure_pa"] = 300000.0
    draft = replace(
        project.scenario_set[0],
        load_provider=MappingProxyType(provider),
    )
    return replace(project, scenario_set=(draft,))


def _process_save(root: str, gate: object, results: object) -> None:
    gate.wait()
    try:
        RefinedBlastStore(Path(root)).save_draft("project-1", changed_kind(minimal_project()), 1)
        results.put("success")
    except DraftConflictError:
        results.put("conflict")
    except Exception as exc:
        results.put(type(exc).__name__)


def _process_commit(root: str, gate: object, results: object) -> None:
    gate.wait()
    try:
        RefinedBlastStore(Path(root)).commit_generated_package(
            "project-1", "scenario-1", {"solver_ready": False}, 1
        )
        results.put("success")
    except DraftConflictError:
        results.put("conflict")
    except Exception as exc:
        results.put(type(exc).__name__)


def _process_hold_project_transaction(
    root: str, project_id: str, entered: object, release: object
) -> None:
    store = RefinedBlastStore(Path(root))
    with store.project_transaction(project_id):
        entered.set()
        if not release.wait(timeout=10):
            raise TimeoutError("project transaction release was not signalled")


def _process_acquire_project_transaction(
    root: str, project_id: str, started: object, acquired: object
) -> None:
    started.set()
    with RefinedBlastStore(Path(root)).project_transaction(project_id):
        acquired.set()


def test_scenario_only_change_preserves_building_cache(tmp_path: Path):
    store = RefinedBlastStore(tmp_path)
    first = store.create(minimal_project())

    second = store.save_draft(first.project_id, changed_kind(first.project), expected_revision=1)

    assert second.revision == 2
    assert second.fingerprints["building"] == first.fingerprints["building"]
    assert second.invalidation.building is False
    assert second.invalidation.scenario is True
    assert second.invalidation.results is True


def test_store_round_trips_closed_module_configuration_from_the_draft(tmp_path: Path):
    project = minimal_project()
    raw = {
        "scenario_id": "scenario-1",
        "scenario_kind": "external",
        "building_placement": {
            "schema_version": "refined_blast.placement@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "building_count": 1,
            "translation_m": [0.0, 0.0, 0.0],
            "budgets": {"schema_version": "refined_blast.module_budgets@1", "max_new_nodes": 100_000, "max_new_elements": 100_000},
        },
        "support_and_ground": {
            "schema_version": "refined_blast.support_ground@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "support_face_ids": ["face:foundation:1"],
            "coupling_semantics": "tied",
            "budgets": {"schema_version": "refined_blast.module_budgets@1", "max_new_nodes": 100_000, "max_new_elements": 100_000},
        },
        "load_provider": store_module._json_value(project.scenario_set[0].load_provider),
        "blast_source": {
            "schema_version": "refined_blast.blast_source@1", "unit_system": "SI_m_s_kg_N_Pa",
            "source_declared_id": "charge:source-1", "source_space_id": "exterior",
            "budgets": {"schema_version": "refined_blast.module_budgets@1", "max_new_nodes": 100_000, "max_new_elements": 100_000},
        },
        "fluid_domain": {
            "schema_version": "refined_blast.fluid_domain@1", "unit_system": "SI_m_s_kg_N_Pa",
            "source_space_id": "exterior", "opening_states": {}, "external_buffer_m": 2.0,
            "budgets": {"schema_version": "refined_blast.module_budgets@1", "max_new_nodes": 100_000, "max_new_elements": 100_000},
        },
        "boundaries": {
            "schema_version": "refined_blast.boundaries@1", "unit_system": "SI_m_s_kg_N_Pa",
            "assignments": [{"boundary_id": "outflow-1", "face_id": "face:exterior:1", "boundary_type": "non_reflecting"}],
            "budgets": {"schema_version": "refined_blast.module_budgets@1", "max_new_nodes": 100_000, "max_new_elements": 100_000},
        },
        "interactions": {
            "schema_version": "refined_blast.interactions@1", "unit_system": "SI_m_s_kg_N_Pa",
            "pairs": [{"interaction_id": "fsi-1", "interaction_type": "fsi_candidate", "source_id": "fluid:scenario-1", "target_id": "building:scenario-1"}],
            "budgets": {"schema_version": "refined_blast.module_budgets@1", "max_new_nodes": 100_000, "max_new_elements": 100_000},
        },
        "solver_controls": {},
        "output_requests": {},
        "resource_versions": {},
        "acknowledged_warning_ids": [],
    }
    draft = normalize_refined_blast_project(
        {**store_module._project_to_raw(project), "scenario_set": [raw]}
    ).scenario_set[0]
    store = RefinedBlastStore(tmp_path)
    first = store.create(project)
    second = store.save_draft(first.project_id, draft, expected_revision=1)
    persisted = store.load_project(first.project_id).project.scenario_set[0]
    assert persisted.building_placement["translation_m"] == (0.0, 0.0, 0.0)
    for field in (
        "building_placement", "support_and_ground", "blast_source",
        "fluid_domain", "boundaries", "interactions",
    ):
        assert getattr(persisted, field) == getattr(second.project.scenario_set[0], field)


def test_store_round_trips_imported_pressure_source_space_and_fingerprint(tmp_path: Path):
    raw_project = store_module._project_to_raw(minimal_project())
    raw_project["scenario_set"][0]["load_provider"] = {
        "provider_id": "imported_pressure_history",
        "provider_input": {
            "schema_version": "imported_pressure_history@2",
            "unit_system": "SI_m_s_kg_N_Pa",
            "source": {
                "schema_version": "imported_pressure_history.source@2",
                "source_id": "history-1", "source_name": "test-history",
                "source_space_id": "exterior", "form": "structured_rows",
                "rows": [[0.0, 0.0], [0.1, 200000.0]],
            },
            "units": {"schema_version": "imported_pressure_history.units@1", "time_unit": "s", "pressure_unit": "Pa"},
            "curve": {"schema_version": "imported_pressure_history.curve@1", "interpolation": "linear", "scale": 1.0},
            "mapping": {"schema_version": "imported_pressure_history.mapping@1", "surface_category": "exterior_surfaces", "target_face_ids": []},
            "budgets": {"schema_version": "imported_pressure_history.budgets@1", "max_input_bytes": 4096, "max_row_count": 100, "max_target_surface_count": 1000},
        },
    }
    project = normalize_refined_blast_project(raw_project)
    created = RefinedBlastStore(tmp_path).create(project)
    loaded = RefinedBlastStore(tmp_path).load_project(created.project_id)

    source = loaded.project.scenario_set[0].load_provider["provider_input"]["source"]
    assert source["source_space_id"] == "exterior"
    assert loaded.fingerprints["provider"] == created.fingerprints["provider"]


def test_output_only_change_invalidates_only_output_downstream_artifacts():
    previous = minimal_project()

    invalidation = derive_invalidation(previous, with_output_request(previous))

    assert invalidation.building is False
    assert invalidation.scenario is False
    assert invalidation.output_requests is True
    assert invalidation.assembly is True
    assert invalidation.preview is False
    assert invalidation.results is True


def test_provider_only_change_keeps_unchanged_preview_fingerprint_valid(tmp_path: Path):
    previous = minimal_project()
    current = with_provider(previous)
    before = RefinedBlastStore(tmp_path / "before").create(previous)
    after = RefinedBlastStore(tmp_path / "after").create(current)

    invalidation = derive_invalidation(previous, current)

    assert before.fingerprints["provider"] != after.fingerprints["provider"]
    assert before.fingerprints["preview"] == after.fingerprints["preview"]
    assert invalidation.provider is True
    assert invalidation.preview is False
    assert invalidation.assembly is True
    assert invalidation.results is True


def test_building_change_invalidates_all_dependents():
    previous = minimal_project()
    current = replace(previous, building_artifact_fingerprint="b" * 64)

    invalidation = derive_invalidation(previous, current)

    assert invalidation.building is True
    assert invalidation.scenario is True
    assert invalidation.provider is True
    assert invalidation.assembly is True
    assert invalidation.preview is True
    assert invalidation.results is True


def test_stale_revision_does_not_overwrite_current_snapshot(tmp_path: Path):
    store = RefinedBlastStore(tmp_path)
    first = store.create(minimal_project())
    second = store.save_draft(first.project_id, changed_kind(first.project), expected_revision=1)

    with pytest.raises(DraftConflictError, match="expected revision 1"):
        store.save_draft(first.project_id, first.project.scenario_set[0], expected_revision=1)

    loaded = store.load_project(first.project_id)
    assert loaded.revision == second.revision == 2
    assert loaded.project.scenario_set[0].scenario_kind == "internal"


def test_concurrent_draft_saves_share_a_project_wide_compare_and_swap(tmp_path: Path):
    first = RefinedBlastStore(tmp_path).create(minimal_project())
    start = threading.Barrier(16)

    def save_once(_: int) -> object:
        start.wait()
        try:
            return RefinedBlastStore(tmp_path).save_draft(
                first.project_id, changed_kind(first.project), expected_revision=1
            )
        except Exception as exc:  # The assertion exercises the public error contract.
            return exc

    with ThreadPoolExecutor(max_workers=16) as executor:
        outcomes = list(executor.map(save_once, range(16)))

    successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(successes) == 1
    assert all(isinstance(outcome, DraftConflictError) for outcome in failures)
    assert RefinedBlastStore(tmp_path).load_project(first.project_id).revision == 2


def test_project_transaction_is_reentrant_for_draft_and_generated_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    acquisitions: list[str] = []
    original_process_lock = store._process_lock

    @contextmanager
    def counted_process_lock(project_id: str):
        acquisitions.append(project_id)
        with original_process_lock(project_id):
            yield

    monkeypatch.setattr(store, "_process_lock", counted_process_lock)

    with store.project_transaction(created.project_id):
        saved = store.save_draft(
            created.project_id, changed_kind(created.project), expected_revision=1
        )
        generated = store.commit_generated_package(
            created.project_id,
            "scenario-1",
            {"solver_ready": False},
            expected_revision=saved.revision,
        )

    assert acquisitions == ["project-1"]
    assert saved.revision == 2
    assert generated.revision == 3


def test_project_transaction_keeps_distinct_projects_concurrent_on_one_store(
    tmp_path: Path,
) -> None:
    store = RefinedBlastStore(tmp_path)
    store.create(minimal_project())
    store.create(replace(minimal_project(), project_id="project-2"))
    distinct_acquired = threading.Event()

    def acquire_distinct_project() -> None:
        with store.project_transaction("project-2"):
            distinct_acquired.set()

    with store.project_transaction("project-1"):
        worker = threading.Thread(target=acquire_distinct_project)
        worker.start()
        assert distinct_acquired.wait(timeout=0.5)

    worker.join(timeout=5)
    assert not worker.is_alive()


def test_store_close_waits_for_an_active_project_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RefinedBlastStore(tmp_path)
    store.create(minimal_project())
    root_close_calls = 0
    original_root_close = store._root_anchor.close

    def counted_root_close() -> None:
        nonlocal root_close_calls
        root_close_calls += 1
        original_root_close()

    monkeypatch.setattr(store._root_anchor, "close", counted_root_close)
    transaction_entered = threading.Event()
    release_transaction = threading.Event()
    close_started = threading.Event()
    close_finished = threading.Event()

    def hold_transaction() -> None:
        with store.project_transaction("project-1"):
            transaction_entered.set()
            assert release_transaction.wait(timeout=5)
            assert store.load_project("project-1").revision == 1

    def close_store() -> None:
        close_started.set()
        store.close()
        close_finished.set()

    holder = threading.Thread(target=hold_transaction)
    holder.start()
    assert transaction_entered.wait(timeout=5)
    closer = threading.Thread(target=close_store)
    closer.start()
    assert close_started.wait(timeout=5)
    deadline = time.monotonic() + 5
    while not store._closing and time.monotonic() < deadline:
        time.sleep(0.01)
    assert store._closing
    assert not close_finished.wait(timeout=0.1)
    with pytest.raises(RuntimeError, match="store is closed"):
        with store.project_transaction("project-2"):
            pass
    release_transaction.set()
    holder.join(timeout=5)
    closer.join(timeout=5)

    assert not holder.is_alive()
    assert not closer.is_alive()
    assert close_finished.is_set()
    store.close()
    assert root_close_calls == 1
    with pytest.raises(RuntimeError, match="store is closed"):
        store.load_project("project-1")


def test_active_transaction_close_fails_while_an_external_close_waits(
    tmp_path: Path,
) -> None:
    store = RefinedBlastStore(tmp_path)
    store.create(minimal_project())
    transaction_entered = threading.Event()
    external_close_started = threading.Event()
    active_close_returned = threading.Event()
    release_transaction = threading.Event()

    def hold_and_close() -> None:
        with store.project_transaction("project-1"):
            transaction_entered.set()
            assert external_close_started.wait(timeout=5)
            deadline = time.monotonic() + 5
            while not store._closing and time.monotonic() < deadline:
                time.sleep(0.01)
            assert store._closing
            with pytest.raises(RuntimeError, match="during a project transaction"):
                store.close()
            active_close_returned.set()
            assert release_transaction.wait(timeout=5)

    holder = threading.Thread(target=hold_and_close, daemon=True)
    holder.start()
    assert transaction_entered.wait(timeout=5)
    closer = threading.Thread(
        target=lambda: (external_close_started.set(), store.close()), daemon=True
    )
    closer.start()
    try:
        assert active_close_returned.wait(timeout=0.5)
    finally:
        release_transaction.set()
    holder.join(timeout=5)
    closer.join(timeout=5)
    assert not holder.is_alive()
    assert not closer.is_alive()


def test_reentrant_project_transaction_releases_after_nested_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingPackage:
        def to_serializable(self) -> dict[str, object]:
            raise RuntimeError("injected package failure")

    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    acquisitions: list[str] = []
    original_process_lock = store._process_lock

    @contextmanager
    def counted_process_lock(project_id: str):
        acquisitions.append(project_id)
        with original_process_lock(project_id):
            yield

    monkeypatch.setattr(store, "_process_lock", counted_process_lock)

    with pytest.raises(RuntimeError, match="injected package failure"):
        with store.project_transaction(created.project_id):
            store.commit_generated_package(
                created.project_id,
                "scenario-1",
                FailingPackage(),
                expected_revision=1,
            )

    with store.project_transaction(created.project_id):
        assert store.load_project(created.project_id).revision == 1

    assert acquisitions == ["project-1", "project-1"]
    assert store._active_transactions == 0
    assert store._active_transaction_threads == {}


def test_safe_lock_directory_creation_accepts_only_a_verified_eexist_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lock_dir = tmp_path / ".refined_blast_locks"
    original_mkdir = Path.mkdir
    calls = 0

    def create_then_report_exists(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        original_mkdir(path, *args, **kwargs)
        raise FileExistsError("simulated competing lock-directory creator")

    monkeypatch.setattr(Path, "mkdir", create_then_report_exists)
    store_module._create_safe_directory(lock_dir, tmp_path)

    assert calls == 1
    assert lock_dir.is_dir()


def test_processes_share_a_revision_compare_and_swap(tmp_path: Path):
    RefinedBlastStore(tmp_path).create(minimal_project())
    context = multiprocessing.get_context("spawn")
    gate = context.Barrier(8)
    results = context.Queue()
    processes = [context.Process(target=_process_save, args=(str(tmp_path), gate, results)) for _ in range(8)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    outcomes = [results.get(timeout=2) for _ in processes]
    assert outcomes.count("success") == 1
    assert outcomes.count("conflict") == 7


def test_processes_serialise_generation_against_a_revision_update(tmp_path: Path):
    RefinedBlastStore(tmp_path).create(minimal_project())
    context = multiprocessing.get_context("spawn")
    gate = context.Barrier(2)
    results = context.Queue()
    generation = context.Process(target=_process_commit, args=(str(tmp_path), gate, results))
    draft = context.Process(target=_process_save, args=(str(tmp_path), gate, results))
    generation.start(); draft.start()
    generation.join(timeout=15); draft.join(timeout=15)
    assert generation.exitcode == draft.exitcode == 0
    outcomes = [results.get(timeout=2), results.get(timeout=2)]
    assert outcomes.count("success") == 1
    assert outcomes.count("conflict") == 1


def test_cross_process_project_transaction_serializes_only_the_same_project(
    tmp_path: Path,
) -> None:
    store = RefinedBlastStore(tmp_path)
    store.create(minimal_project())
    store.create(replace(minimal_project(), project_id="project-2"))
    assert callable(getattr(store, "project_transaction", None))

    context = multiprocessing.get_context("spawn")
    holder_entered = context.Event()
    holder_release = context.Event()
    same_started = context.Event()
    same_acquired = context.Event()
    distinct_started = context.Event()
    distinct_acquired = context.Event()
    holder = context.Process(
        target=_process_hold_project_transaction,
        args=(str(tmp_path), "project-1", holder_entered, holder_release),
    )
    same = context.Process(
        target=_process_acquire_project_transaction,
        args=(str(tmp_path), "project-1", same_started, same_acquired),
    )
    distinct = context.Process(
        target=_process_acquire_project_transaction,
        args=(str(tmp_path), "project-2", distinct_started, distinct_acquired),
    )

    holder.start()
    assert holder_entered.wait(timeout=10)
    same.start()
    distinct.start()
    try:
        assert same_started.wait(timeout=10)
        assert distinct_started.wait(timeout=10)
        assert distinct_acquired.wait(timeout=5)
        assert not same_acquired.wait(timeout=0.2)
    finally:
        holder_release.set()

    assert same_acquired.wait(timeout=5)
    for process in (holder, same, distinct):
        process.join(timeout=10)
        assert process.exitcode == 0


def test_generation_cannot_cross_a_concurrent_draft_revision_boundary(tmp_path: Path):
    class BlockingPackage:
        def __init__(self):
            self.entered = threading.Event()
            self.release = threading.Event()

        def to_serializable(self) -> dict[str, object]:
            self.entered.set()
            assert self.release.wait(timeout=2)
            return {"solver_ready": False}

    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    package = BlockingPackage()
    with ThreadPoolExecutor(max_workers=2) as executor:
        generation = executor.submit(
            store.commit_generated_package,
            created.project_id,
            "scenario-1",
            package,
            1,
        )
        assert package.entered.wait(timeout=2)
        draft = executor.submit(
            RefinedBlastStore(tmp_path).save_draft,
            created.project_id,
            changed_kind(created.project),
            1,
        )
        with pytest.raises(TimeoutError):
            draft.result(timeout=0.1)
        package.release.set()
        artifact = generation.result(timeout=2)
        with pytest.raises(DraftConflictError):
            draft.result(timeout=2)

    assert artifact.revision == 2


def test_project_id_cannot_escape_store(tmp_path: Path):
    with pytest.raises(ValueError, match="project_id"):
        RefinedBlastStore(tmp_path).load_project("../city")


def test_corrupt_project_json_fails_closed(tmp_path: Path):
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    project_json = tmp_path / "workspace" / "refined_building_blast" / created.project_id / "project.json"
    project_json.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt"):
        store.load_project(created.project_id)


def test_project_state_symlink_is_rejected_before_reading_target(tmp_path: Path):
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    project_json = tmp_path / "workspace" / "refined_building_blast" / created.project_id / "project.json"
    external = tmp_path / "external-project.json"
    external.write_text(project_json.read_text(encoding="utf-8"), encoding="utf-8")
    project_json.unlink()
    try:
        project_json.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"ordinary symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="link|reparse"):
        store.load_project(created.project_id)


def test_generated_directory_symlink_is_rejected_before_writing_target(tmp_path: Path):
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    generated = tmp_path / "workspace" / "refined_building_blast" / created.project_id / "generated"
    external = tmp_path / "outside"
    external.mkdir()
    generated.rmdir()
    try:
        generated.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"ordinary directory symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="link|reparse"):
        store.commit_generated_package(
            created.project_id,
            "scenario-1",
            {"solver_ready": False},
            expected_revision=1,
        )
    assert list(external.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows reparse points")
def test_generated_junction_is_rejected_before_writing_target(tmp_path: Path):
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    generated = tmp_path / "workspace" / "refined_building_blast" / created.project_id / "generated"
    external = tmp_path / "outside"
    external.mkdir()
    generated.rmdir()
    junction = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(generated), str(external)],
        capture_output=True,
        text=True,
        check=False,
    )
    if junction.returncode != 0:
        pytest.skip(f"junction creation unavailable: {junction.stderr or junction.stdout}")

    with pytest.raises(ValueError, match="link|reparse"):
        store.commit_generated_package(
            created.project_id,
            "scenario-1",
            {"solver_ready": False},
            expected_revision=1,
        )
    assert list(external.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="directory guard is Windows-specific")
def test_write_guard_blocks_or_rejects_a_parent_junction_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    external = tmp_path / "outside"
    external.mkdir()
    attempted = []

    def swap(parent: Path) -> None:
        attempted.append(parent)
        try:
            parent.rmdir()
        except OSError:
            return
        subprocess.run(["cmd", "/c", "mklink", "/J", str(parent), str(external)], check=False)

    monkeypatch.setattr(store_module, "_WRITE_GUARD_HOOK", swap)
    try:
        artifact = store.commit_generated_package(created.project_id, "scenario-1", {"solver_ready": False}, 1)
    except ValueError:
        artifact = None
    finally:
        monkeypatch.setattr(store_module, "_WRITE_GUARD_HOOK", None)
    assert attempted
    assert list(external.iterdir()) == []
    if artifact is not None:
        assert artifact.path.is_file()


@pytest.mark.skipif(os.name != "nt", reason="lock guard is Windows-specific")
def test_lock_directory_guard_blocks_or_rejects_a_junction_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    external = tmp_path / "outside-locks"
    external.mkdir()
    attempted = []

    def swap(locks_dir: Path) -> None:
        attempted.append(locks_dir)
        try:
            locks_dir.rmdir()
        except OSError:
            return
        subprocess.run(["cmd", "/c", "mklink", "/J", str(locks_dir), str(external)], check=False)

    monkeypatch.setattr(store_module, "_LOCK_GUARD_HOOK", swap, raising=False)
    try:
        result = store.save_draft(created.project_id, changed_kind(created.project), 1)
    except ValueError:
        result = None
    assert attempted
    assert list(external.iterdir()) == []
    if result is not None:
        assert result.revision == 2


def test_closed_store_fails_closed_and_context_manager_closes(tmp_path: Path):
    with RefinedBlastStore(tmp_path) as store:
        created = store.create(minimal_project())

    with pytest.raises(RuntimeError, match="closed"):
        store.load_project(created.project_id)
    with pytest.raises(RuntimeError, match="closed"):
        store.save_draft(created.project_id, changed_kind(created.project), 1)


@pytest.mark.skipif(os.name != "nt", reason="Windows root handles deny delete sharing")
def test_store_holds_root_handle_until_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "store-root"
    root.mkdir()
    moved = tmp_path / "moved-root"
    blocked: list[OSError] = []

    def swap_after_open(opened_root: Path) -> None:
        try:
            opened_root.rename(moved)
        except OSError as exc:
            blocked.append(exc)

    monkeypatch.setattr(store_module, "_ROOT_GUARD_HOOK", swap_after_open, raising=False)
    store = RefinedBlastStore(root)

    assert blocked
    store.close()
    root.rename(moved)
    assert moved.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle leak regression")
def test_root_open_failure_closes_the_windows_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import ctypes
    from ctypes import wintypes

    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    ctypes.windll.kernel32.GetProcessHandleCount.restype = wintypes.BOOL
    process = ctypes.windll.kernel32.GetCurrentProcess()

    def handle_count() -> int:
        count = wintypes.DWORD()
        assert ctypes.windll.kernel32.GetProcessHandleCount(process, ctypes.byref(count))
        return count.value

    def reject_after_open(_root: Path) -> None:
        raise ValueError("root verification failed")

    before = handle_count()
    monkeypatch.setattr(store_module, "_ROOT_GUARD_HOOK", reject_after_open, raising=False)
    for index in range(16):
        root = tmp_path / f"failed-root-{index}"
        root.mkdir()
        with pytest.raises(ValueError, match="verification failed"):
            RefinedBlastStore(root)
    after = handle_count()

    assert after <= before + 2


@pytest.mark.skipif(os.name != "nt", reason="Windows handle leak regression")
def test_directory_guard_verification_failure_closes_the_windows_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import ctypes
    from ctypes import wintypes

    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    ctypes.windll.kernel32.GetProcessHandleCount.restype = wintypes.BOOL
    process = ctypes.windll.kernel32.GetCurrentProcess()

    def handle_count() -> int:
        count = wintypes.DWORD()
        assert ctypes.windll.kernel32.GetProcessHandleCount(process, ctypes.byref(count))
        return count.value

    def reject_after_open(_directory: Path) -> None:
        raise ValueError("directory verification failed")

    store = RefinedBlastStore(tmp_path)
    directory = tmp_path / "guarded"
    directory.mkdir()
    before = handle_count()
    monkeypatch.setattr(store_module, "_DIRECTORY_GUARD_OPEN_HOOK", reject_after_open, raising=False)
    for _ in range(16):
        with pytest.raises(ValueError, match="verification failed"):
            with store_module._DirectoryGuard(directory, tmp_path, anchor=store._root_anchor):
                pass
    after = handle_count()
    store.close()

    assert after <= before + 2


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows reparse points")
def test_lock_file_open_rejects_a_junction_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    external = tmp_path / "outside-lock-file"
    external.mkdir()
    attempted: list[Path] = []

    def swap(lock_path: Path) -> None:
        attempted.append(lock_path)
        lock_path.unlink()
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(lock_path), str(external)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert junction.returncode == 0, junction.stderr or junction.stdout

    monkeypatch.setattr(store_module, "_LOCK_FILE_GUARD_HOOK", swap, raising=False)
    with pytest.raises(ValueError, match="link|reparse|regular file"):
        store.save_draft(created.project_id, changed_kind(created.project), 1)

    assert attempted
    assert list(external.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows reparse points")
def test_project_state_open_rejects_a_junction_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())
    state_path = tmp_path / "workspace" / "refined_building_blast" / created.project_id / "project.json"
    external = tmp_path / "outside-project-state"
    external.mkdir()

    def swap(opened_path: Path) -> None:
        opened_path.unlink()
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(opened_path), str(external)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert junction.returncode == 0, junction.stderr or junction.stdout

    monkeypatch.setattr(store_module, "_PROJECT_READ_GUARD_HOOK", swap, raising=False)
    with pytest.raises(ValueError, match="link|reparse|regular file"):
        store.load_project(created.project_id)

    assert list(external.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows delete sharing is handle-specific")
def test_open_project_snapshot_does_not_block_a_concurrent_atomic_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    created = RefinedBlastStore(tmp_path).create(minimal_project())
    reader_store = RefinedBlastStore(tmp_path)
    writer_store = RefinedBlastStore(tmp_path)
    reader_opened = threading.Event()
    release_reader = threading.Event()
    original_fdopen_owned = store_module._fdopen_owned
    selection_lock = threading.Lock()
    pause_next_reader = True

    class PausingReader:
        def __init__(self, handle: object) -> None:
            self._handle = handle

        def __enter__(self) -> "PausingReader":
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> object:
            return self._handle.__exit__(exc_type, exc, traceback)  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._handle, name)

        def read(self) -> str:
            reader_opened.set()
            assert release_reader.wait(timeout=5)
            return self._handle.read()  # type: ignore[attr-defined,no-any-return]

    def pause_first_text_reader(fd: int, *args: object, **kwargs: object):
        nonlocal pause_next_reader
        handle = original_fdopen_owned(fd, *args, **kwargs)
        with selection_lock:
            should_pause = pause_next_reader and args == ("r",)
            if should_pause:
                pause_next_reader = False
        return PausingReader(handle) if should_pause else handle

    monkeypatch.setattr(store_module, "_fdopen_owned", pause_first_text_reader)
    with ThreadPoolExecutor(max_workers=2) as executor:
        loading = executor.submit(reader_store.load_project, created.project_id)
        assert reader_opened.wait(timeout=2)
        try:
            saved = writer_store.save_draft(
                created.project_id, changed_kind(created.project), expected_revision=1
            )
        finally:
            release_reader.set()
        loaded = loading.result(timeout=2)

    assert saved.revision == 2
    assert loaded.revision == 1


def test_posix_lock_open_is_relative_nofollow_and_validates_inode(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, int, int, int]] = []
    nofollow = 0x20000
    monkeypatch.setattr(store_module, "_O_NOFOLLOW", nofollow, raising=False)

    def fake_open(name: str, flags: int, mode: int, *, dir_fd: int) -> int:
        calls.append((name, flags, mode, dir_fd))
        return 41

    monkeypatch.setattr(store_module.os, "open", fake_open)
    monkeypatch.setattr(
        store_module.os,
        "fstat",
        lambda _fd: os.stat_result((stat.S_IFREG | 0o600, 1, 2, 1, 0, 0, 0, 0, 0, 0)),
    )

    fd = store_module._open_posix_lock_file(17, "project-1.lock")

    assert fd == 41
    assert calls == [("project-1.lock", os.O_CREAT | os.O_RDWR | nofollow, 0o600, 17)]


def test_posix_project_transaction_releases_root_lock_before_lease_yield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class RootAnchor:
        identity = (2, 1)
        fd = 17

        def open_directory(self, name: str, *, create: bool) -> int:
            assert (name, create) == (".refined_blast_locks", True)
            events.append("directory-opened")
            return 23

    class Handle:
        pass

    @contextmanager
    def root_transaction(_fd: int):
        events.append("root-entered")
        try:
            yield
        finally:
            events.append("root-released")

    @contextmanager
    def owned_handle(_fd: int, *_args, **_kwargs):
        events.append("handle-opened")
        try:
            yield Handle()
        finally:
            events.append("handle-closed")

    store = object.__new__(RefinedBlastStore)
    trusted_root = Path("trusted-root")
    store._root = trusted_root
    store._root_anchor = RootAnchor()
    monkeypatch.setattr(store, "_safe_root", lambda: trusted_root)
    monkeypatch.setattr(store_module.os, "name", "posix")
    monkeypatch.setattr(store_module, "_posix_root_transaction_lock", root_transaction)
    monkeypatch.setattr(store_module, "_open_posix_lock_file", lambda *_: 29)
    monkeypatch.setattr(store_module, "_fdopen_owned", owned_handle)
    monkeypatch.setattr(
        store_module, "_locked_file_transaction", lambda _handle: events.append("project-locked")
    )
    monkeypatch.setattr(
        store_module, "_unlock_file", lambda _handle: events.append("project-unlocked")
    )
    monkeypatch.setattr(
        store_module.os, "close", lambda fd: events.append(f"directory-closed:{fd}")
    )

    with store._process_lock("project-1"):
        events.append("lease-yielded")

    assert events.index("root-released") < events.index("lease-yielded")
    assert events.index("project-locked") < events.index("root-released")
    assert events.index("project-unlocked") > events.index("lease-yielded")


def test_posix_root_acquisition_is_serialized_while_project_leases_stay_concurrent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events_lock = threading.Lock()
    first_root_entered = threading.Event()
    release_first_root = threading.Event()
    second_root_entered = threading.Event()
    lease_bodies = threading.Barrier(2)
    root_entries = 0

    class RootAnchor:
        identity = (2, 1)
        fd = 17

        def open_directory(self, _name: str, *, create: bool) -> int:
            assert create is True
            return 23

    class Handle:
        pass

    @contextmanager
    def observed_root_lock(_root_fd: int):
        nonlocal root_entries
        with events_lock:
            root_entries += 1
            entry_index = root_entries
            if entry_index == 1:
                first_root_entered.set()
            else:
                second_root_entered.set()
        if entry_index == 1:
            assert release_first_root.wait(timeout=5)
        yield

    @contextmanager
    def owned_handle(_fd: int, *_args, **_kwargs):
        yield Handle()

    store = object.__new__(RefinedBlastStore)
    trusted_root = Path("trusted-root")
    store._root = trusted_root
    store._root_anchor = RootAnchor()
    monkeypatch.setattr(store, "_safe_root", lambda: trusted_root)
    monkeypatch.setattr(store_module.os, "name", "posix")
    monkeypatch.setattr(
        store_module, "_posix_root_transaction_lock", observed_root_lock
    )
    monkeypatch.setattr(store_module, "_open_posix_lock_file", lambda *_: 29)
    monkeypatch.setattr(store_module, "_fdopen_owned", owned_handle)
    monkeypatch.setattr(store_module, "_locked_file_transaction", lambda _handle: None)
    monkeypatch.setattr(store_module, "_unlock_file", lambda _handle: None)
    monkeypatch.setattr(store_module.os, "close", lambda _fd: None)

    def transact(project_id: str) -> None:
        with store._process_lock(project_id):
            lease_bodies.wait(timeout=5)

    first = threading.Thread(target=transact, args=("project-1",))
    second = threading.Thread(target=transact, args=("project-2",))
    first.start()
    assert first_root_entered.wait(timeout=5)
    second.start()
    try:
        assert not second_root_entered.wait(timeout=0.2)
    finally:
        release_first_root.set()
    assert second_root_entered.wait(timeout=5)
    first.join(timeout=5)
    second.join(timeout=5)
    assert not first.is_alive()
    assert not second.is_alive()


def test_posix_root_open_is_directory_nofollow_and_validates_inode(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[Path, int]] = []
    nofollow = 0x20000
    directory = 0x10000
    monkeypatch.setattr(store_module, "_O_NOFOLLOW", nofollow, raising=False)
    monkeypatch.setattr(store_module, "_O_DIRECTORY", directory, raising=False)

    def fake_open(path: Path, flags: int) -> int:
        calls.append((path, flags))
        return 47

    monkeypatch.setattr(store_module.os, "open", fake_open)
    monkeypatch.setattr(
        store_module.os,
        "fstat",
        lambda _fd: os.stat_result((stat.S_IFDIR | 0o700, 1, 2, 1, 0, 0, 0, 0, 0, 0)),
    )

    fd, identity = store_module._open_posix_root(Path("trusted-root"))

    assert fd == 47
    assert identity == (2, 1)
    assert calls == [(Path("trusted-root"), os.O_RDONLY | directory | nofollow)]


def test_posix_lock_directory_open_is_relative_nofollow(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, int, int]] = []
    created: list[tuple[str, int, int]] = []
    nofollow = 0x20000
    directory = 0x10000
    monkeypatch.setattr(store_module, "_O_NOFOLLOW", nofollow, raising=False)
    monkeypatch.setattr(store_module, "_O_DIRECTORY", directory, raising=False)
    monkeypatch.setattr(
        store_module.os,
        "mkdir",
        lambda name, mode, *, dir_fd: created.append((name, mode, dir_fd)),
    )

    def fake_open(name: str, flags: int, *, dir_fd: int) -> int:
        calls.append((name, flags, dir_fd))
        return 49

    monkeypatch.setattr(store_module.os, "open", fake_open)
    monkeypatch.setattr(
        store_module.os,
        "fstat",
        lambda _fd: os.stat_result((stat.S_IFDIR | 0o700, 1, 2, 1, 0, 0, 0, 0, 0, 0)),
    )

    fd = store_module._open_posix_directory(17, ".refined_blast_locks", create=True)

    assert fd == 49
    assert created == [(".refined_blast_locks", 0o700, 17)]
    assert calls == [(".refined_blast_locks", os.O_RDONLY | directory | nofollow, 17)]


def test_posix_root_verification_rejects_a_moved_canonical_path(monkeypatch: pytest.MonkeyPatch):
    metadata = os.stat_result((stat.S_IFDIR | 0o700, 1, 2, 1, 0, 0, 0, 0, 0, 0))
    monkeypatch.setattr(store_module.os, "fstat", lambda _fd: metadata)
    monkeypatch.setattr(store_module.os, "stat", lambda _path, *, follow_symlinks: metadata)
    monkeypatch.setattr(store_module.os.path, "realpath", lambda _path: "moved/root")

    with pytest.raises(ValueError, match="moved"):
        store_module._verify_posix_root(17, Path("root"), (2, 1), Path("original/root"))


def test_owned_fd_is_closed_when_fdopen_fails(monkeypatch: pytest.MonkeyPatch):
    closed: list[int] = []
    monkeypatch.setattr(store_module.os, "close", closed.append)
    monkeypatch.setattr(
        store_module.os,
        "fdopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fdopen failed")),
    )

    with pytest.raises(OSError, match="fdopen failed"):
        store_module._fdopen_owned(53, "r", encoding="utf-8")

    assert closed == [53]


def test_process_lock_closes_posix_lock_fd_once_when_fdopen_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    class RootAnchor:
        identity = (2, 1)
        fd = 31

        def verify(self) -> None:
            pass

        def open_directory(self, _name: str, *, create: bool) -> int:
            assert create is True
            return 47

    class Transaction:
        def __enter__(self) -> None:
            pass

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            pass

    store = RefinedBlastStore.__new__(RefinedBlastStore)
    store._root = Path("trusted-root")
    store._root_anchor = RootAnchor()
    store._closed = False
    closed: list[int] = []
    monkeypatch.setattr(store_module.os, "name", "posix")
    monkeypatch.setattr(store_module, "_posix_root_transaction_lock", lambda _fd: Transaction())
    monkeypatch.setattr(store_module, "_open_posix_lock_file", lambda _dir_fd, _name: 53)
    monkeypatch.setattr(store_module.os, "close", closed.append)
    monkeypatch.setattr(
        store_module.os,
        "fdopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fdopen failed")),
    )

    with pytest.raises(OSError, match="fdopen failed"):
        with store._process_lock("project-1"):
            pass

    assert closed == [53, 47]


def test_root_anchor_closes_posix_fd_once_when_realpath_fails(monkeypatch: pytest.MonkeyPatch):
    root = Path("trusted-root")
    closed: list[int] = []
    monkeypatch.setattr(store_module.os, "name", "posix")
    monkeypatch.setattr(store_module, "_open_posix_root", lambda _path: (61, (2, 1)))
    monkeypatch.setattr(store_module.os, "close", closed.append)
    monkeypatch.setattr(
        store_module.os.path,
        "realpath",
        lambda _path: (_ for _ in ()).throw(OSError("realpath failed")),
    )

    with pytest.raises(OSError, match="realpath failed"):
        store_module._RootAnchor(root)

    assert closed == [61]


def test_posix_lock_open_rejects_non_regular_or_linked_inode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store_module, "_O_NOFOLLOW", 0x20000, raising=False)
    monkeypatch.setattr(store_module.os, "open", lambda *args, **kwargs: 43)
    monkeypatch.setattr(
        store_module.os,
        "fstat",
        lambda _fd: os.stat_result((stat.S_IFREG | 0o600, 1, 2, 2, 0, 0, 0, 0, 0, 0)),
    )
    closed: list[int] = []
    monkeypatch.setattr(store_module.os, "close", closed.append)

    with pytest.raises(ValueError, match="regular file"):
        store_module._open_posix_lock_file(17, "project-1.lock")

    assert closed == [43]


def test_fingerprints_are_deterministic_and_snapshots_are_isolated(tmp_path: Path):
    first = RefinedBlastStore(tmp_path / "one").create(minimal_project())
    second = RefinedBlastStore(tmp_path / "two").create(minimal_project())

    assert first.fingerprints == second.fingerprints
    loaded = RefinedBlastStore(tmp_path / "one").load_project(first.project_id)
    assert loaded is not first
    assert loaded.project is not first.project
    with pytest.raises(TypeError):
        loaded.project.building_reference["asset_id"] = "changed"  # type: ignore[index]
    assert RefinedBlastStore(tmp_path / "one").load_project(first.project_id).project.building_reference[
        "asset_id"
    ] == "building-1"


def test_generated_package_is_an_immutable_serialized_artifact(tmp_path: Path):
    store = RefinedBlastStore(tmp_path)
    created = store.create(minimal_project())

    artifact = store.commit_generated_package(
        created.project_id,
        "scenario-1",
        {"manifest": {"files": ["case.k"]}, "solver_ready": False},
        expected_revision=1,
    )

    assert artifact.revision == 2
    assert artifact.path.is_file()
    assert artifact.path.parent.name == "scenario-1"
    assert artifact.path.read_text(encoding="utf-8").startswith('{"package":')
