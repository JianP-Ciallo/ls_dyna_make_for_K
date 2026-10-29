# Blast Modeling Agent Foundation and DeepSeek API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立默认关闭、不会写正式项目的 Agent A-B 阶段基础层：版本化 `ModelingCaseSpec`、profile/完整性合同、确定性能力快照、受控 ALE 纯适配器、DeepSeek 云端 provider、Fake/Replay provider，以及单次只读 intake。

**Architecture:** `resources/schemas/agent/` 是结构合同事实源；`profiles.py` 是 profile descriptor/registry 事实源；`hashing.py` 为 A-C 阶段提供唯一 canonical JSON SHA-256 规范。适配器先只编译不含控制参数的 `domain_arguments`，A-B 仅能通过 `bind_dry_run()` 注入安全控制；Phase C 在得到 `action_id` 和派生目标名后才实现 `bind_create()`。Provider 与 intake 不持久化状态、不执行写工具，所有云端 JSON 均在本地闭合校验。

**Tech Stack:** Python 3.10+、标准库 `dataclasses/json/hashlib/urllib`、`unittest`、JSON 资源、现有 `ale_blast_demo_input_schema()` 与 `tool_generate_ale_blast_demo(..., dry_run=True)`。

**Spec:** docs/superpowers/specs/2026-08-15-blast-modeling-agentization-design.md

## Global Constraints

- 前置设计：`docs/superpowers/specs/2026-08-15-blast-modeling-agentization-design.md`。
- 前置路线：`docs/superpowers/plans/2026-08-22-blast-modeling-agent-l2-mvp-roadmap.md`。
- Python 最低版本保持 3.10；核心不新增第三方依赖。
- `LSPP_AGENT_ENABLED` 默认关闭；导入任何 `lsprepost_mcp.agent` 模块不得创建目录、数据库或日志，不得读取 API Key，不得发出网络请求。
- 现有 `TOOLS` 与 `tool_list()` 的 44 个 descriptor 在 feature flag 关闭和打开时都逐项不变；A-B 不修改 `tools.py`、`server.py`、旧 schema 或 Web API。
- 根目录 `.gitignore` 已有 `/workspace/`，本计划不再修改 `.gitignore`。
- DeepSeek base URL 默认且 MVP 仅允许 `https://api.deepseek.com`；模型只允许 2026-08-22 当前模型 `deepseek-v4-flash`、`deepseek-v4-pro`，默认 `deepseek-v4-flash`，拒绝退役别名 `deepseek-chat`、`deepseek-reasoner`。
- DeepSeek 请求固定 `stream=false`、`thinking.type=disabled`、`response_format.type=json_object`；prompt 必须出现 `json`，请求不得包含 `tools`、`tool_choice`、`parallel_tool_calls`。
- DeepSeek JSON mode 不是 JSON Schema mode；响应必须再次经过本地 schema、动作和 capability snapshot 校验。
- A-B 阶段模型可见能力只允许 R0 与受控 R1 dry-run；不得暴露 R2 `agent.intent.create_controlled_ale`、真实 writer、executor key、恢复探针、审批控制、任意路径或外部进程。
- `explosive_mass_kg` 表示当前生成器使用的实际 Composition-B 质量，不是 TNT 当量；MVP 固定 `explosive_material_id=composition_b_reference`，没有明确换算规则时禁止改写物理含义。
- 当前工具没有 `stand_off_m` 输入；追问和合同使用 `/blast_source/explosive_center_m`，并结合板面位置/几何关系做确定性校验。
- 缺失值必须省略并进入 `open_questions`；禁止 `null`、`"unknown"`、NaN、Infinity 或虚构占位值。
- 所有自动化测试都使用 `python -m unittest ...`；真实 DeepSeek 仅由用户显式运行 canary，不进入单元测试或默认 CI。

## Stable Interfaces Shared with Phase C

```python
# lsprepost_mcp/agent/hashing.py
def canonical_json_bytes(value: JSONValue) -> bytes: ...
def canonical_sha256(value: JSONValue) -> str: ...

# lsprepost_mcp/agent/adapters/base.py
@dataclass(frozen=True)
class AdapterCompilation:
    tool_name: str
    tool_contract_hash: str
    adapter_id: str
    adapter_version: str
    domain_arguments: JSONDict

def bind_dry_run(
    compilation: AdapterCompilation,
    validation_project_name: str,
) -> JSONDict: ...
```

`domain_arguments` 永远不含 `project_name`、`dry_run`、`if_exists`。Phase C 复用同一 `canonical_sha256()`，以 domain arguments、用户基名与 precondition 计算 `action_id`，再派生 `target_project_name`，最后新增 `bind_create(compilation, target_project_name)` 注入 `dry_run=False`、`if_exists="error"`；派生目标名本身不得进入其自身 `action_id` 输入，避免循环依赖。

## File Map

| 文件 | 单一职责 |
| --- | --- |
| `lsprepost_mcp/agent/__init__.py` | 包版本与无副作用公共导出 |
| `lsprepost_mcp/agent/config.py` | feature flag、provider 与 DeepSeek 环境配置 |
| `lsprepost_mcp/agent/hashing.py` | A-C 唯一 canonical JSON bytes/SHA-256 实现 |
| `lsprepost_mcp/agent/schema_loader.py` | 固定 allowlist schema 装载及受支持子集校验 |
| `lsprepost_mcp/agent/profiles.py` | `CaseProfileDescriptor`、registry、required path 完整性规则 |
| `lsprepost_mcp/agent/contracts.py` | `ModelingCaseSpec`、证据门禁、完整性与两类指纹 |
| `lsprepost_mcp/agent/decisions.py` | `AgentDecision` 闭合解析与阶段能力校验 |
| `lsprepost_mcp/agent/tool_catalog.py` | 44-tool 基线、完整 descriptor、`CapabilitySnapshot`、只读资源 allowlist |
| `lsprepost_mcp/agent/adapters/base.py` | adapter capability/compilation 协议及 `bind_dry_run()` |
| `lsprepost_mcp/agent/adapters/controlled_ale.py` | `controlled_ale_blast@1` 到 13 个 ALE domain arguments 的纯映射 |
| `lsprepost_mcp/agent/providers/base.py` | provider 请求/响应/能力/错误/health/summary 合同 |
| `lsprepost_mcp/agent/providers/http.py` | 有响应大小上限的 stdlib JSON transport |
| `lsprepost_mcp/agent/providers/deepseek.py` | DeepSeek OpenAI-compatible 非流式实现 |
| `lsprepost_mcp/agent/providers/fake.py` | 可编程、可检查请求的离线 fake |
| `lsprepost_mcp/agent/providers/replay.py` | 按 request fingerprint 匹配的离线 replay |
| `lsprepost_mcp/agent/intake.py` | 单次只读目标提取、追问与计划候选，无 tool loop |
| `resources/schemas/agent/blast_modeling_case@1.schema.json` | 闭合 base case schema |
| `resources/schemas/agent/profiles/controlled_ale_blast@1.schema.json` | 闭合 controlled ALE profile schema |
| `resources/schemas/agent/agent_decision@1.schema.json` | 闭合 decision schema |
| `resources/schemas/agent/capability_snapshot@1.schema.json` | 可持久化能力快照结构 |
| `resources/schemas/agent/readonly_resource_snapshot@1.schema.json` | 只读资源引用快照结构 |
| `tests/snapshots/mcp_tool_catalog_agent_baseline.json` | 44 个旧 descriptor 精确快照 |
| `tests/fixtures/agent/controlled_ale_case_complete.json` | 完整 controlled ALE case |
| `tests/fixtures/agent/controlled_ale_case_incomplete.json` | 结构有效但完整性不足的 case |
| `tests/fixtures/agent/replay/*.json` | 带 request fingerprint 的离线 provider 记录 |
| `scripts/check_deepseek_agent.py` | 用户显式授权后运行的只读 canary |
| `README.zh-CN.md` | 开关、隐私边界、离线测试与 canary 文档 |

