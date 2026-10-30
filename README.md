# LS-DYNA Make for K · lsprepost-mcp

`lsprepost-mcp` 是一个本地运行的 LS-PrePost / LS-DYNA keyword 受控建模工具。它提供 **Web 工作台**和 **MCP 工具服务**两种入口，用项目内白名单场景、模板和校验流程生成 `model.k`，并支持三维预览、项目保存、LS-PrePost 复核及 LS-Run 交接。

项目目录职责、源码与运行产物边界见 [项目结构与文件归属](docs/PROJECT_STRUCTURE.zh-CN.md)。

## 这是 MCP 吗？需要部署到服务器吗？

**项目包含一个本地 stdio MCP Server，也包含独立的 Web 应用。不需要租用云服务器或部署到公网。**

MCP（Model Context Protocol，模型上下文协议）规定 AI 应用如何发现和调用工具。“Server”在这里指提供工具的程序，可以作为子进程运行在你的电脑上。项目当前通过标准输入/输出（`stdio`）交换 JSON-RPC 消息，实现了 `initialize`、`tools/list`、`tools/call` 等协议方法。

| 使用入口 | 运行方式 | 如何连接 |
| --- | --- | --- |
| MCP 工具服务 | AI 客户端启动本地 Python 子进程 | 配置启动命令和参数，通过 stdio 通信 |
| Web 工作台 | 本机 Python HTTP 服务 | 浏览器访问 `http://127.0.0.1:8765/` |

两种入口可以单独使用。打开网页不会自动建立 MCP 连接，`http://127.0.0.1:8765/` 也不是 MCP HTTP 服务地址；网页中的功能只有注册成 MCP 工具后才能通过 MCP 调用。

MCP 也支持基于 HTTP 的连接，但当前项目没有实现远程 MCP HTTP 端点。多人远程共享需要另外设计网络传输、身份认证、任务隔离及求解器所在环境，上传源码到 GitHub 不会自动完成这些部署。协议依据见 [MCP 官方 stdio / Streamable HTTP 传输说明](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)。

本地运行适合本项目：模型文件、LS-PrePost、LS-Run 和求解器均位于使用者电脑上，服务可以直接访问配置的本机路径。

## 主要能力

| 能力 | 说明 |
| --- | --- |
| 受控建模 | 按场景填写几何、材料、网格、约束、载荷和冲击参数，生成 LS-DYNA keyword 文件 |
| 三维预览与校验 | 查看几何、部件和静态校验结果，按需打开 LS-PrePost 人工复核 |
| 项目管理 | 保存、恢复项目，导出模型文件和生成记录 |
| 固定建筑与 TNT 工作台 | 建筑预览、室外 TNT 编辑、受控 K 包生成，以及已保存结果的压力曲线读取；旧给定压力工况保留独立入口 |
| 损伤评估 | 真实结果的受控评估桥接，以及独立的交互式合成演示；两者的数据来源与结论范围不同 |
| 轻量 CPU 场景演示 | `/cpu-blast` 默认提供三层住宅、商超、住宅小区、地铁入口和城市街道的浏览器 Worker 演示、回放与缓存 |
| 可选原生 CPU 试算 | 保留单柱/单板弹性参考试算、历史整栋首试报告/图表查看与下载，以及旧场景记录；非线性整栋候选仍有未通过项 |
| 固定来源模型重建 | GRAN_R5、5-1788-2、B120 等专用 CLI/工具路径；受原来源、单位和材料依赖约束 |
| MCP 调用 | 向 AI 客户端提供模型生成、材料查询、模型校验和预览等已注册工具 |

## 阶段状态摘要

以下状态于 **2026-10-30** 对照当前源码和已保存报告核对。“实现完成”“软件验收”和“指定工况的物理验证”分别表述；本次文档更新没有重新执行历史求解或全量验收。

