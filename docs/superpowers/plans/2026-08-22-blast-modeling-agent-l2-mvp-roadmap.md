# Blast Modeling Agent L2 MVP Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 44 个 MCP 工具、旧 Web 路由和项目格式的前提下，交付采用 DeepSeek 云端 API 的 L2 爆炸快速建模智能体。

**Architecture:** 新增独立 `lsprepost_mcp.agent` 领域包和仅监听 `127.0.0.1` 的 `agentd` sidecar；模型平面只产生结构化候选，控制平面独占状态、审批和执行权，执行平面复用现有受控 ALE 生成器。整个项目拆成三个顺序分册，每个分册都形成可测试、可提交、可回退的交付物。

**Tech Stack:** Python 3.10+ 标准库、`unittest`、JSON Schema 资源、SQLite/WAL/FTS5（可用时）、stdlib HTTPS、DeepSeek OpenAI-compatible Chat Completions API、现有原生 HTML/CSS/JavaScript Web App。

**Spec:** docs/superpowers/specs/2026-08-15-blast-modeling-agentization-design.md

## Global Constraints

- 规范来源是 `docs/superpowers/specs/2026-08-15-blast-modeling-agentization-design.md`；实现不得弱化其中的审批、恢复、兼容和证据边界。
- `LSPP_AGENT_ENABLED` 默认关闭；关闭时不注册 Agent API、不调用 DeepSeek、不创建 `workspace/agent/agent.sqlite3`。
- 开关打开后，数据库仍只在首个通过校验的 `create_run` 中惰性创建。
- 同一源码基线下，现有 44 个 MCP descriptor 的名称、顺序、描述和完整 schema 必须逐项不变。
- 不修改 `model.json@0.2.0`、旧项目目录、旧 project exporter/importer 和旧 Web API 包络。
- 大模型不得直接写 `.k`、`.key`、`.dyn`，不得直接访问文件、shell、GUI、求解器或真实写 handler。
- L2 仅允许 R0/R1 自动执行和经批准的当前单个 R2 新建动作；R3/R4 即使有审批记录也必须 `policy_denied` 或生成旧流程交接。
- R2 使用稳定 `action_id`、确定目标名、`ProjectLock` 和 `if_exists=error`；不得用 `versioned` 恢复重放。
- DeepSeek API Key 只从 `DEEPSEEK_API_KEY` 读取，不进入配置文件、SQLite、日志、trace 或导出包。
- DeepSeek OpenAI-compatible base URL 固定默认为 `https://api.deepseek.com`，请求端点为 `/chat/completions`。
- 2026-08-22 的默认模型为 `deepseek-v4-flash`；只允许配置 `deepseek-v4-flash` 或 `deepseek-v4-pro`，不得使用已废弃的 `deepseek-chat`/`deepseek-reasoner`。
- MVP 每个决策请求显式发送 `"thinking":{"type":"disabled"}`、`"stream":false` 和 `"response_format":{"type":"json_object"}`，不保存或续接 `reasoning_content`。
- 核心运行时不新增第三方 Python 依赖；真实 API 调用使用 Python 标准库 HTTPS，CI 使用 fake/replay provider。
- 所有生产改动遵循 TDD；单测命令统一使用 `python -m unittest`，不使用其他测试运行器的专有功能。
- Phase 18E/F、自动启动 LS-PrePost、自动启动 LS-DYNA 和 L3 求解反馈不属于本轮实施范围。

DeepSeek 当前接口约束来源：

