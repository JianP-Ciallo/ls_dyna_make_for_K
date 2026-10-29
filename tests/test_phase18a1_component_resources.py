from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from lsprepost_mcp.component_model_resources import (
    COMPONENT_RESOURCE_SPECS,
    component_resource_spec,
    write_component_resource_packages,
)
from lsprepost_mcp.keyword_decomposition import decompose_keyword_deck
from lsprepost_mcp.keyword_decomposition import _integer, _keyword_token, _numbers
from lsprepost_mcp.model_library import export_model_resource, get_model_resource, load_model_resources, validate_model_resource
from lsprepost_mcp.component_resource_adapter import ResourceIdNamespace, instantiate_model_resource
from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.schema import default_model_spec, parse_model_spec


SOURCE_2K = Path("E:/Desktop/2.k")
SOURCE_SHA256 = "c1c02a9e832852854b47cd3720bc9348cf48989484d25e1a54036836d0697a22"


class ComponentResourceContractTests(unittest.TestCase):
    @staticmethod
    def _write_manifest(path: Path, resource_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": resource_id}), encoding="utf-8")

    def test_nested_model_manifest_is_discovered_by_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_manifest(root / "components" / "phase18" / "2k" / "beam" / "manifest.json", "stable_beam")

            resources = load_model_resources(root)
            self.assertIn("stable_beam", resources)
            self.assertEqual("components", resources["stable_beam"]["library_section"])

    def test_duplicate_model_resource_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_manifest(root / "references" / "one" / "manifest.json", "duplicate")
            self._write_manifest(root / "components" / "two" / "manifest.json", "duplicate")

            with self.assertRaisesRegex(ValueError, "duplicate model resource id 'duplicate'"):
                load_model_resources(root)

    def test_combined_component_specs_cover_structural_parts_once(self) -> None:
        specs = list(COMPONENT_RESOURCE_SPECS.values())

        self.assertEqual(
            {
                "two_storey_rc_frame_beam_reference",
                "two_storey_rc_frame_column_reference",
                "two_storey_rc_frame_slab_reference",
                "two_storey_rc_frame_foundation_reference",
            },
            {spec.resource_id for spec in specs},
        )
        self.assertEqual(126290, sum(spec.solid_count for spec in specs))
        self.assertEqual(61961, sum(spec.beam_count for spec in specs))
        self.assertEqual(
            [201, 202, 203, 301, 302, 303, 401, 402, 501, 502],
            sorted(pid for spec in specs for pid in spec.part_ids),
        )

    def test_specs_keep_rebar_material_section_and_coupling_closures(self) -> None:
        expected = {
            "two_storey_rc_frame_beam_reference": ((201, 202, 203), (4, 3, 1), (5, 14, 8), (1,), (1, 201, 0, 1)),
            "two_storey_rc_frame_column_reference": ((301, 302, 303), (4, 2, 1), (5, 12, 8), (2,), (2, 301, 0, 1)),
            "two_storey_rc_frame_slab_reference": ((401, 402), (4, 2), (5, 12), (), (402, 401, 1, 1)),
            "two_storey_rc_frame_foundation_reference": ((501, 502), (4, 6), (5, 8), (6,), (6, 501, 0, 1)),
        }

        for resource_id, closure in expected.items():
            with self.subTest(resource_id=resource_id):
                spec = component_resource_spec(resource_id)
                self.assertEqual(closure[0], spec.part_ids)
                self.assertEqual(closure[1], spec.section_ids)
                self.assertEqual(closure[2], spec.material_ids)
                self.assertEqual(closure[3], spec.set_ids)
                self.assertEqual(closure[4], spec.coupling)

    def test_unknown_component_resource_is_rejected_with_known_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "2k_rc_beam_reference"):
            component_resource_spec("missing")


