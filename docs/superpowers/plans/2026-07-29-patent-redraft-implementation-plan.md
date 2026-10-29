# Patent Redraft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a new, visually verified Word patent draft based on `E:\Desktop\专利初稿-高矗.docx`, reflecting the project's current controlled finite-element generation, validation, provenance, scene-editing, and assessment capabilities.

**Architecture:** Treat the existing DOCX as a read-only style template. Keep patent content, figure geometry, DOCX assembly, and QA as separate reproducible units under an ignored internal working directory; assemble the final document only after content and figures pass independent checks. Deliver the verified result to `E:\Desktop\专利初稿-重写版.docx` without changing the original.

**Tech Stack:** Bundled Python 3, `python-docx`, Pillow, WordprocessingML, bundled Poppler, packaged DOCX renderer when available, Microsoft Word COM PDF export as the Windows fallback.

## Global Constraints

- Use `E:\Desktop\专利初稿-高矗.docx` as the sole style and layout reference; never overwrite it.
- Use the approved design in `docs/superpowers/specs/2026-07-29-patent-redraft-design.md`.
- Preserve the reference page setup, Normal-style typography, paragraph rhythm, image width, and black-and-white patent appearance.
- The large-language-model layer may understand requests and call registered tools, but may not directly create, edit, overwrite, or persist K files.
- K-file compilation, validation, persistence, and evidence generation belong exclusively to the controlled-tool execution layer.
- Phase 16B/17 capabilities appear only as optional embodiments and dependent claims; do not claim completed engineering-accuracy certification or complete real-solver acceptance.
- Do not include development phase names, roadmaps, internal completion status, split-patent advice, or drafting notes in the final DOCX.
- Do not modify product source, project tests, or user-authored working-tree changes.
- Store scratch scripts, generated figures, QA renders, and intermediate DOCX/PDF files under `docs/internal/patent/redraft_2026_07_29/`.
- The final DOCX must contain exactly 11 referenced inline figures with no orphan image relationships.
- The final delivery path is `E:\Desktop\专利初稿-重写版.docx`.

---

### Task 1: Capture the Reference Document Contract

**Files:**
- Read: `E:\Desktop\专利初稿-高矗.docx`
- Create: `docs/internal/patent/redraft_2026_07_29/extract_reference.py`
- Create: `docs/internal/patent/redraft_2026_07_29/test_reference_contract.py`
- Create: `docs/internal/patent/redraft_2026_07_29/reference_profile.json`

**Interfaces:**
- Consumes: the reference DOCX path.
- Produces: `extract_reference.extract_profile(path: Path) -> dict` and a JSON profile containing section geometry, margins, paragraph defaults, Normal-style font settings, image widths, paragraph count, and image count.

- [ ] **Step 1: Write the failing reference-contract test**

```python
from pathlib import Path
import unittest

from extract_reference import extract_profile


REFERENCE = Path(r"E:\Desktop\专利初稿-高矗.docx")


class ReferenceContractTests(unittest.TestCase):
    def test_reference_profile_captures_layout_and_media(self):
        profile = extract_profile(REFERENCE)
        self.assertEqual(profile["paragraph_count"], 47)
        self.assertEqual(profile["inline_shape_count"], 9)
        self.assertEqual(profile["section_count"], 1)
        self.assertLess(profile["page_width_emu"], profile["page_height_emu"])
        self.assertGreater(profile["normal_font_size_pt"], 0)
        self.assertGreater(profile["max_inline_width_emu"], 0)
```

- [ ] **Step 2: Run the test and confirm the expected failure**

Run:

```powershell
& 'C:\Users\14989\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest test_reference_contract.py
```

Working directory:

```text
E:\workplace\codex_mcp_k\docs\internal\patent\redraft_2026_07_29
```

Expected: import failure because `extract_reference.py` does not yet exist.

- [ ] **Step 3: Implement deterministic reference extraction**

Implement `extract_profile()` with `python-docx`. Read:

