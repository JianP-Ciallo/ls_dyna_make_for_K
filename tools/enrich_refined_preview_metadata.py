from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = ROOT / "workspace" / "projects"


PROJECTS = {
    "soft_copyright_refined_commercial_blast": {
        "scene_label": "精细商业建筑爆炸（ALE/FSI）",
        "ale_bounds": {"min": [-6.0, -6.0, -4.5], "max": [12.0, 10.0, 7.06641272]},
        "labels": {
            "commercial_column_longitudinal_rebar": "商业建筑柱纵向钢筋",
            "commercial_column_stirrup": "商业建筑柱箍筋",
            "commercial_rc_column": "商业建筑钢筋混凝土柱",
            "commercial_wall_horizontal_rebar": "商业建筑墙体水平钢筋",
            "commercial_wall_vertical_rebar": "商业建筑墙体竖向钢筋",
            "diagnostic_soil_ground": "诊断地基土体",
            "foundation_rebar": "基础钢筋",
            "hybrid_foundation": "钢混组合基础",
            "hybrid_slab": "钢混组合楼板",
            "nonstructural_partition": "非结构隔墙",
            "opaque_facade": "砌体外墙",
            "slab_rebar": "楼板钢筋",
            "steel_beam": "钢梁",
            "steel_roof_deck": "钢屋面板",
            "ale_air_tnt_domain": "ALE 空气-TNT 耦合域",
            "tnt_high_explosive": "TNT 高能炸药",
        },
    },
    "soft_copyright_refined_residential_blast": {
        "scene_label": "精细住宅结构爆炸（ALE/FSI）",
        "ale_bounds": {"min": [-6.0, -6.0, -4.5], "max": [10.0, 10.0, 9.0]},
        "labels": {
            "beam_longitudinal": "梁纵向钢筋",
            "beam_stirrup": "梁箍筋",
            "column_longitudinal": "柱纵向钢筋",
            "column_stirrup": "柱箍筋",
            "diagnostic_soil_ground": "诊断地基土体",
            "foundation_rebar": "基础钢筋",
            "nonstructural_balcony_barrier": "阳台非结构护栏",
            "nonstructural_partition": "非结构隔墙",
            "opaque_facade": "砌体外墙",
            "rc_beam_x": "X 向钢筋混凝土梁",
            "rc_beam_y": "Y 向钢筋混凝土梁",
            "rc_column": "钢筋混凝土柱",
            "rc_foundation": "钢筋混凝土基础",
            "rc_shear_wall": "钢筋混凝土剪力墙",
            "rc_slab": "钢筋混凝土楼板",
            "slab_rebar": "楼板钢筋",
            "wall_rebar": "剪力墙钢筋",
            "ale_air_tnt_domain": "ALE 空气-TNT 耦合域",
            "tnt_high_explosive": "TNT 高能炸药",
        },
    },
    "soft_copyright_refined_subway_blast": {
        "scene_label": "精细地铁入口爆炸（ALE/FSI）",
        "ale_bounds": {"min": [-6.0, -6.0, -4.5], "max": [11.6, 9.0, 8.3950406]},
        "labels": {
            "diagnostic_soil_ground": "诊断地基土体",
            "escalator_1_balustrade": "1 号扶梯栏板",
            "escalator_1_handrails": "1 号扶梯扶手",
            "escalator_1_step_band": "1 号扶梯梯级带",
            "escalator_1_truss_guides": "1 号扶梯桁架导轨",
            "escalator_2_balustrade": "2 号扶梯栏板",
            "escalator_2_handrails": "2 号扶梯扶手",
            "escalator_2_step_band": "2 号扶梯梯级带",
            "escalator_2_truss_guides": "2 号扶梯桁架导轨",
            "fixed_stair_A": "固定楼梯 A",
            "fixed_stair_distribution_rebar": "楼梯分布钢筋",
            "fixed_stair_local_rebar": "楼梯局部钢筋",
            "fixed_stair_rebar": "楼梯主筋",
            "landing_rebar": "平台钢筋",
            "lower_landing_8": "下部平台",
            "pavilion_frame": "入口亭框架",
            "pavilion_glazing": "入口亭玻璃幕墙",
            "pavilion_opaque_solid_roof": "入口亭实体屋面",
            "pavilion_rc_plinth": "入口亭钢筋混凝土基座",
            "plinth_rebar": "基座钢筋",
            "rc_box_floor": "地下箱体底板",
            "rc_box_roof": "地下箱体顶板",
            "rc_box_wall": "地下箱体侧墙",
            "slab_rebar": "箱体板钢筋",
            "upper_landing": "上部平台",
            "wall_rebar": "箱体墙钢筋",
            "ale_air_tnt_domain": "ALE 空气-TNT 耦合域",
            "tnt_high_explosive": "TNT 高能炸药",
        },
    },
}


def main() -> None:
    for project_name, config in PROJECTS.items():
        project_dir = PROJECTS_ROOT / project_name
        model_path = project_dir / "model.json"
        manifest_path = project_dir / "manifest.json"
        model = json.loads(model_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        labels = config["labels"]
        components = [
            {
                "part_id": int(part_id),
                "id": labels.get(component_id, component_id),
                "source_component_id": component_id,
            }
            for component_id, part_id in manifest["part_ids"]
        ]
        charge = manifest["charge"]
        model["metadata"] = {
            "scene_label": config["scene_label"],
            "components": components,
            "blast_sources": [
                {
                    "kind": "ale_explosive_volume",
                    "label": f"{charge['mass_kg']:g} kg TNT 装药",
                    "position_m": charge["position_m"],
                    "radius_m": charge["radius_m"],
                    "mass_kg": charge["mass_kg"],
                    "detonation_time_s": charge["detonation_time_s"],
                }
            ],
            "ale_domain": {
                "part_id": 9001,
                "bounds_m": config["ale_bounds"],
                "label": "ALE 空气-TNT 耦合域",
            },
            "fsi": {
                "slave_segment_count": manifest["fsi_slave_segment_count"],
                "ground_segment_count": manifest["ground_fsi_segment_count"],
                "total_segment_count": manifest["total_fsi_segment_count"],
            },
            "mesh_statistics": {
                "node_count": manifest["total_node_count"],
                "element_count": manifest["total_element_count"],
                "ale_node_count": manifest["ale_node_count"],
                "ale_element_count": manifest["ale_element_count"],
            },
        }
        model_path.write_text(
            json.dumps(model, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"updated {project_name}: {len(components)} components")


if __name__ == "__main__":
    main()
