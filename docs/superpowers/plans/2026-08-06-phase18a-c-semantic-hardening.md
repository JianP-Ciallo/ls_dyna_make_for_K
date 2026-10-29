# Phase 18A–C Semantic Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复第二轮对抗测试确认的 10 个 Phase 18B/18C 缺陷，并以统一的资源身份、结构空间、几何包络和输出清理语义防止关联回归。

**Architecture:** Phase 18B 在清单入口统一校验资源身份、证据和结构关系唯一性；Phase 18C 在合同层拒绝冲突开口，在结构后端生成网格前维护包络约束，并在通用验证器中提供第二道防线。`spaces` 只描述房间拓扑，只有 `openings` 切除结构；表面发布和钢筋输出分别使用完整覆盖判定与引用闭包清理。

**Tech Stack:** Python 3、`unittest`/`pytest`、现有 `lsprepost_mcp.refined_building` 数据类与共形并集网格器。

## Global Constraints

- 不修改 `E:/Desktop/2.k`、Phase 18A 拆分载荷、资源计数、规范 ID、别名和导出格式。
- 不修改任何场景生成器；精细化建筑内核继续仅位于 `lsprepost_mcp/refined_building/` 边界内。
- `spaces` 表示房间/空气拓扑，不切除梁、柱、板、墙或钢筋；当前只有 `openings` 切除结构。
- RC 箱体空腔继续由底板、顶板和外墙的显式构件几何形成，不引入 `structural_voids`。
- 不实现 `custom_hybrid`，不把 Phase 18C 角色自动绑定到 Phase 18B 材料版本，不宣称完成工程验证。
- 所有相关资源和构件继续保持 `requires_project_review=true`。
- 每项生产代码修改必须先新增真实行为测试并确认 RED，再实施最小修复并确认 GREEN。
- 当前工作区含用户的既有未提交改动；只修改和暂存本计划列出的路径，不清理、不覆盖其他文件。

## File Structure

- `lsprepost_mcp/phase18_resource_review.py`：Phase 18 审核清单头、记录证据和资源身份闭包。
- `lsprepost_mcp/structural_resources.py`：截面、曲线、Part、Set、材料和耦合目录的引用闭包与唯一性。
- `lsprepost_mcp/refined_building/contracts.py`：建筑定义规范化、空间/开口拓扑和开口冲突验证。
- `lsprepost_mcp/refined_building/backends/rc.py`：RC 构件盒、楼层连续性、开口切除和预网格尺寸约束。
- `lsprepost_mcp/refined_building/backends/hybrid.py`：钢—混凝土混合结构的板/基础尺寸约束和开口切除。
- `lsprepost_mcp/refined_building/validation.py`：产物级结构包络、开口侵入、连接性和引用闭包防线。
- `lsprepost_mcp/refined_building/surfaces.py`：Shell 与 Solid 共面覆盖去重及暴露表面发布。
- `lsprepost_mcp/refined_building/reinforcement.py`：开口过滤后的钢筋节点引用闭包和稳定重编号。
- `tests/test_phase18b_resource_review.py`、`tests/test_phase18b_structural_resources.py`：Phase 18B 身份/唯一性回归。
- `tests/test_phase18c_contracts.py`、`tests/test_phase18c_rc_backend.py`、`tests/test_phase18c_structural_backends.py`、`tests/test_phase18c_compiler.py`：Phase 18C 空间、楼层和包络回归。
- `tests/test_phase18c_surfaces.py`、`tests/test_phase18c_reinforcement.py`：表面覆盖和钢筋闭包回归。
- `docs/reviews/phase18/PHASE18A_C_ADVERSARIAL_AUDIT_REPAIR_REPORT.zh-CN.md`：第二轮修复证据、命令和限制声明。

---

### Task 1: Phase 18B fail-closed identity and relation closure