- `len(document.paragraphs)`;
- `len(document.inline_shapes)`;
- section width, height, and margins in EMU;
- Normal style font name and size, including East Asian `w:rFonts`;
- paragraph alignment, indentation, line spacing, space before, and space after from representative non-empty body paragraphs;
- all inline image widths and the maximum width.

Write `reference_profile.json` with `ensure_ascii=False` and sorted keys.

- [ ] **Step 4: Re-run the reference test**

Expected: one passing test and a non-empty `reference_profile.json`.

- [ ] **Step 5: Record a read-only baseline hash**

Run:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'E:\Desktop\专利初稿-高矗.docx'
```

Save the hash in `reference_profile.json` as `reference_sha256`.

---

### Task 2: Author the Patent Content and Claim Contract

**Files:**
- Read: `docs/superpowers/specs/2026-07-29-patent-redraft-design.md`
- Read: `README.zh-CN.md`
- Read: `docs/ROADMAP.zh-CN.md`
- Create: `docs/internal/patent/redraft_2026_07_29/patent_content.py`
- Create: `docs/internal/patent/redraft_2026_07_29/test_patent_content.py`

**Interfaces:**
- Produces:
  - `PATENT_TITLE: str`
  - `ABSTRACT: str`
  - `SECTIONS: list[tuple[str, list[str]]]`
  - `FIGURE_CAPTIONS: list[str]`
  - `CLAIMS: list[str]`
  - `FORBIDDEN_FINAL_TERMS: tuple[str, ...]`

- [ ] **Step 1: Write failing content-contract tests**

```python
import unittest

import patent_content as content


class PatentContentTests(unittest.TestCase):
    def test_core_trust_boundary_is_present(self):
        full_text = "\n".join(
            [content.PATENT_TITLE, content.ABSTRACT]
            + [p for _, paragraphs in content.SECTIONS for p in paragraphs]
            + content.CLAIMS
        )
        self.assertIn("大语言模型", full_text)
        self.assertIn("受控工具", full_text)
        self.assertIn("不得直接", full_text)
        self.assertIn("K 文件", full_text)
        self.assertIn("语义场景中间表示", full_text)
        self.assertIn("能力声明", full_text)
        self.assertIn("分级就绪", full_text)
        self.assertIn("证据溯源", full_text)

    def test_document_has_complete_patent_sections(self):
        names = [name for name, _ in content.SECTIONS]
        self.assertEqual(
            names,
            ["技术领域", "背景技术", "发明内容", "附图说明", "具体实施方式"],
        )
        self.assertEqual(len(content.FIGURE_CAPTIONS), 11)
        self.assertEqual(len(content.CLAIMS), 20)

    def test_final_text_excludes_internal_language(self):
        full_text = "\n".join(
            [content.PATENT_TITLE, content.ABSTRACT]
            + [p for _, paragraphs in content.SECTIONS for p in paragraphs]
            + content.CLAIMS
        )
        for term in content.FORBIDDEN_FINAL_TERMS:
            self.assertNotIn(term, full_text)