| 阶段 | 当前可确认的范围 |
| --- | --- |
| Phase 1–10 | 已有受控生成、校验、材料/资源查询、预览、诊断与分发等基础工具链；默认 smoke 仅是轻量检查。 |
| Phase 11–13 | 本地 Web、组件装配、物理动作、受控爆炸预设与结果摘要已实现，工程精度依赖各自证据。 |
| Phase 14 | MM-ALE 生成、求解结果封存与验收门禁已实现；旧三档网格收敛证据已降级，不能引用为当前收敛结论。 |
| Phase 15 | 当前实现基线已完成，已有受控案例的历史波传递通过记录；共形方案资格单独限定。 |
| Phase 16–17 | 城市对象评估、多保真编排、场景编辑与项目状态流程已实现；损伤评估桥接另有验收，规则仍为研究参考。 |
| Phase 18 | 18A–18F 有软件交付/验收记录；后续独立 ALE/FSI 路径有三类模型的指定短时求解记录，不能扩大为完整事件或工程精度验收。 |

各阶段的来源、后续功能入口及仍未通过的事项见[阶段与功能核对记录](docs/reviews/README_STATUS_AUDIT_20261030.zh-CN.md)。[路线图](docs/ROADMAP.zh-CN.md)保留早期规划快照，不作为当前状态的唯一依据。

## 从 GitHub 开始

本仓库保存项目源码、受控材料与模板、测试及文档。第一次使用请阅读
[源码安装与启动指南](docs/QUICKSTART.zh-CN.md)；全部说明入口见
[文档导航](docs/README.zh-CN.md)。

```powershell
git clone https://github.com/JianP-Ciallo/ls_dyna_make_for_K.git
cd ls_dyna_make_for_K
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "numpy>=1.26,<3" Pillow
.\.venv\Scripts\python.exe -m lsprepost_mcp.web.app --open-browser
```

这是私有仓库，克隆时需要使用有仓库访问权限的 GitHub 账号。
上面的源码启动示例以已安装 Python 3.12 为前提；主项目支持 Python 3.10 或更高版本。
界面和必要的受控模板已随源码提供，普通使用无需安装 Node.js 或重新构建前端。
GitHub 源码不包含便携 Python 运行时、商业求解器、本机配置或历史计算结果。
下方双击启动方式适用于已准备好运行环境的电脑；从源码首次安装请先按快速指南配置 Python。

它不是完整的 LS-DYNA 前处理器，也不支持开放式任意建模。真实工程使用前，仍需由具备经验的人员检查单位、材料、网格、接触、约束、载荷和求解设置。

## 一键启动

环境要求：

- Windows 10/11 64 位。
- **另行制作的便携包（portable-win64）**可包含 Python、NumPy、Pillow 和损伤评估所需依赖，完整解压后按包内说明启动；须保留 `runtime` 与启动文件的相对位置。GitHub 源码 ZIP 不包含该运行时。
- **源码包**需另装 Python 3.10 或更高版本，并按 [中文说明](README.zh-CN.md) 安装对应功能依赖；开发测试工具不包含在便携运行时中。
- 建议安装 LS-PrePost；需要求解交接时再准备 LS-Run 和 LS-DYNA 求解器。
- LS-PrePost、LS-Run 和 LS-DYNA 不随包分发，由用户在页面中配置本机路径。

解压后双击根目录中的：

```text
start_web_app.cmd
```

浏览器将打开：

```text
http://127.0.0.1:8765/
```

这个地址只供当前电脑访问，不需要把项目部署到互联网。关闭启动命令窗口后，Web App 也会停止。

## Web App 使用流程

1. 在工具/配置入口点击“导入 LS-PrePost”，选择本机真实存在的 `lsprepost*.exe`。
2. 选择受控场景，填写尺寸、材料、网格、载荷或冲击速度。
3. 先确认生成摘要，再点击“生成模型”。
4. 在中央三维视窗中拖动、缩放、切换视角和显示部件。
5. 查看校验摘要；需要时保存模型副本或打开 LS-PrePost 人工复核。
6. 需要求解交接时，在右侧点击“导入 LS-Run”和“导入 LS-DYNA 求解器”，再点击“送入 LS-Run”。

本机程序路径只写入：

```text
var\generated_configs\web_app.local.json
```

该文件不应随压缩包分发。

每个生成项目通常包含：

```text
model.k
model.json
checks.json
open_model.cfile
```

导出到用户指定目录时，还会生成 `export_manifest.json`。

## 当前受控场景

