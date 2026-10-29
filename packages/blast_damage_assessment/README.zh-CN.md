# 爆炸后建筑与地面损伤评估模块

`blast-damage-assessment` 是一个与主项目解耦的 Python 模块，用于读取已有 LS-DYNA 求解结果，对爆炸后的建筑与地面进行确定性评估，并输出可追溯的损伤报告。它当前不调用 DeepSeek，也不替代工程师审查；后续智能体化应通过本模块的稳定 API、快照和证据索引获取事实。

## 当前边界

- 评估对象仅包括建筑和地面。
- 输入为已有求解结果、语义清单及其 SHA-256，不负责建模和求解。
- LS-DYNA `d3plot` 由 `lasso-python==2.0.4` 适配器读取。
- 内置规则包是研究参考规则，`formal_eligible=false`，不能给出正式工程结论。
- 数据不足时降级为 `provisional`（暂定）或 `blocked`（不可评估），不会伪造缺失量。
- 输出带来源哈希、规则快照、证据链和可复算指纹。

## 可评估性门禁

每次运行分别检查整体、建筑和地面三个门禁：

| 状态 | 含义 | 允许输出 |
| --- | --- | --- |
| `formal` | 数据与规则均满足正式判定条件 | 正式分级；当前内置规则不会进入此状态 |
| `provisional` | 可以计算，但仍有推断、缺项或待审查内容 | 暂定分级和明确限制 |
| `blocked` | 关键输入、几何或结果不可用 | 仅输出原因与补救建议，不输出伪分级 |

报告中的严重度为 `0`—`4`，只表示当前规则包下的相对分级。使用前必须同时查看门禁状态、限制项和证据，不得只读取严重度数字。

## 安装与能力检查

建议在独立虚拟环境中安装：

```powershell
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -e packages/blast_damage_assessment
& .venv/Scripts/python.exe -m blast_damage_assessment capabilities
```

`capabilities` 返回支持的请求/结果版本、适配器、字段、单位制、依赖版本和规则包哈希，主项目接入前应先检查它。

## 输入请求

请求使用 `blast_damage.assessment_request@1`。示例：

```json
{
  "schema_version": "blast_damage.assessment_request@1",
  "project_id": "demo-project",
  "case_id": "case-001",
  "result_dir": "E:/cases/case-001/solver_runs/run-001",
  "semantic_manifest": {
    "path": "E:/cases/case-001/manifest.json",
    "sha256": "将这里替换为 manifest.json 的 64 位 SHA-256"
  },
  "building_rule_pack": "building_research_reference@1",
  "ground_rule_pack": "ground_research_reference@1",
  "output_dir": "E:/cases/case-001/assessment/run-001",
  "state_chunk_size": 4
}
```

要求：

- `semantic_manifest.sha256` 必须与文件实际内容一致；运行中若来源变化，评估失败。
- 当前单位制为 `SI_m_s_kg_N_Pa`。
- 语义清单应明确建筑构件、地面 Part/表面、材料和运行目标；旧版 Phase 18 清单可兼容读取，但推断项会保留在报告中。
- `output_dir` 必须是不存在的新目录，避免覆盖既有证据。
- `state_chunk_size` 只影响读取批量，不应改变评估指纹和结论。

## CLI 调用

```powershell
& .venv/Scripts/python.exe -m blast_damage_assessment evaluate --request E:/cases/request.json
```

成功时标准输出返回结果摘要，退出码为 `0`；请求契约错误为 `2`；评估、文件或运行错误为 `3`。

## Python API

```python
import json
from blast_damage_assessment import assess, capabilities

print(capabilities())
request = json.loads(open("request.json", encoding="utf-8").read())
result = assess(request)
print(result.gate, result.severity, result.assessment_fingerprint)
```

稳定公开入口只有 `assess`、`capabilities` 和公开契约类型。主项目不要依赖模块内部类或直接解析临时对象。

## 固定输出

一次成功运行原子性发布以下八个文件：

| 文件 | 用途 |
| --- | --- |
| `assessment_request.json` | 规范化请求和已绑定来源 |
| `assessment_result.json` | 结果信封、门禁、严重度、工件哈希 |
| `assessment_snapshot.json` | 供报告、API 和后续智能体读取的确定性事实快照 |
| `evidence_index.json` | 来源—字段—指标—规则—结论证据链 |
| `rule_snapshot.json` | 本次使用的完整规则及哈希 |
| `damage_report.html` | 人可读中文损伤报告 |
| `building_components.csv` | 建筑构件明细 |
| `ground_regions.csv` | 地面区域明细 |

