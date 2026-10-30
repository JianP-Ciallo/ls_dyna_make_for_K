# lsprepost-mcp

项目目录职责、源码与运行产物边界见 [项目结构与文件归属](docs/PROJECT_STRUCTURE.zh-CN.md)。

从 GitHub 克隆后首次运行，请先阅读 [源码安装与启动指南](docs/QUICKSTART.zh-CN.md)。
其他使用、开发和验收资料集中在 [文档导航](docs/README.zh-CN.md)。

`lsprepost-mcp` 提供本地 Web 工作台与 stdio MCP 工具服务，用于受控生成 LS-DYNA keyword 模型、管理项目、复核模型及衔接本机 LS-PrePost/求解工具。AI 客户端通过已注册的 MCP 工具使用这些能力，普通用户也可单独使用网页。

## MCP 与 Web 工作台的区别

本项目包含本地 stdio MCP 工具服务和独立的本地 Web 工作台。MCP 中的 Server 指提供工具的程序，可以由 AI 客户端作为子进程运行在本机，无需购买云服务器或部署到公网。当前 MCP 入口为 `lsprepost_mcp/server.py`，通过标准输入/输出传递 JSON-RPC 消息，提供 `initialize`、`tools/list`、`tools/call` 等方法。

Web 入口为 `python -m lsprepost_mcp.web.app`，地址默认为 `http://127.0.0.1:8765/`。这个地址提供网页和普通业务 API，不是 MCP HTTP 端点。使用网页不要求连接 AI 客户端，连接 stdio MCP 也不要求先启动网页；Web 专属功能不会自动成为 MCP 工具。

