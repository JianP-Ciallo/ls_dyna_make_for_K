from __future__ import annotations

import argparse
from pathlib import Path

import pypdfium2 as pdfium


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(args.pdf))
    scale = args.dpi / 72.0
    for index in range(len(document)):
        page = document[index]
        bitmap = page.render(scale=scale)
        bitmap.to_pil().save(args.output_dir / f"page-{index + 1:03d}.png")
        bitmap.close()
        page.close()
    document.close()
    print(f"rendered_pages={index + 1 if 'index' in locals() else 0}")


if __name__ == "__main__":
    main()