@unittest.skipUnless(SOURCE_2K.is_file(), "audited E:/Desktop/2.k is unavailable")
class ComponentPackageWriterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.output_root = Path(cls.temp.name) / "components"
        cls.report = decompose_keyword_deck(SOURCE_2K, "tonne_mm_s_N_MPa")
        cls.written = write_component_resource_packages(cls.report, cls.output_root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_writes_four_si_component_manifests_with_exact_counts(self) -> None:
        self.assertEqual(set(COMPONENT_RESOURCE_SPECS), set(self.written))
        for resource_id, spec in COMPONENT_RESOURCE_SPECS.items():
            with self.subTest(resource_id=resource_id):
                package = self.output_root / resource_id
                manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
                payload = package / manifest["payload"]["path"]
                digest = hashlib.sha256(payload.read_bytes()).hexdigest()

                self.assertEqual("SI_m_s_kg_N_Pa", manifest["unit_system"])
                self.assertEqual(SOURCE_SHA256, manifest["provenance"]["source_sha256"])
                self.assertEqual("source_reference", manifest["validation_status"])
                self.assertTrue(manifest["requires_project_review"])
                self.assertEqual(spec.part_ids, tuple(manifest["source_part_ids"]))
                self.assertEqual(spec.solid_count, manifest["solid_count"])
                self.assertEqual(spec.beam_count, manifest["beam_count"])
                self.assertEqual(digest, manifest["payload"]["sha256"])
                self.assertTrue((package / "audit.json").is_file())

    def test_ten_node_solids_keep_solver_keyword_and_two_line_records(self) -> None:
        for resource_id, spec in COMPONENT_RESOURCE_SPECS.items():
            with self.subTest(resource_id=resource_id):
                payload = self.output_root / resource_id / "component.k.gz"
                active = ""
                expecting_connectivity = False
                solid_count = 0
                solid_keyword = ""
                with gzip.open(payload, "rt", encoding="utf-8", errors="strict") as handle:
                    for line in handle:
                        stripped = line.strip()
                        if stripped.startswith("*"):
                            if active == "*ELEMENT_SOLID":
                                self.assertFalse(expecting_connectivity)
                            active = stripped.split()[0].upper()
                            if active == "*ELEMENT_SOLID":
                                solid_keyword = stripped
                            continue
                        if active != "*ELEMENT_SOLID" or not stripped or stripped.startswith("$"):
                            continue
                        fields = [field.strip() for field in stripped.split(",")]
                        if not expecting_connectivity:
                            self.assertEqual(2, len(fields))
                            int(fields[0])
                            int(fields[1])
                            expecting_connectivity = True
                            solid_count += 1
                        else:
                            self.assertEqual(10, len(fields))
                            self.assertTrue(all(int(value) >= 0 for value in fields))
                            expecting_connectivity = False

                self.assertEqual("*ELEMENT_SOLID (ten nodes format)", solid_keyword)
                self.assertFalse(expecting_connectivity)
                self.assertEqual(spec.solid_count, solid_count)

    def test_each_payload_is_standalone_and_reference_closed(self) -> None:
        for resource_id, spec in COMPONENT_RESOURCE_SPECS.items():
            with self.subTest(resource_id=resource_id):
                payload = self.output_root / resource_id / "component.k.gz"
                active = ""
                nodes: set[int] = set()
                references: set[int] = set()
                part_ids: set[int] = set()
                solid_rows = beam_rows = 0
                beam_orientation_nodes: set[int] = set()
                keywords: list[str] = []
                pending_solid = False
                with gzip.open(payload, "rt", encoding="utf-8", errors="strict") as handle:
                    for line in handle:
                        stripped = line.strip()
                        if stripped.startswith("*"):
                            if active == "*ELEMENT_SOLID":
                                self.assertFalse(pending_solid)
                            active = stripped.split()[0].upper()
                            keywords.append(active)
                            pending_solid = False
                            continue
                        if not stripped or stripped.startswith("$"):
                            continue
                        fields = [field.strip() for field in stripped.split(",")]
                        if active == "*NODE":
                            nodes.add(int(fields[0]))
                            self.assertLess(abs(float(fields[1])), 100.0)
                            self.assertLess(abs(float(fields[2])), 100.0)
                            self.assertLess(abs(float(fields[3])), 100.0)
                        elif active == "*ELEMENT_BEAM":
                            beam_rows += 1
                            part_ids.add(int(fields[1]))
                            references.update((int(fields[2]), int(fields[3]), int(fields[4])))
                            beam_orientation_nodes.add(int(fields[4]))
                        elif active == "*ELEMENT_SOLID":
                            if not pending_solid:
                                self.assertEqual(2, len(fields))
                                solid_rows += 1
                                part_ids.add(int(fields[1]))
                                pending_solid = True
                            else:
                                self.assertEqual(10, len(fields))
                                references.update(int(value) for value in fields if int(value) != 0)
                                pending_solid = False

                self.assertEqual("*KEYWORD", keywords[0])
                self.assertEqual("*END", keywords[-1])
                self.assertEqual(spec.part_ids, tuple(sorted(part_ids)))
                self.assertEqual(spec.solid_count, solid_rows)
                self.assertEqual(spec.beam_count, beam_rows)
                self.assertTrue(beam_orientation_nodes)
                self.assertFalse(references - nodes)
                self.assertNotIn(1001, part_ids)
                self.assertNotIn(1002, part_ids)

    def test_four_payloads_are_an_exact_disjoint_reassembly_of_structural_elements_and_nodes(self) -> None:
        package_rows: dict[tuple[str, int], tuple[int, ...]] = {}
        package_nodes: dict[int, tuple[float, float, float]] = {}
        package_keys: list[set[tuple[str, int]]] = []

        for resource_id, spec in COMPONENT_RESOURCE_SPECS.items():
            active = ""
            data_index = 0
            pending_solid: tuple[int, int] | None = None
            keys: set[tuple[str, int]] = set()
            part_bindings: dict[int, tuple[int, int]] = {}
            coupling: tuple[int, int, int, int] | None = None
            payload = self.output_root / resource_id / "component.k.gz"
            with gzip.open(payload, "rt", encoding="utf-8", errors="strict") as handle:
                for line in handle:
                    stripped = line.strip()
                    if stripped.startswith("*"):
                        if active == "*ELEMENT_SOLID":
                            self.assertIsNone(pending_solid)
                        active = stripped.split()[0].upper()
                        data_index = 0
                        pending_solid = None
                        continue
                    if not stripped or stripped.startswith("$"):
                        continue
                    fields = [field.strip() for field in stripped.split(",")]
                    try:
                        int(float(fields[0]))
                    except ValueError:
                        continue
                    if active == "*ELEMENT_SOLID":
                        if pending_solid is None:
                            self.assertEqual(2, len(fields))
                            pending_solid = (int(fields[0]), int(fields[1]))
                        else:
                            self.assertEqual(10, len(fields))
                            row = (*pending_solid, *(int(value) for value in fields))
                            key = (active, row[0])
                            self.assertNotIn(key, package_rows)
                            package_rows[key] = row
                            keys.add(key)
                            pending_solid = None
                    elif active == "*ELEMENT_BEAM":
                        row = tuple(int(value) for value in fields)
                        key = (active, row[0])
                        self.assertNotIn(key, package_rows)
                        package_rows[key] = row
                        keys.add(key)
                    elif active == "*NODE":
                        nid = int(fields[0])
                        coordinates = tuple(float(value) for value in fields[1:4])
                        if nid in package_nodes:
                            self.assertEqual(package_nodes[nid], coordinates)
                        package_nodes[nid] = coordinates  # type: ignore[assignment]
                    elif active == "*PART" and data_index == 0:
                        part_bindings[int(fields[0])] = (int(fields[1]), int(fields[2]))
                    elif active == "*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE" and data_index == 0:
                        coupling = tuple(int(value) for value in fields[:4])  # type: ignore[assignment]
                    data_index += 1
            package_keys.append(keys)
            self.assertEqual(
                dict(zip(spec.part_ids, zip(spec.section_ids, spec.material_ids))),
                part_bindings,
            )
            self.assertEqual(spec.coupling, coupling)

        for index, left in enumerate(package_keys):
            for right in package_keys[index + 1:]:
                self.assertTrue(left.isdisjoint(right))

        source_rows: dict[tuple[str, int], tuple[int, ...]] = {}
        source_nodes: dict[int, tuple[float, float, float]] = {}
        active = ""
        pending_solid: tuple[int, int] | None = None
        selected_pids = {pid for spec in COMPONENT_RESOURCE_SPECS.values() for pid in spec.part_ids}
        with SOURCE_2K.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lstrip().startswith("*"):
                    active = _keyword_token(line)
                    pending_solid = None
                    continue
                if not line.strip() or line.lstrip().startswith("$"):
                    continue
                if active == "*ELEMENT_SOLID":
                    if pending_solid is None:
                        values = [_integer(value) for value in _numbers(line, (8, 8))]
                        if len(values) >= 2:
                            pending_solid = (values[0], values[1])
                        continue
                    eid, pid = pending_solid
                    pending_solid = None
                    if pid in selected_pids:
                        row = (eid, pid, *[_integer(value) for value in _numbers(line, (8,) * 10)])
                        source_rows[("*ELEMENT_SOLID", eid)] = row
                elif active == "*ELEMENT_BEAM":
                    values = [_integer(value) for value in _numbers(line, (8,) * 5)]
                    if len(values) >= 5 and values[1] in selected_pids:
                        source_rows[("*ELEMENT_BEAM", values[0])] = tuple(values[:5])
                elif active == "*NODE":
                    fields = _numbers(line, (8, 16, 16, 16))
                    if len(fields) >= 4:
                        nid = _integer(fields[0])
                        if nid in package_nodes:
                            source_nodes[nid] = tuple(float(fields[index]) * 0.001 for index in range(1, 4))  # type: ignore[assignment]

        self.assertEqual(source_rows, package_rows)
        self.assertEqual(set(package_nodes), set(source_nodes))
        for nid, coordinates in package_nodes.items():
            with self.subTest(nid=nid):
                for actual, expected in zip(coordinates, source_nodes[nid]):
                    self.assertAlmostEqual(expected, actual, places=11)

    def test_regeneration_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as second_directory:
            second_root = Path(second_directory) / "components"
            write_component_resource_packages(self.report, second_root)
            for resource_id in COMPONENT_RESOURCE_SPECS:
                for filename in ("manifest.json", "audit.json", "component.k.gz"):
                    with self.subTest(resource_id=resource_id, filename=filename):
                        first = self.output_root / resource_id / filename
                        second = second_root / resource_id / filename
                        self.assertEqual(first.read_bytes(), second.read_bytes())


class ComponentResourceLibraryTests(unittest.TestCase):
    def test_validates_audited_component_payload_against_manifest(self) -> None:
        result = validate_model_resource("2k_rc_beam_reference")

        self.assertTrue(result["valid"])
        self.assertEqual(6600, result["solid_count"])
        self.assertEqual(11540, result["beam_count"])
        self.assertEqual(6600, result["ten_node_solid_count"])
        self.assertEqual("SI_m_s_kg_N_Pa", result["unit_system"])
        self.assertEqual(SOURCE_SHA256, result["source_sha256"])

    def test_exports_one_component_as_an_independent_plain_k_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "beam_component.k"
            exported = export_model_resource("2k_rc_beam_reference", target)
            text = exported.read_text(encoding="utf-8")

        self.assertEqual(target, exported)
        self.assertTrue(text.startswith("*KEYWORD\n"))
        self.assertTrue(text.rstrip().endswith("*END"))
        self.assertIn("*ELEMENT_SOLID (ten nodes format)", text)
        self.assertIn("*ELEMENT_BEAM", text)

    def test_export_refuses_to_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "beam_component.k"
            target.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "beam_component.k"):
                export_model_resource("2k_rc_beam_reference", target)
            self.assertEqual("keep", target.read_text(encoding="utf-8"))


