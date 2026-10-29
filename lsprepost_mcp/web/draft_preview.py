from __future__ import annotations

from copy import deepcopy

from lsprepost_mcp.city_editor import (
    apply_city_blast_source,
    apply_city_component_operation,
    apply_city_editor_transforms,
)
from lsprepost_mcp.city_street_blast import (
    build_city_street_blast_keyword,
    default_city_street_blast_spec,
)
from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.physics_actions import compile_physics_actions
from lsprepost_mcp.paths import safe_project_name
from lsprepost_mcp.project_store import write_compiled_keyword_project
from lsprepost_mcp.schema import default_model_spec, parse_model_spec
from lsprepost_mcp.web.preview_mesh import build_preview_mesh_from_keyword


SOURCE_KINDS = {"assembly", "controlled_scene", "city_street_blast"}


def city_editor_template(project_name: str) -> JSONDict:
    if (
        not isinstance(project_name, str)
        or not project_name
        or safe_project_name(project_name) != project_name
    ):
        raise ValueError("project_name must be a valid non-empty project name")
    spec = default_city_street_blast_spec(project_name)
    explosive = spec["explosive"]
    base = explosive["base_center_m"]
    center = [
        float(base[0]),
        float(base[1]),
        float(base[2]) + 0.5 * float(explosive["length_m"]),
    ]
    return {
        "source_kind": "city_street_blast",
        "revision": 0,
        "project_name": project_name,
        "spec": spec,
        "blast_source": {
            "source_id": "city_tnt",
            "position_m": center,
        },
        "transforms": {},
        "component_operations": [],
    }


def build_editor_draft_preview(payload: JSONDict) -> JSONDict:
    revision, project_name, keyword, metadata = _compile_payload(payload)

    preview = build_preview_mesh_from_keyword(
        keyword,
        metadata,
        project_name=project_name,
        revision=revision,
    )
    preview["validation"] = {
        "ok": True,
        "status": "draft_compiled_in_memory",
        "full_static_checks": "pending_project_generation",
        "issues": [],
    }
    ale_domain = metadata.get("ale_domain")
    if isinstance(ale_domain, dict):
        preview["ale_mesh"] = {
            "mesh_fingerprint": ale_domain.get("mesh_fingerprint"),
            "refinement_center_m": deepcopy(
                ale_domain.get("refinement_center_m")
            ),
            "local_cell_size_m": deepcopy(ale_domain.get("local_cell_size_m")),
            "remesh_reason": ale_domain.get("remesh_reason"),
        }
    preview["resolved_spec"] = deepcopy(metadata.get("resolved_spec", {}))
    return preview


def generate_editor_project(payload: JSONDict) -> JSONDict:
    revision, project_name, keyword, metadata = _compile_payload(payload)
    source_project_name = payload.get("source_project_name")
    if source_project_name is not None:
        if (
            not isinstance(source_project_name, str)
            or safe_project_name(source_project_name) != source_project_name
        ):
            raise ValueError("source_project_name is invalid")
    source_model_sha256 = payload.get("source_model_sha256")
    if source_model_sha256 is not None:
        _sha256(source_model_sha256, "source_model_sha256")
    ale_domain = metadata.get("ale_domain", {})
    metadata["editor_provenance"] = {
        "editor_phase": 17,
        "source_project_name": source_project_name,
        "source_model_sha256": source_model_sha256,
        "layout_fingerprint": _sha256(
            metadata.get("layout_fingerprint"),
            "layout_fingerprint",
        ),
        "editor_state_fingerprint": _sha256(
            metadata.get("editor_state_fingerprint"),
            "editor_state_fingerprint",
        ),
        "ale_mesh_fingerprint": _sha256(
            (
                ale_domain.get("mesh_fingerprint")
                if isinstance(ale_domain, dict)
                else None
            ),
            "ale_mesh_fingerprint",
        ),
        "draft_revision": revision,
        "transforms": deepcopy(payload.get("transforms", {})),
        "blast_source": deepcopy(payload.get("blast_source")),
        "component_operations": deepcopy(
            _component_operation_history(
                payload.get("component_operations", [])
            )
        ),
    }
    resolved_spec = metadata.get("resolved_spec")
    if not isinstance(resolved_spec, dict):
        raise ValueError("compiled editor draft is missing resolved_spec")
    result = write_compiled_keyword_project(
        project_name,
        keyword,
        resolved_spec,
        metadata,
        if_exists="error",
    )
    result["operation"] = "generate_phase17_editor_project"
    result["editor_provenance"] = metadata["editor_provenance"]
    result["ok"] = bool(result.get("checks", {}).get("ok"))
    return result


