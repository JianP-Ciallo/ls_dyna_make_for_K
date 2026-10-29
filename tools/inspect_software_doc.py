from docx import Document
from pathlib import Path


path = Path("E:/Desktop/城市关键基础设施爆炸毁伤数字化建模与智能评估系统V1.0-软件设计与操作说明书.docx")
document = Document(path)
print(
    "paragraphs",
    len(document.paragraphs),
    "tables",
    len(document.tables),
    "images",
    len(document.inline_shapes),
    "sections",
    len(document.sections),
)
for index, paragraph in enumerate(document.paragraphs):
    text = " ".join(paragraph.text.split())
    if text and (paragraph.style.name.startswith("Heading") or index < 120):
        print(index, paragraph.style.name, ":", text)
for table_index, table in enumerate(document.tables):
    print("\nTABLE", table_index, "rows", len(table.rows), "cols", len(table.columns))
    for row_index, row in enumerate(table.rows):
        values = [" ".join(cell.text.split()) for cell in row.cells]
        print(row_index, " | ".join(values))
