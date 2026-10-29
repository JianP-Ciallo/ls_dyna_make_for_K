import re
import sys
from pathlib import Path

from docx import Document
from pypdf import PdfReader


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def main():
    source = Path(sys.argv[1])
    pdf_path = Path(sys.argv[2])
    output = Path(sys.argv[3])

    document = Document(source)
    pdf_pages = [normalize(page.extract_text() or "") for page in PdfReader(pdf_path).pages]
    toc_paragraphs = [p for p in document.paragraphs if p.style.name.lower().startswith("toc ")]

    fixed_pages = {"文档信息": 2, "版本记录": 2, "目录": 3}
    missing = []
    updates = []
    for paragraph in toc_paragraphs:
        title = paragraph.text.split("\t", 1)[0].strip()
        if title in fixed_pages:
            page_number = fixed_pages[title]
        else:
            needle = normalize(title)
            matches = [i + 1 for i, page_text in enumerate(pdf_pages) if needle in page_text]
            body_matches = [page for page in matches if page >= 6]
            if not body_matches:
                missing.append((title, matches))
                continue
            page_number = max(body_matches)
        updates.append((paragraph, title, page_number))

    if missing:
        raise RuntimeError(f"Unresolved TOC entries: {missing}")
    if len(updates) != len(toc_paragraphs):
        raise RuntimeError("TOC update count mismatch")

    for paragraph, title, page_number in updates:
        paragraph.text = f"{title}\t{page_number}"

    document.save(output)
    print(f"updated={len(updates)} output={output}")


if __name__ == "__main__":
    main()