```

- [ ] **Step 2: Run the tests and verify they fail**

Expected: import failure because `patent_content.py` is absent.

- [ ] **Step 3: Write the title, abstract, and formal sections**

Use the title:

```text
一种基于受控语义场景的有限元模型生成与验证方法及系统
```

The abstract must state:

- the project is supplied to a large-language-model environment;
- the model selects registered controlled tools;
- the model cannot directly write K files;
- requests become a semantic-scene intermediate representation;
- deterministic compilation emits model and evidence files;
- capability-driven validation and graded readiness gates are applied;
- immutable project and provenance records are produced.

Write complete paragraphs for:

- technical field;
- background technology;
- technical problems;
- technical solution;
- beneficial effects;
- eleven figure captions;
- detailed embodiments 1 through 11 from the approved design.

Use generic patent language in the main solution and reserve LS-DYNA, LS-PrePost, LS-Run, MCP, and Three.js for embodiments.

Set:

```python
FORBIDDEN_FINAL_TERMS = (
    "Phase 16",
    "Phase 17",
    "路线图",
    "建议拆分",
    "尚未实施",
    "内部完成度",
)
```

- [ ] **Step 4: Write exactly 20 claims**

Claim organization:

1. Independent method claim covering project supply, LLM-controlled tool invocation, semantic intermediate representation, deterministic compilation, capability-driven validation, graded readiness, immutable persistence, and provenance.
2. Registered-tool manifest and invocation authorization.
3. Natural-language classification, parameter extraction, unit normalization, and missing-parameter confirmation.
4. Semantic-scene intermediate representation fields.
5. Component, material, and physical-action registries.
6. Deterministic keyword compilation and auxiliary project files.
7. Capability declaration and required/alternative card groups.
8. ID, reference graph, mesh, material, mass, timestep, and physical-consistency checks.
9. Graded readiness gates.
10. Transactional project writing and collision policy.
11. Recompilation and hash-based provenance.
12. Whitelisted external-software script and evidence binding.
13. LS-Run or solver authorization, immutable input snapshot, and execution evidence.
14. Controlled scene-draft editing with object-specific degrees of freedom.
15. ALE, initialization, FSI, sensor, and semantic-map regeneration after editing.
16. Stable semantic-object mapping to Part, Set, sensor, and result data.
17. Multi-fidelity comparison, uncertainty analysis, refinement, bounded surrogate estimation, protection ranking, and fingerprint-based stale-result isolation.
18. Independent system claim with modules corresponding to claim 1.
19. Independent electronic-device claim.
20. Independent computer-readable-storage-medium claim.

- [ ] **Step 5: Re-run content tests**

Expected: all content-contract tests pass, claim count is 20, caption count is 11, and no forbidden internal terms appear.

---

### Task 3: Generate Eleven Patent-Style Figures

**Files:**
- Create: `docs/internal/patent/redraft_2026_07_29/figure_specs.py`
- Create: `docs/internal/patent/redraft_2026_07_29/generate_figures.py`
- Create: `docs/internal/patent/redraft_2026_07_29/test_figure_geometry.py`
- Create: `docs/internal/patent/redraft_2026_07_29/figures/fig01.png` through `fig11.png`
- Create: `docs/internal/patent/redraft_2026_07_29/figures/contact_sheet.png`

**Interfaces:**
- `FIGURE_SPECS: list[FigureSpec]`
- `render_figure(spec: FigureSpec, output_path: Path) -> None`
- `validate_routes(spec: FigureSpec) -> list[str]`

Use these exact immutable interfaces:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class NodeSpec:
    node_id: str
    label: str
    shape: str
    rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class RouteSpec:
    route_id: str
    points: tuple[tuple[int, int], ...]
    label: str | None = None
    label_pos: tuple[int, int] | None = None


@dataclass(frozen=True)
class FigureSpec:
    number: int
    title: str
    width: int
    height: int
    nodes: tuple[NodeSpec, ...]
    routes: tuple[RouteSpec, ...]
```

- [ ] **Step 1: Write failing figure-contract tests**

```python
import unittest

from figure_specs import FIGURE_SPECS
from generate_figures import validate_routes


class FigureGeometryTests(unittest.TestCase):
    def test_figure_count_and_canvas(self):
        self.assertEqual(len(FIGURE_SPECS), 11)
        for spec in FIGURE_SPECS:
            self.assertEqual(spec.width, 1800)
            self.assertEqual(spec.height, 1200)

    def test_routes_are_orthogonal_and_clear(self):
        for spec in FIGURE_SPECS:
            self.assertEqual(validate_routes(spec), [], spec.title)
```

- [ ] **Step 2: Run tests and verify the expected import failure**

- [ ] **Step 3: Define all figure nodes and routes**

Create specs for:

1. overall method flow;
2. system modules and trust boundary;
3. project supply, LLM interpretation, and controlled tool invocation;
4. semantic-scene intermediate representation;
5. deterministic compilation and capability declaration;
6. multi-level validation and graded readiness;
7. immutable project writing and provenance;
8. external preprocessing/solver validation and evidence archive;
9. controlled scene editing and dependent-physics regeneration;
10. semantic-result mapping and multi-fidelity refinement;
11. project, layout, edit-state, and result fingerprint isolation.

All connectors must be orthogonal polylines. Every route must terminate at a node boundary, avoid unrelated node interiors, and avoid crossing another route except at an explicitly declared junction.

- [ ] **Step 4: Implement black-and-white rendering**

Use:

- 1800 x 1200 RGB canvas;
- white background;
- black 3-4 px lines;
- SimSun for body text and SimHei for titles when available;
- rounded process rectangles, diamonds only for decisions, and no decorative color;
- centered text with measured bounding boxes and minimum 18 px inner padding;
- inline figure title and horizontal rule matching the existing patent figures.

- [ ] **Step 5: Run geometry tests and generate figures**

Expected: all tests pass and 11 PNG files are created.

- [ ] **Step 6: Inspect the contact sheet and every full-size figure**

Use `view_image` at high detail. Reject any figure with:

- line/text overlap;
- connectors crossing nodes;
- cropped labels;
- ambiguous branch labels;
- text smaller than the previous reference figures at equivalent scale.

Revise specs and regenerate until all eleven figures pass.

---

### Task 4: Assemble the Word Patent Draft

**Files:**
- Read: `E:\Desktop\专利初稿-高矗.docx`
- Read: `docs/internal/patent/redraft_2026_07_29/reference_profile.json`
- Read: `docs/internal/patent/redraft_2026_07_29/patent_content.py`
- Read: `docs/internal/patent/redraft_2026_07_29/figures/*.png`
- Create: `docs/internal/patent/redraft_2026_07_29/build_docx.py`
- Create: `docs/internal/patent/redraft_2026_07_29/test_docx_structure.py`
- Create: `docs/internal/patent/redraft_2026_07_29/output/专利初稿-重写版.docx`

**Interfaces:**
- `build_document(reference: Path, output: Path) -> None`
- `purge_body_keep_section(document: Document) -> None`
- `drop_unreferenced_image_relationships(document: Document) -> None`

- [ ] **Step 1: Write failing DOCX-structure tests**

```python
from pathlib import Path
import unittest

from docx import Document
from docx.oxml.ns import qn


OUTPUT = Path(
    r"docs\internal\patent\redraft_2026_07_29\output\专利初稿-重写版.docx"
)


class DocxStructureTests(unittest.TestCase):
    def test_complete_document_structure(self):
        document = Document(str(OUTPUT))
        text = "\n".join(p.text for p in document.paragraphs)
        for heading in (
            "摘要",
            "技术领域",
            "背景技术",
            "发明内容",
            "附图说明",
            "具体实施方式",
            "权利要求书",
        ):
            self.assertIn(heading, text)
        self.assertEqual(len(document.inline_shapes), 11)

    def test_no_orphan_image_relationships(self):
        document = Document(str(OUTPUT))
        referenced = {
            blip.get(qn("r:embed"))
            for blip in document.element.body.xpath(".//a:blip")
        }
        image_rels = {
            rel_id
            for rel_id, relation in document.part.rels.items()
            if "image" in relation.reltype
        }
        self.assertEqual(referenced, image_rels)
```

- [ ] **Step 2: Run tests and confirm failure because the output is absent**

- [ ] **Step 3: Implement template-preserving assembly**

Load the reference DOCX, remove all body children except the final `w:sectPr`, and remove now-unused document image relationships. Preserve:

- section geometry and margins;
- style definitions;
- Normal-style font and paragraph defaults;
- document compatibility settings.

Insert:

1. name;
2. abstract label and abstract body;
3. formal patent sections;
4. each figure caption followed by one centered inline image;
5. detailed embodiments;
6. claim heading and numbered claims.

Use real Word paragraphs, not text boxes or tables. Keep each caption with its following figure using `keep_with_next`. Insert page breaks only where necessary to keep a figure and its caption together.

