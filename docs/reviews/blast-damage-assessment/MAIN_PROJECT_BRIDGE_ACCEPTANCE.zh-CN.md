# 建筑与地面损伤评估：主项目受控桥接验收

日期：2026-09-08。范围：已批准的独立评估模块接入、可信结果选择、版本化 HTTP 接口和不可覆盖产物登记。DeepSeek、前端面板改造与工程规则标定不在本轮范围内。

## 接入契约

主项目仅延迟导入 `blast_damage_assessment.api`，调用 `capabilities()` 和 `assess()`，通过公开 `to_dict()` 获取结果。LASSO、指标、门禁、规则和报告逻辑仍由独立包拥有。缺少可选依赖时能力为不可用，不阻止原有建模启动。

HTTP 接口：

- `GET /api/damage-assessment/capabilities`。
- `POST /api/refined-building-blast/projects/{project_id}/assess-latest-run`。
- `GET /api/refined-building-blast/projects/{project_id}/assessments/latest`。
- `GET /api/refined-building-blast/projects/{project_id}/assessments/{assessment_id}/artifacts/{artifact_name}`。

POST 契约为 `lsprepost_mcp.damage_assessment_request@1`，除版本字段外仅接受当前 `scenario_id`、`generated_revision`、`artifact_fingerprint`、`package_fingerprint`。服务端在项目事务锁内验证当前生成包与结果源身份，不重新编译模型、不启动求解器。浏览器不能指定文件路径、可执行程序、Python 模块、规则或阈值。

桥接能力、结果与登记表分别使用 `lsprepost_mcp.damage_assessment_capabilities@1`、`lsprepost_mcp.damage_assessment_response@1`、`lsprepost_mcp.damage_assessment_registry@1`。独立包请求/结果仍为 `blast_damage.assessment_request@1`、`blast_damage.assessment_result@1`。HTTP JSON 沿用主应用 `{ok, result}` 包装。

## 结果选择与兼容

新生成包保留 `model.k`、原始 `manifest.json` 和 `assessment_semantics.json`；不向旧封闭清单添加字段。求解结束后登记 `damage_assessment_source.json`，读取时复核服务器快照布局、run/latest 身份、终态及输入/清单/语义哈希；运行中与不可信输入不进入评估。

自动登记仅针对已验证生成包明确声明 `assessment_semantics.json` 的情况。既有其他类型的求解交接即使返回完成、失败或超时记录，也不强制要求新评估文件，原交接响应保持不变；声明了原生语义的快照若文件丢失，仍然拒绝，不按文件是否存在静默降级。此兼容边界由最终独立复核发现，并补充失败到通过的回归验证。

终态包括完成、求解失败和超时；终态只允许执行诊断，不代表数据合格。最终质量由独立包门禁判断。缺少必要证据时输出阻断原因，不推断损伤等级。

历史 `phase18.solver_blast.deck_manifest@1` 至 `@4` 可由服务器登记时显式指定 `semantic_format="legacy_deck_manifest"`；记录仅为此增加可选格式字段，未指定仍严格要求原生旁文件。原生文件丢失不会自动降级为历史格式。浏览器不能选择该模式，也没有通用任意目录导入入口。历史恢复应使用已核实的服务端快照和生成包身份。

每次调用创建项目内新的 `artifacts/damage_assessments/assessment_<唯一编号>/`。登记表只追加；同一评估 ID、指纹和源证据重复调用返回原登记记录。单纯更新源登记时间不改变源身份。登记失败返回 `completed_unregistered` 并保留文件；重试会重新计算到新目录并尝试登记，不是后台自动重试，也不会覆盖原报告。冲突指纹拒绝登记。

产物白名单为 `assessment_request.json`、`assessment_result.json`、`assessment_snapshot.json`、`evidence_index.json`、`rule_snapshot.json`、`damage_report.html`、`building_components.csv`、`ground_regions.csv`。下载前校验登记引用、路径、大小和 SHA-256，使用固定内容类型及 HTML 沙箱策略；不复用旧任意产物路由。

为避免公开文件泄露本地路径，请求快照使用 `source/result_dir`、`source/semantic_manifest_parent` 和 `output` 逻辑根。它是审计快照，不是可直接执行的原始请求。该调整不改变评估身份；`to_dict()` 同时递归规范化告警详情，确保返回值与磁盘 JSON 一致。

