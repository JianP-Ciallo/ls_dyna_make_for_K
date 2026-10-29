"""Creation and recovery remain usable without constructing an HTTP adapter."""
from dataclasses import replace

import pytest

from lsprepost_mcp.refined_blast import project_repository as repository_module
from lsprepost_mcp.refined_blast.project_metadata import building_definition_fingerprint, normalize_building_recipe
from lsprepost_mcp.refined_blast.record_contract import RecordError
from lsprepost_mcp.refined_blast.store import RefinedBlastStore
from test_phase18e_assembler import _artifact, _project


def pending_project():
    recipe = normalize_building_recipe({"asset_id": "repository-fixture"})
    fingerprint = building_definition_fingerprint(recipe)
    project = replace(_project(_artifact()), building_reference={"asset_id": "repository-fixture"}, building_artifact_fingerprint=fingerprint)
    return project, recipe, fingerprint


def test_create_is_idempotent_and_reopens_without_web(tmp_path):
    project, recipe, fingerprint = pending_project()
    with RefinedBlastStore(tmp_path) as store:
        repository = repository_module.ProjectRepository(store)
        first = repository.create(project, recipe, compilation_state="pending", definition_fingerprint=fingerprint)
        assert first.revision == 1
        assert repository.create(project, recipe, compilation_state="pending", definition_fingerprint=fingerprint).revision == 1
    with RefinedBlastStore(tmp_path) as store:
        stored, restored, metadata = repository_module.ProjectRepository(store).verified_record(project.project_id)
        assert stored.project == project
        assert restored == recipe
        assert metadata["compilation_state"] == "pending"


def test_failed_metadata_publication_hides_project_until_same_request_recovers(tmp_path, monkeypatch):
    project, recipe, fingerprint = pending_project()
    with RefinedBlastStore(tmp_path) as store:
        repository = repository_module.ProjectRepository(store)
        original = repository_module.store_module._atomic_write_json
        def fail_metadata(path, *args, **kwargs):
            if path.name == "phase18f_refined_blast_metadata.json":
                raise OSError("injected metadata failure")
            return original(path, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(repository_module.store_module, "_atomic_write_json", fail_metadata)
            with pytest.raises(OSError):
                repository.create(project, recipe, compilation_state="pending", definition_fingerprint=fingerprint)
        with pytest.raises(RecordError) as hidden:
            repository.verified_record(project.project_id)
        assert hidden.value.code == "project_creation_incomplete"
        different = replace(project, preset_version="different")
        with pytest.raises(RecordError) as conflict:
            repository.create(different, recipe, compilation_state="pending", definition_fingerprint=fingerprint)
        assert conflict.value.code == "project_exists"
        assert repository.create(project, recipe, compilation_state="pending", definition_fingerprint=fingerprint).revision == 1


def test_corrupted_metadata_fails_closed(tmp_path):
    project, recipe, fingerprint = pending_project()
    with RefinedBlastStore(tmp_path) as store:
        repository = repository_module.ProjectRepository(store)
        repository.create(project, recipe, compilation_state="pending", definition_fingerprint=fingerprint)
        repository.metadata_path(project.project_id).write_text("{}", encoding="utf-8")
        with pytest.raises(RecordError) as failure:
            repository.verified_record(project.project_id)
        assert failure.value.code == "metadata_integrity_error"


@pytest.mark.parametrize("identifier", ["../outside", "bad/name", "bad\\name", ".", ""])
def test_transaction_path_rejects_unsafe_id_before_creating_directories(tmp_path, identifier):
    with RefinedBlastStore(tmp_path) as store:
        repository = repository_module.ProjectRepository(store)
        with pytest.raises(ValueError):
            repository.transaction_path(identifier, create=True)
        assert not (tmp_path / "workspace").exists()
