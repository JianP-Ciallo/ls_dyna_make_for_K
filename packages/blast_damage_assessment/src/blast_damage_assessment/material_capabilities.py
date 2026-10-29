"""Conservative mapping from material definitions to defensible result meanings."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from .errors import ContractError


@dataclass(frozen=True)
class MaterialCapability:
    material_id: int
    model: str
    engineering_validated: bool
    supported_metrics: tuple[str, ...]
    history_meanings: Mapping[int, str] = field(default_factory=dict)
    yield_stress_pa: float | None = None
    calibration_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "history_meanings", MappingProxyType(dict(self.history_meanings)))


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value > 0 else None


def capability_for_material(record: Mapping[str, object]) -> MaterialCapability:
    try:
        material_id = record["material_id"]
        model = record["model"]
    except KeyError as exc:
        raise ContractError(f"material record is missing {exc.args[0]}") from exc
    if isinstance(material_id, bool) or not isinstance(material_id, int) or material_id <= 0:
        raise ContractError("material_id must be a positive integer")
    if not isinstance(model, str) or not model.strip():
        raise ContractError("material model must be a non-empty string")
    validated = record.get("engineering_validated", False)
    if not isinstance(validated, bool):
        raise ContractError("material engineering_validated must be boolean")
    normalized = model.strip().lower().replace("*", "")
    supported = ["stress", "deformation"]
    history: dict[int, str] = {}
    yield_stress = _positive_number(record.get("yield_stress_pa"))
    calibration = record.get("calibration_id")
    if calibration is not None and (not isinstance(calibration, str) or not calibration.strip()):
        raise ContractError("material calibration_id must be a non-empty string")

    if normalized in {"mat_072r3", "mat_concrete_damage_rel3", "k&c", "kandc"}:
        nout = record.get("nout")
        if nout == 2 and not isinstance(nout, bool):
            history[0] = "scaled_damage_measure"
            supported.append("scaled_damage_measure")
    elif normalized in {"steel_plasticity", "mat_024", "mat_piecewise_linear_plasticity"}:
        if yield_stress is not None and isinstance(calibration, str) and calibration.strip():
            supported.append("effective_plastic_strain")
    elif normalized in {"elastic", "mat_001", "mat_elastic"}:
        pass

    return MaterialCapability(
        material_id=material_id,
        model=model,
        engineering_validated=validated,
        supported_metrics=tuple(supported),
        history_meanings=history,
        yield_stress_pa=yield_stress,
        calibration_id=calibration if isinstance(calibration, str) else None,
    )


def meaning_for_alive_state() -> str:
    return "numerical_deletion"