**Files:**
- Modify: `lsprepost_mcp/phase18_resource_review.py` (`_validate_review_record`, `validate_phase18_review_manifest`)
- Modify: `lsprepost_mcp/structural_resources.py` (`validate_structural_catalog_closure`)
- Test: `tests/test_phase18b_resource_review.py`
- Test: `tests/test_phase18b_structural_resources.py`

**Interfaces:**
- Consumes: `canonical_resource_sha256(resource) -> str`, `validate_phase18_review_manifest(manifest, resources) -> JSONDict`。
- Produces: 映射键、对象 `id`、审核记录 `id` 三者一致的清单；唯一的 `(set_type, source_id)`、`coupling_index` 和完整耦合签名。

- [ ] **Step 1: Add review evidence and identity regression tests**

  在 `Phase18ReviewContractTests` 中新增两个测试。第一个把有效记录的 `evidence` 改为 `["   "]`，断言 `validate_phase18_review_manifest(...)` 抛出包含 `evidence` 的 `ValueError`。第二个用键 `"material.demo"` 包装对象 `{"id": "material.other", ...}`，审核记录仍使用键 ID 和该对象的真实规范哈希，断言仍因 `key/object identity mismatch` 失败；这样可证明测试不是依靠哈希偶然失败。

- [ ] **Step 2: Run the review tests and verify RED**

  Run: `python -m pytest tests/test_phase18b_resource_review.py -q`

  Expected: 新增的空白证据和映射键/对象 ID 测试均失败，既有测试继续通过。

- [ ] **Step 3: Implement review fail-closed checks**

  在 `_validate_review_record` 中把证据条件改为 `isinstance(item, str) and bool(item.strip())`。在 `validate_phase18_review_manifest` 比较记录集合前，逐项要求 `str(resource.get("id", "")).strip() == resource_id`，否则抛出明确的 `key/object identity mismatch`；随后才允许按映射键取对象并校验记录哈希。

- [ ] **Step 4: Run the review tests and verify GREEN**

  Run: `python -m pytest tests/test_phase18b_resource_review.py -q`

  Expected: 全部通过。

- [ ] **Step 5: Add structural Set and coupling uniqueness tests**

  在 `StructuralCatalogWriterTests` 中从实际五类目录和材料目录建立深拷贝 fixture：

  ```python
  duplicate_set = copy.deepcopy(resources)
  duplicate_set[sets_index]["items"][1] = copy.deepcopy(
      duplicate_set[sets_index]["items"][0]
  )
  with self.assertRaisesRegex(ValueError, "duplicate Set identity"):
      validate_structural_catalog_closure(duplicate_set, materials)
  ```

  分别把第五条耦合的 `coupling_index` 改为第一条索引、以及保留不同索引但复制第一条的 slave/master kind、ID、`sstyp`、`mstyp`，断言错误包含 `duplicate coupling_index` 和 `duplicate coupling relation`。

- [ ] **Step 6: Run structural closure tests and verify RED**

  Run: `python -m pytest tests/test_phase18b_structural_resources.py -q`

  Expected: 三个新增唯一性测试失败。

- [ ] **Step 7: Implement canonical Set and coupling identities**

  在 Set 循环中维护 `set_identities: set[tuple[str, int]]`；重复 `(set_type, source_id)` 时拒绝，同时继续维护原有 `published_set_ids` 供端点闭包使用。在 coupling 循环中维护：

  ```python
  coupling_indexes: set[int] = set()
  coupling_signatures: set[tuple[str, int, str, int, int, int]] = set()
  ```

  完整签名顺序固定为 `(slave_kind, ssid, master_kind, msid, sstyp, mstyp)`；先验证字段可转换和端点闭包，再声明唯一性，避免错误输入绕过闭包。

- [ ] **Step 8: Run Phase 18B tests and commit**

  Run: `python -m pytest tests/test_phase18b_resource_review.py tests/test_phase18b_structural_resources.py tests/test_phase18_resource_library.py -q`

  Expected: 全部通过。

  Commit only the four Task 1 files with message: `fix: harden phase18 resource review closure`。