### Task 1: Freeze Legacy Compatibility and Add Side-Effect-Free Settings

**Files:**
- Create: `lsprepost_mcp/agent/__init__.py`
- Create: `lsprepost_mcp/agent/config.py`
- Create: `tests/test_agent_feature_flag.py`
- Create: `tests/test_agent_legacy_compat.py`
- Create: `tests/snapshots/mcp_tool_catalog_agent_baseline.json`

**Interfaces:**
- Produces: `AgentSettings`, `agent_enabled(env=None)`, `load_agent_settings(env=None, workspace_root=WORKSPACE_DIR)`。
- Does not modify: `.gitignore`, `lsprepost_mcp/config.py`, `lsprepost_mcp/tools.py`。

- [ ] **Step 1: Write failing feature-flag and import-side-effect tests**

```python
class AgentFeatureFlagTests(unittest.TestCase):
    def test_disabled_by_default_does_not_create_workspace_or_require_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {}, clear=True
        ):
            settings = load_agent_settings(workspace_root=Path(temp_dir))
        self.assertFalse(settings.enabled)
        self.assertEqual("deepseek", settings.provider)
        self.assertFalse((Path(temp_dir) / "agent").exists())

    def test_truthy_values_are_explicit(self) -> None:
        for value in ("1", "true", "yes", "on"):
            self.assertTrue(agent_enabled({"LSPP_AGENT_ENABLED": value}))
        for value in ("", "0", "false", "off", "unexpected"):
            self.assertFalse(agent_enabled({"LSPP_AGENT_ENABLED": value}))
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
python -m unittest tests.test_agent_feature_flag -v
```

Expected: FAIL with missing `lsprepost_mcp.agent`.

- [ ] **Step 3: Implement immutable settings without I/O**

```python
@dataclass(frozen=True)
class AgentSettings:
    enabled: bool
    provider: Literal["deepseek", "fake", "replay"]
    workspace_dir: Path

def agent_enabled(env: Mapping[str, str] | None = None) -> bool: ...

def load_agent_settings(
    env: Mapping[str, str] | None = None,
    *,
    workspace_root: Path = WORKSPACE_DIR,
) -> AgentSettings: ...
```

`load_agent_settings()` 只解析值，不创建 `workspace/agent`，也不调用 `load_deepseek_settings()`；因此关闭开关时没有 Key 也能启动旧服务。`__init__.py` 只定义 `AGENT_PACKAGE_VERSION = "0.1.0"`。

- [ ] **Step 4: Freeze and compare the exact 44 descriptors under both flag values**

先一次性生成并人工审阅快照：

```powershell
python -c "import json; from pathlib import Path; from lsprepost_mcp.tools import tool_list; value=tool_list(); assert len(value['tools']) == 44; Path('tests/snapshots/mcp_tool_catalog_agent_baseline.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')"
```

测试分别在 `LSPP_AGENT_ENABLED=0` 与 `1` 下导入 `tool_list()`，断言顺序、名称、description 和 `inputSchema` 与快照完全相等，且数量为 44。不要快照 `server_info` 的运行结果，因为其 source fingerprint 会随新增 Python 文件真实变化。

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m unittest tests.test_agent_feature_flag tests.test_agent_legacy_compat tests.test_jsonrpc -v
git diff --check
```

Expected: PASS; feature-off imports remain side-effect-free and all 44 frozen descriptors stay byte-for-byte unchanged.

```powershell
git add lsprepost_mcp/agent/__init__.py lsprepost_mcp/agent/config.py tests/test_agent_feature_flag.py tests/test_agent_legacy_compat.py tests/snapshots/mcp_tool_catalog_agent_baseline.json
git commit -m "feat(agent): add disabled-by-default foundation"
```

### Task 2: Add Canonical Hashing, Closed Schemas, Profiles, and Completeness

**Files:**
- Create: `lsprepost_mcp/agent/hashing.py`
- Create: `lsprepost_mcp/agent/schema_loader.py`
- Create: `lsprepost_mcp/agent/profiles.py`
- Create: `lsprepost_mcp/agent/contracts.py`
- Create: `resources/schemas/agent/blast_modeling_case@1.schema.json`
- Create: `resources/schemas/agent/profiles/controlled_ale_blast@1.schema.json`
- Create: `resources/schemas/agent/agent_decision@1.schema.json`
- Create: `tests/fixtures/agent/controlled_ale_case_complete.json`
- Create: `tests/fixtures/agent/controlled_ale_case_incomplete.json`
- Create: `tests/test_agent_contracts.py`

**Interfaces:**

```python
# hashing.py
def canonical_json_bytes(value: JSONValue) -> bytes: ...
def canonical_sha256(value: JSONValue) -> str: ...

# schema_loader.py
class ContractValidationError(ValueError):
    code: str
    path: str

def load_agent_schema(schema_id: str) -> JSONDict: ...
def validate_agent_json(
    value: JSONValue,
    schema: JSONDict,
    path: str = "$",
) -> None: ...

# profiles.py
@dataclass(frozen=True)
class CaseProfileDescriptor:
    profile_id: str
    profile_version: str
    schema_id: str
    scenario_kind: str
    required_paths: tuple[str, ...]
    optional_paths: tuple[str, ...]
    critical_paths: tuple[str, ...]
    canonical_unit_by_path: Mapping[str, str]
    collection_identity_and_ordering: Mapping[str, CollectionRule]
    adapter_id: str
    adapter_version: str
    required_capabilities: tuple[str, ...]