## 验收环境与规则冻结

- Python 3.13.5；NumPy 2.3.2；LASSO-Python 2.0.4。
- `blast-damage-assessment` 0.1.0；`lsdyna_d3plot` 适配器 1.0.0。
- 本轮安装 wheel SHA-256：`883a958ed3300b7c891aaf7e0c5b48c073209c89f2fadf1dfc7b58991e6fb8ec`（构建产物标识，不承诺跨次构建字节一致）。
- 建筑规则 `building_research_reference@1`：`9e954869105fb608f1fc8530f9b8e4081741f5858cfaeb5a3b357bbdc46d6979`。
- 地面规则 `ground_research_reference@1`：`168de503a87f9533abf4ac4c189830b663338a48eca436306c0ec59d93a3ee87`。
- 独立验收摘要 SHA-256：`2eedebfee2d2ed31c39cec189212914416dbfe113188bbf389f64364b6eb8dad`。

两套参考规则均 `formal_eligible=false`。研究等级不是建筑可使用性、安全鉴定、人员风险或爆炸优化结论；尤其等级 0 不能解释为建筑安全。

## 真实结果验收

| 算例 | 与独立验收完全相同的评估指纹 | 门禁 | 研究等级 |
| --- | --- | --- | --- |
| 商业建筑 | `ee5a4a1dfbe6cdf274300695bc8f17ac4afa85b5d44d33bba8365f9ecf4b9f74` | provisional | 0 |
| 住宅建筑 | `380ab593e0adebccd4d783d857413d05cf3de2ec395d14a1045a97d28aeeb6f5` | provisional | 0 |
| 地铁入口 | `74edc78a2590b424646c3a326c8470c6518df4e0256060f9e476383ccebe4b9b` | provisional | 3 |

三组真实求解证据先复制到隔离验收存储，再通过桥接执行；调用前后原始证据哈希不变，24 个输出文件均通过 Web 适配层读取校验。本轮单次评估分别约 12.31、14.17、13.02 秒；这不是既有完整建模工作流的耗时，也不构成性能承诺。

真实 HTTP 验收使用商业案例的隔离恢复夹具：通过项目存储登记原始生成文件、建立服务器快照和可信结果源，再启用实际 HTTP 服务器，完成能力查询、POST 评估、GET latest 及全部 8 个产物下载。未替换 HTTP 处理器或评估函数。此项验证历史恢复链路，不声称用户当前活动工作台已有可直接评估的求解记录。

复现入口（在仓库根目录；`ASSESSMENT_PYTHON` 指向已安装可选包的测试解释器；输出目录必须不存在）：

```powershell
$env:PYTHONPATH='.'
& $env:ASSESSMENT_PYTHON scripts/verify_damage_assessment_bridge.py --accepted-summary var/tmp/blast-damage-assessment-acceptance-review-fixed-v2/acceptance_summary.json --output-root var/tmp/bridge-installed-real-acceptance-20260908
```

机器可读记录保留于隔离工作区 `var/tmp/bridge-installed-real-acceptance-20260908/summary.json`；真实求解文件、验收目录、虚拟环境和包构建目录不进入分发包。验收解释器为临时环境，已在合并后复验结束后删除，不修改用户日常 Python 安装。

脱离本机求解文件仍可查阅的摘要副本见 [机器可读验收摘要](bridge_reference_acceptance_20260908.json)。其中输出路径相对于隔离验收根目录，并非活动项目路径。

## 自动化测试与审查

主项目与独立包测试分开运行；独立包使用 `--import-mode=importlib`，避免安装环境中的同名 `tests` 包干扰。pytest 能同时收集主项目的函数式测试与 unittest 测试，不能只用 unittest discover 代替本轮完整验收。

```powershell
python -m pytest tests -q --basetemp var/tmp/bridge-full-repository-20260908 --junitxml=var/tmp/bridge-full-repository-20260908.xml
$env:PYTHONPATH='.;packages/blast_damage_assessment/src'
python -m pytest packages/blast_damage_assessment/tests --import-mode=importlib -q --basetemp var/tmp/bridge-final-package-importlib-20260908
python -m compileall -q lsprepost_mcp packages/blast_damage_assessment/src scripts/verify_damage_assessment_bridge.py
git diff --check
```

