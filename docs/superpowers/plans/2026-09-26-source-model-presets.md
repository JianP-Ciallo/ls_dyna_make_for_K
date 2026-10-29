# 三个参考模型预工况 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans 按任务执行。本项目尽量不使用子智能体，仅在必要的独立审查中少量使用；不自动并行委派。步骤用复选框跟踪。

**Goal:** 在现有建模模式菜单加入三个可参数化的预工况，实现内置默认本构与自定义材料接口两种模式，以及可追溯的检查、生成、保存和导出。

**Architecture:** 原三个 source-faithful 重建器继续保留，新增统一的派生工况 schema、材料解析和独立编译适配层。前端采用一个按模板字段描述驱动的面板，后端复用工程存储、预览和求解配置能力，派生工况单独做来源与参数验证。

**Tech Stack:** 项目现有 Python、pytest、Web API、JavaScript/HTML、现有 Node/Playwright 专项；不新增框架或依赖。

**Spec:** [2026-09-26-source-model-presets-design.md](../specs/2026-09-26-source-model-presets-design.md)。执行前同时阅读本计划和该设计。

**Status:** 2026-09-26 用户要求先固定本版计划。仅文档已保存；以下实现均未开始。默认内置本构选型在任务 1 完成之前不视为已确定。

## Global Constraints

- 三个入口直接并列加入“建模模式”；保留全部现有入口和原生成能力。
- 自定义模式只要求用户选择配套求解器、填写接口编号；原卡参数自动带入，高级编辑可选。
- 默认模式使用内置材料本构；不能把换过材料的派生工况标为原卡复刻。
- 使用 SI_m_s_kg_N_Pa，明确显示单位；不凭未知 MT41 常数位置推断物理量。
- 原模型、资源、用户改动和测试证据保留；不自动提交、合并或清理工作区。
- 建模专项先用小网格；仅运行与改动有关的专项。全量回归、真实重型案例和求解必须说明范围、预计耗时并获得用户当次明确同意。
- 未运行、跳过或中断的检查不能写成通过；默认 smoke 不能代表本功能验收。

## Review Focus

1. 同一 MT 下两个部件接口配置不一致：应拒绝不兼容组合而非生成后交给用户发现（任务 2）。
2. 材料/模板切换丢失草稿或继承上一模板参数：应隔离保留并正确恢复（任务 6）。
3. 修改孔深、层厚、外环位置、空气间距后旧绑定残留：所有关联必须随新几何重建（任务 3）。
4. 原值空白、零值、无解释常数被错误补全或改名：保留其区别和原顺序（任务 2）。
5. 参数改变仍导出或求解旧结果：所有动作绑定生成版本及内容指纹（任务 4～6）。

## 文件与职责

拟新增文件（均未创建实现）：

- `lsprepost_mcp/source_presets/catalog.py`：三个菜单项、默认几何/网格/输出字段描述。
- `lsprepost_mcp/source_presets/schema.py`：派生工况 schema、单位、数值和几何约束。
- `lsprepost_mcp/source_presets/materials.py`：两种材料模式、原值带入、接口组合和资源版本。
- `lsprepost_mcp/source_presets/compilers.py`：分派三个参数化编译器并汇总元数据。
- `lsprepost_mcp/source_presets/gran.py`、`impact.py`、`b120.py`：各模型几何、网格及物理引用重建。
- `lsprepost_mcp/source_presets/projects.py`：草稿/生成版本与工程结果适配。
- `lsprepost_mcp/web/source_presets_api.py`：模板、检查、草稿和生成端点。
- `lsprepost_mcp/web/static/source_presets.js`：表单、草稿、材料模式和过期状态。

最小接入修改：`lsprepost_mcp/web/app.py`、`web/static/index.html` 和 `web/static/app.js`（后两者均位于 `lsprepost_mcp/` 下）；`project_store.py`、`provenance.py`、`tool_helpers.py` 的新模型类型分支。复用既有 `config_api.py`，只有必要的接口证据记录才补字段；不把用户材料兼容状态等同于路径检查。

包内数据与接口使用 JSON 可序列化 dict/list；纯参数检查和模板估算不得启动外部程序。

## Task 1: 内置默认本构选型与模板契约

**Files:** 新增 `docs/reviews/source_presets/material_selection.zh-CN.md`；新增 `catalog.py`、`schema.py`；测试 `tests/test_source_presets_schema.py`。

**Interfaces:** `preset_catalog() -> list[dict]`；`default_draft(preset_id: str) -> dict`；`normalize_draft(raw: dict) -> dict`。草稿包含 `schema_version=source_model_preset@1`、`preset_id`、`project_name`、`unit_system`、`geometry`、`mesh`、`materials`、`controls`、`solver_profile`；默认名称和所有数值以设计表为准。

