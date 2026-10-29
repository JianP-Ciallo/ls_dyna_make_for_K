from __future__ import annotations

from .config import JSONDict
from .component_resource_adapter import attach_model_resources
from .schema import ModelSpec
from .ale_blast import build_ale_blast_scene
from .dyna_assembly import build_assembly_scene
from .dyna_cards import build_cfile
from .dyna_geometry import (
    build_beam_bar,
    build_cylinder_shell,
    build_cylinder_solid,
    build_shell_box,
    build_shell_plate,
    build_single_solid_element_test,
    build_solid_block,
)
from .preflight import preflight_model_spec


def build_keyword(spec: ModelSpec) -> tuple[str, JSONDict]:
    preflight = preflight_model_spec(spec)
    builders = {
        "shell_plate": build_shell_plate,
        "solid_block": build_solid_block,
        "shell_box": build_shell_box,
        "cylinder_shell": build_cylinder_shell,
        "cylinder_solid": build_cylinder_solid,
        "beam_bar": build_beam_bar,
        "assembly_scene": build_assembly_scene,
        "ale_blast_scene": build_ale_blast_scene,
        "single_solid_element_test": build_single_solid_element_test,
    }
    try:
        builder = builders[spec.model_type]
    except KeyError as exc:
        raise ValueError(f"unsupported model_type: {spec.model_type}") from exc
    keyword, metadata = builder(spec)
    keyword, resource_instances = attach_model_resources(keyword, spec.model_resources)
    if resource_instances:
        metadata["model_resource_instances"] = resource_instances
        metadata["model_resource_instance_count"] = len(resource_instances)
    metadata["preflight"] = preflight
    return keyword, metadata
