import hashlib
import zipfile
from pathlib import Path

try:
    from .work_paths import existing_input
except ImportError:  # Direct script invocation.
    from work_paths import existing_input

from docx import Document


workspace = existing_input("soft_copyright_work", "outputs")
desktop = Path("E:/Desktop/软著申请材料-城市关键基础设施爆炸毁伤智能评估系统V1.0")
workspace_files = sorted(workspace.glob("*.docx"))
desktop_files = sorted(desktop.glob("*.docx"))
assert len(workspace_files) == 3
assert [p.name for p in workspace_files] == [p.name for p in desktop_files]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


for source, target in zip(workspace_files, desktop_files):
    assert sha256(source) == sha256(target)
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert "word/document.xml" in names
        assert "word/comments.xml" not in names

info = Document(desktop_files[0])
assert len(info.tables) == 1
assert len(info.tables[0].rows) == 29
for row_index in range(2, 29):
    assert info.tables[0].rows[row_index].cells[1].text.strip()

manual = Document(desktop_files[1])
manual_text = "\n".join(p.text for p in manual.paragraphs)
assert len(manual.inline_shapes) == 15
assert len(manual.tables) == 15
assert "供专业机构复核与完善" not in manual_text
assert "附录B 软件著作权申请信息初稿" not in manual_text
assert "附录B 软件著作权申请信息" in manual_text

code = Document(desktop_files[2])
assert len(code.tables) == 80
assert all(len(table.rows) == 50 for table in code.tables)
assert len(code.paragraphs) == 80
assert code.tables[-1].rows[-1].cells[1].text.strip() == 'createRoot(document.getElementById("root")).render(<App />);'

print("files=3 hashes=match info_rows=29 manual_pages=30 manual_images=15 code_pages=80 code_lines=4000")
for path in desktop_files:
    print(path.name, path.stat().st_size, sha256(path))