- [ ] 只读核对四个原 MT41 部件的单元类型、EOS/输出依赖与项目材料候选，按正式手册记录兼容性证据。
- [ ] 写出每个部件的默认内置资源 ID、实际卡类型、参数来源和限制；参数不充分时列出具体所需物理量，向用户获取，不杜撰默认强度。
- [ ] 只有选型足以落地才固定默认材料资源；不能静默改变 MM-ALE/SPG/常规实体路线。需要求解验证的部分另行申请，不在本任务自动运行。
- [ ] 写失败测试 `test_three_presets_keep_source_geometry_defaults`：三个 ID、几何和输出默认值等于设计；`test_units_and_invalid_geometry`：拒绝非有限值、非正尺寸、孔/装药越界、错误模板字段和无明确换算的单位。
- [ ] 运行 `python -m pytest tests/test_source_presets_schema.py -q`，确认失败后实现 schema/catalog，再运行同一专项至通过。

## Task 2: 材料双模式与求解器关联

**Files:** 新增 `materials.py`；新增版本化材料资源（具体 ID 由任务 1 固定）；测试 `tests/test_source_presets_materials.py`。

**Interfaces:** `resolve_materials(draft: dict) -> dict`，返回 `cards`、`resources`、`overrides`、`solver_requirements`、`warnings`。`mode` 取 `builtin` 或 `user_interface`；后者 `mt` 常规范围 41～50，默认 41，缺省覆盖为空而不是重设原参数。

- [ ] 写失败测试 `test_user_interface_auto_loads_original_constants`：源 LMC 分别 47/47/32/32，NHV 31/31/20/20，LMCA 均为 0，未编辑字段按源保留。
- [ ] 写失败测试 `test_blanks_and_order_preserved`、`test_same_mt_header_conflict_rejected`、`test_solver_path_is_not_material_compatibility`，覆盖 Review Focus 1、4。
- [ ] 写失败测试 `test_builtin_uses_selected_non_umat_resource` 和 `test_unconfigured_solver_allows_export_not_solve`：内置卡符合任务 1；草稿不因缺求解器无法生成，真实运行条件单独检查。
- [ ] 运行 `python -m pytest tests/test_source_presets_materials.py -q` 确认预期失败，实现双模式与可选高级覆盖，再运行同一专项至通过。
- [ ] 确认切换自定义编号只改变指定接口字段，不自动转换常数；原资源字节及来源哈希不变。

## Task 3: 三个模型参数化与空间绑定

**Files:** 新增 `gran.py`、`impact.py`、`b120.py`、`compilers.py`；测试 `tests/test_source_presets_mesh.py`。

**Interfaces:** 各模型 `iter_keyword(draft: dict, materials: dict) -> Iterator[str]`、`estimate(draft: dict) -> dict`；统一 `prepare_draft(raw: dict) -> dict` 返回规范化参数、规模估计、材料和几何问题，不写 K。需要提取原网格模块纯函数时保留默认行为和旧入口合同。

- [ ] 分别写小规模失败测试：`test_gran_scaled_domain_and_axial_charge`、`test_impact_gap_gets_real_air_cells`、`test_b120_layers_bore_bands_and_sale_rebind`，核验用户修改字段确实进入坐标及物理卡。
- [ ] 补充 `test_positive_jacobians_and_interface_topology`、`test_new_bottom_sets_are_spatial`、`test_sale_ranges_are_disjoint`：检查实际生成网格、共享/接触关系和引用，不仅断言参数字典。
- [ ] 运行 `python -m pytest tests/test_source_presets_mesh.py -q`，确认失败，再按模型顺序实现并逐项验证。
- [ ] 默认自定义原卡模式与现有三个重建器做小样本几何/物理设置比较；禁止读原节点/连接表作为生成输入。
- [ ] 增加网格预算、过细网格及不合法派生位置的快速拒绝；估算阶段不构建默认百万级网格。

## Task 4: 草稿、版本、来源验证和生成

**Files:** 新增 `projects.py`；按需修改 `project_store.py`、`provenance.py`、`tool_helpers.py`；测试 `tests/test_source_presets_projects.py`。

**Interfaces:** `save_draft(raw: dict, *, expected_revision: int | None) -> dict`、`load_draft(project_name: str) -> dict`、`generate_draft(raw: dict, *, if_exists: str='versioned') -> dict`、`validate_project(path: Path) -> dict`。派生工程 `model_type=source_model_preset`，元数据区分原源哈希、覆盖参数、实际资源版本和生成哈希。

