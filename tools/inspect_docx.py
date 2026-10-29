from pathlib import Path
import sys

from docx import Document


def main() -> None:
    path = Path(sys.argv[1])
    doc = Document(path)
    print(f"paragraphs={len(doc.paragraphs)} tables={len(doc.tables)} inline_shapes={len(doc.inline_shapes)}")
    for index, paragraph in enumerate(doc.paragraphs):
        text = " ".join(paragraph.text.split())
        if text:
            print(f"P{index:04d}\t{paragraph.style.name}\t{text}")
    for table_index, table in enumerate(doc.tables):
        print(f"TABLE {table_index}: rows={len(table.rows)} cols={len(table.columns)}")
        for row_index, row in enumerate(table.rows[:8]):
            cells = [" ".join(cell.text.split()) for cell in row.cells]
            print(f"  R{row_index}: " + " || ".join(cells))


if __name__ == "__main__":
    main()