- [ ] **Step 4: Build the DOCX and run structure tests**

Expected: section headings exist, 11 inline figures exist, 11 image relationships are referenced, and no old figure or old patent title remains.

---

### Task 5: Run Structural and Content QA

**Files:**
- Create: `docs/internal/patent/redraft_2026_07_29/audit_docx.py`
- Create: `docs/internal/patent/redraft_2026_07_29/output/audit.json`

**Interfaces:**
- `audit_document(path: Path) -> dict`

- [ ] **Step 1: Add audit assertions**

The audit must verify:

- final title equals the approved title;
- exactly 20 numbered claims appear;
- exactly 11 figure captions and 11 drawings appear;
- every image relation is referenced;
- no reference-document title or old S1-S10-only body survives;
- the trust-boundary phrases appear in abstract, invention content, detailed embodiments, and claim 1;
- forbidden terms are absent;
- no paragraph contains empty placeholder markers;
- the original file hash still matches `reference_profile.json`.

- [ ] **Step 2: Run the audit**

Expected output:

```json
{
  "ok": true,
  "claim_count": 20,
  "figure_count": 11,
  "orphan_image_relationships": 0,
  "reference_unchanged": true
}
```

- [ ] **Step 3: Correct all audit failures and rerun**

Do not proceed until `ok` is `true`.

---

### Task 6: Render and Inspect Every Page

**Files:**
- Read: `docs/internal/patent/redraft_2026_07_29/output/专利初稿-重写版.docx`
- Create: `docs/internal/patent/redraft_2026_07_29/render/`

**Interfaces:**
- Produces one `page-<N>.png` per final Word page and an internal QA PDF when Word COM fallback is used.

- [ ] **Step 1: Invoke the documents skill and packaged DOCX renderer**

Run the current packaged `render_docx.py` with the bundled Python runtime and the render directory.

- [ ] **Step 2: If LibreOffice is unavailable, use the Windows fallback**

Open a workspace copy through hidden Microsoft Word COM in read-only mode, export PDF to the render directory, close the document and Word in `finally`, then rasterize with bundled Poppler at 144 DPI.

- [ ] **Step 3: Inspect every rendered page**

Use `view_image` at high detail for every page. Check:

- no clipped text;
- no line or figure overlap;
- captions remain adjacent to figures;
- claim numbering is continuous;
- no unexpected blank page;
- no excessively large blank gaps;
- Chinese and Latin fonts render correctly;
- all eleven figures remain legible at the Word scale.

- [ ] **Step 4: Iterate until the rendered document is clean**

After every DOCX modification, rebuild, rerun structural tests, rerun the audit, rerender all pages, and inspect all pages again.

---

### Task 7: Deliver the Verified Word File

**Files:**
- Read: `docs/internal/patent/redraft_2026_07_29/output/专利初稿-重写版.docx`
- Create: `E:\Desktop\专利初稿-重写版.docx`

**Interfaces:**
- Final deliverable: `E:\Desktop\专利初稿-重写版.docx`

- [ ] **Step 1: Record final verification evidence**

Run fresh structural tests, figure geometry tests, content tests, and `audit_docx.py`. Confirm all exit with code 0 and `audit.json` has `"ok": true`.

- [ ] **Step 2: Copy the verified DOCX to Desktop with approval**

Copy only the verified DOCX. Do not copy scratch scripts, QA PNGs, or PDFs to Desktop.

- [ ] **Step 3: Verify delivery**

Confirm:

- destination exists and is non-empty;
- destination SHA-256 matches the verified workspace output;
- original reference SHA-256 remains unchanged;
- destination opens through `python-docx`;
- destination has 20 claims, 11 captions, 11 drawings, 11 referenced image relationships, and no orphan media.

- [ ] **Step 4: Report completion**

Link only the final Desktop DOCX. State the rendered page count and that every page was inspected. State any unavoidable legal or engineering limitations without linking internal QA artifacts.