class ComponentResourceAdapterTests(unittest.TestCase):
    def _first_source_node(self, resource_id: str) -> tuple[int, float, float, float]:
        resource = get_model_resource(resource_id)
        payload = Path(resource["_resource_dir"]) / resource["payload"]["path"]
        active = ""
        with gzip.open(payload, "rt", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("*"):
                    active = stripped.split()[0].upper()
                elif active == "*NODE" and stripped and not stripped.startswith("$"):
                    fields = stripped.split(",")
                    return int(fields[0]), float(fields[1]), float(fields[2]), float(fields[3])
        raise AssertionError("resource has no node")

    def test_instantiation_applies_rigid_transform_and_all_id_offsets(self) -> None:
        source_nid, source_x, source_y, source_z = self._first_source_node("2k_rc_beam_reference")
        namespace = ResourceIdNamespace.from_offsets(
            node=1_000_000, element=2_000_000, part=3000,
            section=4000, material=5000, set_id=6000, curve=7000,
        )
        fragment = instantiate_model_resource(
            "2k_rc_beam_reference",
            transform={"translation_m": [2.0, 3.0, 4.0], "rotation_deg": [0.0, 0.0, 90.0]},
            id_namespace=namespace,
        )

        active = ""
        first_node = None
        part_ids: set[int] = set()
        coupling = None
        pending_solid = False
        saw_ten_node_keyword = False
        for line in fragment.keyword_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("*"):
                if active == "*ELEMENT_SOLID":
                    self.assertFalse(pending_solid)
                active = stripped.split()[0].upper()
                if stripped == "*ELEMENT_SOLID (ten nodes format)":
                    saw_ten_node_keyword = True
                pending_solid = False
                continue
            if not stripped or stripped.startswith("$"):
                continue
            fields = stripped.split(",")
            if active == "*NODE" and first_node is None:
                first_node = (int(fields[0]), *(float(value) for value in fields[1:4]))
            elif active == "*ELEMENT_SOLID":
                if not pending_solid:
                    self.assertEqual(2, len(fields))
                    part_ids.add(int(fields[1]))
                    self.assertGreaterEqual(int(fields[0]), 2_000_000)
                    pending_solid = True
                else:
                    self.assertEqual(10, len(fields))
                    self.assertTrue(all(int(value) >= 1_000_000 for value in fields if int(value)))
                    pending_solid = False
            elif active == "*ELEMENT_BEAM":
                part_ids.add(int(fields[1]))
                self.assertTrue(all(int(value) >= 1_000_000 for value in fields[2:5]))
            elif active == "*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE" and len(fields) == 8 and coupling is None:
                coupling = tuple(int(value) for value in fields[:4])

        self.assertIsNotNone(first_node)
        assert first_node is not None
        self.assertEqual(source_nid + 1_000_000, first_node[0])
        self.assertAlmostEqual(-source_y + 2.0, first_node[1], places=9)
        self.assertAlmostEqual(source_x + 3.0, first_node[2], places=9)
        self.assertAlmostEqual(source_z + 4.0, first_node[3], places=9)
        self.assertEqual({3201, 3202, 3203}, part_ids)
        self.assertEqual((6001, 3201, 0, 1), coupling)
        self.assertTrue(saw_ten_node_keyword)
        self.assertEqual(6600, fragment.metadata["solid_count"])
        self.assertEqual(11540, fragment.metadata["beam_count"])
        json.dumps(fragment.metadata)

    def test_two_instances_use_disjoint_namespaces_and_stable_fingerprints(self) -> None:
        first = instantiate_model_resource(
            "2k_rc_base_reference", {}, ResourceIdNamespace.from_offsets(node=1_000_000, element=2_000_000, part=3000, section=4000, material=5000, set_id=6000, curve=7000),
        )
        repeated = instantiate_model_resource(
            "2k_rc_base_reference", {}, ResourceIdNamespace.from_offsets(node=1_000_000, element=2_000_000, part=3000, section=4000, material=5000, set_id=6000, curve=7000),
        )
        second = instantiate_model_resource(
            "2k_rc_base_reference", {}, ResourceIdNamespace.from_offsets(node=31_000_000, element=32_000_000, part=33000, section=34000, material=35000, set_id=36000, curve=37000),
        )

        self.assertEqual(first.fingerprint, repeated.fingerprint)
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        self.assertLess(first.metadata["id_ranges"]["node"][1], second.metadata["id_ranges"]["node"][0])

    def test_rejects_non_rigid_or_non_finite_transform_and_material_downgrade(self) -> None:
        namespace = ResourceIdNamespace.from_offsets()
        invalid = (
            ({"scale": 2.0}, "unsupported transform"),
            ({"translation_m": [math.nan, 0.0, 0.0]}, "finite"),
        )
        for transform, message in invalid:
            with self.subTest(transform=transform):
                with self.assertRaisesRegex(ValueError, message):
                    instantiate_model_resource("2k_rc_slab_reference", transform, namespace)
        with self.assertRaisesRegex(ValueError, "material_binding"):
            instantiate_model_resource("2k_rc_slab_reference", {}, namespace, material_binding="drop_rebar")


class ExistingGenerationCompatibilityTests(unittest.TestCase):
    def test_resource_free_specs_keep_empty_additive_contract(self) -> None:
        for model_type in ("shell_plate", "solid_block", "single_solid_element_test"):
            with self.subTest(model_type=model_type):
                parsed = parse_model_spec(default_model_spec(f"baseline_{model_type}", model_type))
                keyword, metadata = build_keyword(parsed)
                self.assertEqual([], parsed.model_resources)
                self.assertNotIn("model_resource_instances", metadata)
                self.assertEqual(1, sum(1 for line in keyword.splitlines() if line.strip().upper() == "*END"))

    def test_common_dispatcher_attaches_component_resource_to_three_existing_model_types(self) -> None:
        for model_type in ("shell_plate", "solid_block", "single_solid_element_test"):
            with self.subTest(model_type=model_type):
                spec = default_model_spec(f"{model_type}_with_column_resource", model_type)
                spec["model_resources"] = [
                    {
                        "id": "column_1",
                        "model_resource_id": "2k_rc_column_reference",
                        "transform": {"translation_m": [1.0, 2.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]},
                        "material_binding": "source_reference",
                    }
                ]
                keyword, metadata = build_keyword(parse_model_spec(spec))

                self.assertIn("$ MODEL_RESOURCE_INSTANCE column_1 2k_rc_column_reference", keyword)
                self.assertEqual(1, metadata["model_resource_instance_count"])
                self.assertEqual("2k_rc_column_reference", metadata["model_resource_instances"][0]["resource_id"])
                self.assertEqual(6000, metadata["model_resource_instances"][0]["solid_count"])
                self.assertEqual(12546, metadata["model_resource_instances"][0]["beam_count"])
                self.assertEqual(1, sum(1 for line in keyword.splitlines() if line.strip().upper() == "*END"))

    def test_common_dispatcher_allocates_disjoint_ids_for_repeated_resources(self) -> None:
        spec = default_model_spec("two_base_resources", "solid_block")
        spec["model_resources"] = [
            {"id": "base_1", "model_resource_id": "2k_rc_base_reference"},
            {
                "id": "base_2",
                "model_resource_id": "2k_rc_base_reference",
                "transform": {"translation_m": [10.0, 0.0, 0.0]},
            },
        ]
        keyword, metadata = build_keyword(parse_model_spec(spec))
        first, second = metadata["model_resource_instances"]

        for kind in ("node", "element", "part", "section", "material", "set", "curve"):
            if first["id_ranges"][kind] is not None:
                self.assertLess(first["id_ranges"][kind][1], second["id_ranges"][kind][0])
        self.assertEqual(2, keyword.count("$ MODEL_RESOURCE_INSTANCE"))
        self.assertEqual(1, sum(1 for line in keyword.splitlines() if line.strip().upper() == "*END"))

    def test_schema_rejects_duplicate_instances_unknown_resources_and_extra_fields(self) -> None:
        base = default_model_spec("invalid_resource_refs", "shell_plate")
        valid = {
            "id": "beam_1",
            "model_resource_id": "2k_rc_beam_reference",
            "transform": {"translation_m": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]},
            "material_binding": "source_reference",
        }
        cases = (
            ([valid, dict(valid)], "duplicate model resource instance id"),
            ([{**valid, "model_resource_id": "missing"}], "unknown component model resource"),
            ([{**valid, "unexpected": 1}], "unsupported field"),
        )
        for refs, message in cases:
            with self.subTest(message=message):
                spec = dict(base)
                spec["model_resources"] = refs
                with self.assertRaisesRegex(ValueError, message):
                    parse_model_spec(spec)


if __name__ == "__main__":
    unittest.main()