- 集成专项：135 passed，16 subtests passed；涵盖语义、可信源、桥接、Web、既有 refined API/外部动作、city-impact、分发。
- 独立包：150 passed、2 skipped、59 subtests passed；1 项需 `BLAST_DAMAGE_REAL_CASE` 显式 opt-in，已由三组真实验收补充；1 项目录符号链接测试因 Windows 缺少创建权限（WinError 1314）未运行，不把该路径防护用例算作通过。
- 后续补充的门禁阻断、源重登记幂等性与构建产物排除回归：23 passed、6 subtests passed。
- 登记失败重试、接口版本和产物白名单补验：24 passed、6 subtests passed（与上述专项有重叠，不累计成独立用例总数）。
- 最终旧求解包终态兼容修复：先复现 3 个失败状态，再通过 47 项相关测试及 6 个 subtests；修复提交 `f0964e4`。完整回归早于此最终修复启动，因此采用完整回归加最终差异专项复验的证据组合，不声称完整回归进程重新加载了全部后续改动。
- 首次完整主项目回归：1792 passed、9 skipped、278609 subtests passed、5 failed，耗时 11914.75 秒。5 个失败记录包含 3 个示例子测试及 2 个启动测试，原因和消除证据见下节；不将首次运行记为全绿。
- 冻结源码并补齐既有测试夹具后：60 passed、9 subtests passed，覆盖全部失败用例及最终桥接/旧交接兼容改动。
- 其余最终冻结专项：93 passed、10 subtests passed，覆盖语义导出、分发、既有 refined API 与 city-impact；与上述 60 项使用不同测试文件。
- 编译检查及 `git diff --check`：通过。

人工复核重点：主项目不导入评估内部算法；无可选包时正常建模；当前身份与可信源双重检查；目录和产物白名单；登记幂等与异常保留；旧 city-impact 接口、schema、报告文件名及 risk.level 不变。测试覆盖缺依赖、过期身份、源记录/清单篡改、非终态、畸形结果、产物篡改、包异常、登记失败和 blocked 无等级返回。

最终增加一次独立只读代码审查：发现 1 项旧包终态交接兼容问题，已修复并由同一审查者复核；没有其他阻断项。未增加开发子智能体。主项目既有优化的合并前基线为 98 passed、4 subtests passed；pytest 默认缓存目录写入权限警告不影响测试结果，合并后复验使用独立缓存目录。

## 完整回归异常与复验

1. 三个 `CompleteSolverExampleTests` 子测试：隔离工作树未包含被 Git 忽略的 `examples/complete_solver_cases/*/` 生成示例。主项目同组测试通过。仅向隔离工作树的三个不存在目录复制既有示例，每个 9 个文件，逐文件比较 SHA-256；未修改或重新生成主项目示例，未放宽断言。
2. 两个 `WebStartupTests`：`tool_server.py` 在导入时冻结源码指纹。长回归期间完成最终兼容修复，测试进程持有旧指纹，而启动脚本的新进程读取当前源码指纹，按设计拒绝停止非 Web 主进程。源码冻结后的独立重跑立即通过；未改动启动脚本、缓存机制或进程保护。

复验命令：

```powershell
python -m pytest tests/test_web_startup.py tests/test_complete_solver_examples.py tests/test_phase18f_external_actions.py tests/test_damage_assessment_web_api.py tests/test_assessment_result_source.py tests/test_damage_assessment_bridge.py -q -o cache_dir=var/tmp/bridge-frozen-recheck-cache --basetemp var/tmp/bridge-frozen-recheck-20260908 --junitxml=var/tmp/bridge-frozen-recheck-20260908.xml
```

上述复验为 60 passed、9 subtests passed。相同启动/示例测试在未合并主项目为 13 passed、3 subtests passed。验收采用“完整运行 + 已定位失败和最终差异的冻结复验”组合，不将其描述为一次无失败的完整运行。

完整运行的三项重型建模测试均通过：商业 362.262 秒、地铁入口 7969.273 秒、住宅 177.013 秒。9 项跳过为 6 项 LS-PrePost GUI 显式 opt-in、1 项 LS-PrePost/LS-DYNA 联合显式 opt-in、2 项 Windows 无符号链接权限；这些用例未计入通过数。