- [ ] 写失败测试 `test_draft_round_trip_preserves_both_material_modes`、`test_generator_provenance_detects_modified_deck`、`test_changed_parameters_make_old_artifacts_stale`、`test_existing_source_projects_keep_strict_validation`。
- [ ] 运行 `python -m pytest tests/test_source_presets_projects.py -q`，确认失败，实现保存与事务生成，再运行同一专项至通过。
- [ ] 输出 model.k/model.json/checks.json 与差异记录；使用现有工程流程，不手写交付 K。原始资源包及已交付模型不能覆盖。
- [ ] 区分静态通过、求解器已配置、用户材料匹配证据、实际求解证据，禁止将任一项替代其他状态。

## Task 5: Web API 接入

**Files:** 新增 `web/source_presets_api.py`；修改 `web/app.py`；测试 `tests/test_source_presets_api.py`。

**Interfaces:** `GET /api/source-presets`；`POST /api/source-presets/prepare`、`/save`、`/generate`；`GET /api/source-presets/draft?project_name=...`。载荷为草稿；保存包含 expected_revision，输出包含实际版本/哈希；复用既有导出和求解路径，不额外增加任意命令执行入口。

- [ ] 写失败测试 `test_catalog_and_small_generation`、`test_field_errors_are_addressable`、`test_save_conflict_and_stale_generation`、`test_existing_routes_unchanged`。
- [ ] 运行 `python -m pytest tests/test_source_presets_api.py -q`，确认失败；实现对任务 1～4 的薄适配并运行同一专项至通过。
- [ ] 验证模式选择、参数、保存和生成一致；求解器路径复用原配置，不修改其他工程的兼容性声明。

## Task 6: 前端入口与材料操作

**Files:** 新增 `web/static/source_presets.js`；最小修改 `web/static/index.html`、`web/static/app.js`；这些路径均位于 `lsprepost_mcp/` 下。新增 `web/tests/source-presets.runtime.cjs`、`web/tests/source-presets.e2e.cjs`；修改相关 `tests/test_web_static.py` 断言。

**Interfaces:** `initSourcePresets(api, hooks)`，由现有初始化调用；`hooks` 提供项目名称、预览更新、生成状态与既有导出动作适配。三个菜单值采用 `source_gran_r5`、`source_impact_1788`、`source_b120_spg_sale`，映射到固定 preset_id。

- [ ] 写失败交互测试：菜单原四项与新三项并存；选中直接显示字段；各模板/部件/模式草稿互不覆盖。
- [ ] 写失败交互测试：自定义模式填写 41、选择已配置求解器即可继续，材料常数自动填入、高级区默认折叠；切换默认模式显示具体内置材料及替换记录。
- [ ] 写失败交互测试：单位显示/转换正确；非法几何定位到字段；修改参数使旧结果过期，不能误导出或误用旧求解文件。
- [ ] 运行 `node web/tests/source-presets.runtime.cjs` 确认失败，完成表单和状态连接后运行至通过。
- [ ] 运行 `node web/tests/source-presets.e2e.cjs` 做三模板小网格页面/API闭环，不启动默认重型网格或求解器。

## Task 7: 定向兼容性审查与交付

**Files:** 测试证据保存到本功能专用目录；更新设计旁实施状态和用户操作说明。

- [ ] 先运行 `scripts/run_test_matrix.ps1 -List` 或 `-DryRun` 确认专项范围，不启动全量发现。
- [ ] 运行新增七类测试文件和对应前端专项；对共享入口选择 `tests/test_gran_r5_rebuild.py`、`tests/test_impact_1788_rebuild.py`、`tests/test_b120_spg_sale_rebuild.py` 中确认轻量的相关项。
- [ ] 对来源验证、材料库、配置、预览和导出只选本次影响的 node id；不因选择某测试文件而意外带入重型案例。
- [ ] 审查本次差异，核对原入口/资源未被替代、新材料兼容性证据与全部未验证状态；必要时只做一次小范围独立只读审查。
- [ ] 用小模型导出一组可复现 K、参数、检查报告和预览，提供新旧入口及两种材料模式操作说明。
- [ ] 若交付验收需要实际重型生成或求解，先给出具体案例、范围和预计耗时，获得当次明确同意后再执行；否则如实标注未执行。

## 计划自审与交接

- 本版已覆盖：菜单、所有数值分组、材料两模式、可选高级编辑、求解器关联、几何绑定、版本追溯、兼容性与按需验收。
- 尚待任务 1 明确：默认内置本构型号、来源参数、各单元组合适用性。该项公开记录，未以假设填充；不影响本轮保存计划。
- 执行方式遵守 AGENTS.md：主代理顺序实施，必要时少量独立审查。用户本轮只要求定下计划，不自动开始实现或启动测试。
