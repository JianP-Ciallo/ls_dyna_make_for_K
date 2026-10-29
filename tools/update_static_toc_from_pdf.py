from __future__ import annotations

import argparse
import re
from pathlib import Path

import pdfplumber
from docx import Document


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    document = Document(args.docx)
    with pdfplumber.open(args.pdf) as pdf:
        pages = [compact(page.extract_text() or "") for page in pdf.pages]

    fixed = {"文档信息": 2, "版本记录": 2, "目录": 3}
    updates = []
    for paragraph in document.paragraphs:
        if not paragraph.style.name.startswith("toc"):
            continue
        title = paragraph.text.partition("\t")[0].strip()
        if not title:
            continue
        if title in fixed:
            page_number = fixed[title]
        else:
            normalized_title = compact(title)
            matches = [index + 1 for index, page_text in enumerate(pages) if normalized_title in page_text]
            if not matches:
                continue
            page_number = max(matches)
        paragraph.text = f"{title}\t{page_number}"
        updates.append((title, page_number))

    document.save(args.docx)
    print(f"updated_toc_entries={len(updates)}")
    for title, page_number in updates:
        print(f"{page_number}\t{title}")


if __name__ == "__main__":
    main()
