# Web App 与 AI IDE 双入口工作流设计

日期：2026-06-19

## 目标

在现有 `lsprepost-mcp` 后端基础上，增加一个可移植的本地 Web App。用户拿到项目 zip 后，可以在自己的 Windows 电脑上运行项目，通过浏览器选择受控场景、填写参数、生成 LS-DYNA keyword 模型、查看校验结果和 PNG/GIF 预览；如果自动预览或校验异常，可以一键打开 LS-PrePost 排查。

同时保留 AI IDE 入口。AI IDE 适合高级用户用自然语言描述工况，Web App 适合普通用户通过界面完成受控建模。两个入口必须使用同一个后端生成流程，不能各自生成 keyword。

## 定位

这是一个本地单机、可移植、玩具级到原型级的工程工作台，不是云端平台。

默认运行方式：

```text
用户解压项目 zip
  -> 配置本机 LS-PrePost 路径
  -> 启动本地 Web 后端
  -> 浏览器访问 localhost
  -> 选择场景或输入自然语言
  -> 后端生成 model.json / model.k / checks.json
  -> 浏览器展示摘要、校验、预览、日志
```

## 运行依赖

最终用户运行时要求：

- Windows
- Python
- 本机已安装 LS-PrePost
- 可选 Pillow，仅用于 GIF 预览

最终用户运行时不强制要求 Node.js。

开发和构建时：

- 有 Node.js 时，优先使用 React/Vite 开发并构建前端。
- 打包时把构建后的静态文件放入分发包。
- 无 Node.js 或构建产物缺失时，使用原生 HTML/CSS/JS 兜底前端。

## 入口策略

采用双入口：

```text
Web App 普通入口
  场景选择、参数填写、自然语言输入、项目管理、预览、排错

AI IDE 高级入口
  自然语言描述、调用 MCP 工具、辅助解释和排错
```

两个入口共享同一个后端能力：

- `generate_model`
- `generate_scene_from_prompt`
- `validate_model`
- `model_summary`
- `read_project`
- `list_projects`
- `export_preview_image`
- `export_preview_images`
- `export_preview_gif`
- `validate_lsprepost_import`
- `open_in_lsprepost`

## 技术路线

采用“先 A，后续演进到 C”的路线。

### 当前阶段采用方案 A

首版 Web App 是轻量 Web 壳，Web 后端直接调用现有 Python 工具函数：

```text
浏览器
  -> 本地 Web 后端
    -> lsprepost_mcp.tool_* Python 函数
      -> workspace/projects
      -> LS-PrePost
```

优点：

- 改动小。
- 能最大程度复用现有后端。
- 不需要 Web 后端再管理 MCP 子进程。
- 适合当前单人维护和本地可移植目标。

限制：

- Web API 会与现有工具函数有一定耦合。
- 后续如果要长期维护，需要逐步沉淀 service layer。

### 后续演进到方案 C

当 Web App 稳定后，把 MCP 和 Web 共用的业务逻辑沉到 service layer：

```text
浏览器 -> Web API -> service layer -> generator/project/lspp
AI IDE -> MCP tools -> service layer -> generator/project/lspp
```

目标是让 Web API 和 MCP tools 都变成薄入口，真实业务逻辑集中到可测试、可复用的服务层。

## 前端形态

采用混合式界面：

```text
新建模型：向导式
项目管理/预览/排错：工作台式
```

### 向导式新建模型

用于普通用户创建模型：

1. 选择受控场景。
2. 填写参数。
3. 可选输入自然语言补充说明。
4. 后端解析并返回待确认参数。
5. 用户确认。
6. 后端生成模型。
7. 自动执行静态校验和可选预览。

### 工作台式项目管理

用于查看和排错：

- 左侧：项目列表、场景类型、生成时间、状态。
- 中间：参数、自然语言输入、模型摘要、校验结果。
- 右侧：PNG/GIF 预览、日志、错误信息、打开 LS-PrePost 按钮。

## 自然语言能力

