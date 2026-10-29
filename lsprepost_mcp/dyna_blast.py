from __future__ import annotations

from .config import JSONDict
from .dyna_common import Segment
from .dyna_selectors import segment_set_lines


def blast_keyword_lines(
    blast_loads: list[JSONDict],
    component_segments: dict[str, list[Segment]],
) -> tuple[list[str], JSONDict]:
    if not blast_loads:
        return [], {
            "blast_count": 0,
            "blast_target_count": 0,
            "blast_segment_count": 0,
            "blast_sources": [],
        }

    lines: list[str] = []
    sources: list[JSONDict] = []
    segment_count = 0
    output_dt = min(float(load["output_dt_s"]) for load in blast_loads)
    next_segment_set_id = 900001

    for blast_index, load in enumerate(blast_loads, start=1):
        bid = blast_index
        for target in load["targets"]:
            component_id = str(target["component"])
            surface = str(target["surface"])
            segments = list(component_segments.get(component_id, []))
            if not segments:
                raise ValueError(f"blast target component {component_id} has no shell segments")
            if surface in {"bottom_surface", "inner_surface"}:
                segments = [(n1, n4, n3, n2) for n1, n2, n3, n4 in segments]
            sid = next_segment_set_id
            next_segment_set_id += 1
            lines.extend(segment_set_lines(sid, f"blast target {component_id}.{surface}", segments))
            lines.extend(
                [
                    "*LOAD_BLAST_SEGMENT_SET",
                    "$#   bid      ssid    alepid     sfnrb    scalep",
                    f"{bid},{sid},0,0.0,1.0",
                ]
            )
            segment_count += len(segments)

        xbo, ybo, zbo = [float(value) for value in load["position_m"]]
        lines.extend(
            [
                "*LOAD_BLAST_ENHANCED",
                "$#   bid         m       xbo       ybo       zbo       tbo      unit     blast",
                (
                    f"{bid},{float(load['equivalent_mass_kg']):.9g},{xbo:.9g},{ybo:.9g},"
                    f"{zbo:.9g},0.0,{int(load['unit'])},{int(load['blast_type'])}"
                ),
                "$#   cfm       cfl       cft       cfp     nidbo     death    negphs",
                "0.0,0.0,0.0,0.0,0,1.0e20,0",
            ]
        )
        sources.append(
            {
                "id": str(load.get("id", f"blast_{bid}")),
                "blast_id": bid,
                "charge_type": "tnt",
                "equivalent_mass_kg": float(load["equivalent_mass_kg"]),
                "position_m": [xbo, ybo, zbo],
                "mode": "free_air_burst",
                "targets": [dict(target) for target in load["targets"]],
            }
        )

    lines.extend(
        [
            "*DATABASE_BINARY_BLSTFOR",
            "$#      dt",
            f"{output_dt:.9g}",
            "*DATABASE_GLSTAT",
            "$#      dt",
            f"{output_dt:.9g}",
            "*DATABASE_MATSUM",
            "$#      dt",
            f"{output_dt:.9g}",
            "*DATABASE_SPCFORC",
            "$#      dt",
            f"{output_dt:.9g}",
        ]
    )
    return lines, {
        "blast_count": len(blast_loads),
        "blast_target_count": sum(len(load["targets"]) for load in blast_loads),
        "blast_segment_count": segment_count,
        "blast_sources": sources,
        "blast_output_dt_s": output_dt,
    }