### Task 2: Phase 18C topology, continuity, and envelope invariants

**Files:**
- Modify: `lsprepost_mcp/refined_building/contracts.py`
- Modify: `lsprepost_mcp/refined_building/backends/rc.py`
- Modify: `lsprepost_mcp/refined_building/backends/hybrid.py`
- Modify: `lsprepost_mcp/refined_building/validation.py`
- Test: `tests/test_phase18c_contracts.py`
- Test: `tests/test_phase18c_rc_backend.py`
- Test: `tests/test_phase18c_structural_backends.py`
- Test: `tests/test_phase18c_compiler.py`

**Interfaces:**
- Consumes: `normalize_building_definition(value) -> JSONDict`, `compile_rc_structure(...)`, `compile_steel_concrete_hybrid(...)`, `validate_building_artifact(artifact) -> JSONDict`。
- Produces: 只由 `openings` 切除的结构、跨楼层连续 RC、网格生成前与生成后的建筑包络不变量。

- [ ] **Step 1: Add positive-volume opening overlap test**

  在合同测试中建立两个不同 ID、端点合法、三轴均正长度相交的 opening，断言规范化抛出包含 `opening regions overlap` 的 `ValueError`；另建只在一个面接触的两个 opening，断言规范化成功且保留两个开口。

- [ ] **Step 2: Run contract tests and verify RED**

  Run: `python -m pytest tests/test_phase18c_contracts.py -q`

  Expected: 重叠开口测试失败；面接触测试通过。

- [ ] **Step 3: Reject overlapping openings in the normalized contract**

  在所有 opening 完成边界、端点和 ID 校验并生成规范化 bounds 后，对不同 opening 做成对 `_boxes_overlap` 检查。该函数保持严格正体积交集语义，因此边界接触不报错；错误消息同时列出两个 opening ID。

- [ ] **Step 4: Add RC room-grid and two-level continuity tests**

  新增默认 3×3 轴网测试，按 metadata/member role 断言生成 9 根柱、X/Y 方向各 6 段梁，并断言 `(3.0, 3.0, 1.5)` 位于某个 `column` 构件盒内部。新增两层 RC fixture（第二层 `elevation_m` 等于首层顶面），断言验证报告不含 `disconnected_concrete` 且混凝土连接分量为 1。

- [ ] **Step 5: Run RC tests and verify RED**

  Run: `python -m pytest tests/test_phase18c_rc_backend.py -q`

  Expected: 3×3 构件计数和两层连接性均失败。

- [ ] **Step 6: Make room spaces non-destructive and upper levels continuous**

  在 `compile_rc_structure` 中，传给混凝土并集网格器和 `generate_reinforcement` 的 exclusions 仅来自 `topology.opening_regions`。在 `_build_member_boxes` 中删除以 `topology.classify_point(_centroid(...)) == "void"` 跳过梁柱的分支。按最小 `elevation_m` 识别最低层：最低层柱底为 `level_base + foundation_thickness`，其他层柱底为本层 `level_base`；所有层柱顶仍为 `level_top - slab_thickness`，从而让上层柱与下层顶板在相同坐标面共享节点。

- [ ] **Step 7: Add pre-mesh dimension tests**

  新增三类真实编译测试：RC `beam_depth_m=4.0` 时抛出包含 `beam_depth_m` 的错误；hybrid `foundation_thickness_m` 大于 envelope 高度时抛出包含字段名的错误；hybrid `slab_thickness_m` 大于所属 level 高度时抛出包含字段名的错误。再为用户声明的 shear wall 越出 envelope 建立 RC 测试，断言生成网格前失败。

- [ ] **Step 8: Run backend tests and verify RED**

  Run: `python -m pytest tests/test_phase18c_rc_backend.py tests/test_phase18c_structural_backends.py -q`

  Expected: 四个新增边界测试失败。