Web App 支持自然语言输入，但 AI 是可选增强，不是强依赖。

默认离线模式：

- 调用现有 `generate_scene_from_prompt`。
- 使用当前受控规则解析 prompt。
- 不需要 API Key。

可选 AI 增强模式：

- 用户配置 API Key 后启用。
- AI 只负责把自然语言转换为受控 scene/spec。
- 后端必须继续执行 schema 校验、材料校验、场景白名单校验和 keyword 生成校验。
- AI 不得直接写 `.k` / `.key` / `.dyn` 文件。

## 首版功能范围

首版 Web App 包含：

- 环境检查。
- LS-PrePost 路径配置。
- 场景选择。
- 参数表单。
- 自然语言输入。
- 参数确认流程。
- 项目列表和历史项目读取。
- 生成 `model.json` / `model.k` / `checks.json`。
- 静态校验结果展示。
- 模型摘要展示。
- PNG/GIF 预览展示。
- 打开 LS-PrePost 排查。
- 日志和错误面板。
- 项目打包导出。

## 非目标

首版不做：

- 多用户系统。
- 公网部署。
- 账号和权限。
- 云端数据库。
- 在线材料库。
- 浏览器内有限元求解。
- 开放式任意建模。
- 前端直接编辑 keyword。
- AI 直接生成 keyword。

## 安全和一致性边界

必须保持以下规则：

- 前端不能直接创建、编辑或覆盖 `.k` / `.key` / `.dyn`。
- AI 不能直接创建、编辑或覆盖 `.k` / `.key` / `.dyn`。
- 所有 keyword 文件必须由现有后端生成流程产生。
- Web 后端只能暴露受控 API，不能暴露任意 cfile 执行。
- Web 后端调用 LS-PrePost 时必须复用现有 runtime lock、manifest/hash、readiness gate 和 process record 机制。
- 项目生成后必须保留 provenance，用于证明 `model.k` 来自本项目生成流程。

## 启动方式

同时支持两种方式：

```text
双击 start_web_app.ps1
```

和：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web_app.ps1 -LsppExe "<LS_PREPOST_EXE>"
```

如果没有传入 `LsppExe`，Web App 应进入配置页，引导用户填写或确认 LS-PrePost 路径。

## 阶段建议

### 第 11 阶段：本地 Web App 首版

目标：

- 增加本地 Web 后端。
- 增加 React/Vite 前端构建目录。
- 增加原生 HTML/CSS/JS 兜底页面。
- 增加 `start_web_app.ps1`。
- 提供场景选择、参数表单、生成、校验、预览、打开 LS-PrePost 的闭环。

验收：

- 无 Node.js 的用户也能运行兜底页面。
- 有构建产物时优先加载 React/Vite 页面。
- Web App 生成的 `model.k` 可通过 `verify_generated_k.ps1` 验证。
- Web App 不能直接写 keyword。

### 第 12 阶段：后端 service layer 演进

目标：

- 将 Web API 和 MCP tools 共用逻辑沉淀到 service layer。
- 让 MCP tools 和 Web API 都变成薄入口。
- 增强测试覆盖和错误结构。

验收：

- Web App 和 MCP 对同一输入生成一致项目产物。
- 核心业务逻辑有直接单元测试。
- API 错误、校验错误、LS-PrePost 错误有统一结构。

## 风险

- React/Vite 构建会引入 Node.js 开发依赖，需要保证运行时不依赖 Node。
- Web App 会增加用户误操作路径，必须保持“确认后生成”的流程。
- 可选 AI 增强可能引入不确定输出，必须通过受控 schema 和白名单收束。
- LS-PrePost 不同版本的预览导出行为可能不同，Web App 必须把“预览失败”和“模型生成失败”区分开。

## 当前结论

采用本地可移植双入口方案：

```text
第 11 阶段先做轻量 Web App，直接复用现有 tool_* 后端能力。
第 12 阶段再把共用逻辑沉淀为 service layer。
```

这是当前成本、稳定性和可分发性之间最合适的路线。
