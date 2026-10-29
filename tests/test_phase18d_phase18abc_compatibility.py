from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lsprepost_mcp.component_library import (
    component_definition,
    default_component_geometry,
)
from lsprepost_mcp.config import MODEL_LIBRARY_DIR
from lsprepost_mcp.model_library import validate_model_resource
from lsprepost_mcp.refined_building import (
    compile_refined_building,
    default_building_definition,
)
from lsprepost_mcp.tool_structural_resources import (
    tool_validate_phase18_resource_review,
)


LEGACY_BUILDING_SNAPSHOT = {
    "commercial_supermarket": {
        "length_m": 22.0,
        "width_m": 18.0,
        "height_m": 8.0,
        "wall_thickness_m": 0.25,
        "entrance_width_m": 6.0,
        "entrance_height_m": 3.2,
    },
    "residential_community": {
        "tower_length_m": 8.0,
        "tower_width_m": 10.0,
        "tower_height_m": 18.0,
        "tower_count": 3,
        "tower_spacing_m": 4.0,
        "wall_thickness_m": 0.20,
        "balcony_depth_m": 1.2,
    },
    "subway_entrance": {
        "length_m": 6.0,
        "width_m": 4.0,
        "platform_height_m": 0.3,
        "enclosure_height_m": 2.8,
        "wall_thickness_m": 0.2,
        "roof_thickness_m": 0.2,
    },
}

PHASE18C_FINGERPRINTS = {
    "rc_frame": "48289fc948abd6cd9d6b1df627405a5cee8f91ad35d537321ed22b7a17baa03b",
    "rc_frame_shear_wall": "4f4fd26f4fac7ca607555805f89505b07c79b9752cd0589227067c53bcef6723",
    "steel_frame": "07d1119cdc7bf23848ede68acd644bedaac9594044f682a8fb0c981e5151f150",
    "steel_concrete_hybrid": "8adc42e4beeb973a1515f03e1734a8c782e978d76c322ba4c1b09b90ea3978cf",
    "rc_box": "fa4be2c35728d340da3ea6b97cf259678c018f6cac2f651c76f4ae1ecb6e8262",
}

COMPONENT_ALIAS_PAIRS = (
    ("2k_complete_reference", "two_storey_rc_frame_blast_reference"),
    ("2k_rc_beam_reference", "two_storey_rc_frame_beam_reference"),
    ("2k_rc_column_reference", "two_storey_rc_frame_column_reference"),
    ("2k_rc_slab_reference", "two_storey_rc_frame_slab_reference"),
    ("2k_rc_base_reference", "two_storey_rc_frame_foundation_reference"),
)

NODE_WIDTHS = (8, 16, 16, 16, 8, 8)
SOLID_IDENTITY_WIDTHS = (8, 8)
SOLID_CONNECTIVITY_WIDTHS = (8,) * 10
BEAM_WIDTHS = (8,) * 10


def _record(values: tuple[object, ...], widths: tuple[int, ...], syntax: str) -> str:
    rendered = tuple("" if value is None else str(value) for value in values)
    if syntax == "comma":
        return ",".join(rendered)
    if syntax == "whitespace":
        return " ".join(rendered)
    if syntax == "fixed":
        return "".join(value.rjust(width) for value, width in zip(rendered, widths))
    raise AssertionError(f"unknown test syntax: {syntax}")


def _model_deck(
    syntax: str,
    *,
    node_line: str | None = None,
    solid_identity_line: str | None = None,
    solid_connectivity_line: str | None = None,
    beam_line: str | None = None,
) -> str:
    solid_identity = solid_identity_line or _record((1, 1), SOLID_IDENTITY_WIDTHS, syntax)
    solid_connectivity = solid_connectivity_line or _record(
        tuple(range(1, 11)), SOLID_CONNECTIVITY_WIDTHS, syntax
    )
    beam = beam_line or _record((2, 1, 1, 2, 3, 0, 0, 0, 0, 2), BEAM_WIDTHS, syntax)
    nodes = []
    for node_id in range(1, 11):
        values = (
            node_id,
            "-1.25" if node_id == 1 else node_id,
            "2.5e1" if node_id == 1 else 0,
            "-3E-2" if node_id == 1 else 0,
            0,
            0,
        )
        nodes.append(node_line if node_id == 1 and node_line is not None else _record(values, NODE_WIDTHS, syntax))
    return "\n".join(
        (
            "*KEYWORD",
            "*ELEMENT_SOLID (TEN NODES FORMAT)",
            solid_identity,
            solid_connectivity,
            "*ELEMENT_BEAM",
            beam,
            "*NODE",
            *nodes,
            "*END",
            "",
        )
    )