class CaseProfileRegistry:
    def register(self, descriptor: CaseProfileDescriptor) -> None: ...
    def get(
        self,
        profile_id: str,
        profile_version: str,
    ) -> CaseProfileDescriptor: ...

DEFAULT_PROFILE_REGISTRY: CaseProfileRegistry

# contracts.py
@dataclass(frozen=True)
class ModelingCaseSpec:
    document: JSONDict
    profile: CaseProfileDescriptor

    @classmethod
    def parse(
        cls,
        raw: Mapping[str, object],
        registry: CaseProfileRegistry = DEFAULT_PROFILE_REGISTRY,
    ) -> "ModelingCaseSpec": ...

    def to_dict(self) -> JSONDict: ...

@dataclass(frozen=True)
class CompletenessReport:
    missing_required_paths: tuple[str, ...]
    unanswered_question_paths: tuple[str, ...]
    unqualified_evidence_paths: tuple[str, ...]
    ready_for_plan: bool
    ready_for_execution: bool

@dataclass(frozen=True)
class RevisionContext:
    adapter_version: str
    policy_version: str
    checker_version: str

def check_case_completeness(case: ModelingCaseSpec) -> CompletenessReport: ...
def semantic_fingerprint(case: ModelingCaseSpec) -> str: ...
def revision_fingerprint(
    case: ModelingCaseSpec,
    context: RevisionContext,
) -> str: ...
```

- [ ] **Step 1: Write failing canonical hashing tests**

Tests must assert:

- mapping insertion order and insignificant whitespace do not change bytes/hash；
- strings encode as UTF-8 without ASCII-only escaping；
- `-0.0` normalizes to numeric zero；
- NaN、positive/negative Infinity、non-JSON objects and non-string mapping keys fail；
- `None` is a valid generic JSON value for hashing, while schema validation independently rejects it where the contract disallows `null`；
- Phase C can import these helpers without importing providers or adapters。

```powershell
python -m unittest tests.test_agent_contracts.AgentCanonicalHashTests -v
```

Expected: FAIL because `hashing.py` is missing.

- [ ] **Step 2: Implement the one canonical JSON SHA-256 standard**

`canonical_json_bytes()` recursively validates JSON types, rejects bool where a caller claims a number only in schema validation, normalizes negative zero, sorts object keys lexicographically, uses `ensure_ascii=False`、`sort_keys=True`、compact separators and `allow_nan=False`, then returns UTF-8 bytes. `canonical_sha256()` is exactly `sha256(canonical_json_bytes(value)).hexdigest()`；不得在 `contracts.py`、`tool_catalog.py` 或 Phase C 复制另一套实现。

- [ ] **Step 3: Write failing schema/profile/completeness tests**

```python
class AgentProfileContractTests(unittest.TestCase):
    def test_profile_id_and_version_are_separate_and_registered(self) -> None:
        profile = DEFAULT_PROFILE_REGISTRY.get("controlled_ale_blast", "1")
        self.assertEqual("controlled_ale_blast@1", profile.schema_id)
        self.assertEqual("controlled_ale_blast_adapter", profile.adapter_id)

    def test_incomplete_case_is_structurally_valid_but_not_complete(self) -> None:
        case = ModelingCaseSpec.parse(self.incomplete_case())
        report = check_case_completeness(case)
        self.assertIn(
            "/blast_source/explosive_center_m",
            report.missing_required_paths,
        )
        self.assertFalse(report.ready_for_plan)

    def test_composition_b_identity_is_fixed(self) -> None:
        raw = self.complete_case()
        raw["blast_source"]["explosive_material_id"] = "tnt_equivalent"
        with self.assertRaisesRegex(ContractValidationError, "const"):
            ModelingCaseSpec.parse(raw)
```

Also cover unknown property、wrong profile version、null/`unknown`/NaN、bool-as-number、vector length、domain bounds、duplicate assumption/question/resource IDs、unstable collection order and evidence JSON Pointer validity.

```powershell
python -m unittest tests.test_agent_contracts.AgentProfileContractTests -v
```

Expected: FAIL before schemas/registry exist.

- [ ] **Step 4: Create closed base/profile schemas and descriptor registry**

The fixture uses separate profile identity fields:

```json
"scenario": {
  "kind": "controlled_ale_blast",
  "profile_id": "controlled_ale_blast",
  "profile_version": "1",
  "unit_system": "SI_m_s_kg_N_Pa"
}
```

The base requires `schema_version`、`case_id`、`goal`、`scenario`、`field_evidence`、`assumptions`、`open_questions`、`review`、`provenance` and closes top-level names. The selected profile separately closes each profile-owned object. Do not use an `allOf` extension that tries to add fields to an already closed object. Profile physical fields may be omitted so an incomplete case remains representable；`required_paths` and `check_case_completeness()` enforce readiness instead of structural `required`.

`blast_source.explosive_material_id` is `const: "composition_b_reference"`；`explosive_mass_kg` is documented as actual Composition-B mass in kg. All normalized physical values are finite SI. Raw value/unit lives only in evidence.

`field_evidence` source kinds are exactly `user_input`、`approved_preset`、`knowledge_record`、`existing_project`、`tool_result`、`agent_recommendation`. A critical field is qualified only for the first five kinds with an allowed stable `source_ref`/version/hash and required review status；`agent_recommendation` alone is never qualified. Every evidence JSON Pointer must point to an existing value or the same path in `open_questions`.

- [ ] **Step 5: Implement schema loader and deterministic domain checks**

`load_agent_schema()` resolves only a fixed ID-to-resource map and rejects absolute/relative arbitrary paths. The validator supports `type`、`const`、`enum`、`required`、`additionalProperties`、`properties`、`items`、`minItems/maxItems`、`uniqueItems`、`minimum/maximum/exclusiveMinimum`、`minLength/maxLength`、`pattern` and finite-number/bool distinction. Do not reuse the existing server validator alone because it lacks the required keywords.

Cross-field checks enforce domain min < max、explosive center inside domain with existing ALE clearance/mesh rules、positive plate/mesh/time values、unique stable IDs, and stable sort/physical time ordering.

- [ ] **Step 6: Write failing semantic/revision fingerprint tests with corrected timestamp expectations**

```python
def test_identity_and_timestamps_change_neither_fingerprint(self) -> None:
    first = ModelingCaseSpec.parse(self.complete_case())
    changed = self.complete_case()
    changed["case_id"] = "case_other"
    changed["field_evidence"][
        "/blast_source/explosive_mass_kg"
    ]["recorded_at"] = "2099-01-01T00:00:00Z"
    second = ModelingCaseSpec.parse(changed)
    context = RevisionContext("1", "1", "1")
    self.assertEqual(semantic_fingerprint(first), semantic_fingerprint(second))
    self.assertEqual(
        revision_fingerprint(first, context),
        revision_fingerprint(second, context),
    )