MCP 协议也支持 HTTP 传输，但本项目当前没有实现远程 MCP HTTP 端点。远程共享需另外设计传输、认证、项目隔离和求解环境。协议依据见 [MCP 官方传输说明](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)。本项目的客户端连接示例见下文“MCP 配置示例”；使用源码虚拟环境时，也可采用 [首页的显式 Python 配置](README.md#ai-ide--mcp)。

## MCP 建模流程

典型流程是：

```text
用户在 AI IDE 中描述工况
  -> AI IDE 调用 lsprepost MCP 工具
  -> MCP Server 校验受控输入
  -> 生成 model.json / model.k / checks.json
  -> LS-PrePost 打开、校验并导出预览
```

项目定位为受控建模与仿真研究工具，已超出早期仅演示桥接的范围；功能实现、软件验收与工程精度仍分别判定。它不开放任意 LS-PrePost 命令，也不让 AI 直接拼接任意 LS-DYNA keyword，MCP 只执行白名单工具和受控模板。

## 阶段状态与页面入口

阶段状态于 2026-10-30 对照当前源码及已有验收报告核对，详见[阶段与功能核对记录](docs/reviews/README_STATUS_AUDIT_20261030.zh-CN.md)和[首页阶段摘要](README.md#阶段状态摘要)。下表描述当前路由，不把历史预览服务的端口当作默认端口。

| 路径 | 当前用途 |
| --- | --- |
| `/` | 原受控建模工作台、组件和场景入口。 |
| `/refined-building-blast` | Phase 18 精细建筑爆炸工作台、项目验证/生成及损伤评估入口。 |
| `/fixed-building-pressure` | 固定建筑三维预览。 |
| `/structural-pressure` | 默认进入室外 TNT 工况与 K 包工作流。 |
| `/structural-pressure?legacy=1` | 保留的用户给定压力工况与结构 K 包页面。 |
| `/cpu-blast` | 五类简化场景的浏览器 Worker 演示、回放与独立缓存。 |
| `/cpu-blast?legacy=1` | 保留的原生候选场景、历史结果与诊断入口，不代表整栋已验收。 |
| `/fixed-building-pressure/response` | 可选 OpenSeesPy 单柱/单板弹性参考试算，以及可用历史整栋首试报告/静态图表的只读查看与下载。 |
| `/damage_assessment_demo.html` | 交互式合成损伤评估演示，不是真实求解结果。 |

## 适用场景

适合用它做：

- 在 AI IDE 中用自然语言生成简单 LS-DYNA keyword 模型。
- 让几何、材料、载荷、约束、接触和预览导出走受控工具。
- 从 AI IDE 中打开 LS-PrePost 查看生成模型。
- 导出 LS-PrePost PNG 预览图或多视图 GIF。
- 打包发给其他 Windows 机器使用，并保留旧 zip 版本用于回退。

## 环境要求

**另行制作的 Windows 便携包**可内含独立 Python、NumPy、Pillow 及损伤评估依赖。在 Windows 10/11 64 位电脑上完整解压到可写目录，按包内说明启动；`runtime/` 必须与启动文件一同保留，文件夹可整体移动。GitHub 源码 ZIP 不包含这一运行时。LS-PrePost、LS-Run、LS-DYNA 和求解许可证由用户自行准备，并在页面中配置本机路径。

启动脚本优先使用 `runtime/python/python.exe`，不修改系统 Python 或系统 PATH。内置运行时损坏时会提示重新解压。日常使用保留启动窗口，关闭窗口即结束服务。便携包不带历史工况和求解结果；请使用本机浏览器访问。

下面的 Python 安装要求仅适用于**源码包**；开发测试仍需要独立的开发环境与 pytest/Node.js。便携包内的嵌入式 Python 不提供 pip 或开发工具。

- Windows
- Python 3.10 或更高版本
- 使用外部导入/预览时准备本机 LS-PrePost；单纯打开网页和进行部分静态操作不要求先安装它。
- 使用 MCP 时准备支持 stdio 的客户端；单独使用 Web 不要求 AI 客户端。
- NumPy 用于固定建筑模板等能力，Pillow 用于 GIF 导出；独立损伤评估与原生 CPU 试算另装各自依赖。基础生成/校验与这些可选能力的依赖范围不同。

### 固定建筑预览与压力工况

固定建筑采用独立入口：`/fixed-building-pressure` 用于预览，`/structural-pressure` 默认提供室外 TNT 工况与 K 包工作流，旧给定压力工况保留在 `/structural-pressure?legacy=1`。源码包需在启动 Web 应用的同一个 Python 环境中安装：

```powershell
python -m pip install "numpy>=1.26,<3"
```

安装后双击 `start_web_app.cmd`，或运行 `python -m lsprepost_mcp.web.app`，打开 `/fixed-building-pressure`。固定结构模板与 Three.js 已随包提供。没有安装 NumPy 时，新压力 API 返回模板不可用提示，原主工作台仍可启动。分发包不包含本机虚拟环境、已保存工况、历史求解结果或 LS-DYNA 可执行文件。

当前 TNT 页面支持室外爆源位置/尺寸或质量编辑、三维拖动、初始门窗状态、监测与输出配置。轻量保存/预览不等于生成有限元网格；确认后才执行受控 K 包生成，页面不提供原生求解器启动端点。读取压力曲线时，由本机目录选择器选择既有结果，核对输入身份后读取并可导出 CSV。旧室内工况只保留读取/备份，不能覆盖、预览或导出为新的室内任务。详见 [TNT 接入记录](docs/reviews/2026-10-23-fixed-building-tnt-integration.md)，其中历史预览端口不替代本项目默认端口。

读取既有 `binout` 压力曲线还需在启动 Web 服务的同一个 Python 环境中安装 `lasso-python`；可复用下文“可选的爆炸损伤评估能力”的安装步骤，该步骤固定安装 `lasso-python==2.0.4`。仅安装 NumPy/Pillow 不包含这项读取依赖，保存工况和轻量预览不要求先安装它。

开发者运行 `tests/browser/fixed_building_workspace.cjs` 前，在 `web` 目录执行 `npm install` 和 `npx playwright install chromium`。脚本默认读取该目录的 Playwright；可通过 `PLAYWRIGHT_MODULE` 指定模块，通过 `CHROME_PATH` 指定已有的浏览器可执行文件。

### 可选的爆炸损伤评估能力

建筑与地面损伤评估在便携包中已安装。源码包需要评估功能时，在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_damage_assessment.ps1 -PythonExe python
```

安装脚本会安装隔离在 `packages/blast_damage_assessment` 下的评估包，并验证固定的 `lasso-python 2.0.4`、请求/结果契约和内置研究参考规则包。运行 `scripts\doctor.ps1` 时，`damage_assessment_optional` 为 `ok` 表示能力可用；为 `warning` 仅表示未安装或版本不满足，主项目仍可正常建模。

当前建筑和地面规则是用于工程研究与流程验证的临时参考规则，输出不能替代专业结构安全鉴定。

评估模块现通过受控桥接接入主项目，算法仍在独立包内。新接口只接受当前生成包的身份信息；求解目录由服务器选择，不接受浏览器提交路径、阈值或任意规则。调用评估不会重新建模或重新启动求解器。

| 方法 | 接口（项目接口前缀为 `/api/refined-building-blast/projects/{project_id}`） |
| --- | --- |
| GET | `/api/damage-assessment/capabilities`：查询可选能力 |
| POST | `{前缀}/assess-latest-run`：诊断当前生成包对应的已登记终态结果 |
| GET | `{前缀}/assessments/latest`：读取最新已登记评估 |
| GET | `{前缀}/assessments/{assessment_id}/artifacts/{artifact_name}`：校验哈希后下载产物 |

POST 使用 `lsprepost_mcp.damage_assessment_request@1`，仅包含 `schema_version`、`scenario_id`、`generated_revision`、`artifact_fingerprint` 和 `package_fingerprint`；身份值取自当前项目生成响应，不应手填或沿用旧版本。未安装依赖、无可信结果或身份过期时明确拒绝，不影响建模。评估成功与工程可评估性分开表示：`blocked` 不输出损伤等级，`provisional` 仅为研究参考。

每次调用在项目 `artifacts/damage_assessments/assessment_<唯一编号>/` 下保存独立产物，登记失败时保留文件并返回 `completed_unregistered`，重试不会覆盖旧报告。旧 city-impact 接口和页面保持不变，不接入 DeepSeek。接口、历史结果恢复与验收证据见 [主项目桥接验收说明](docs/reviews/blast-damage-assessment/MAIN_PROJECT_BRIDGE_ACCEPTANCE.zh-CN.md)。

#### 页面入口与交互式合成演示

进入“精细化建筑爆炸”页面，点击底部“损伤评估”，打开右侧评估面板。

- **先看演示**：点击面板顶部“查看演示”，进入三层建筑及地面的独立合成场景。可编辑 1–5 个演示爆源的位置、高度和当量字段，点击“开始评估”后调用评估模块处理合成时序；修改参数立即撤销旧结论。
- **查看报告与局部显示**：可查看构件依据、整体等级、固定标尺的局部合成影响云图，下载带合成标记的报告和证据。该动态演示需要可选评估依赖；不启动求解、不登记真实求解完成，也不更改真实项目。局部显示值不是材料损伤变量或真实爆炸响应。
- **真实项目评估**：面板沿用受控 API。开始评估需要模块可用、当前草稿已保存且页面取得对应生成包身份；服务器再次核对终态求解结果和版本。打开面板或刷新不会自动执行评估。模块未安装时仍可查看已登记报告；最新报告不一定属于当前版本。

原住宅只读网格与已保存报告保留为历史资料，不再作为默认演示。当前合成映射没有当量物理换算或真实冲击波叠加；界面的输入范围只是资源/交互边界，不是实际爆源设计范围。演示通过不构成真实 d3plot 解析、规则工程标定或安全鉴定通过。

演示资源生成与验收方式见 [演示说明](docs/reviews/blast-damage-assessment/FRONTEND_DEMO.zh-CN.md)。

每台机器都要使用自己的 LS-PrePost 路径，例如：

```text
<LS_PREPOST_INSTALL_DIR>\lsprepost4.12.exe
```

不要复制开发机器上的绝对路径。不同机器必须设置自己的 `LSPP_EXE`。

## AI IDE 快速接入

最推荐的方式是：把整个项目文件夹交给 AI IDE，然后让 AI IDE 先读取根目录的：

```text
AI_IDE_START_HERE.zh-CN.md
```

这个文件已经写明：

- AI IDE 不得修改项目源代码。
- AI IDE 不得修改 `scripts\`、`resources\`、`tests\`。
- AI IDE 不得直接创建、编辑或覆盖 `.k` / `.key` / `.dyn` 文件。
- AI IDE 只允许运行诊断、生成 `var\generated_configs\`，以及在用户确认后写入 AI IDE 配置。
- 命令可以使用绝对路径运行，不要求用户手动进入项目目录。

你可以直接把下面这句话发给 AI IDE：

```text
请先阅读本项目根目录的 AI_IDE_START_HERE.zh-CN.md。严格按里面的只读使用流程操作：不要修改项目源代码，不要修改 scripts/resources/tests；不得直接创建、编辑或覆盖任何 .k/.key/.dyn 文件；所有 keyword 文件都必须通过本项目生成流程产生。只允许运行诊断、生成配置、生成模型、校验模型和打开 LS-PrePost。我的 LS-PrePost 路径是：<LS_PREPOST_EXE>。
```

如果你希望手动运行，也可以使用下面的命令。

在项目根目录运行诊断：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\doctor.ps1 -LsppExe "<LS_PREPOST_INSTALL_DIR>\lsprepost4.12.exe" -RequireLsPrePost
```

生成 AI IDE 配置：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -LsppExe "<LS_PREPOST_INSTALL_DIR>\lsprepost4.12.exe"
```

生成结果位于：

```text
var\generated_configs\
```

常见输出文件：

- `codex.mcp.json`
- `cursor.mcp.json`
- `claude_desktop_config.fragment.json`
- `windsurf.mcp.json`
- `vscode.mcp.json`
- `visualstudio.mcp.json`

把对应配置复制到 AI IDE 中，然后重启或刷新 AI IDE 的 MCP 工具列表。

Windows 下推荐让 AI IDE 启动这个入口：

```text
cmd /c <PROJECT_DIR>\scripts\start_mcp_server.cmd
```

这个脚本会定位项目根目录并启动：

```text
lsprepost_mcp\server.py
```

## 本地 Web App 入口

第 11 阶段开始，本项目提供本地 Web App 入口。它默认只监听 `127.0.0.1`，用于普通用户选择受控场景、填写参数、生成模型、查看校验和预览。

分发包解压后，Windows 用户可直接双击：

```text
start_web_app.cmd
```

启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web_app.ps1 -LsppExe $env:LSPP_EXE -OpenBrowser
```

正式 Web 界面统一位于 `lsprepost_mcp/web/static/`，服务始终读取该目录，不会因 `web/dist` 存在而切换页面。Node.js 用于前端开发、静态副本构建和浏览器专项；原 React 文件是历史原型，不是当前正式界面的构建输入。普通启动不需要 Node.js，详见 [前端说明](web/README.md)。

Web App 右侧提供 LS-Run 交接入口。点击“导入 LS-Run”选择本机 `lsrun.exe`，点击“导入 LS-DYNA 求解器”选择本机求解器可执行文件，然后可以对当前项目执行“送入 LS-Run”。当前实现负责校验路径、保存本机配置并打开 LS-Run；它不自动填入全部任务字段，不自动提交求解，不自动监控任务，也不自动解释结果。

## MCP 配置示例

以下为采用 `mcpServers` JSON 结构的客户端示例，具体顶层结构按客户端要求填写；源码虚拟环境也可直接使用[首页的绝对 Python 路径配置](README.md#ai-ide--mcp)：

```json
{
  "mcpServers": {
    "lsprepost": {
      "command": "cmd",
      "args": [
        "/c",
        "<PROJECT_DIR>\\scripts\\start_mcp_server.cmd"
      ],
      "env": {
        "LSPP_EXE": "<LS_PREPOST_INSTALL_DIR>\\lsprepost4.12.exe"
      }
    }
  }
}
```

VS Code、Visual Studio 常见格式：

```json
{
  "servers": {
    "lsprepost": {
      "type": "stdio",
      "command": "cmd",
      "args": [
        "/c",
        "<PROJECT_DIR>\\scripts\\start_mcp_server.cmd"
      ],
      "env": {
        "LSPP_EXE": "<LS_PREPOST_INSTALL_DIR>\\lsprepost4.12.exe"
      }
    }
  }
}
```

更多说明见：

```text
docs\AI_IDE_COMPAT.zh-CN.md
docs\DISTRIBUTION.zh-CN.md
docs\PROMPTS.zh-CN.md
```

## 在 AI IDE 中怎么提需求

建议把需求说清楚：几何、尺寸、材料、单位、约束、载荷、接触、是否需要 LS-PrePost 校验和预览。

## 统一初始启动词

别人拿到 zip 并用 AI IDE 打开项目文件夹后，建议统一使用下面这段话启动项目：

```text
请把当前文件夹当作一个现成的 LS-PrePost/LS-DYNA keyword 生成工具项目使用。先阅读 AI_IDE_START_HERE.zh-CN.md 和 README.zh-CN.md。不要修改项目源代码，不要修改 scripts/resources/tests，不得直接创建、编辑或覆盖任何 .k/.key/.dyn 文件；所有 keyword 文件必须通过本项目生成流程产生。请先检查 Python 和 LS-PrePost 路径，然后告诉我当前环境是否可用。环境可用后，请先列出当前项目支持的可控场景建模选项，只给出模糊场景和需要我补充的数据项，不要直接编造参数。我的 LS-PrePost 路径是：<LS_PREPOST_EXE>。如果 LS-PrePost 因版本差异无法自动导出 PNG/GIF 预览，请明确告诉我需要自行打开 LS-PrePost 验证，不要把导图失败判断为模型生成失败。
```

如果用户还不知道 LS-PrePost 路径，可以把最后一句改成：

```text
我暂时不知道 LS-PrePost 路径，请先告诉我需要找到哪个 lsprepost*.exe 文件。
```

AI IDE 完成环境检查后，应先给出类似下面的选项：

```text
当前项目支持这些可控场景：

1. 钢筋以给定初速度冲击头盔
   可填写：钢筋长度/直径、初始间距、冲击速度、头盔尺寸/厚度、材料、是否导出预览。

2. 圆柱杆冲击钢板
   可填写：杆长度/直径、冲击速度、钢板长宽厚、材料、是否导出预览。

3. 立方体顶面四角受压
   可填写：立方体尺寸、四角向下载荷大小、材料、网格尺寸。

4. 壳板受均布压力
   可填写：板长宽厚、压力大小、固定边界、材料、网格尺寸。

请选择一个场景，并补充你已经确定的数据；不确定的数据可以先留空，我会继续追问。
```

示例 1：生成并打开简单钢板

```text
使用 lsprepost MCP 创建一个 0.12 x 0.06 x 0.0015 m 的低碳钢壳单元板。
单位使用 SI_m_s_kg_N_Pa，网格尺寸 0.01 m，固定 x_min 边界。
生成后校验模型，并在 LS-PrePost 中打开。
```

AI IDE 应调用的工具通常是：

```text
generate_model
validate_model
model_summary
open_in_lsprepost
```

示例 2：自然语言受控场景

```text
使用 lsprepost MCP 生成一个钢筋以给定初速度冲击头盔的场景：
一根 1 m 长的竖直钢筋位于固定椭球头盔壳上方 0.5 m，向下初速度为 10 m/s。
使用受控面面接触和 d3plot 输出。
完成 LS-PrePost 导入校验，并导出三视图 GIF 预览。
```

AI IDE 应调用的工具通常是：

```text
generate_scene_from_prompt
validate_lsprepost_import
export_preview_gif
read_project
```

示例 3：只导出预览

```text
对 rebar_drop_on_helmet_demo 项目导出 iso/top/front 三个视图，
并合成为一个 GIF 预览。
```

AI IDE 应调用的工具通常是：

```text
export_preview_images
export_preview_gif
```

## 主要 MCP 工具

- `server_info`：返回 Server 路径、项目目录、LS-PrePost 路径和运行信息。
- `generate_scene_from_prompt`：把受支持的自然语言工况解析为受控模型 spec，并可选执行校验和预览。
- `generate_model`：根据结构化 `spec` 生成 `model.json`、`model.k`、`open_model.cfile` 和 `checks.json`。
- `create_plate_demo`：早期兼容 demo，生成简单壳板模型。
- `validate_model`：重新校验项目并更新 `checks.json`。
- `model_summary`：返回模型摘要，方便 AI IDE 向用户解释模型。
- `read_project`：读取项目文件、路径和校验结果。
- `list_projects`：列出活动、旧版和归档项目。
- `archive_project`：通过精确项目名确认后归档项目。
- `import_keyword`：把已有 LS-DYNA keyword 文件导入为 workspace 项目。
- `list_materials` / `get_material`：查询内置 SI 材料库。
- `open_in_lsprepost`：通过 readiness 检查后在 LS-PrePost 中打开 `model.k`。
- `validate_lsprepost_import`：打开 `model.k`、保存 keyword reader 信息、导出 PNG 并检查导入状态。
- `export_preview_image`：导出单张受控 LS-PrePost PNG 预览。
- `export_preview_images`：导出多个受控视图。
- `export_preview_gif`：导出多视图并合成为 GIF 预览。
- `run_cfile`：只运行 manifest/hash 校验通过的服务端生成 cfile。
- `generate_ale_blast_demo`：生成或 dry-run 校验受控 MM-ALE 空气/炸药/钢板参考模型；该工具不会启动 LS-DYNA。

## 当前建模能力

下面分别列出自然语言场景、通用结构化模型与专用生成入口；它们不是同一份能力清单。AI IDE 不应承诺开放式任意建模。

当前自然语言场景只支持：

- `rebar_drop_on_helmet`：钢筋以给定初速度冲击固定椭球头盔壳。
- `rod_impact_plate`：实体圆柱杆以初速度冲击固定钢板。
- `cube_top_corner_load`：立方体底面固定，顶面四角向下集中载荷。
- `plate_pressure`：壳板固定边界，板面均布压力。

通用 `generate_model` 的基础结构化生成类型包括：

- `shell_plate`
- `solid_block`
- `shell_box`
- `cylinder_shell`
- `cylinder_solid`
- `beam_bar`
- `single_solid_element_test`
- `assembly_scene`
- `ale_blast_scene`

`imported_keyword` 是导入工作流管理的模型类型，不表示可随意提交该类型生成任意模型。其他专用入口包括 Phase 15、城市街道/地面、Phase 18 精细建筑与分层爆炸、固定建筑 TNT，以及来源固定的 [GRAN_R5](docs/GRAN_R5_REBUILD.zh-CN.md)、[5-1788-2](docs/IMPACT_1788_REBUILD.zh-CN.md)、[B120 SPG/S-ALE](docs/B120_SPG_SALE_REBUILD.zh-CN.md) 重建。源卡复用不等于已补齐缺失的用户材料实现或完成工程验证。

其他当前受控能力包括：

- 单位制：`SI_m_s_kg_N_Pa`
- 基础 SI 材料预设：`mild_steel`、`aluminum_6061_t6`、`rubber_generic`；专用材料/结构资源通过独立资源库和受控编译器管理，不限于这三个基础预设。
- 弹性材料：`*MAT_ELASTIC`
- 受控高级材料/用户自定义材料卡：用于明确确认的测试场景
- 载荷和约束：固定边界、规定运动、节点力、重力、压力、初速度
- 接触：受控面面接触和节点到面接触模板
- LS-PrePost 预览：PNG 和多视图 GIF
- 静态 keyword 检查和 readiness gate：写入 `checks.json`

## 本地 smoke test

不接入 AI IDE，直接生成一个简单模型：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_generate_model.ps1
```

运行默认轻量单元检查（不生成重型模型，不等于全量验收）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

手动通过 JSON-RPC 打开已有项目：

```powershell
$env:LSPP_EXE = "<LS_PREPOST_INSTALL_DIR>\lsprepost4.12.exe"
@'
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"open_in_lsprepost","arguments":{"project_name":"generic_plate_demo"}}}
'@ | cmd /c .\scripts\start_mcp_server.cmd
```

`open_in_lsprepost` 默认只有在 `checks.readiness.ok_for_gui_preview=true` 时才会启动 LS-PrePost。除非你明确知道风险，否则不要随意使用 `force: true`。

## 按需测试与合并验收

自 2026-09-09 起，普通合并按改动范围进行专项验收，不默认要求全量回归或三个重型工作台案例全部通过。测试仍然保留；全量和真实重型测试均须先取得用户当次明确同意。默认 smoke 只是快速检查，不能代替相关功能验收。

| 改动范围 | 默认验证范围 |
| --- | --- |
| 页面、评估入口、演示交互 | 相关前端与 API 专项 |
| 评估规则、数据解析 | 单元测试、小样本、已保存结果回放 |
| 建模、网格、耦合 | 先做小规模验证，再申请必要的重型案例 |

以下命令只做轻量检查或查看执行计划：

```powershell
# 项目根目录无参数启动：仅 JSON-RPC 与错误输入 smoke
python -m pytest -q
# 保留原有专项分组；先列出分组或预览命令
powershell -NoProfile -File .\scripts\run_test_matrix.ps1 -List
powershell -NoProfile -File .\scripts\run_tests.ps1 -Group full -DryRun
# 修改测试入口时，选运行开关的专项（其中重型用例均为不生成模型的替身）
python -m pytest tests/test_test_execution_policy.py -q
```

仅在取得相应授权后使用：

```powershell
# 全量主测试目录回归，仍跳过 heavy_provider_e2e 标记的三个重型案例
powershell -NoProfile -File .\scripts\run_tests.ps1 -Group full -RunFull
# 重型案例优先单选，例如仅 residential；无需顺带跑全量
python -m pytest tests/test_phase18f_web_e2e_contract.py -m heavy_provider_e2e -k residential --run-heavy
# 只有用户明确要求全部重型案例时才用此组
powershell -NoProfile -File .\scripts\run_tests.ps1 -Group heavy -RunHeavy
```

`all` 保留为全量主测试目录加 `compileall`，同样需要 `-RunFull`。全量与重型开关独立；全量中也要包含重型时必须同时给出 `-RunFull -RunHeavy`。独立评估包仍通过 `-Group assessment` 单独验证，`full` 不代表所有可选集成都已验收。

所有 Python 专项统一使用 pytest，兼容旧 unittest 类测试。`refined-api` 针对工作台 API 的小型创建、恢复和并发夹具；`web-runtime` 针对状态、验证和静态界面。使用 `-DryRun` 查看每组具体文件；这两个分组也不能代替其他改动所需的专项。

```powershell
powershell -NoProfile -File .\scripts\run_tests.ps1 -Group refined-api -DryRun
powershell -NoProfile -File .\scripts\run_tests.ps1 -Group web-runtime -DryRun
```


直接 `pytest tests` / `pytest .` 会要求 `--run-full`；`--collect-only` 可以仅查看收集范围。只选重型文件、node id 或 `-m heavy_provider_e2e` 不会自动开启重型执行，仍需 `--run-heavy`。未标记的慢测试不保证轻量，指定专项时仍应检查范围。旧分组如 `critical`、`snapshots`、`web-e2e` 也不承诺都是快速检查。

这些开关防止常见入口误启动，不是安全沙箱：直接 `unittest discover` 或自定义命令可能绕开技术拦截，但同样受 [项目约定](AGENTS.md) 的授权限制。验收记录须明确通过的专项、未执行的全量/重型及仍未覆盖的风险。

## 确认 model.k 是否由本项目生成

为了避免 AI IDE 直接手写 `model.k`，本项目提供校验脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<PROJECT_DIR>\scripts\verify_generated_k.ps1" -ProjectDir "<PROJECT_DIR>\workspace\projects\<PROJECT_NAME>"
```

这个脚本会检查：

- `model.k` 是否包含本项目生成签名。
- `model.json` 是否存在且不是 `imported_keyword`。
- `checks.json` 是否存在。
- 根据 `model.json` 重新调用本项目生成器生成 keyword，并与磁盘上的 `model.k` 做 SHA256 一致性比较。

只有返回：

```text
"ok": true
"classification": "generated_by_lsprepost_mcp"
```

才能认为该 `model.k` 是本项目生成流程产生的，而不是 AI 手写或外部复制的 keyword。

## 分发与回退

生成干净 zip：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pack.ps1 -BuildLabel "source-review"
```

如果要生成“纯净分发包”，不包含历史 demo、生成型 examples、workspace、dist、var 等中间产物，使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pack.ps1 -BuildLabel "clean-release" -Pure
```

压缩包输出到：

```text
dist\
```

包名包含优化标签和时间戳，不覆盖旧版本。出现问题时，可以停止当前 MCP，解压旧 zip，并按旧版本 README 重新配置 `LSPP_EXE` 后启动。
上面的普通打包入口生成源码包；便携包还需传入经过校验的 `-PortableRuntimeDir`，不能把不含运行时的源码包当作免安装包。

其他机器使用流程：

1. 解压 zip 到新目录。
2. 安装 Python 3.10+ 和 LS-PrePost。
3. 用本机 LS-PrePost 路径运行 `doctor.ps1`。
4. 用 `setup.ps1` 生成 AI IDE 配置。
5. 把配置复制到 AI IDE。
6. 重启或刷新 AI IDE。
7. 先调用 `server_info`，或生成一个小 demo 验证闭环。

## 故障排查

如果 AI IDE 看不到 MCP 工具：

- 检查配置外层字段应使用 `mcpServers` 还是 `servers`。
- 检查 `scripts\start_mcp_server.cmd` 路径是否正确。
- 修改配置后重启 AI IDE。
- 在 PowerShell 中先运行 `doctor.ps1`。

如果 LS-PrePost 没有打开：

- 检查 `LSPP_EXE` 是否指向真实存在的 `lsprepost*.exe`。
- 调用 `server_info` 查看 `lspp_doctor`。
- 检查 `checks.readiness.ok_for_gui_preview`。

如果预览导出失败：

- 先调用 `validate_lsprepost_import`。
- 查看项目下的 `artifacts\lspp_verifications.json`。
- 查看项目 artifacts 目录下的 keyword reader XML。
- 如果是 GIF 导出失败，先运行 `doctor.ps1` 查看 `pillow_optional`；需要 GIF 功能时安装 Pillow。
- 不同 LS-PrePost 版本可能存在 cfile 命令或图片导出差异。如果模型已经生成且静态校验通过，但 PNG/GIF 导出失败，应提示用户自行打开 LS-PrePost 验证模型，而不是直接判定模型生成失败。

## 固定建筑 CPU 构件试算

当前有三条不同的 CPU 路径，不能把它们的功能和验证结论混用。

### 默认轻量场景演示

`/cpu-blast` 默认提供三层住宅、商超、住宅小区、地铁入口和城市街道五类简化场景。用户显式开始后在浏览器 Worker 中计算，可选择当前场景的破坏表现、查看局部碎裂/飞散、曲线与回放；匹配的结果保存在独立 IndexedDB 缓存中，不自动重算，也不调用旧原生求解 API。

这条默认演示路径不要求先安装 OpenSeesPy。其简化连接、板片与接触响应不等于 LS-DYNA/OpenSees 工程有限元验收；烟尘是表现效果，显示结果不能当作已求得的真实钢筋应力或经标定的损伤预测。当前入口与验证范围见 [CPU 默认入口接入记录](docs/superpowers/reports/2026-10-24-cpu-demo-workbench-integration.md)及[演示响应改进记录](docs/superpowers/reports/2026-10-24-scene-physics.md)。

### 可选弹性参考算例与历史整栋首试

开发验证入口为 `/fixed-building-pressure/response`。给定压力工况与 K 包保留在 `/structural-pressure?legacy=1`，TNT 默认工况使用 `/structural-pressure`；这些参数和任务与 CPU 参考试算独立。

该开发验证页提供 3 m 悬臂配筋柱、2 m × 2 m 分层配筋板两种弹性参考算例。点击“开始 CPU 计算”后才启动独立 OpenSeesPy 进程，可查看位移云图、钢筋纤维或配筋层轴向应力、位移/速度/加速度/能量曲线，回放历史结果，导出 CSV、JSON 和图片。压力着色表示给定表面荷载，未求解空气压力场。默认材料和压力用于数值验证，不代表本建筑标定参数。

Windows 可选环境位于 `.venv/cpu-response`，使用 Python 3.12.10 x64、OpenSeesPy 3.8.0.0。安装和两个极小能力探针均为显式操作，不由页面 GET 自动执行：

```powershell
python scripts/setup_cpu_response.py --install
# 已安装环境只验证，不下载或改动系统 Python：
python scripts/setup_cpu_response.py --verify-only
```

依赖 wheel 哈希锁定在 `lsprepost_mcp/architecture/cpu_response/requirements-win-py312.txt`；Python 官方下载地址和 SHA256 在安装脚本中固定。能力记录核对解释器、内核 DLL/PYD 和包文件的路径/大小/时间身份；环境改变后须重新显式验证。每次任务冻结输入、来源、适配代码指纹和环境身份；失败、停止、超时、服务重启或产物校验失败均不发布 completed 结果。

每例限 30 s、10,000 积分步、500 帧和 5,000 曲线点，同时仅运行一个 CPU 求解进程。内部每步提取峰值，回放抽稀不改变峰值。钢筋为完全粘结的弹性纤维/配筋层；尚无开裂、屈服、滑移、断裂或倒塌预测。

2026-10-22 保存的单柱/单板报告记录：完整 150 ms、16→32 网格及 32 网格步长减半的检查通过。钢筋峰值空间变化为柱 0.0676%、板 0.8288%；最细单板含启动和写盘用时 7.864 s。这是两个弹性参考模型的历史结论，不代表实际建筑或真实爆炸精度，也不是本次重跑结果。来源见 [CPU 参考算例历史记录](docs/reviews/README_STATUS_AUDIT_20261030.zh-CN.md#cpu-参考算例历史记录)。

单板加速只用于已验证的平板、对称配筋和均布横向荷载参考模型：使用原生有限元矩阵，精确消去无质量转角并保留全部有质量自由度；钢筋恢复经原生记录器核对。

历史三层柱板参考模型完成过原生数据、连接、配筋与质量映射核对：630 个结构节点、402 个柔性壳和 144 个纤维梁柱单元；填充、楼梯和屋顶附属构件仅计质量/荷载，保留原 K。该理想化参考模型不同于默认轻量演示及后续非线性整栋候选，来源见[状态核对记录](docs/reviews/README_STATUS_AUDIT_20261030.zh-CN.md#cpu-参考算例历史记录)。

2026-10-22 经当次授权执行过一个线弹性整栋参考工况：首层单块 9.0666 m² 墙面给定 10 kPa 压力，150 ms、1500 步；父进程耗时 97.947 s，节点位移幅值峰值 0.080701 mm、钢筋采样点轴向应力绝对值峰值 1.508288 MPa。该次通过独立 CLI 运行；当前页面可在本机历史产物存在时只读查看报告、静态图表和下载数据，新的整栋参考求解与三维回放仍未启用。GitHub 源码不包含这份历史结果。本例未完成整栋收敛、经验空气冲击波或非线性损伤验证，不能用于判断真实建筑抗爆安全。

`scripts/prepare_cpu_response_building.py --output-dir <新目录>` 只读取原生数据并生成预备输入；`scripts/run_cpu_response_building.py --case <reference-case.json>` 默认只读检查。实际整栋运行需按根 AGENTS.md 说明范围和预计耗时、取得当次明确同意后才显式加 `--run --output-dir <新目录>`。完整150 ms的微型三层已跑通，不能替代真实整栋稳定性、收敛或性能验证。方法、历史失败证据及复现命令见[实施记录](docs/superpowers/plans/2026-10-22-fixed-building-cpu-response.md#执行记录)。

### 保留的原生非线性场景与诊断

`/cpu-blast?legacy=1` 保留原场景工作台、历史结果和诊断；后端/API 仍存在，不表示所有候选模型已可可靠计算。2026-10-24 的[精度运行时复验](docs/superpowers/reports/2026-10-24-native-whole-gravity-precision-revalidation.md)和[局部保护运行时复验](docs/superpowers/reports/2026-10-24-native-whole-gravity-guard-revalidation.md)均记录整栋自重未通过：10% 已接受状态通过，目标 25% 步原生失败并按首次失败停止。不能把该候选写成满自重、后续 TNT 或完整建筑非线性响应已验收，也不能用默认轻量演示的通过替代它。

## 重要限制

- 这不是完整 LS-DYNA 前处理器。
- `checks.ok` 只表示本地静态校验通过，不等同于求解器认证结果。
- 内置材料参数是名义值，真实工程使用前必须复核。
- 自然语言能力是受控模板解析，不是开放式任意建模。
- `cylinder_solid` 和 `beam_bar` 当前是六面体近似。
- 既有“导入 LS-Run”流程仍只负责打开 LS-Run 完成本地交接，不自动提交求解、监控任务或判定损伤。新损伤评估接口是独立的显式操作，仅处理服务器已登记的求解结果，不替代专业鉴定。