- [ ] **Step 9: Enforce backend geometry bounds before meshing**

  在 RC 每层构件创建前要求 `level_top - beam_depth_m >= level_base`；对每个声明剪力墙要求 envelope 在容差内完整包含其 bounds。在 hybrid 后端要求基础厚度不大于 envelope 高度、每层板厚不大于该层高度。错误均点名字段或 wall ID。hybrid 的结构 exclusions 同样只采用 openings。

- [ ] **Step 10: Add validator out-of-envelope defense test**

  在编译器测试中深拷贝一个有效 `BuildingArtifact`，把被 Solid、Shell 或 Beam 引用的结构节点坐标移到 envelope 外，断言 `validate_building_artifact` 返回 `valid=False` 且 findings 含 `structural_node_outside_envelope`。同时确认位于 room space 中但不在 opening 中的合法结构不再得到 `solid_centroid_in_void`。

- [ ] **Step 11: Run validator test and verify RED**

  Run: `python -m pytest tests/test_phase18c_compiler.py -q`

  Expected: 包络外节点未被发现或合法房间结构被误报。

- [ ] **Step 12: Implement validator second defense and verify GREEN**

  由 Solid、Shell 和 Beam 的 connectivity 收集结构节点 ID；逐个检查坐标在 `topology.envelope` 内，否则生成去重后的 `structural_node_outside_envelope` finding。现有结构侵入检查只针对 `topology.opening_regions`，不再把 `space` 当作实体 void。

  Run: `python -m pytest tests/test_phase18c_contracts.py tests/test_phase18c_rc_backend.py tests/test_phase18c_structural_backends.py tests/test_phase18c_compiler.py -q`

  Expected: 全部通过，默认和两层 RC 都保持单一混凝土连接分量。

  Commit only the eight Task 2 files with message: `fix: enforce refined building topology invariants`。

### Task 3: Exact Shell coverage and reinforcement reference closure

**Files:**
- Modify: `lsprepost_mcp/refined_building/surfaces.py`
- Modify: `lsprepost_mcp/refined_building/reinforcement.py`
- Test: `tests/test_phase18c_surfaces.py`
- Create: `tests/test_phase18c_reinforcement.py`

**Interfaces:**
- Consumes: `build_fluid_exposed_surface_catalog(...)`, `generate_reinforcement(..., exclusions=...) -> MeshFragment`。
- Produces: 仅在 Shell 的完整同平面区域被 Solid 面覆盖时去重；所有钢筋节点均被至少一个 Beam 引用并稳定重编号。

- [ ] **Step 1: Add partially covered Shell regression test**

  构造一个轴对齐大 Shell，其质心落在一个较小 Solid 的共面顶面内，但 Shell 仍有正面积暴露。断言结果中保留该 Shell 的一个可选暴露表面；保留既有“完全覆盖不重复发布”和“纯钢框架四张屋面 Shell 全发布”测试。

- [ ] **Step 2: Run surface tests and verify RED**

  Run: `python -m pytest tests/test_phase18c_surfaces.py -q`

  Expected: 部分覆盖 Shell 被错误抑制，新测试失败。

- [ ] **Step 3: Replace centroid coincidence with full rectangle-union coverage**

  对轴对齐 Shell 确定固定坐标轴并投影成二维矩形。收集同平面 Solid 面与 Shell 的裁剪矩形，将全部矩形边界坐标排序成单元格；对每个单元格质心判断是否被至少一个矩形覆盖并累加面积。只有覆盖面积在既有容差下等于 Shell 面积时才抑制。非轴对齐 Shell 仅允许既有精确 face-key 重合路径抑制，不能使用质心近似。

- [ ] **Step 4: Run surface tests and verify GREEN**

  Run: `python -m pytest tests/test_phase18c_surfaces.py -q`

  Expected: 全部通过。

