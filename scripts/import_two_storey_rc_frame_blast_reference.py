from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lsprepost_mcp.component_model_resources import write_component_resource_packages
from lsprepost_mcp.keyword_decomposition import decompose_keyword_deck, write_decomposition_package
from lsprepost_mcp.phase18_reference_naming import REFERENCE_DISPLAY_NAME_EN, REFERENCE_FAMILY_ID


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Import the audited {REFERENCE_DISPLAY_NAME_EN} resources into the local libraries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("source", type=Path, help="Source keyword deck; the accepted legacy filename is 2.k.")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=ROOT / "resources" / "model_library" / "references" / "phase18" / REFERENCE_FAMILY_ID,
        help="Canonical complete-model resource directory.",
    )
    parser.add_argument(
        "--materials-dir",
        type=Path,
        default=ROOT / "resources" / "materials" / "phase18" / REFERENCE_FAMILY_ID,
        help="Canonical material resource directory.",
    )
    parser.add_argument(
        "--structural-dir",
        type=Path,
        default=ROOT / "resources" / "model_library" / "structural" / "phase18" / REFERENCE_FAMILY_ID,
        help="Canonical structural-resource directory.",
    )
    parser.add_argument(
        "--component-packages",
        action="store_true",
        help="Also generate the four Phase 18A-1 component bundles.",
    )
    parser.add_argument(
        "--components-dir",
        type=Path,
        default=ROOT / "resources" / "model_library" / "components" / "phase18" / REFERENCE_FAMILY_ID,
        help="Canonical component-package directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = decompose_keyword_deck(args.source, "tonne_mm_s_N_MPa")
    written = write_decomposition_package(report, args.model_dir, args.materials_dir, args.structural_dir)
    if args.component_packages:
        written["component_packages"] = write_component_resource_packages(report, args.components_dir)
    print(json.dumps(written, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
