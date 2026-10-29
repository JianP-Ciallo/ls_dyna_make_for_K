# 项目结构与文件归属

本文档说明仓库中各顶层目录的职责。整理工作的原则是：源码与长期资产进入版本管理，运行产物留在固定的生成目录；不因文件体积大就判断其可以删除。

## 顶层目录

| 路径 | 类型 | 职责 | 版本管理 |
| --- | --- | --- | --- |
| `lsprepost_mcp/` | 核心源码 | MCP 服务、受控建模、校验、LS-PrePost 与 LS-DYNA 交接逻辑 | 应纳管 |
| `packages/blast_damage_assessment/` | 独立评估模块 | 读取既有 LS-DYNA 结果，执行建筑与地面损伤评估，并提供稳定 API/CLI、规则和验收脚本 | 独立审核后纳管；不直接依赖主项目内部实现 |
| `web/` | 前端源码 | 前端开发配置、构建脚本与验收；完整界面源码统一位于 `lsprepost_mcp/web/static/` | 应纳管源码，忽略依赖和构建输出 |
| `tests/` | 测试 | 单元、集成、快照、Web 和分发边界测试 | 应纳管 |
| `resources/materials/` | 受控资产 | 材料定义及其单位、参数来源 | 应纳管 |
| `resources/templates/` | 受控资产 | LS-PrePost cfile 等可复用模板 | 应纳管 |
| `examples/` | 示例 | 可复现的 MCP 请求与受控输入；生成后的完整模型案例留在本地 | 审核后纳管 |
| `scripts/` | 运维脚本 | 安装、诊断、启动、测试、打包和验证入口 | 应纳管 |
| `docs/` | 正式文档 | 用户说明、路线图、验收说明、设计与实施记录 | 审核后纳管 |
| `docs/internal/` | 内部资料 | 团队内部说明、专利草稿和渲染检查，不进入分发包 | 本地保留 |
| `docs/reviews/` | 评审资料 | 场景评审、验收说明与必要评审资产 | 审核后纳管 |
| `extras/special_pages_rod_impact/` | 独立附属页面 | 钢筋/杆件冲击专题页面和验证脚本 | 作为独立附属模块审核 |
| `workspace/` | 运行数据 | 活动项目、实验、归档、锁、日志及求解结果 | 不纳管、不自动删除 |
| `var/generated_configs/` | 本机配置 | 由脚本生成的本地 MCP/Web 配置 | 不纳管 |
| `dist/` | 发布产物 | 历史和当前 zip 分发包、打包暂存目录 | 不纳管 |
| `var/tmp/` | 临时资料 | 临时 PDF、截图、诊断和求解分析产物 | 不纳管 |

## 根目录允许保留的文件

根目录只保留新用户需要立即看到或直接运行的入口：

- `README.md`
- `README.zh-CN.md`
- `AI_IDE_START_HERE.zh-CN.md`
- `start_web_app.cmd`
- `.gitignore`

`qrun.inf` 属于本地运行产物，已加入忽略规则。新增的说明、评审和阶段资料应进入 `docs/`，不再放到根目录。

## 文件放置规则

1. 主项目 Python 业务代码放在 `lsprepost_mcp/`，对应测试放在 `tests/`；可独立安装且具有稳定契约的模块放在 `packages/<模块名>/`，其测试、规则和说明随包放置。
2. 可复用材料和模板分别放在 `resources/materials/` 与 `resources/templates/`，不要复制到示例目录。
3. 示例必须能够说明用途并可复现；一次性调试输入应放入 `var/tmp/`。
4. 正式说明放在 `docs/`；评审资料放在 `docs/reviews/`；内部总结、专利草稿和未确认资料放在 `docs/internal/`。
5. 任何模型运行、求解结果和预览产物都应写入 `workspace/`。
6. 本机路径、生成配置、依赖目录和发布压缩包不得进入版本管理。
7. 清理 `workspace/` 前必须先确认项目用途；本轮结构整理不删除其中任何数据。

`docs/internal/` 中的文档渲染检查、专利图稿和修改前备份属于本地留档内容，已从版本管理和分发包中排除。`examples/phase*/`、完整案例内的生成项目以及 `extras/` 专题页面的下载压缩包同样不进入版本管理。

## 当前整理边界

爆炸损伤评估已完成独立验收，并增加主项目受控调用桥接；不改造旧 city-impact 页面，不连接 DeepSeek，不迁移或删除既有活动项目和历史求解结果。

职责划分：

- `packages/blast_damage_assessment/`：LASSO 解析适配、可评估性门禁、建筑和地面指标、规则、证据链及报告；主项目不复制这些算法。
- `lsprepost_mcp/damage_assessment_semantics.py`：从当前生成包导出独立语义旁文件，保留既有封闭清单格式。
- `lsprepost_mcp/assessment_result_source.py`：服务器登记并验证已结束的求解快照、输入哈希和生成包身份。
- `lsprepost_mcp/damage_assessment_bridge.py`：延迟调用独立包公开 API、验证返回产物、原子追加登记表。
- `lsprepost_mcp/web/damage_assessment_api.py`：受控 HTTP 参数和产物下载；当前项目身份及锁仍由现有项目存储层管理。
- `scripts/verify_damage_assessment_bridge.py`：使用既有验收摘要，在新的隔离目录复制证据并验证三组指纹和真实 HTTP 链路，不启动求解器。

桥接验收详情见 `docs/reviews/blast-damage-assessment/MAIN_PROJECT_BRIDGE_ACCEPTANCE.zh-CN.md`。验收运行产物留在 `var/tmp/`，不进入源码和分发包。

## 可维护性边界（2026-09-09）

- `lsprepost_mcp/refined_blast/project_repository.py` 管理创建事务、恢复和元数据身份；不依赖 HTTP、不编译模型。
- `project_metadata.py` 管理版本化元数据契约和创建证据；`generated_records.py` 管理生成索引与产物完整性校验。
- HTTP 适配器通过仓储对象和存储公开接口工作；`tests/test_maintainability_boundaries.py` 防止存储私有访问和反向依赖重新出现。
- 前端的 `refined_blast_persistence.js` 管理浏览器存储，`refined_blast_autosave.js` 管理保存请求与超时取消，`refined_blast_http.js` 统一 JSON 请求解析。页面渲染和交互协调留在工作台。
- 正式服务固定使用内置界面；`web/dist` 是显式构建的副本，不再因文件存在而覆盖正式页面。开发和构建说明见 `web/README.md`。

文档和截图生成脚本通过 `tools/work_paths.py` / `tools/work-paths.mjs` 计算输出路径，不依赖启动时的工作目录：

| 产物 | 新默认位置 |
| --- | --- |
| 软著文档、截图与清单 | `var/tmp/soft_copyright_work/` |
| 技术交底图稿 | `var/tmp/technical_disclosure_work/figures/` |
| 文档章节插图 | `var/tmp/generated_softdoc_figures/` |
| 本轮专项测试证据 | `var/tmp/maintainability-tests/` |

脚本显式传入的输出路径仍然有效。输入读取优先使用新目录；未生成相应输入时可读取旧的本地工作目录。历史文件不自动移动或删除，旧输出目录纳入忽略规则。带有个人桌面输入或本机浏览器配置的一次性脚本仍需按实际环境传参或调整本地配置。