def test_evidence_content_and_revision_versions_change_only_revision(self) -> None:
    first = ModelingCaseSpec.parse(self.complete_case())
    changed = self.complete_case()
    changed["field_evidence"][
        "/blast_source/explosive_mass_kg"
    ]["source_ref"] = "approved:mass:v2"
    second = ModelingCaseSpec.parse(changed)
    self.assertEqual(semantic_fingerprint(first), semantic_fingerprint(second))
    self.assertNotEqual(
        revision_fingerprint(first, RevisionContext("1", "1", "1")),
        revision_fingerprint(second, RevisionContext("1", "1", "1")),
    )
    self.assertNotEqual(
        revision_fingerprint(first, RevisionContext("1", "1", "1")),
        revision_fingerprint(first, RevisionContext("2", "1", "1")),
    )
```

Semantic projection includes normalized engineering fields plus stable resource IDs/versions, but excludes `case_id`、evidence、assumptions、questions、review、timestamps、trace/message/display fields. Revision projection includes semantic hash、evidence source/version/hash (excluding timestamps)、assumption/question status、review decision digest、adapter/policy/checker versions, and excludes identity/timestamps/traces.

- [ ] **Step 7: Run GREEN and commit**

```powershell
python -m unittest tests.test_agent_contracts -v
python -m unittest tests.test_schema tests.test_jsonrpc -v
git diff --check
```

Expected: PASS; canonical hashes, closed schemas, profile completeness and legacy schema/JSON-RPC regressions all remain green.

```powershell
git add lsprepost_mcp/agent/hashing.py lsprepost_mcp/agent/schema_loader.py lsprepost_mcp/agent/profiles.py lsprepost_mcp/agent/contracts.py resources/schemas/agent tests/fixtures/agent/controlled_ale_case_complete.json tests/fixtures/agent/controlled_ale_case_incomplete.json tests/test_agent_contracts.py
git commit -m "feat(agent): add profiled modeling contracts"
```

### Task 3: Compile Controlled ALE Domain Arguments and Bind Dry-Run Separately

**Files:**
- Create: `lsprepost_mcp/agent/adapters/__init__.py`
- Create: `lsprepost_mcp/agent/adapters/base.py`
- Create: `lsprepost_mcp/agent/adapters/controlled_ale.py`
- Create: `tests/test_agent_ale_adapter.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class RequiredToolContract:
    tool_name: str
    schema_version: str
    schema_hash: str

@dataclass(frozen=True)
class AdapterCapability:
    adapter_id: str
    adapter_version: str
    supported_case_schema: str
    required_tool_contracts: tuple[RequiredToolContract, ...]
    required_domain_capabilities: tuple[str, ...]
    supported_scenarios: tuple[str, ...]
    output_contract: str

@dataclass(frozen=True)
class AdapterCompilation:
    tool_name: str
    tool_contract_hash: str
    adapter_id: str
    adapter_version: str
    domain_arguments: JSONDict

class CapabilityLookup(Protocol):
    def require_tool_contract(
        self,
        tool_name: str,
    ) -> RequiredToolContract: ...
    def require_domain_capability(
        self,
        capability_id: str,
    ) -> None: ...

class ModelingCaseAdapter(Protocol):
    def capability(self) -> AdapterCapability: ...
    def compile(
        self,
        case: ModelingCaseSpec,
        capabilities: CapabilityLookup,
    ) -> AdapterCompilation: ...

def bind_dry_run(
    compilation: AdapterCompilation,
    validation_project_name: str,
) -> JSONDict: ...
```

- [ ] **Step 1: Write failing separation, mapping, and capability tests**

```python
class ControlledAleAdapterTests(unittest.TestCase):
    def test_compile_returns_only_physical_domain_arguments(self) -> None:
        compiled = ControlledAleAdapter().compile(self.case(), self.snapshot())
        self.assertEqual(
            {
                "mesh_size_m", "domain_min_m", "domain_max_m",
                "explosive_center_m", "explosive_mass_kg",
                "plate_length_m", "plate_width_m", "plate_thickness_m",
                "plate_z_m", "plate_material_name", "end_time_s",
                "d3plot_dt_s", "fsi_dt_s",
            },
            set(compiled.domain_arguments),
        )
        self.assertTrue(
            {"project_name", "dry_run", "if_exists"}.isdisjoint(
                compiled.domain_arguments
            )
        )

    def test_bind_dry_run_injects_only_safe_control_arguments(self) -> None:
        args = bind_dry_run(
            ControlledAleAdapter().compile(self.case(), self.snapshot()),
            "agent_validate_ab12cd34",
        )
        self.assertEqual("agent_validate_ab12cd34", args["project_name"])
        self.assertIs(args["dry_run"], True)
        self.assertEqual("error", args["if_exists"])

    def test_changed_required_tool_contract_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            AdapterCompatibilityError,
            "missing_capability|schema_hash_mismatch",
        ):
            ControlledAleAdapter().compile(
                self.case(),
                self.incompatible_snapshot(),
            )
```

Also assert compilation does not call `tool_generate_ale_blast_demo`、`write_model_project` or create a directory. A case-supplied `project_name`、`dry_run`、`if_exists` is an unknown contract field and fails before compilation.

```powershell
python -m unittest tests.test_agent_ale_adapter -v
```

Expected: FAIL because adapter modules are absent.

- [ ] **Step 2: Implement the expanded capability descriptor and pure mapping**

The adapter capability declares:

- `adapter_id="controlled_ale_blast_adapter"`, `adapter_version="1"`；
- `supported_case_schema="blast_modeling_case@1"`；
- exact `generate_ale_blast_demo` input schema hash from `canonical_sha256(ale_blast_demo_input_schema())`；
- required domain capabilities including controlled ALE、Composition-B source、plate coupling、SI units；
- supported scenario `controlled_ale_blast`；
- output contract identifying the dry-run validation result shape。

`compile()` first requires a complete/qualified case and compatible snapshot, verifies `explosive_material_id == "composition_b_reference"`, then maps the 13 accepted physical fields. It never accepts target name or policy arguments. `bind_dry_run()` validates a safe project name, injects exactly the three control fields, validates the final object against the existing tool input schema plus its missing range/vector rules, and still does not call the handler.

Do not implement `bind_create()` in this task. Phase C owns its implementation after `action_id`/target derivation and must reuse this `AdapterCompilation` unchanged.

- [ ] **Step 3: Add a dry-run integration safety test**

Call the existing handler only in one integration-style test with the bound arguments and patch the project writer. Assert response is validation-only, writer was not called, and no project directory exists. This verifies the current handler's `dry_run=True` contract without exposing it to the model.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m unittest tests.test_agent_ale_adapter tests.test_phase14_ale tests.test_tools -v
git diff --check
```