- [DeepSeek Your First API Call](https://api-docs.deepseek.com/zh-cn/guides/function_calling/)
- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- [DeepSeek Chat Completion API](https://api-docs.deepseek.com/api/create-chat-completion)

---

## Plan Set and Dependency Order

| 顺序 | 分册 | 独立交付 | 开放权限上限 |
| --- | --- | --- | --- |
| 1 | [合同、兼容与 DeepSeek API](./2026-08-22-blast-modeling-agent-foundation-deepseek-plan.md) | canonical hashing、`ModelingCaseSpec`/profile registry、受控 ALE 适配、能力/只读资源快照、DeepSeek/Fake/Replay providers、只读 intake | R0/R1；不写项目 |
| 2 | [可恢复运行时、审批与受控执行](./2026-08-22-blast-modeling-agent-runtime-execution-plan.md) | SQLite 状态机、动作账本、审批、`agentd`、Web 代理、受控 ALE R2 | 经批准的单个 R2 |
| 3 | [记忆、知识、交付与评测](./2026-08-22-blast-modeling-agent-memory-knowledge-plan.md) | 长期记忆、知识索引、快照、交付包、回放评测 | 不扩大 R2 权限 |

分册必须按 1 → 2 → 3 执行。分册 2 依赖分册 1 的合同、provider 和能力目录；分册 3 依赖分册 2 的 SQLite migration、run/action/approval 身份和事件序列。

### Task 1: Establish an Isolated Execution Baseline

**Files:**
- Read: `docs/superpowers/specs/2026-08-15-blast-modeling-agentization-design.md`
- Read: 本路线图及三个分册
- Verify: `lsprepost_mcp/tools.py`, `lsprepost_mcp/web/app.py`, `tests/`

**Interfaces:**
- Consumes: 当前 Git HEAD、现有 44 个 MCP descriptors、现有 unittest 基线。
- Produces: 独立 implementation worktree、基线提交号、基线测试结果和旧 descriptor 快照。

- [ ] **Step 1: Create an isolated implementation worktree**

使用 `superpowers:using-git-worktrees` 创建隔离工作区；分支名使用 `codex/blast-agent-l2-mvp`。不得直接在持续优化分支上执行下面的生产任务。

- [ ] **Step 2: Record the immutable starting point**

Run:

```powershell
git rev-parse HEAD
git status --short
python -c "from lsprepost_mcp.tools import tool_list; print(len(tool_list()['tools']))"
```

Expected: 工作区干净，工具数量输出 `44`。把提交号写入执行日志，不写入运行时合同。

- [ ] **Step 3: Run the first Foundation contract as RED**

Run:

```powershell
python -m unittest tests.test_agent_feature_flag -v
```

Expected: FAIL because `tests.test_agent_feature_flag` and `lsprepost_mcp.agent` do not exist on the untouched baseline. A PASS means the worktree is not the recorded starting point.

- [ ] **Step 4: Run the legacy baseline as GREEN**

Run:

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q .\lsprepost_mcp
```

Expected: PASS; 全部旧测试通过且 `compileall` 返回 0。若失败，停止实施并先区分既有失败与计划引入失败。

- [ ] **Step 5: Commit the baseline checkpoint**

本任务不改生产文件；用空提交记录后续可回退的明确锚点：

```powershell
git status --short
git commit --allow-empty -m "chore(agent): checkpoint clean L2 baseline"
```

Expected: PASS; checkpoint commit 创建成功，提交前工作树为空。

### Task 2: Execute Foundation and DeepSeek Plan

**Files:**
- Execute: `docs/superpowers/plans/2026-08-22-blast-modeling-agent-foundation-deepseek-plan.md`
- Verify: `lsprepost_mcp/agent/hashing.py`, `lsprepost_mcp/agent/profiles.py`, `lsprepost_mcp/agent/providers/base.py`, `lsprepost_mcp/agent/providers/http.py`, `lsprepost_mcp/agent/providers/deepseek.py`, `lsprepost_mcp/agent/providers/fake.py`, `lsprepost_mcp/agent/providers/replay.py`
- Verify: `tests/test_agent_feature_flag.py`, `tests/test_agent_legacy_compat.py`, `tests/test_agent_contracts.py`, `tests/test_agent_ale_adapter.py`, `tests/test_agent_tool_catalog.py`, `tests/test_agent_providers.py`, `tests/test_agent_intake.py`
- Verify: `scripts/check_deepseek_agent.py`。

**Interfaces:**
- Consumes: Task 1 的干净基线。
- Produces: `canonical_json_bytes()`、`canonical_sha256()`、`ModelingCaseSpec`、`CaseProfileDescriptor`、`CaseProfileRegistry`、`DEFAULT_PROFILE_REGISTRY`、`check_case_completeness()`、`controlled_ale_blast@1`、`AgentDecision`、`LLMProvider`、`DeepSeekProvider`、`FakeProvider`、`ReplayProvider`、`CapabilitySnapshot`、`ReadOnlyResourceSnapshot`、`AdapterCompilation` 与 `bind_dry_run()`。
- Provider boundary: `capabilities()`、`create_decision(request, response_schema)`、`summarize_context(events, budget)`、`health_check()`；DeepSeek MVP 仍固定 non-streaming JSON、thinking disabled 且不发送 tools。

- [ ] **Step 1: Run the Foundation boundary as RED**

Run before implementing the Foundation subplan:

```powershell
python -m unittest tests.test_agent_feature_flag tests.test_agent_contracts tests.test_agent_providers tests.test_agent_intake -v
```

Expected: FAIL because the planned Agent package, contracts, providers and intake tests are not implemented yet.

- [ ] **Step 2: Execute every checkbox in the foundation plan**

按分册顺序执行，不跳过失败测试、API 响应本地验证或 descriptor 兼容快照。

- [ ] **Step 3: Run the Foundation gate as GREEN**

Run:

```powershell
python -m unittest tests.test_agent_feature_flag tests.test_agent_legacy_compat tests.test_agent_contracts tests.test_agent_ale_adapter tests.test_agent_tool_catalog tests.test_agent_providers tests.test_agent_intake -v
python -m unittest tests.test_jsonrpc tests.test_schema tests.test_tools tests.test_web_api tests.test_phase14_ale -v
```

Expected: PASS; 没有 `DEEPSEEK_API_KEY` 时全部离线测试仍通过，且不会发起网络请求。

- [ ] **Step 4: Verify feature-off compatibility**

Run:

```powershell
$env:LSPP_AGENT_ENABLED="0"
python -m unittest tests.test_agent_feature_flag tests.test_agent_legacy_compat -v
```

Expected: PASS; 旧 44 个 descriptor 逐项相等，Agent API 不可用，且 `agent.sqlite3` 不存在。

- [ ] **Step 5: Commit the Foundation checkpoint**

Foundation 分册中的逐任务提交必须已完成；再创建路线图级回退锚点：

```powershell
git status --short
git commit --allow-empty -m "chore(agent): checkpoint foundation and DeepSeek gate"
```

Expected: PASS; checkpoint commit 创建成功，且没有遗漏的未提交 Foundation 文件。

### Task 3: Execute Recoverable Runtime and Controlled Execution Plan

**Files:**
- Execute: `docs/superpowers/plans/2026-08-22-blast-modeling-agent-runtime-execution-plan.md`
- Verify: `tests/test_agent_state.py`, `tests/test_agent_events.py`, `tests/test_agent_store.py`, `tests/test_agent_policy.py`, `tests/test_agent_actions.py`, `tests/test_agent_orchestrator.py`, `tests/test_agent_recovery.py`, `tests/test_agent_audit.py`
- Verify: `tests/test_agent_service.py`, `tests/test_agent_runtime.py`, `tests/test_agent_web_api.py`, `tests/test_agent_controlled_ale_e2e.py`, `tests/test_web_startup.py`, `tests/test_packaging_and_integration_boundaries.py`
- Verify: `lsprepost_mcp/agent/runtime.py`, `lsprepost_mcp/web/agent_sidecar.py`, `lsprepost_mcp/web/agent_api.py`, `start_agent_web_app.cmd`, `scripts/start_web_app.ps1`

**Interfaces:**
- Consumes: Task 2 的 `canonical_sha256()`、case/profile/decision 合同、provider、`CapabilitySnapshot`/`ReadOnlyResourceSnapshot`、`AdapterCompilation.domain_arguments` 和 tool catalog。
- Produces: 仅 127.0.0.1 可用的 sidecar、可恢复 run、结构化审批和经批准的确定目标 R2 写入。

- [ ] **Step 1: Run the Phase C runtime boundary as RED**

Run before implementing the runtime subplan:

```powershell
python -m unittest tests.test_agent_state tests.test_agent_store tests.test_agent_policy tests.test_agent_actions tests.test_agent_recovery -v
```

Expected: FAIL because the Phase C state, ledger, policy, action and recovery modules/tests are not implemented yet.

- [ ] **Step 2: Execute every checkbox in the runtime plan**

在 `agent_runs`、`agent_events`、`agent_actions`、CAS 和恢复测试完成前，不得连接真实 `tool_generate_ale_blast_demo` 写路径。Phase C 必须复用 foundation 的 `canonical_sha256()`；先以 domain arguments、用户基名和 precondition 计算 `action_id`，再派生目标名并实现 `bind_create()`，不得把派生目标名放回其自身 action hash。

- [ ] **Step 3: Run the Phase C safety gate as GREEN before R2**

Run:

```powershell
python -m unittest tests.test_agent_store tests.test_agent_state tests.test_agent_events tests.test_agent_policy tests.test_agent_actions tests.test_agent_orchestrator tests.test_agent_recovery tests.test_agent_audit -v
```

Expected: PASS; 崩溃窗口、重复请求、过期审批、R3/R4、外部预览和求解请求全部 fail-closed。

- [ ] **Step 4: Run the controlled ALE end-to-end gate as GREEN**

Run:

```powershell
python -m unittest tests.test_agent_service tests.test_agent_runtime tests.test_agent_web_api tests.test_agent_controlled_ale_e2e tests.test_web_startup tests.test_packaging_and_integration_boundaries tests.test_jsonrpc -v
```

Expected: PASS; 同一个 `action_id` 最多对应一个项目目录，恢复不会生成 `_v2`，且没有真实 DeepSeek、LS-PrePost 或 LS-DYNA 进程。

- [ ] **Step 5: Commit the Phase C checkpoint**

Runtime 分册中的逐任务提交必须已完成；再创建路线图级回退锚点：

```powershell
git status --short
git commit --allow-empty -m "chore(agent): checkpoint recoverable runtime gate"
```

Expected: PASS; checkpoint commit 创建成功，且没有遗漏的未提交 Phase C 文件。

### Task 4: Execute Memory, Knowledge, Delivery, and Evaluation Plan

**Files:**
- Execute: `docs/superpowers/plans/2026-08-22-blast-modeling-agent-memory-knowledge-plan.md`
- Verify: `tests/test_agent_memory.py`, `tests/test_agent_knowledge.py`, `tests/test_agent_knowledge_index.py`, `tests/test_agent_knowledge_snapshot.py`, `tests/test_agent_delivery.py`, `tests/test_agent_evaluation.py`

**Interfaces:**
- Consumes: Task 3 的 run/event/action/approval 事务身份。
- Produces: 可审计长期记忆、可重建知识索引、不可变知识快照、独立 Agent 交付包和离线回放评测。

- [ ] **Step 1: Run the Phase D data boundary as RED**

Run before implementing the memory and knowledge subplan:

```powershell
python -m unittest tests.test_agent_memory tests.test_agent_knowledge tests.test_agent_knowledge_index tests.test_agent_knowledge_snapshot tests.test_agent_delivery tests.test_agent_evaluation -v
```

Expected: FAIL because the Phase D memory, knowledge index, snapshot, delivery and evaluation modules/tests are not implemented yet.

- [ ] **Step 2: Execute every checkbox in the memory and knowledge plan**

知识正文仍以 `resources/` 和允许的私有来源为事实源；SQLite 只保存运行事实、记忆和可重建索引。

- [ ] **Step 3: Run the Phase D data-governance gate as GREEN**

Run:

```powershell
python -m unittest tests.test_agent_memory tests.test_agent_knowledge tests.test_agent_knowledge_index tests.test_agent_knowledge_snapshot tests.test_agent_delivery tests.test_agent_evaluation -v
```

Expected: PASS; 未审核/过期知识不能成为 hard rule 或关键参数，删除偏好不会破坏项目证据，且旧 exporter/importer 测试保持通过。

- [ ] **Step 4: Run the full regression gate**

Run:

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q .\lsprepost_mcp
git diff --check
git status --short
```

Expected: PASS; 全部测试通过、无编译错误、无 whitespace error，且只存在计划内修改。

- [ ] **Step 5: Commit the Phase D checkpoint**

Memory/Knowledge 分册中的逐任务提交必须已完成；再创建路线图级回退锚点：

```powershell
git status --short
git commit --allow-empty -m "chore(agent): checkpoint memory knowledge and delivery gate"
```

Expected: PASS; checkpoint commit 创建成功，且没有遗漏的未提交 Phase D 文件。

### Task 5: L2 Release Acceptance

**Files:**
- Verify: `README.md`, `README.zh-CN.md`, `resources/README.zh-CN.md`, `docs/PROJECT_STRUCTURE.zh-CN.md`
- Verify: `scripts/run_agent_evals.py`, `scripts/check_deepseek_agent.py`, `start_agent_web_app.cmd`, `scripts/start_web_app.ps1`
- Verify: `workspace/agent/` 仅包含本地运行数据且被 Git 忽略。

**Interfaces:**
- Consumes: 三个已完成分册。
- Produces: 可发布但默认关闭的 L2 MVP。

- [ ] **Step 1: Prove the real-provider gate is RED without a Key**

Run:

```powershell
Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
$env:LSPP_AGENT_ENABLED="1"
$env:LSPP_AGENT_PROVIDER="deepseek"
python scripts/check_deepseek_agent.py --json-only --no-tools
```

Expected: FAIL before provider construction with the documented missing-Key/explicit-authorization error; network, project, SQLite and long-term-memory write counts remain zero.

- [ ] **Step 2: Run offline ReplayProvider acceptance as GREEN through unittest**

Run:

```powershell
$env:LSPP_AGENT_ENABLED="1"
$env:LSPP_AGENT_PROVIDER="replay"
python -m unittest tests.test_agent_evaluation.AgentEvaluationTests -v
```

Expected: PASS; 需求提取、缺失项追问、计划批准、单个 R2 生成、校验、恢复和交付场景全部通过，R3/R4 执行计数为 0。

- [ ] **Step 3: Run the evaluation CLI as a non-test entry point**

This command is an operational smoke run, not the automated test runner:

```powershell
$env:LSPP_AGENT_ENABLED="1"
$env:LSPP_AGENT_PROVIDER="replay"
python scripts/run_agent_evals.py --suite tests/fixtures/agent/evals/l2_mvp.json
```

Expected: PASS; the command exits 0 and reports the same zero-tolerance metrics as the unittest gate.

- [ ] **Step 4: Run the optional real DeepSeek canary**

仅在用户显式提供 `DEEPSEEK_API_KEY` 并同意产生 API 费用时运行：

```powershell
$env:LSPP_AGENT_ENABLED="1"
$env:LSPP_AGENT_PROVIDER="deepseek"
$env:LSPP_AGENT_DEEPSEEK_MODEL="deepseek-v4-flash"
python scripts/check_deepseek_agent.py --json-only --no-tools
```

Expected: PASS; 返回通过本地 schema 校验的单个 `AgentDecision`，不创建项目、不写长期记忆、不调用任何执行器。

- [ ] **Step 5: Verify rollback as GREEN**

Run:

```powershell
$env:LSPP_AGENT_ENABLED="0"
python -m unittest tests.test_agent_feature_flag tests.test_agent_legacy_compat tests.test_web_api tests.test_jsonrpc -v
```

Expected: PASS; 关闭 Agent 后旧 MCP/Web 路径与基线一致，既有 Agent 数据保留但不被旧项目发现或清理。

- [ ] **Step 6: Commit the L2 release checkpoint**

```powershell
git status --short
git commit --allow-empty -m "chore(agent): checkpoint L2 release acceptance"
```

Expected: PASS; checkpoint commit 创建成功，且所有三个分册的实现与文档提交均已落地。

- [ ] **Step 7: Stop before L3**

不得在本路线图内加入自动 GUI、求解器启动、Phase 18E/F 私有接口或自动工程结论。L3 必须在 L2 真实使用评测通过后另写设计与实施计划。