def mutate_city_editor_component(payload: JSONDict) -> JSONDict:
    if not isinstance(payload, dict):
        raise ValueError("city component mutation payload must be an object")
    if payload.get("source_kind") != "city_street_blast":
        raise ValueError("city component mutation requires city_street_blast")
    raw_spec = payload.get("spec")
    if not isinstance(raw_spec, dict):
        raise ValueError("city component mutation requires spec")
    spec = deepcopy(raw_spec)
    project_name = payload.get("project_name")
    if not isinstance(project_name, str):
        raise ValueError("city component mutation requires project_name")
    spec["project_name"] = project_name
    spec = apply_city_editor_transforms(spec, payload.get("transforms", {}))
    if "blast_source" in payload:
        spec = apply_city_blast_source(spec, payload["blast_source"])

    operation_result = apply_city_component_operation(
        spec,
        payload.get("operation"),
    )
    draft = deepcopy(payload)
    draft.pop("operation", None)
    draft["spec"] = operation_result["spec"]
    draft["transforms"] = {}
    raw_history = _component_operation_history(
        draft.get("component_operations", [])
    )
    if len(raw_history) >= 100:
        raw_history = raw_history[-99:]
    raw_history.append(
        {
            "revision": _nonnegative_int(
                draft.get("revision"),
                "revision",
            ),
            "action": operation_result["action"],
            "template": operation_result["template"],
            "selected_component_id": operation_result[
                "selected_component_id"
            ],
            "removed_component_id": operation_result.get(
                "removed_component_id"
            ),
        }
    )
    draft["component_operations"] = raw_history
    preview = build_editor_draft_preview(draft)
    return {
        "action": operation_result["action"],
        "template": operation_result["template"],
        "selected_component_id": operation_result["selected_component_id"],
        "removed_component_id": operation_result.get("removed_component_id"),
        "draft": draft,
        "preview": preview,
    }


def _compile_payload(
    payload: JSONDict,
) -> tuple[int, str, str, JSONDict]:
    if not isinstance(payload, dict):
        raise ValueError("editor preview payload must be an object")
    revision = _nonnegative_int(payload.get("revision"), "revision")
    source_kind = payload.get("source_kind")
    if not isinstance(source_kind, str) or source_kind not in SOURCE_KINDS:
        raise ValueError(
            "source_kind must be assembly, controlled_scene, or city_street_blast"
        )
    _component_operation_history(payload.get("component_operations", []))
    project_name = payload.get("project_name")
    if (
        not isinstance(project_name, str)
        or not project_name
        or safe_project_name(project_name) != project_name
    ):
        raise ValueError("project_name must be a valid non-empty project name")
    if source_kind == "city_street_blast":
        keyword, metadata = _compile_city(payload, project_name)
    else:
        keyword, metadata = _compile_structured(payload, project_name, source_kind)
    return revision, project_name, keyword, metadata


def _compile_city(
    payload: JSONDict,
    project_name: str,
) -> tuple[str, JSONDict]:
    raw_spec = payload.get("spec")
    if not isinstance(raw_spec, dict):
        raise ValueError("city editor preview requires spec")
    spec = deepcopy(raw_spec)
    spec["project_name"] = project_name
    spec = apply_city_editor_transforms(spec, payload.get("transforms", {}))
    if "blast_source" in payload:
        spec = apply_city_blast_source(spec, payload["blast_source"])
    return build_city_street_blast_keyword(spec)