- 钢筋以给定初速度冲击固定椭球头盔壳：可填写钢筋尺寸、初始间距、冲击速度、头盔尺寸和材料。
- 圆柱杆以给定初速度冲击固定钢板：可填写杆件、钢板、材料、网格和冲击速度。
- 立方体底部固定、顶面四角向下受载：可填写尺寸、材料、网格和集中载荷。
- 壳板固定边界、承受均布压力：可填写板长宽厚、材料、网格、压力和固定边界。
- MM-ALE 爆炸冲击钢板：显式空气域、Composition B 参考炸药、球形体积分数初始化、非反射边界和流固耦合，已实现求解结果封存和传播验收门禁；旧三档收敛报告已降级，详见 [Phase 14 说明](docs/reviews/phase14/PHASE14_MM_ALE_ACCEPTANCE.zh-CN.md)。真实求解仍须另行授权。
- K&C 柱形埋置装药混凝土模型（Phase 15，当前实现基线已完成）：二维轴对称 TNT/空气 MM-ALE、K&C 混凝土和钢箍。支持受控网格、材料、FSI 接口和 Web 生成流程，已有历史受控案例的波传递验收记录；共形方案和工程精度仍需按各自范围验证。
- 精细化建筑爆炸（Phase 18）：商业超市、住宅和地铁入口的资产、八步工作台及分层 ALE/FSI 配置；软件验收与不同版本的指定短时求解分别记录，不代表所有配置已获工程验证。

