from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


SCREEN_NAMES = [
    "01-refined-commercial-overview.png",
    "02-refined-commercial-solver.png",
    "03-refined-commercial-structure.png",
    "04-refined-residential-components.png",
    "05-refined-residential-mesh.png",
    "06-refined-commercial-blast-domain.png",
    "07-refined-subway-components.png",
    "08-refined-subway-validation.png",
]


def replace_screens(source: Path, output: Path, screenshot_dir: Path) -> None:
    replacements = {
        f"word/media/image{index}.png": (screenshot_dir / screen_name).read_bytes()
        for index, screen_name in enumerate(SCREEN_NAMES, start=16)
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(source, "r") as src, ZipFile(output, "w", ZIP_DEFLATED) as dst:
        names = set(src.namelist())
        missing = sorted(set(replacements) - names)
        if missing:
            raise ValueError(f"DOCX media entries missing: {missing}")
        for item in src.infolist():
            data = replacements.get(item.filename, src.read(item.filename))
            dst.writestr(item, data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("screenshot_dir", type=Path)
    args = parser.parse_args()
    replace_screens(args.source, args.output, args.screenshot_dir)
    print(args.output)


if __name__ == "__main__":
    main()