JSON 是机器接口，HTML/CSV 是展示接口。调用方应以 `assessment_result.json` 中记录的 SHA-256 校验其余七项，且不得将 HTML 文本反向解析为业务数据。

## 三算例独立验收

验收脚本没有机器专属默认路径，必须显式提供三个案例和全新的输出根目录：

```powershell
python packages/blast_damage_assessment/scripts/run_reference_acceptance.py `
  --commercial E:/cases/01_commercial_supermarket/solver_runs/run-id `
  --residential E:/cases/02_residential_community/solver_runs/run-id `
  --subway E:/cases/03_subway_entrance/solver_runs/run-id `
  --output-root E:/acceptance/blast-damage-assessment `
  --manifest-name manifest.json
```

脚本对每个案例执行 CLI 分块大小 `1`、CLI 分块大小 `8` 和 Python API 调用，并检查：

- 三种调用的评估 ID、指纹、快照和报告一致；
- 恰好发布八项工件，且交叉引用哈希闭合；
- 来源文件验收前后哈希不变；
- 求解终止时间、几何数量和语义清单一致；
- 每次 CLI 和 API 子进程均不超过 300 秒、进程树峰值 RSS 不超过 2 GiB；
- 研究规则只能产生 `provisional`，不能误报 `formal`；
- 十类负向输入按预期拒绝或降级。

最终汇总写入 `acceptance_summary.json`。输出根目录含所有复核证据；只有该汇总为 `passed` 后，才可进入主项目接口接入评审。

## 已知材料限制与排错

当前三个 Phase 18 案例使用兼容归一得到的旧版语义，材料参数也尚未完成面向正式毁伤判定的专业标定，因此门禁保持 `provisional`。其中 `shell_history_variables` 和 `shell_strain` 在现有结果中不可用；模块会公开列入 `missing_fields`，不会用零代替。弹性材料没有塑性损伤能力时，只报告其可支持的运动、应力或几何指标。

结果读取采用分块压缩策略：位移和速度保留时间历程以支持连续受损区域与稳定性判定；应力、应变、材料历史量在读取时压缩为逐单元峰值；删除状态只保留最终帧。三算例验收同时测量整个 CLI/API 进程树的峰值内存。超过当前算例规模的新模型在获得同等级资源验收前，不应直接宣称已满足 2 GiB 上限。

报告字段约定：

- `response_metrics` 是建筑构件的原始或归一化响应指标，不会在缺少绑定规则时自行升级损伤等级；
- `material_metrics` 是地面材料响应指标，只有规则包显式提供对应校准规则时才参与定级；JSON、CSV、HTML 均展示这些指标，机器调用仍以 JSON 快照为准。

常见问题：

| 现象 | 检查与处理 |
| --- | --- |
| 退出码 `2` | 检查请求 schema、必填字段、未知字段和 64 位 SHA-256 |
| 退出码 `3` | 检查 `d3plot` 连续文件、`d3hsp`、`run.json`、清单路径及输出父目录权限 |
| `semantic manifest hash mismatch` | 重新独立计算清单哈希；不要在请求生成后修改清单 |
| `blocked` | 按 `blockers` 中的 issue code 和 remediation 补充身份、单位、几何或求解证据 |
| `provisional` | 查看 `review_items`、`limitations`、`inferences` 和 `missing_fields`；不要擅自升级为正式结论 |
| 输出目录已存在 | 指定一个不存在的新目录；模块不会覆盖既有评估证据 |
| 地面只显示“瞬时末态” | 速度缺失或尾段尚未稳定，不能使用“残余爆坑/最终沉降”措辞 |

若能力或规则版本不同，先保存 `capabilities` 输出再复现问题；报告问题时同时提供请求、结果信封、快照和证据索引的哈希，不要只截取 HTML 页面。


## 兼容与演进规则

1. 新增字段优先采用可选字段和能力声明，禁止静默改变既有字段语义。
2. 不兼容变更必须提升 schema 主版本；调用方应先协商 `capabilities()`。
3. 规则阈值变更必须形成新规则包 ID 和新哈希，旧快照仍应可复核。
4. DeepSeek 或其他大模型未来只能分析已落盘快照和证据，不得覆盖确定性计算、门禁或来源记录。
5. 正式工程判定需要经过专业审查、规则验证、案例标定和版本批准，不能仅靠模型生成结论。

## 开发验证

```powershell
python -m unittest discover -s packages/blast_damage_assessment/tests -v
```