- [ ] **Step 5: Add orphan-rebar-node regression test**

  在新测试文件中复用偏心门洞 RC-box 定义并直接调用真实后端或 `generate_reinforcement`。计算 `used = {node_id for beam in fragment.beams for node_id in beam.connectivity}`，断言 `used == {node.id for node in fragment.nodes}`，且重复生成的节点坐标与 Beam connectivity 完全相同。

- [ ] **Step 6: Run reinforcement test and verify RED**

  Run: `python -m pytest tests/test_phase18c_reinforcement.py -q`

  Expected: 当前开口过滤结果存在未引用节点，集合断言失败。

- [ ] **Step 7: Prune and deterministically remap reinforcement nodes**

  在全部 Beam 经过开口过滤后，按旧 node ID 排序收集实际引用节点，建立从旧 ID 到连续新 ID 的映射；重建节点元组并重写每个保留 Beam 的 connectivity。保留 Beam 的角色和其他属性，顺序稳定，不保留任何未引用节点。

- [ ] **Step 8: Run Phase 18C surface/rebar cross-tests and commit**

  Run: `python -m pytest tests/test_phase18c_surfaces.py tests/test_phase18c_reinforcement.py tests/test_phase18c_structural_backends.py tests/test_phase18c_rc_backend.py -q`

  Expected: 全部通过。

  Commit only the four Task 3 files with message: `fix: close refined surface and rebar outputs`。

### Task 4: Cross-phase verification and repair report

**Files:**
- Modify: `docs/reviews/phase18/PHASE18A_C_ADVERSARIAL_AUDIT_REPAIR_REPORT.zh-CN.md`

**Interfaces:**
- Consumes: Tasks 1–3 的代码与测试证据。
- Produces: 可追溯的第二轮修复结论，同时保留 `requires_project_review=true` 和非工程验证声明。

- [ ] **Step 1: Run focused Phase 18A integrity tests**

  Run: `python -m pytest tests/test_keyword_decomposition.py tests/test_phase18a1_component_resources.py tests/test_phase18_reference_naming_migration.py -q`

  Expected: Phase 18A 源哈希、拆分计数、构件包和别名测试全部通过。

- [ ] **Step 2: Run the complete Phase 18A–C matrix**

  Run: `python -m pytest tests/test_phase18_resource_library.py tests/test_phase18b_resource_review.py tests/test_phase18b_structural_resources.py tests/test_phase18c_contracts.py tests/test_phase18c_spatial.py tests/test_phase18c_meshing.py tests/test_phase18c_rc_backend.py tests/test_phase18c_structural_backends.py tests/test_phase18c_surfaces.py tests/test_phase18c_reinforcement.py tests/test_phase18c_compiler.py -q`

  Expected: 全部通过，无 warning/error 输出。

- [ ] **Step 3: Re-run meshing invariants**

  Run the repository's existing deterministic/random conforming-union mesh regression command documented in the repair report; require 100 random geometries and 50 reversed-member-order cases to pass, plus the normal parameter matrix.

- [ ] **Step 4: Run the full project suite**

  Run: `python -m pytest -q`

  Expected: 全部项目测试通过；只有仓库既有的明确 skip 可以存在。

- [ ] **Step 5: Inspect only planned diffs**

  Run: `git diff --check -- <all Task 1–4 production, test, and report paths>` and inspect `git diff --stat` plus the full scoped diff. Confirm no Phase 18A payload, scenario generator, material JSON or model package changed.

- [ ] **Step 6: Update the audit repair report**

  记录 10 个缺陷各自的根因、RED 测试、修复位置、GREEN 命令和最终测试计数；明确材料/结构资源仍需项目审核、未实现 `custom_hybrid`、未完成工程级爆炸验证。

- [ ] **Step 7: Commit the verification report**

  Commit only the report with message: `docs: record phase18 semantic hardening verification`。