隔离工作树证据：

- `var/tmp/bridge-full-repository-20260908.xml`：SHA-256 `d75cb2d889ab4765a5cdf3d35d776231e52f6e43000e69b70c188857bb73d083`。
- `var/tmp/bridge-frozen-recheck-20260908.xml`：SHA-256 `595d3e10e3376779f22f8385c80cc279a4f17606c09d8dba9708a40d9a4bb687`。

后续长回归应先补齐约定的本地示例，并在源码冻结后启动，避免验证期间修改参与服务指纹的文件。

## 合并状态

已在主项目当前分支 `codex/phase15-conforming-air-gap` 完成本地快进合并：`f8ac11a21a128cbe1aac152b064c159182a39973` → `62371cd4262df1eac8947945ea15b8378a71508c`。未推送远端。本文件的合并后记录另作独立文档提交。

合并后在主项目目录、最终源码和原有用户优化同时存在的状态下验证：

- 主项目专项：251 passed、23 subtests passed，耗时 185.29 秒，覆盖桥接、语义、可信源、Web、旧外部交接、refined API、city-impact、分发、工具、生成来源、quarter-two 优化、启动和既有完整示例。
- 独立评估包：150 passed、2 skipped、59 subtests passed，耗时 2.50 秒；跳过原因与前述独立包验证相同。
- `compileall` 与 `git diff --check`：通过。
- 逐项比较合并前后 `project_store.py`、`provenance.py`、`tools.py`、原智能体化设计文档、`quarter_two_tnt.py` 及其测试的 SHA-256，全部不变；原设计文档的暂存对象记录也不变。未暂存或提交这些用户改动。

主项目验证命令（测试解释器与前述临时验收环境相同；以下用变量代替机器路径）：

```powershell
$env:PYTHONPATH='.;packages/blast_damage_assessment/src'
& $env:ASSESSMENT_PYTHON -m pytest tests/test_damage_assessment_semantics.py tests/test_assessment_result_source.py tests/test_damage_assessment_bridge.py tests/test_damage_assessment_web_api.py tests/test_phase18f_external_actions.py tests/test_phase18f_api.py tests/test_city_impact.py tests/test_packaging_and_integration_boundaries.py tests/test_tools.py tests/test_generated_keyword_provenance.py tests/test_quarter_two_tnt.py tests/test_web_startup.py tests/test_complete_solver_examples.py -q -o cache_dir=var/tmp/bridge-postmerge-cache --basetemp var/tmp/bridge-postmerge-main-20260908 --junitxml=var/tmp/bridge-postmerge-main-20260908.xml
& $env:ASSESSMENT_PYTHON -m pytest packages/blast_damage_assessment/tests --import-mode=importlib -q -rs -o cache_dir=var/tmp/bridge-postmerge-package-cache --basetemp var/tmp/bridge-postmerge-package-20260908 --junitxml=var/tmp/bridge-postmerge-package-20260908.xml
```

主项目证据：

- `var/tmp/bridge-postmerge-main-20260908.xml`：SHA-256 `dad21203fba903730703d3bdbbb1f5f70d0d7d9eef8267d4d4fa988de08642b6`。
- `var/tmp/bridge-postmerge-package-20260908.xml`：SHA-256 `5dea9a8f3c8453694ba62902a78ed055317e2f797482308a96ade7732e47ffc8`。

## 清理与启用

已精确删除隔离工作树内本次创建的 `var/tmp/bridge-integration-env`（35022 个生成文件）和 `packages/blast_damage_assessment/build`（36 个生成文件），删除前确认无活动测试解释器和重解析点。这些是可重新安装/构建的临时内容，不是用户求解结果。

原始求解文件、全部验收输出与测试证据均保留。由于隔离工作树包含仅在本机保存的审计证据，保留该工作树及其分支，不执行整体删除。

合并源码不等于在日常解释器中启用可选依赖。使用时按 README 运行 `scripts/setup_damage_assessment.ps1`，重启主项目服务后查询能力接口。未安装依赖仍可使用原建模功能；本轮没有新增前端评估面板，也没有连接 DeepSeek。当前报告仍仅为研究参考，不能替代专业安全鉴定。