Expected: PASS; compilation stays pure, dry-run binding writes nothing, and the existing ALE/tool contracts remain unchanged.

```powershell
git add lsprepost_mcp/agent/adapters tests/test_agent_ale_adapter.py
git commit -m "feat(agent): compile controlled ALE domain arguments"
```

### Task 4: Capture Deterministic Capabilities and a Read-Only Resource Allowlist

**Files:**
- Create: `lsprepost_mcp/agent/tool_catalog.py`
- Create: `resources/schemas/agent/capability_snapshot@1.schema.json`
- Create: `resources/schemas/agent/readonly_resource_snapshot@1.schema.json`
- Create: `tests/test_agent_tool_catalog.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class AgentToolDescriptor:
    name: str
    version: str
    input_schema_hash: str
    tags: tuple[str, ...]
    effect: str
    risk: str
    idempotency: str
    confirmation_policy: str
    readiness_requirement: str
    timeout_s: float
    resource_limits: Mapping[str, int]
    concurrency_key: str | None
    dry_run_executor: str | None
    executor: str | None
    recovery_probe: str | None
    result_summarizer: str | None

@dataclass(frozen=True)
class LegacyToolContract:
    tool_name: str
    schema_version: str
    schema_hash: str
    tags: tuple[str, ...]
    side_effect: str
    approval: str
    adapter_version: str | None

@dataclass(frozen=True)
class RegisteredResourceRef:
    resource_kind: str
    resource_id: str
    version: str
    validation_status: str
    requires_project_review: bool
    summary: str

@dataclass(frozen=True)
class ReadOnlyResourceSnapshot:
    schema_version: str
    refs: tuple[RegisteredResourceRef, ...]
    snapshot_hash: str

@dataclass(frozen=True)
class CapabilitySnapshot:
    schema_version: str
    legacy_tools: tuple[LegacyToolContract, ...]
    agent_tools: tuple[AgentToolDescriptor, ...]
    adapters: tuple[AdapterCapability, ...]
    snapshot_hash: str

    def require_tool_contract(
        self,
        tool_name: str,
    ) -> RequiredToolContract: ...
    def require_domain_capability(
        self,
        capability_id: str,
    ) -> None: ...

def build_control_catalog() -> Mapping[str, AgentToolDescriptor]: ...
def capture_capability_snapshot() -> CapabilitySnapshot: ...
def capture_readonly_resource_snapshot(
    invoke_readonly: Callable[[str, JSONDict], JSONDict],
) -> ReadOnlyResourceSnapshot: ...
def compare_capability_snapshots(
    saved: CapabilitySnapshot,
    current: CapabilitySnapshot,
    required_ids: Collection[str],
) -> CapabilityCompatibility: ...
def require_descriptor(
    name: str,
    catalog: Mapping[str, AgentToolDescriptor],
) -> AgentToolDescriptor: ...
def model_visible_catalog(
    snapshot: CapabilitySnapshot,
    *,
    phase: Literal["foundation"] = "foundation",
) -> JSONDict: ...
```

- [ ] **Step 1: Write failing descriptor/snapshot/read-only tests**

Tests assert:

- snapshot has all 44 legacy names in original order and their canonical input schema hashes；
- repeated capability and resource capture produces identical canonical bytes/hash, and both documents validate against their versioned schemas；
- a required schema hash/adapter version change is incompatible and names the exact capability；
- a non-required additive capability is reported but does not silently change required compatibility；
- descriptor omission raises `descriptor_missing`；
- serialized model catalog has no callable、executor/recovery key、path、secret、timestamp or approval override；
- foundation model-visible risks are a subset of `{R0, R1}` and contain no R2 intent。

```python
def test_foundation_does_not_expose_write_intent(self) -> None:
    visible = model_visible_catalog(capture_capability_snapshot())
    text = json.dumps(visible, ensure_ascii=False)
    self.assertNotIn("agent.intent.create_controlled_ale", text)
    self.assertNotIn('"risk":"R2"', text.replace(" ", ""))
```

```powershell
python -m unittest tests.test_agent_tool_catalog -v
```

Expected: FAIL because catalog/snapshot code is absent.

- [ ] **Step 2: Define the exact read-only resource allowlist**

```python
READ_ONLY_RESOURCE_TOOL_ALLOWLIST = frozenset({
    "list_component_templates", "get_component_template",
    "list_physics_actions", "list_materials", "get_material",
    "validate_material_resource", "list_structural_resources",
    "get_structural_resource", "list_model_resources",
    "get_model_resource", "validate_model_resource",
})
```

Only public resource ID、version、kind、validation status、requires-project-review and concise description may enter `ReadOnlyResourceSnapshot.refs`. Strip absolute paths、internal `_...` fields、complete keyword decks、project content and executable data. Explicitly exclude:

- `server_info` because it returns local paths/process metadata；
- `read_project` and `validate_model` because validation refresh can write checks/state；
- `export_model_resource`、archive/import/open/export/run tools because they write or call external programs；
- `list_projects`、`model_summary` and project files from cloud intake by default because they may contain private project context。

- [ ] **Step 3: Implement full descriptors and deterministic snapshot comparison**

Maintain a metadata overlay separate from legacy `TOOLS`. The snapshot includes every legacy contract but only explicitly registered agent candidates get full `AgentToolDescriptor`. When building a model-visible catalog, any candidate without the full descriptor fails closed.

Foundation virtual capabilities are limited to `agent.case.check` and `agent.case.compile_controlled_ale`, plus allowlisted read-only resource lookups. The R1 compile capability represents bound dry-run validation, never raw caller-controlled `generate_ale_blast_demo` arguments. Define the future R2 descriptor only in the Phase C plan, not here.

`CapabilitySnapshot` implements the Task 3 `CapabilityLookup` methods by returning a `RequiredToolContract` view and checking declared adapter domain capabilities, without creating an adapter-to-catalog import cycle. Capability and read-only resource snapshot hashes are each computed from all fields except their own hash；do not include capture time. Use `canonical_sha256()` from `hashing.py`.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m unittest tests.test_agent_tool_catalog tests.test_agent_legacy_compat tests.test_jsonrpc -v
git diff --check
```

Expected: PASS; capability/resource snapshots are deterministic, incomplete descriptors fail closed, and the 44-tool baseline is unchanged.

```powershell
git add lsprepost_mcp/agent/tool_catalog.py resources/schemas/agent/capability_snapshot@1.schema.json resources/schemas/agent/readonly_resource_snapshot@1.schema.json tests/test_agent_tool_catalog.py
git commit -m "feat(agent): snapshot fail-closed capabilities"
```

### Task 5: Define Provider Contracts, Configuration, Fake, and Fingerprinted Replay

**Files:**
- Create: `lsprepost_mcp/agent/providers/__init__.py`
- Create: `lsprepost_mcp/agent/providers/base.py`
- Create: `lsprepost_mcp/agent/providers/fake.py`
- Create: `lsprepost_mcp/agent/providers/replay.py`
- Modify: `lsprepost_mcp/agent/config.py`
- Create: `tests/fixtures/agent/replay/intake_missing_fields.json`
- Create: `tests/fixtures/agent/replay/intake_plan_candidate.json`
- Create: `tests/test_agent_providers.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    provider_id: str
    native_tool_calls: bool
    json_mode: bool
    streaming: bool
    parallel_tool_calls: bool
    thinking: bool
    context_window_tokens: int
    max_output_tokens: int

