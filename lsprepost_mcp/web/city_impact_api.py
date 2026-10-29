from __future__ import annotations

from lsprepost_mcp.city_impact import (
    build_city_impact_assessment,
    write_city_impact_report,
)
from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.paths import find_project_dir


def city_impact_payload(project_name: str) -> JSONDict:
    return build_city_impact_assessment(find_project_dir(project_name))


def write_city_impact_report_payload(payload: JSONDict) -> JSONDict:
    project_name = payload.get("project_name")
    if not isinstance(project_name, str) or not project_name.strip():
        raise ValueError("project_name must be a non-empty string")
    return write_city_impact_report(find_project_dir(project_name))