def _compile_structured(
    payload: JSONDict,
    project_name: str,
    source_kind: str,
) -> tuple[str, JSONDict]:
    if source_kind == "controlled_scene":
        raw_spec = payload.get("spec")
        if not isinstance(raw_spec, dict):
            raise ValueError("controlled_scene preview requires spec")
        spec = deepcopy(raw_spec)
        spec["project_name"] = project_name
    else:
        components = payload.get("components")
        if not isinstance(components, list):
            raise ValueError("assembly preview requires components")
        if len(components) > 32:
            raise ValueError("assembly preview supports at most 32 components")
        actions = payload.get("actions", [])
        if not isinstance(actions, list):
            raise ValueError("actions must be an array")
        compiled = compile_physics_actions(
            deepcopy(components),
            deepcopy(actions),
            contacts=deepcopy(payload.get("contacts", [])),
            loads=deepcopy(payload.get("loads", [])),
        )
        spec = default_model_spec(project_name, "assembly_scene")
        spec["components"] = compiled["components"]
        spec["contacts"] = compiled["contacts"]
        spec["loads"] = compiled["loads"]
        for field in (
            "sets",
            "boundary_conditions",
            "curves",
            "analysis_control",
            "database",
        ):
            if field in payload:
                spec[field] = deepcopy(payload[field])
    parsed = parse_model_spec(spec)
    return build_keyword(parsed)


def _nonnegative_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path} must be a nonnegative integer")
    return value


def _sha256(value: object, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{path} must be a lowercase SHA-256 string")
    return value


def _component_operation_history(value: object) -> list[JSONDict]:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("component_operations must be an array of at most 100 entries")
    result: list[JSONDict] = []
    allowed = {
        "revision",
        "action",
        "template",
        "selected_component_id",
        "removed_component_id",
    }
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"component_operations[{index}] must be an object")
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(
                f"component_operations[{index}] has unsupported fields: "
                + ", ".join(unknown)
            )
        action = raw.get("action")
        if action not in {"add", "duplicate", "delete"}:
            raise ValueError(
                f"component_operations[{index}].action is invalid"
            )
        template = raw.get("template")
        if template not in {
            "parked_vehicle",
            "subway_entrance",
            "shell_box",
        }:
            raise ValueError(
                f"component_operations[{index}].template is invalid"
            )
        selected = raw.get("selected_component_id")
        selected_is_optional = (
            action == "delete"
            and template == "shell_box"
            and selected is None
        )
        if (
            not selected_is_optional
            and not _operation_component_matches_template(selected, template)
        ):
            raise ValueError(
                f"component_operations[{index}].selected_component_id is invalid"
            )
        removed = raw.get("removed_component_id")
        if removed is not None and (
            not _operation_component_matches_template(removed, template)
        ):
            raise ValueError(
                f"component_operations[{index}].removed_component_id is invalid"
            )
        result.append(
            {
                "revision": _nonnegative_int(
                    raw.get("revision"),
                    f"component_operations[{index}].revision",
                ),
                "action": action,
                "template": template,
                "selected_component_id": selected,
                "removed_component_id": removed,
            }
        )
    return result


def _operation_component_matches_template(
    component_id: object,
    template: object,
) -> bool:
    if not isinstance(component_id, str):
        return False
    if template == "parked_vehicle":
        suffix = component_id.removeprefix("parked_vehicle_")
        return (
            component_id.startswith("parked_vehicle_")
            and suffix.isdigit()
            and int(suffix) >= 1
        )
    if template == "subway_entrance":
        if component_id == "subway_entrance":
            return True
        suffix = component_id.removeprefix("subway_entrance_")
        return (
            component_id.startswith("subway_entrance_")
            and suffix.isdigit()
            and int(suffix) >= 2
        )
    if template == "shell_box":
        suffix = component_id.removeprefix("shell_box_")
        return (
            component_id.startswith("shell_box_")
            and suffix.isdigit()
            and int(suffix) >= 1
        )
    return False