@dataclass(frozen=True)
class ProviderMessage:
    role: Literal["system", "user", "assistant"]
    content: str

@dataclass(frozen=True)
class ContextSummary:
    provider_id: str
    summary: JSONDict
    source_event_count: int
    request_fingerprint: str

@dataclass(frozen=True)
class ProviderHealth:
    provider_id: str
    model: str
    ok: bool
    detail_code: str

@dataclass(frozen=True)
class ProviderRequest:
    request_id: str
    system_prompt: str
    messages: tuple[ProviderMessage, ...]
    max_output_tokens: int

@dataclass(frozen=True)
class ProviderResponse:
    provider_id: str
    model: str
    request_id: str
    content: JSONDict
    usage: JSONDict
    finish_reason: str
    latency_ms: int

@dataclass(frozen=True)
class ContextBudget:
    max_input_tokens: int
    max_output_tokens: int

class LLMProvider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...
    def create_decision(
        self,
        request: ProviderRequest,
        response_schema: JSONDict,
    ) -> ProviderResponse: ...
    def summarize_context(
        self,
        events: Sequence[JSONDict],
        budget: ContextBudget,
    ) -> ContextSummary: ...
    def health_check(self) -> ProviderHealth: ...

def provider_request_fingerprint(
    request: ProviderRequest,
    response_schema: JSONDict,
) -> str: ...
```

`ProviderRequest` deliberately does not own `response_schema`；the design signature passes it separately. Request fingerprint includes provider-visible prompt/messages/output budget and response schema, but excludes request ID、latency、timestamps and secrets.

- [ ] **Step 1: Write failing settings/protocol tests**

Test these defaults and gates:

- `https://api.deepseek.com`、`deepseek-v4-flash`、timeout 30s、max retries 2、app output cap 16384；
- only `deepseek-v4-flash|deepseek-v4-pro`；
- only HTTPS host `api.deepseek.com`, no credentials/query/fragment；
- timeout `1..120`、retry `0..3`、output `256..16384`, all finite；
- API Key `repr=False` and absent from errors；
- loading general disabled Agent settings never requires a Key；constructing enabled DeepSeek settings does require it；
- Fake、Replay and later DeepSeek expose all four protocol methods and all capability fields。

```powershell
python -m unittest tests.test_agent_providers.AgentProviderContractTests -v
```

Expected: FAIL before provider types exist.

- [ ] **Step 2: Implement provider contracts and DeepSeek settings**

```python
class ProviderError(RuntimeError):
    def __init__(
        self,
        category: Literal[
            "authentication", "rate_limit", "timeout", "unavailable",
            "context_exceeded", "empty_response", "truncated",
            "invalid_json", "unknown_response",
        ],
        message: str,
        *,
        retryable: bool,
        status: int | None = None,
    ) -> None: ...

@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: Literal[
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ] = "deepseek-v4-flash"
    timeout_s: float = 30.0
    max_retries: int = 2
    max_output_tokens: int = 16384
    max_response_bytes: int = 4 * 1024 * 1024
```

- [ ] **Step 3: Write failing Fake/Replay behavioral tests**

```python
class FakeReplayProviderTests(unittest.TestCase):
    def test_fake_records_request_and_validates_schema(self) -> None:
        provider = FakeProvider([self.response("ask_user")])
        provider.create_decision(self.request(), self.schema())
        self.assertEqual(1, len(provider.requests))

    def test_replay_matches_fingerprint_not_fifo_position(self) -> None:
        provider = ReplayProvider.from_files(
            [PLAN_FIXTURE, QUESTION_FIXTURE]
        )
        response = provider.create_decision(
            self.question_request(),
            self.schema(),
        )
        self.assertEqual("ask_user", response.content["action"])

    def test_replay_rejects_unknown_or_exhausted_fingerprint(self) -> None:
        with self.assertRaises(ReplayMismatchError):
            self.provider().create_decision(
                self.changed_request(),
                self.schema(),
            )
```

Replay fixture format contains `schema_version`、`request_fingerprint`、sanitized request summary and `response`；no Key/header. Load into a fingerprint map, reject duplicates, consume a matching record exactly once, and never fall back to FIFO. Both Fake and Replay locally validate the supplied `response_schema`, implement deterministic `summarize_context()`/`health_check()`, expose remaining count, and perform no network/filesystem writes after fixture loading.

```powershell
python -m unittest tests.test_agent_providers.FakeReplayProviderTests -v
```

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m unittest tests.test_agent_providers.AgentProviderContractTests tests.test_agent_providers.FakeReplayProviderTests tests.test_agent_feature_flag -v
git diff --check
```

Expected: PASS; Fake/Replay satisfy the full provider contract, replay matches request fingerprints, and no network or enabled-only side effect occurs.

```powershell
git add lsprepost_mcp/agent/providers/__init__.py lsprepost_mcp/agent/providers/base.py lsprepost_mcp/agent/providers/fake.py lsprepost_mcp/agent/providers/replay.py lsprepost_mcp/agent/config.py tests/fixtures/agent/replay tests/test_agent_providers.py
git commit -m "feat(agent): add offline provider contracts"
```

### Task 6: Implement the DeepSeek OpenAI-Compatible JSON Provider

**Files:**
- Create: `lsprepost_mcp/agent/providers/http.py`
- Create: `lsprepost_mcp/agent/providers/deepseek.py`
- Modify: `tests/test_agent_providers.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class HttpJsonResponse:
    status: int
    headers: Mapping[str, str]
    body: JSONDict

class JsonTransport(Protocol):
    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: JSONDict,
        timeout_s: float,
        max_response_bytes: int,
    ) -> HttpJsonResponse: ...

