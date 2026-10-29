# lsprepost-mcp

`lsprepost-mcp` 是一个本地运行的 LS-PrePost / LS-DYNA keyword 受控建模工具。它提供 Web App 和 MCP 两种入口，用项目内白名单场景、模板和校验流程生成 `model.k`，并支持三维预览、LS-PrePost 复核及 LS-Run 交接。

项目目录职责、源码与运行产物边界见 [项目结构与文件归属](docs/PROJECT_STRUCTURE.zh-CN.md)。

## 从 GitHub 开始

本仓库保存项目源码、受控材料与模板、测试及文档。第一次使用请阅读
[源码安装与启动指南](docs/QUICKSTART.zh-CN.md)；全部说明入口见
[文档导航](docs/README.zh-CN.md)。

```powershell
git clone https://github.com/JianP-Ciallo/ls_dyna_make_for_K.git
cd ls_dyna_make_for_K
```

这是私有仓库，克隆时需要使用有仓库访问权限的 GitHub 账号。
GitHub 源码不包含便携 Python 运行时、商业求解器、本机配置或历史计算结果。
下方双击启动方式适用于已准备好运行环境的电脑；从源码首次安装请先按快速指南配置 Python。

它不是完整的 LS-DYNA 前处理器，也不支持开放式任意建模。真实工程使用前，仍需由具备经验的人员检查单位、材料、网格、接触、约束、载荷和求解设置。

## 一键启动

环境要求：

- Windows 10/11 64 位。
- **便携包（portable-win64）**已内置 Python、NumPy、Pillow 和损伤评估所需依赖，无需安装 Python、pip 或 Node.js。完整解压到可写目录，保留 `runtime` 与启动文件的相对位置。
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

1. 在左侧点击“导入 LS-PrePost”，选择本机真实存在的 `lsprepost*.exe`。
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
- MM-ALE 爆炸冲击钢板：显式空气域、Composition B 参考炸药、球形体积分数初始化、非反射边界和流固耦合；当前只完成生成与 LS-PrePost 导入验收，真实求解必须单独获得许可。
- K&C 柱形埋置装药混凝土模型（Phase 15，开发中）：二维轴对称 TNT/空气 MM-ALE、K&C 混凝土和钢箍。已显式生成孔壁、装药底面和混凝土顶面的 FSI 线段集，并提供 1–3 层 ALE 数值侵入覆盖；当前生成结果仍不得直接用于混凝土压力、应力或损伤结论。

以上场景生成的是受控模板模型，不应被描述为任意几何或任意工况生成能力。

### Phase 15 当前状态

`phase15_a1_kc_axisymmetric_acceptance_r12fix3` 只作为 FSI 失效基线保留：求解能够正常结束且 TNT 能够起爆，但 `d3hsp` 显示 `number of slave segments for coupling = 0`，冲击波没有有效传入混凝土。

当前生成器会显式生成上述二维线段集，并静态检查每条 FSI 线段两侧是否具有所选层数的 ALE 覆盖。Web App 默认采用 2 层，可选择 1–3 层，并实时显示“层数 × 网格尺寸”得到的计算侵入深度；该深度是 immersed FSI 的数值覆盖，不是物理空气层厚度。

真实验收仍必须满足：`d3hsp` 中 FSI slave segment 数量大于 0、混凝土静水压力和主应力出现有效响应、K&C 损伤变量可读取。静态校验通过或求解正常结束都不能替代这些检查。

## LS-Run 交接边界

当前 Web App 会校验并保存本机 `lsrun.exe` 与 LS-DYNA 求解器路径，然后打开 LS-Run。使用者仍需在 LS-Run 中核对 `model.k`、求解器、CPU、内存和工作目录后手动启动任务。

上述既有 LS-Run 交接流程不自动把所有字段填入 LS-Run，不自动提交 LS-DYNA 求解，不自动监控任务，也不自动判断应力、损伤、贯穿或失效结果。求解完成后，应在 LS-PrePost 中打开 `d3plot` 等结果文件进行检查。

建筑与地面损伤评估现提供可选的受控 API 桥接：显式读取服务器登记的已结束求解结果，保存研究参考报告，不改变旧页面，也不接入 DeepSeek。安装方式与接口见 [中文说明](README.zh-CN.md#可选的爆炸损伤评估能力)。

## AI IDE / MCP

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
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pack.ps1 -BuildLabel "phase11.9-lsrun-handoff-dev"
```

输出位于 `dist\`。包名带时间戳，不覆盖旧版本；`PACKAGE_MANIFEST.txt` 记录包内文件的 SHA256。

## 重要限制

- `checks.ok` 只表示本项目静态校验通过，不代表 LS-DYNA 求解成功。
- 内置材料参数是名义值，正式分析前必须复核材料模型和参数来源。
- 自动 PNG/GIF 预览受 LS-PrePost 版本影响；导图失败不等于 `model.k` 生成失败。
- Web 三维视窗用于生成前后检查几何和部件，不替代 LS-PrePost 的 keyword、接触、边界条件和结果复核。
- 当前 LS-Run 功能是本地交接入口，不是求解队列管理器或结果分析器。
- `Normal termination` 只表示求解器正常结束，不证明载荷、接触或 FSI 已经物理生效；爆炸模型还必须检查 `d3hsp`、`dbfsi`、材料压力和结构响应。

更多分发、测试和兼容说明见 `docs\`。