class Phase18DPhase18ABCCompatibilityTests(unittest.TestCase):
    def _validate_fixture(
        self,
        deck: str,
        *,
        resource_updates: dict[str, object] | None = None,
        remove_resource_keys: tuple[str, ...] = (),
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory(dir=MODEL_LIBRARY_DIR) as temporary_directory:
            root = Path(temporary_directory)
            payload_path = root / "fixture.k.gz"
            with gzip.open(payload_path, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(deck)
            resource: dict[str, object] = {
                "id": "phase18d_compatibility_fixture",
                "_resource_dir": str(root),
                "payload": {
                    "path": payload_path.name,
                    "sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
                },
                "node_count": 10,
                "solid_count": 1,
                "beam_count": 1,
            }
            for key in remove_resource_keys:
                resource.pop(key, None)
            if resource_updates:
                resource.update(copy.deepcopy(resource_updates))
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(resource), encoding="utf-8")
            with patch("lsprepost_mcp.model_library._manifest_files", return_value=[manifest_path]):
                return validate_model_resource("phase18d_compatibility_fixture")

    def test_legacy_building_catalog_contract_is_unchanged(self) -> None:
        for template_id, expected_geometry in LEGACY_BUILDING_SNAPSHOT.items():
            with self.subTest(template_id=template_id):
                definition = component_definition(template_id)
                self.assertEqual("shell", definition.element_family)
                self.assertEqual(expected_geometry, default_component_geometry(template_id))

    def test_phase18d_does_not_change_phase18c_default_fingerprints(self) -> None:
        for system_id, expected_fingerprint in PHASE18C_FINGERPRINTS.items():
            with self.subTest(system_id=system_id):
                definition = default_building_definition(structural_system=system_id)
                self.assertEqual(
                    expected_fingerprint,
                    compile_refined_building(definition).fingerprint,
                )

    def test_phase18_resource_review_and_fixed_component_aliases_remain_valid(self) -> None:
        self.assertTrue(tool_validate_phase18_resource_review({})["valid"])
        for alias, canonical in COMPONENT_ALIAS_PAIRS:
            with self.subTest(alias=alias, canonical=canonical):
                canonical_report = validate_model_resource(canonical)
                alias_report = validate_model_resource(alias)
                self.assertTrue(canonical_report["valid"])
                self.assertTrue(alias_report["valid"])
                self.assertEqual(
                    canonical_report["payload_sha256"],
                    alias_report["payload_sha256"],
                )

    def test_complete_reference_package_validates_its_real_fixed_width_payload(self) -> None:
        report = validate_model_resource("two_storey_rc_frame_blast_reference")

        self.assertTrue(report["valid"])
        self.assertEqual(461452, report["node_count"])
        self.assertEqual(286840, report["solid_count"])
        self.assertEqual(61961, report["beam_count"])

    def test_model_validation_rejects_conflicting_flat_and_nested_mesh_counts(self) -> None:
        from lsprepost_mcp.model_library import get_model_resource

        resource = copy.deepcopy(get_model_resource("two_storey_rc_frame_beam_reference"))
        resource["mesh_statistics"] = {
            "nodes": int(resource["node_count"]) + 1,
            "solid_elements": resource["solid_count"],
            "beam_elements": resource["beam_count"],
        }

        with patch("lsprepost_mcp.model_library.get_model_resource", return_value=resource):
            with self.assertRaisesRegex(ValueError, "conflicting node count"):
                validate_model_resource("two_storey_rc_frame_beam_reference")

    def test_model_validation_accepts_all_supported_record_syntaxes(self) -> None:
        for syntax in ("comma", "fixed", "whitespace"):
            with self.subTest(syntax=syntax):
                report = self._validate_fixture(_model_deck(syntax))

                self.assertTrue(report["valid"])
                self.assertEqual(10, report["node_count"])
                self.assertEqual(1, report["solid_count"])
                self.assertEqual(1, report["beam_count"])

    def test_model_validation_rejects_duplicate_node_ids(self) -> None:
        for syntax in ("comma", "fixed", "whitespace"):
            with self.subTest(syntax=syntax):
                duplicate = _record((1, 0, 0, 0, 0, 0), NODE_WIDTHS, syntax)
                deck = _model_deck(syntax).replace("*END\n", f"{duplicate}\n*END\n")

                with self.assertRaisesRegex(ValueError, "duplicate node ID"):
                    self._validate_fixture(deck)

    def test_model_validation_rejects_zero_or_negative_node_ids(self) -> None:
        for syntax in ("comma", "fixed", "whitespace"):
            for node_id in (0, -1):
                with self.subTest(syntax=syntax, node_id=node_id):
                    invalid = _record((node_id, 0, 0, 0, 0, 0), NODE_WIDTHS, syntax)
                    deck = _model_deck(syntax).replace("*END\n", f"{invalid}\n*END\n")

                    with self.assertRaisesRegex(ValueError, "node ID must be positive"):
                        self._validate_fixture(deck, resource_updates={"node_count": 11})

    def test_model_validation_rejects_duplicate_solid_element_ids(self) -> None:
        for syntax in ("comma", "fixed", "whitespace"):
            with self.subTest(syntax=syntax):
                duplicate_identity = _record((1, 1), SOLID_IDENTITY_WIDTHS, syntax)
                connectivity = _record(
                    tuple(range(1, 11)), SOLID_CONNECTIVITY_WIDTHS, syntax
                )
                deck = _model_deck(syntax).replace(
                    "*ELEMENT_BEAM\n",
                    f"{duplicate_identity}\n{connectivity}\n*ELEMENT_BEAM\n",
                )

                with self.assertRaisesRegex(ValueError, "duplicate element ID"):
                    self._validate_fixture(deck, resource_updates={"solid_count": 2})

    def test_model_validation_rejects_zero_or_negative_solid_element_ids(self) -> None:
        for syntax in ("comma", "fixed", "whitespace"):
            for element_id in (0, -1):
                with self.subTest(syntax=syntax, element_id=element_id):
                    identity = _record((element_id, 1), SOLID_IDENTITY_WIDTHS, syntax)

                    with self.assertRaisesRegex(ValueError, "element ID must be positive"):
                        self._validate_fixture(
                            _model_deck(syntax, solid_identity_line=identity)
                        )

    def test_model_validation_rejects_duplicate_beam_element_ids(self) -> None:
        for syntax in ("comma", "fixed", "whitespace"):
            with self.subTest(syntax=syntax):
                duplicate = _record(
                    (2, 1, 1, 2, 3, 0, 0, 0, 0, 2), BEAM_WIDTHS, syntax
                )
                deck = _model_deck(syntax).replace("*NODE\n", f"{duplicate}\n*NODE\n")

                with self.assertRaisesRegex(ValueError, "duplicate element ID"):
                    self._validate_fixture(deck, resource_updates={"beam_count": 2})

    def test_model_validation_rejects_zero_or_negative_beam_element_ids(self) -> None:
        for syntax in ("comma", "fixed", "whitespace"):
            for element_id in (0, -1):
                with self.subTest(syntax=syntax, element_id=element_id):
                    beam = _record(
                        (element_id, 1, 1, 2, 3, 0, 0, 0, 0, 2), BEAM_WIDTHS, syntax
                    )

                    with self.assertRaisesRegex(ValueError, "element ID must be positive"):
                        self._validate_fixture(_model_deck(syntax, beam_line=beam))

    def test_model_validation_rejects_element_ids_reused_across_families(self) -> None:
        for syntax in ("comma", "fixed", "whitespace"):
            with self.subTest(syntax=syntax):
                beam = _record((1, 1, 1, 2, 3, 0, 0, 0, 0, 2), BEAM_WIDTHS, syntax)

                with self.assertRaisesRegex(ValueError, "duplicate element ID"):
                    self._validate_fixture(_model_deck(syntax, beam_line=beam))

    def test_model_validation_distinguishes_padded_whitespace_from_fixed_width(self) -> None:
        node = "1 -1.25 2.5e1 -3E-2 0 0".ljust(sum(NODE_WIDTHS))

        report = self._validate_fixture(_model_deck("whitespace", node_line=node))

        self.assertTrue(report["valid"])

    def test_model_validation_accepts_long_and_fixed_boundary_whitespace_records(self) -> None:
        long_coordinate = "0." + ("1" * 80)
        cases = (
            (
                "long_coordinate",
                f"1 {long_coordinate} 2e0 -3e-1 0 0",
                _record(tuple(range(1, 11)), SOLID_CONNECTIVITY_WIDTHS, "whitespace"),
                _record((2, 1, 1, 2, 3), BEAM_WIDTHS[:5], "whitespace"),
            ),
            (
                "eight_digit_id_padded_to_fixed_total",
                "12345678 -1 2 3 0 0".ljust(sum(NODE_WIDTHS)),
                "12345678 2 3 4 5 6 7 8 9 10",
                "2 1 12345678 2 3",
            ),
        )
        for label, node, connectivity, beam in cases:
            with self.subTest(case=label):
                self.assertTrue(
                    self._validate_fixture(
                        _model_deck(
                            "whitespace",
                            node_line=node,
                            solid_connectivity_line=connectivity,
                            beam_line=beam,
                        )
                    )["valid"]
                )

    def test_model_validation_rejects_empty_required_fixed_width_fields(self) -> None:
        malformed_records = (
            (
                "node_x",
                {"node_line": _record((1, None, 2, 3, 0, 0), NODE_WIDTHS, "fixed")},
                "invalid node record",
            ),
            (
                "beam_n1",
                {"beam_line": _record((2, 1, None, 2, 3, 0, 0, 0, 0, 2), BEAM_WIDTHS, "fixed")},
                "invalid beam record",
            ),
            (
                "hybrid_node_x",
                {
                    "node_line": (
                        str(1).rjust(NODE_WIDTHS[0])
                        + ("".rjust(NODE_WIDTHS[1]))
                        + "2 3 0 0".ljust(sum(NODE_WIDTHS[2:]))
                    )
                },
                "invalid node record",
            ),
        )
        for label, replacement, expected_error in malformed_records:
            with self.subTest(record=label):
                with self.assertRaisesRegex(ValueError, expected_error):
                    self._validate_fixture(_model_deck("fixed", **replacement))

    def test_model_validation_rejects_ambiguous_fixed_width_and_whitespace_semantics(self) -> None:
        ambiguous_node = "12345678 " + ("1" * 47) + " 2345678 3456789"
        self.assertEqual(sum(NODE_WIDTHS), len(ambiguous_node))

        with self.assertRaisesRegex(ValueError, "invalid node record"):
            self._validate_fixture(
                _model_deck(
                    "whitespace",
                    node_line=ambiguous_node,
                    solid_connectivity_line="12345678 2 3 4 5 6 7 8 9 10",
                    beam_line="2 1 12345678 2 3",
                )
            )

    def test_model_validation_rejects_extra_or_trailing_record_data(self) -> None:
        fixed_node = _record((1, -1, 2, 3, 0, 0), NODE_WIDTHS, "fixed")
        fixed_beam = _record((2, 1, 1, 2, 3, 0, 0, 0, 0, 2), BEAM_WIDTHS, "fixed")
        fixed_identity = _record((1, 1), SOLID_IDENTITY_WIDTHS, "fixed")
        fixed_connectivity = _record(tuple(range(1, 11)), SOLID_CONNECTIVITY_WIDTHS, "fixed")
        malformed_records = (
            ("node_comma_extra", "comma", {"node_line": "1,-1,2,3,0,0,9"}, "invalid node record"),
            ("node_whitespace_extra", "whitespace", {"node_line": "1 -1 2 3 0 0 9"}, "invalid node record"),
            ("node_comma_attached_tail", "comma", {"node_line": "1,-1,2,3,0,0junk"}, "invalid node record"),
            ("node_fixed_tail", "fixed", {"node_line": fixed_node + "X"}, "invalid node record"),
            (
                "node_fixed_overwide_id",
                "fixed",
                {"node_line": _record((123456789, -1, 2, 3, 0, 0), NODE_WIDTHS, "fixed")},
                "invalid node record",
            ),
            (
                "node_fixed_overwide_id_with_blank_last_field",
                "fixed",
                {"node_line": _record((123456789, -1, 2, 3, 0, None), NODE_WIDTHS, "fixed")},
                "invalid node record",
            ),
            (
                "node_fixed_overwide_id_with_full_following_fields",
                "fixed",
                {
                    "node_line": _record(
                        (
                            123456789,
                            "1234567890123456",
                            "2234567890123456",
                            "3234567890123456",
                            "12345678",
                            None,
                        ),
                        NODE_WIDTHS,
                        "fixed",
                    )
                },
                "invalid node record",
            ),
            (
                "beam_fixed_overwide_id",
                "fixed",
                {"beam_line": _record((123456789, 1, 1, 2, 3, 0, 0, 0, 0, 2), BEAM_WIDTHS, "fixed")},
                "invalid beam record",
            ),
            ("beam_comma_extra", "comma", {"beam_line": "2,1,1,2,3,0,0,0,0,2,9"}, "invalid beam record"),
            ("beam_whitespace_tail", "whitespace", {"beam_line": "2 1 1 2 3 0 0 0 0 2 junk"}, "invalid beam record"),
            ("beam_fixed_tail", "fixed", {"beam_line": fixed_beam + "X"}, "invalid beam record"),
            (
                "solid_identity_fixed_overwide_id",
                "fixed",
                {"solid_identity_line": _record((123456789, 1), SOLID_IDENTITY_WIDTHS, "fixed")},
                "invalid solid identity record",
            ),
            (
                "solid_identity_fixed_tail",
                "fixed",
                {"solid_identity_line": fixed_identity + "X"},
                "invalid solid identity record",
            ),
            (
                "solid_connectivity_fixed_tail",
                "fixed",
                {"solid_connectivity_line": fixed_connectivity + "X"},
                "invalid solid connectivity record",
            ),
        )
        for label, syntax, replacement, expected_error in malformed_records:
            with self.subTest(record=label):
                with self.assertRaisesRegex(ValueError, expected_error):
                    self._validate_fixture(_model_deck(syntax, **replacement))

    def test_model_validation_rejects_non_finite_node_coordinates(self) -> None:
        for coordinate in (math.nan, math.inf, -math.inf, "1e309"):
            with self.subTest(coordinate=coordinate):
                node = _record((1, coordinate, 2, 3, 0, 0), NODE_WIDTHS, "comma")
                with self.assertRaisesRegex(ValueError, "invalid node record"):
                    self._validate_fixture(_model_deck("comma", node_line=node))

    def test_model_validation_rejects_invalid_flat_and_nested_mesh_counts(self) -> None:
        count_fields = (
            ("node_count", "nodes", 10),
            ("solid_count", "solid_elements", 1),
            ("beam_count", "beam_elements", 1),
        )
        invalid_values = (
            True,
            None,
            -1,
            -0.5,
            1.5,
            "-1",
            "-0.5",
            "1.5",
            "1e0",
            "+1",
            " 1",
            "1 ",
            math.nan,
            math.inf,
            -math.inf,
        )
        nested_defaults = {"nodes": 10, "solid_elements": 1, "beam_elements": 1}
        for flat_key, nested_key, _ in count_fields:
            label = flat_key.removesuffix("_count")
            for location in ("flat", "nested"):
                for invalid_value in invalid_values:
                    with self.subTest(field=flat_key, location=location, value=invalid_value):
                        if location == "flat":
                            updates = {
                                flat_key: invalid_value,
                                "mesh_statistics": dict(nested_defaults),
                            }
                            remove_keys: tuple[str, ...] = ()
                        else:
                            nested = dict(nested_defaults)
                            nested[nested_key] = invalid_value
                            updates = {"mesh_statistics": nested}
                            remove_keys = ()
                        with self.assertRaisesRegex(ValueError, f"invalid {label} count"):
                            self._validate_fixture(
                                _model_deck("comma"),
                                resource_updates=updates,
                                remove_resource_keys=remove_keys,
                            )

    def test_model_validation_accepts_integral_float_and_decimal_string_mesh_counts(self) -> None:
        report = self._validate_fixture(
            _model_deck("comma"),
            resource_updates={
                "node_count": 10.0,
                "solid_count": "1",
                "beam_count": 1.0,
            },
        )

        self.assertTrue(report["valid"])

    def test_model_validation_rejects_explicit_null_mesh_statistics(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid mesh_statistics"):
            self._validate_fixture(
                _model_deck("comma"),
                resource_updates={"mesh_statistics": None},
            )

    def test_model_validation_rejects_missing_or_conflicting_mesh_counts(self) -> None:
        count_fields = (
            ("node_count", "nodes", "node", 10),
            ("solid_count", "solid_elements", "solid", 1),
            ("beam_count", "beam_elements", "beam", 1),
        )
        nested_defaults = {"nodes": 10, "solid_elements": 1, "beam_elements": 1}
        for flat_key, nested_key, label, expected in count_fields:
            with self.subTest(field=flat_key, case="missing"):
                with self.assertRaisesRegex(ValueError, f"no {label} count metadata"):
                    self._validate_fixture(
                        _model_deck("comma"),
                        remove_resource_keys=(flat_key,),
                    )
            with self.subTest(field=flat_key, case="conflict"):
                nested = dict(nested_defaults)
                nested[nested_key] = expected + 1
                with self.assertRaisesRegex(ValueError, f"conflicting {label} count metadata"):
                    self._validate_fixture(
                        _model_deck("comma"),
                        resource_updates={"mesh_statistics": nested},
                    )


if __name__ == "__main__":
    unittest.main()
