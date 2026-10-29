"""Closed Web adapter for the optional blast damage assessment bridge."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from lsprepost_mcp import damage_assessment_bridge as bridge
from lsprepost_mcp.assessment_result_source import (
    resolve_assessment_result_source,
)
from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.refined_blast import store as store_module
from lsprepost_mcp.refined_blast.store import RefinedBlastStore
from lsprepost_mcp.web.http_utils import ApiError


ASSESSMENT_REQUEST_SCHEMA = "lsprepost_mcp.damage_assessment_request@1"
ASSESSMENT_REQUEST_KEYS = frozenset(
    {
        "schema_version",
        "scenario_id",
        "generated_revision",
        "artifact_fingerprint",
        "package_fingerprint",
    }
)
ASSESSMENT_IDENTITY_KEYS = frozenset(ASSESSMENT_REQUEST_KEYS - {"schema_version"})
ARTIFACT_NAMES = frozenset(
    {
        "assessment_request.json",
        "assessment_result.json",
        "assessment_snapshot.json",
        "evidence_index.json",
        "rule_snapshot.json",
        "damage_report.html",
        "building_components.csv",
        "ground_regions.csv",
    }
)
_CONTENT_TYPES = {
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
}


def assessment_capabilities_payload() -> JSONDict:
    """Return the optional bridge capability without importing its package eagerly."""

    return bridge.assessment_capabilities()


class DamageAssessmentWebApi:
    """Map current refined-project authority to the path-free public bridge."""

    def __init__(self, store: RefinedBlastStore) -> None:
        if not isinstance(store, RefinedBlastStore):
            raise TypeError("store must be a RefinedBlastStore")
        self._store = store

    def capabilities(self) -> JSONDict:
        return bridge.assessment_capabilities()

    def assess_current(
        self,
        *,
        project_id: str,
        case_id: str,
        project_dir: Path,
        identity: Mapping[str, object],
    ) -> JSONDict:
        capabilities = self.capabilities()
        if capabilities.get("available") is not True:
            raise ApiError(
                409,
                "assessment_unavailable",
                "blast damage assessment is not available in this installation",
            )
        try:
            source = resolve_assessment_result_source(project_dir)
        except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
            raise ApiError(
                409,
                "assessment_source_unavailable",
                "a verified terminal solver result is not available for assessment",
            ) from exc
        record = source.get("record") if isinstance(source, dict) else None
        if not isinstance(record, Mapping):
            raise ApiError(
                409,
                "assessment_source_unavailable",
                "the terminal solver result source record is invalid",
            )
        expected = {key: identity[key] for key in ASSESSMENT_IDENTITY_KEYS}
        actual = {key: record.get(key) for key in ASSESSMENT_IDENTITY_KEYS}
        if actual != expected:
            raise ApiError(
                409,
                "assessment_source_stale",
                "the registered solver result does not match the current generated package",
            )
        run_dir = source.get("run_dir")
        semantic_manifest = source.get("semantic_manifest")
        if not isinstance(run_dir, Path) or not isinstance(semantic_manifest, Path):
            raise ApiError(
                409,
                "assessment_source_unavailable",
                "the terminal solver result source paths are invalid",
            )
        try:
            return bridge.assess_completed_run(
                project_id=project_id,
                case_id=case_id,
                project_dir=project_dir,
                run_dir=run_dir,
                semantic_manifest=semantic_manifest,
            )
        except bridge.DamageAssessmentUnavailableError as exc:
            raise ApiError(
                409,
                "assessment_unavailable",
                "blast damage assessment became unavailable",
            ) from exc
        except bridge.DamageAssessmentRegistryConflictError as exc:
            raise ApiError(
                409,
                "assessment_conflict",
                "assessment identity conflicts with an existing registered result",
            ) from exc
        except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
            raise ApiError(
                409,
                "assessment_integrity_error",
                "assessment source, result, or registry failed integrity validation",
            ) from exc
        except Exception as exc:
            raise ApiError(
                500,
                "assessment_failed",
                "damage assessment execution failed",
            ) from exc

    def latest(self, project_dir: Path) -> JSONDict:
        try:
            return bridge.latest_registered_assessment(project_dir)
        except bridge.DamageAssessmentNotFoundError as exc:
            raise ApiError(
                404,
                "assessment_not_found",
                "no registered damage assessment is available",
            ) from exc
        except (OSError, TypeError, ValueError) as exc:
            raise ApiError(
                409,
                "assessment_registry_integrity_error",
                "the damage assessment registry failed integrity validation",
            ) from exc

    def artifact(
        self,
        *,
        project_dir: Path,
        assessment_id: str,
        artifact_name: str,
    ) -> tuple[int, dict[str, str], bytes]:
        if artifact_name not in ARTIFACT_NAMES:
            raise ApiError(
                404,
                "not_found",
                "registered assessment artifact was not found",
            )
        try:
            record = bridge.registered_assessment(project_dir, assessment_id)
        except bridge.DamageAssessmentNotFoundError as exc:
            raise ApiError(
                404,
                "assessment_not_found",
                "the requested damage assessment is not registered",
            ) from exc
        except (OSError, TypeError, ValueError) as exc:
            raise ApiError(
                409,
                "assessment_registry_integrity_error",
                "the damage assessment registry failed integrity validation",
            ) from exc
        artifacts = record.get("artifacts")
        reference = (
            artifacts.get(artifact_name)
            if isinstance(artifacts, Mapping)
            else None
        )
        if not isinstance(reference, Mapping):
            raise ApiError(
                409,
                "assessment_registry_integrity_error",
                "the registered assessment artifact reference is invalid",
            )
        relative = _registered_path(reference.get("path"), artifact_name)
        target = project_dir.joinpath(*relative.parts)
        try:
            with self._store.project_transaction(project_dir.name):
                root = self._store._safe_root()
                store_module._assert_safe_file(target, root, missing_ok=False)
                data = store_module._read_bytes_file(
                    target,
                    root=root,
                    anchor=self._store._root_anchor,
                )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ApiError(
                409,
                "assessment_artifact_integrity_error",
                "the registered assessment artifact is missing or unsafe",
            ) from exc
        expected_size = reference.get("size_bytes")
        expected_hash = reference.get("sha256")
        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or len(data) != expected_size
            or not isinstance(expected_hash, str)
            or hashlib.sha256(data).hexdigest() != expected_hash
        ):
            raise ApiError(
                409,
                "assessment_artifact_integrity_error",
                "the registered assessment artifact hash or size changed",
            )
        project_tokens = {
            str(project_dir).encode("utf-8"),
            project_dir.as_posix().encode("utf-8"),
        }
        if any(token and token in data for token in project_tokens):
            raise ApiError(
                409,
                "assessment_artifact_integrity_error",
                "the registered assessment artifact contains a local absolute path",
            )
        content_type = _CONTENT_TYPES[Path(artifact_name).suffix]
        return 200, {
            "Content-Type": content_type,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        }, data


def _registered_path(value: object, artifact_name: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ApiError(409, "assessment_registry_integrity_error", "artifact path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(path.parts) != 4
        or path.parts[:2] != ("artifacts", "damage_assessments")
        or path.parts[-1] != artifact_name
    ):
        raise ApiError(409, "assessment_registry_integrity_error", "artifact path is invalid")
    return path


__all__ = [
    "ASSESSMENT_REQUEST_KEYS",
    "ASSESSMENT_REQUEST_SCHEMA",
    "ARTIFACT_NAMES",
    "DamageAssessmentWebApi",
    "assessment_capabilities_payload",
]