固定建筑 TNT、轻量 CPU 演示和固定来源模型重建采用独立入口，不等同于上面四类自然语言场景；路径和使用边界见[中文说明](README.zh-CN.md#阶段状态与页面入口)。

以上场景生成的是受控模板模型，不应被描述为任意几何或任意工况生成能力。

### Phase 15 状态与验证范围

Phase 15 已完成当前实现基线，与[路线图的阶段定义](docs/ROADMAP.zh-CN.md#3-阶段总览)一致。本地保存的 2026-07-23 案例 `phase15_a1_kc_axisymmetric_fsi_mmgfix` 在当时的验收报告中记录 `wave_transfer_verified: true`，FSI 从属线段数为 193，并有有限的混凝土压力、主应力及沿测点传播的响应。记录来源、数值及适用边界见 [Phase 15 状态核对说明](docs/reviews/phase15/PHASE15_STATUS.zh-CN.md)。这属于已有案例的历史证据，不代表本次重新运行了求解或新版验收。

早期案例 `phase15_a1_kc_axisymmetric_acceptance_r12fix3` 的 FSI 从属线段数为 0，仅保留为历史失效基线，不能用它代表 Phase 15 整体的当前实现状态。

当前生成器会显式生成上述二维线段集，并静态检查每条 FSI 线段两侧是否具有所选层数的 ALE 覆盖。Web App 默认采用 2 层，可选择 1–3 层，并实时显示“层数 × 网格尺寸”得到的计算侵入深度；该深度是 immersed FSI 的数值覆盖，不是物理空气层厚度。

共形共享节点和共形空气间隙方案在当前代码中仍标为 `experimental_unqualified`，不能直接沿用上述案例的通过结论。新工况需独立核对传递证据和对应验收条件；历史波传递通过也不能证明材料工程标定、网格收敛或损伤预测已经完成。静态校验通过或求解正常结束不能替代这些检查。

## LS-Run 交接边界

当前 Web App 会校验并保存本机 `lsrun.exe` 与 LS-DYNA 求解器路径，然后打开 LS-Run。使用者仍需在 LS-Run 中核对 `model.k`、求解器、CPU、内存和工作目录后手动启动任务。

上述既有 LS-Run 交接流程不自动把所有字段填入 LS-Run，不自动提交 LS-DYNA 求解，不自动监控任务，也不自动判断应力、损伤、贯穿或失效结果。求解完成后，应在 LS-PrePost 中打开 `d3plot` 等结果文件进行检查。

建筑与地面损伤评估提供可选的受控 API 桥接，读取已登记终态结果并输出研究参考报告；页面还提供独立的交互式合成演示。演示不启动求解器，不能用作真实 d3plot 解析或工程验证。安装方式与接口见[中文说明](README.zh-CN.md#可选的爆炸损伤评估能力)。上述 LS-Run 按钮的行为不代表其他显式计算入口也仅负责打开程序。

## AI IDE / MCP

MCP 入口是 [`lsprepost_mcp/server.py`](lsprepost_mcp/server.py)。支持 stdio 的客户端可启动该脚本，无需先启动 Web 工作台。

以下为采用 `mcpServers` JSON 配置的客户端示例；请把所有 `C:/path/to/...` 替换为当前电脑上的真实绝对路径。其他客户端按自身配置格式填写相同启动命令和参数。

```json
{
  "mcpServers": {
    "lsprepost": {
      "command": "C:/path/to/ls_dyna_make_for_K/.venv/Scripts/python.exe",
      "args": [
        "-B",
        "-X",
        "utf8",
        "C:/path/to/ls_dyna_make_for_K/lsprepost_mcp/server.py"
      ],
      "env": {
        "LSPP_EXE": "C:/path/to/LS-PrePost/lsprepost4.12.exe"
      }
    }
  }
}
```

客户端通过 `tools/list` 获取工具，再通过 `tools/call` 调用。例如 `server_info`、`list_materials`、`generate_scene_from_prompt`、`generate_model`、`validate_model` 和 `open_in_lsprepost`。实际可用工具以服务返回的清单为准，Web 专属功能不会自动进入 MCP 工具清单。

直接在终端运行 MCP 脚本时，程序会等待标准输入中的协议消息，不会自动打开网页。标准输出用于协议通信，诊断信息写入标准错误。源码虚拟环境的使用者应确认客户端启动的是安装依赖的同一个 Python。

把项目交给 Codex、Cursor、VS Code 等 AI IDE 时，先让它阅读：

```text
AI_IDE_START_HERE.zh-CN.md
README.zh-CN.md
```

AI IDE 必须遵守：

- 不修改项目源代码、脚本、模板、材料库和测试。
- 不直接手写、编辑或覆盖 `.k`、`.key`、`.dyn` 文件。
- 所有 keyword 文件都必须由本项目的受控生成流程产生。
- 只调用项目提供的生成、校验、预览和打开工具。
- 未获得用户当次明确授权时，不得启动 LS-Run 或 LS-DYNA；初始化检查和完整求解分别授权。

MCP 配置、统一启动词和工具说明见 [README.zh-CN.md](README.zh-CN.md)。

## 开发与复核

运行默认轻量检查（不是全量验收；合并时还需选择与改动相关的专项）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

全量回归和三个重型工作台案例不再作为每次合并的固定门槛，须先取得用户明确同意。
默认入口已增加按需开关，详见 [按需测试与合并验收](README.zh-CN.md#按需测试与合并验收) 和 [项目约定](AGENTS.md)。

检查 Python 文件：

```powershell
python -m compileall -q .\lsprepost_mcp
```

生成带测试和开发文档的审查包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pack.ps1 -BuildLabel "source-review"
```

输出位于 `dist\`。包名带时间戳，不覆盖旧版本；`PACKAGE_MANIFEST.txt` 记录包内文件的 SHA256。
普通打包生成源码包；制作便携包还需通过 `-PortableRuntimeDir` 提供已经准备并校验的 Windows 运行时，不能把源码包直接描述为免安装便携包。

## 重要限制

- `checks.ok` 只表示本项目静态校验通过，不代表 LS-DYNA 求解成功。
- 内置材料参数是名义值，正式分析前必须复核材料模型和参数来源。
- 自动 PNG/GIF 预览受 LS-PrePost 版本影响；导图失败不等于 `model.k` 生成失败。
- Web 三维视窗用于生成前后检查几何和部件，不替代 LS-PrePost 的 keyword、接触、边界条件和结果复核。
- 当前 LS-Run 功能是本地交接入口，不是求解队列管理器或结果分析器。
- `Normal termination` 只表示求解器正常结束，不证明载荷、接触或 FSI 已经物理生效；爆炸模型还必须检查 `d3hsp`、`dbfsi`、材料压力和结构响应。

更多分发、测试和兼容说明见 `docs\`。
