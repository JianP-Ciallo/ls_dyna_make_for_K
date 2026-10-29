from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from pypdf import PdfReader


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("screenshot_dir", type=Path)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    document = Document(args.docx)
    with ZipFile(args.docx) as archive:
        assert archive.testzip() is None
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
        checks = [
            sha256(archive.read(f"word/media/image{index}.png")).hexdigest()
            == sha256((args.screenshot_dir / screen_name).read_bytes()).hexdigest()
            for index, screen_name in enumerate(SCREEN_NAMES, start=16)
        ]
    assert all(checks)
    print(f"docx_bytes={args.docx.stat().st_size}")
    print(
        f"paragraphs={len(document.paragraphs)} "
        f"inline_shapes={len(document.inline_shapes)} media={len(media)}"
    )
    print(
        f"replacements_verified={sum(checks)}/8 "
        f"pdf_pages={len(PdfReader(str(args.pdf)).pages)}"
    )
    print(f"sha256={sha256(args.docx.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
