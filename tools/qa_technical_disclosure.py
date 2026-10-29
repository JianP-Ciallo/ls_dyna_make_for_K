import hashlib
import json
import zipfile
from pathlib import Path

try:
    from .work_paths import existing_input
except ImportError:  # Direct script invocation.
    from work_paths import existing_input

from docx import Document
from pypdf import PdfReader


DOCX_NAME = (
    "\u57ce\u5e02\u5173\u952e\u57fa\u7840\u8bbe\u65bd\u7206\u70b8\u6bc1\u4f24"
    "\u7cbe\u7ec6\u5316\u5efa\u6a21\u4e0e\u667a\u80fd\u8bc4\u4f30\u65b9\u6cd5"
    "\u53ca\u7cfb\u7edf-\u6280\u672f\u4ea4\u5e95\u4e66.docx"
)
PDF_NAME = "\u6280\u672f\u4ea4\u5e95\u4e66-\u9884\u89c8.pdf"
TITLE = (
    "\u4e00\u79cd\u9762\u5411\u57ce\u5e02\u5173\u952e\u57fa\u7840\u8bbe\u65bd"
    "\u7206\u70b8\u6bc1\u4f24\u7684\u7cbe\u7ec6\u5316\u5efa\u6a21\u4e0e"
    "\u667a\u80fd\u8bc4\u4f30\u65b9\u6cd5\u53ca\u7cfb\u7edf"
)


def main() -> None:
    docx_path = Path("E:/Desktop") / DOCX_NAME
    pdf_path = (
        existing_input("technical_disclosure_work", "render")
        / PDF_NAME
    )
    document = Document(str(docx_path))
    all_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    all_text += "\n" + "\n".join(
        cell.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
    )
    right_text = "\n".join(
        row.cells[-1].text
        for table in document.tables
        for row in table.rows
        if row.cells
    )

    with zipfile.ZipFile(docx_path) as archive:
        media = [
            name
            for name in archive.namelist()
            if name.startswith("word/media/") and not name.endswith("/")
        ]

    checks = {
        "docx_exists": docx_path.exists(),
        "docx_bytes": docx_path.stat().st_size,
        "sha256": hashlib.sha256(docx_path.read_bytes()).hexdigest(),
        "pdf_pages": len(PdfReader(str(pdf_path)).pages),
        "tables": len(document.tables),
        "inline_shapes": len(document.inline_shapes),
        "media_files": len(media),
        "title_exact": TITLE in all_text,
        "critical_infrastructure": "\u57ce\u5e02\u5173\u952e\u57fa\u7840\u8bbe\u65bd" in right_text,
        "legacy_building_asset": "\u5efa\u7b51\u8d44\u4ea7" in right_text,
        "llm_optional": (
            "\u53ef\u9009\u5b9e\u65bd\u65b9\u5f0f" in right_text
            and "\u5927\u8bed\u8a00\u6a21\u578b" in right_text
        ),
        "llm_not_implemented": (
            "\u5c1a\u672a\u5b9e\u73b0" in right_text
            or "\u6982\u5ff5\u9636\u6bb5" in right_text
        ),
        "llm_no_direct_k": (
            "\u4e0d\u5f97\u76f4\u63a5\u5199\u5165K\u6587\u4ef6" in right_text
            or "\u4e0d\u80fd\u76f4\u63a5\u5199\u5165K\u6587\u4ef6" in right_text
        ),
        "example_gpr_residue": (
            "\u4e00\u79cd\u57fa\u4e8eGPR" in right_text
            or "\u91c7\u96c6 GPR" in right_text
        ),
        "contact_pending": "\u5f85\u7533\u8bf7\u4eba\u586b\u5199" in all_text,
        "required_figures": all(
            ("\u56fe" + str(index)) in all_text for index in range(1, 12)
        ),
    }
    print(json.dumps(checks, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