class DeepSeekProvider:
    def __init__(
        self,
        settings: DeepSeekSettings,
        *,
        transport: JsonTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None: ...
    def capabilities(self) -> ProviderCapabilities: ...
    def create_decision(
        self,
        request: ProviderRequest,
        response_schema: JSONDict,
    ) -> ProviderResponse: ...
    def summarize_context(
        self,
        events: Sequence[JSONDict],
        budget: ContextBudget,
    ) -> ContextSummary: ...
    def health_check(self) -> ProviderHealth: ...
```

- [ ] **Step 1: Write failing exact request-shape tests**

Assert the transport receives:

```python
{
    "model": "deepseek-v4-flash",
    "messages": [...],
    "response_format": {"type": "json_object"},
    "thinking": {"type": "disabled"},
    "stream": False,
    "max_tokens": requested_bounded_tokens,
}
```

URL is exactly `https://api.deepseek.com/chat/completions`；Authorization is `Bearer ...`；system prompt contains case-insensitive `json`. Assert payload omits `tools`、`tool_choice`、`parallel_tool_calls` and any prior `reasoning_content`.

```powershell
python -m unittest tests.test_agent_providers.DeepSeekProviderRequestTests -v
```

Expected: FAIL because the provider is missing.

- [ ] **Step 2: Write failing response-shape and finish-reason tests**

Cover all of these independently:

- exactly one choice、one string `message.content`、decoded JSON object、`finish_reason == "stop"` -> success；
- empty/whitespace content -> `empty_response`；
- malformed JSON or top-level array/scalar -> `invalid_json`；
- locally schema-invalid object -> fail closed before `ProviderResponse`；
- missing/multiple choices -> `unknown_response`；
- `finish_reason == "length"` -> `truncated`；
- `finish_reason == "tool_calls"` or any non-empty `message.tool_calls` -> `unknown_response` and never execute；
- `content_filter` -> `unknown_response`；
- `insufficient_system_resource` -> `unavailable`, retryable within bound；
- response over byte cap -> `truncated`；
- `reasoning_content`, if unexpectedly returned, is ignored and never stored/logged/replayed。

```powershell
python -m unittest tests.test_agent_providers.DeepSeekProviderResponseTests -v
```

- [ ] **Step 3: Implement bounded stdlib transport and error classification**

`StdlibJsonTransport` reads at most `max_response_bytes + 1`, parses only a JSON object, limits error bodies to 64 KiB, never includes Authorization/API Key or an untrusted full response body in exceptions. Map:

| Condition | Category | Retryable |
| --- | --- | --- |
| HTTP 401/403 | `authentication` | no |
| HTTP 429 | `rate_limit` | yes |
| socket/DNS timeout | `timeout` | yes |
| HTTP 5xx / insufficient resource | `unavailable` | yes |
| provider context-limit error | `context_exceeded` | no |
| empty success content | `empty_response` | no |
| length/byte limit | `truncated` | no |
| JSON decode/object/schema failure | `invalid_json` | no |
| other status/shape/finish/tool call | `unknown_response` | no |

Retry only retryable categories, at deterministic injected delays `0.25, 0.5, 1.0` truncated by `max_retries`. Never retry authentication, local contract failures, empty output or truncated output.

- [ ] **Step 4: Implement all four provider methods**

`capabilities()` truthfully reports DeepSeek native capabilities (including tool/parallel/thinking support), with current tests pinning `context_window_tokens=1_000_000` and provider ceiling `max_output_tokens=393_216` (384 Ki tokens), while the application request cap remains 16384 and MVP policy still disables/omits those features. `summarize_context()` makes an independent JSON-mode call with its own closed summary schema and budget. `health_check()` calls `/models` only when explicitly invoked, validates the configured model appears, and never runs at import/construction. Tests inject transport for both.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m unittest tests.test_agent_providers -v
python -m unittest tests.test_agent_legacy_compat tests.test_web_api -v
git diff --check
```

Expected: PASS; all tests use fake transport and network count is zero.

```powershell
git add lsprepost_mcp/agent/providers/http.py lsprepost_mcp/agent/providers/deepseek.py tests/test_agent_providers.py
git commit -m "feat(agent): connect DeepSeek JSON API safely"
```

### Task 7: Add Closed Decisions and Single-Shot Read-Only Intake

**Files:**
- Create: `lsprepost_mcp/agent/decisions.py`
- Create: `lsprepost_mcp/agent/intake.py`
- Create: `tests/test_agent_intake.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class AgentDecision:
    decision_id: str
    run_id: str
    expected_revision: int
    action: Literal["ask_user", "propose_plan", "call_tool", "finish"]
    arguments: JSONDict
    concise_rationale: str
    evidence_refs: tuple[str, ...]

def parse_agent_decision(
    raw: JSONDict,
    *,
    expected_run_id: str,
    expected_revision: int,
    snapshot: CapabilitySnapshot,
) -> AgentDecision: ...

@dataclass(frozen=True)
class ReadOnlyIntakeRequest:
    run_id: str
    expected_revision: int
    objective: str
    current_case: JSONDict | None
    capability_snapshot: CapabilitySnapshot
    resource_snapshot: ReadOnlyResourceSnapshot

@dataclass(frozen=True)
class IntakeResult:
    decision: AgentDecision
    provider_id: str
    request_fingerprint: str

def compile_intake_request(
    value: ReadOnlyIntakeRequest,
) -> ProviderRequest: ...
def run_read_only_intake(
    provider: LLMProvider,
    value: ReadOnlyIntakeRequest,
) -> IntakeResult: ...
```

- [ ] **Step 1: Write failing closed decision tests**

`agent_decision@1` allows exactly `decision_id`、`run_id`、`expected_revision`、`action`、`arguments`、`concise_rationale`、`evidence_refs`. Action-specific arguments are closed. Reject top-level or nested `required_approval`、`approval_hint`、`manual_ack`、`force`、`allow_external`、`if_exists`、executable path、unknown action, wrong run ID, wrong revision, unknown tool and multiple actions encoded in one response.

For `call_tool`, only a capability whose name appears in `model_visible_catalog(snapshot)` and whose risk is R0/R1 is accepted. It remains a proposed read-only/dry-run call；this task does not execute it.

```powershell
python -m unittest tests.test_agent_intake.AgentDecisionTests -v
```

Expected: FAIL before decision parser exists.

- [ ] **Step 2: Write failing incomplete-case and plan-candidate intake tests**

```python
class AgentIntakeTests(unittest.TestCase):
    def test_incomplete_case_asks_for_real_profile_paths(self) -> None:
        result = run_read_only_intake(
            self.replay(),
            self.incomplete_request(),
        )
        self.assertEqual("ask_user", result.decision.action)
        self.assertEqual(
            [
                "/blast_source/explosive_mass_kg",
                "/blast_source/explosive_center_m",
            ],
            result.decision.arguments["missing_fields"],
        )

    def test_complete_case_returns_read_only_plan_without_r2_intent(self) -> None:
        result = run_read_only_intake(
            self.fake(),
            self.complete_request(),
        )
        self.assertEqual("propose_plan", result.decision.action)
        self.assertNotIn(
            "agent.intent.create_controlled_ale",
            json.dumps(asdict(result.decision)),
        )

    def test_intake_never_invokes_handlers_or_writes_state(self) -> None:
        with patch(
            "lsprepost_mcp.tool_generation.tool_generate_ale_blast_demo"
        ) as handler:
            run_read_only_intake(
                self.replay(),
                self.incomplete_request(),
            )
        handler.assert_not_called()
```

Also assert the Composition-B const/source gate cannot be weakened by a provider response, replay matches the compiled request fingerprint, objective length is `1..10000`, `resource_snapshot.refs` contain no path/private payload, and exactly one `create_decision(request, response_schema)` call occurs.

```powershell
python -m unittest tests.test_agent_intake.AgentIntakeTests -v
```

- [ ] **Step 3: Implement one-call intake without runtime/orchestrator behavior**

The prompt requires one JSON object, omission rather than guessed values, exact JSON Pointer questions, only supplied snapshot capabilities, and the warning that software validation is not engineering validation. It includes only normalized current case、snapshot digest/model-visible summaries and sanitized resource refs. It excludes complete `.k` files、absolute paths、secrets、private project documents、executors and approval mechanisms.

`run_read_only_intake()` performs exactly: validate input -> compile provider request -> call provider once with decision schema -> parse/validate decision -> return result. It does not run a tool loop, call a handler, mutate case state, create a project, open SQLite or persist provider reasoning.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m unittest tests.test_agent_intake tests.test_agent_providers.FakeReplayProviderTests tests.test_agent_tool_catalog -v
git diff --check
```

Expected: PASS; intake returns one locally validated decision, exposes no R2 intent, invokes no handler, and performs no persistence or project write.

```powershell
git add lsprepost_mcp/agent/decisions.py lsprepost_mcp/agent/intake.py tests/test_agent_intake.py
git commit -m "feat(agent): add read-only modeling intake"
```

### Task 8: Document and Verify the Optional DeepSeek Canary

**Files:**
- Create: `scripts/check_deepseek_agent.py`
- Modify: `README.zh-CN.md`
- Modify: `tests/test_agent_providers.py`
- Modify: `tests/test_agent_intake.py`

**Interfaces:**
- Canary requires `--json-only --no-tools`, `LSPP_AGENT_ENABLED=1`, and `DEEPSEEK_API_KEY`。
- Canary invokes only `run_read_only_intake()` and prints a sanitized decision；it imports no writer/runtime/action module。

- [ ] **Step 1: Write a failing subprocess safety test for canary gates**

Without flags, without the feature flag, and without Key, the script exits before provider construction. Patch provider/transport and assert `--json-only --no-tools` makes one read-only request, never calls project writer, and never prints the Key.

```powershell
python -m unittest tests.test_agent_providers.DeepSeekCanaryTests -v
```

Expected: FAIL because `scripts/check_deepseek_agent.py` and its explicit canary gates do not exist yet.

- [ ] **Step 2: Implement and document explicit canary usage**

```powershell
$env:LSPP_AGENT_ENABLED="1"
$env:DEEPSEEK_API_KEY="<从 DeepSeek 平台获取的密钥>"
$env:LSPP_AGENT_DEEPSEEK_MODEL="deepseek-v4-flash"
python scripts/check_deepseek_agent.py --json-only --no-tools
```

Documentation states what normalized fields/resource summaries leave the machine, that thinking is disabled but cloud processing still occurs, that no real project is written, that output is not engineering approval, and that Fake/Replay are the default CI paths. Do not place a real Key or provider response in fixtures.

- [ ] **Step 3: Run the complete foundation gate**

```powershell
python -m unittest tests.test_agent_feature_flag tests.test_agent_legacy_compat tests.test_agent_contracts tests.test_agent_ale_adapter tests.test_agent_tool_catalog tests.test_agent_providers tests.test_agent_intake -v
python -m unittest tests.test_jsonrpc tests.test_schema tests.test_tools tests.test_web_api tests.test_phase14_ale -v
python -m compileall -q .\lsprepost_mcp
git diff --check
```

Expected: PASS without `DEEPSEEK_API_KEY`, network, project writes, SQLite or Agent directories. The real canary command is optional and must not be run as part of this gate.

- [ ] **Step 4: Commit docs/canary**

```powershell
git add scripts/check_deepseek_agent.py README.zh-CN.md tests/test_agent_providers.py tests/test_agent_intake.py
git commit -m "docs(agent): add opt-in DeepSeek canary"
```

## Foundation Completion Gate

- [ ] All task test commands use `python -m unittest` and pass from repository root.
- [ ] `tests/snapshots/mcp_tool_catalog_agent_baseline.json` still matches all 44 legacy descriptors with feature flag both off and on.
- [ ] Importing Agent modules with the flag off creates no filesystem entries, requires no Key, and sends no network request.
- [ ] Base/profile schemas are closed, profile ID/version are separate, incomplete cases are representable, and completeness/evidence gates fail closed.
- [ ] Composition-B identity is constant, its kg mass is not silently treated as TNT equivalent, and questions use `explosive_center_m` rather than nonexistent `stand_off_m`.
- [ ] Semantic/revision fingerprints share `hashing.py`；case IDs/timestamps/traces change neither, while evidence content、review/assumption/question state and adapter/policy/checker versions change revision.
- [ ] Capability and read-only resource snapshots are deterministic；the capability snapshot covers all 44 old contracts and full agent/adapter metadata, while the resource snapshot contains only sanitized allowlisted references.
- [ ] Adapter compilation contains only 13 domain arguments；A-B implements only `bind_dry_run()`；Phase C owns `bind_create()` after action/target derivation.
- [ ] Fake is programmable and inspectable；Replay matches/consumes exact request fingerprints rather than FIFO positions；neither uses network.
- [ ] DeepSeek requests explicitly disable thinking, omit tool calling, accept only one `finish_reason=stop` JSON object, and classify empty/truncated/tool-call/error responses fail-closed.
- [ ] Foundation model catalog contains only R0/R1 and never exposes R2 intent, writer, executor, approval control or arbitrary path.
- [ ] No production integration file outside the File Map is modified；the next Phase C plan can consume the stable interfaces without renaming them.

## DeepSeek Primary References (verified 2026-08-22)

- Models/pricing and current model IDs: <https://api-docs.deepseek.com/quick_start/pricing/?article_id=article_1779470751466_8>
- OpenAI-compatible first call/base URL: <https://api-docs.deepseek.com/guides/function_calling/>
- Thinking mode control: <https://api-docs.deepseek.com/guides/thinking_mode>
- JSON output requirements: <https://api-docs.deepseek.com/guides/json_mode/>
- Chat completion response and finish reasons: <https://api-docs.deepseek.com/api/create-chat-completion>
- Model-list health endpoint: <https://api-docs.deepseek.com/api/list-models/>
