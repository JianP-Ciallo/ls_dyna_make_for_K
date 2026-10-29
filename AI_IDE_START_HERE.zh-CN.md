# AI IDE 从这里开始

这份文件给 Codex、Cursor、Claude Desktop、Windsurf、VS Code、Visual Studio 等 AI IDE 读取。目标是：用户把本项目文件夹交给 AI IDE 后，AI IDE 可以按步骤完成诊断和 MCP 配置，而不要求用户手动进入项目目录运行命令。

## 统一初始启动词

用户可以把下面这段话直接发给 AI IDE：

```text
请把当前文件夹当作一个现成的 LS-PrePost/LS-DYNA keyword 生成工具项目使用。先阅读 AI_IDE_START_HERE.zh-CN.md 和 README.zh-CN.md。不要修改项目源代码，不要修改 scripts/resources/tests，不得直接创建、编辑或覆盖任何 .k/.key/.dyn 文件；所有 keyword 文件必须通过本项目生成流程产生。请先检查 Python 和 LS-PrePost 路径，然后告诉我当前环境是否可用。环境可用后，请先列出当前项目支持的可控场景建模选项，只给出模糊场景和需要我补充的数据项，不要直接编造参数。我的 LS-PrePost 路径是：<LS_PREPOST_EXE>。如果 LS-PrePost 因版本差异无法自动导出 PNG/GIF 预览，请明确告诉我需要自行打开 LS-PrePost 验证，不要把导图失败判断为模型生成失败。
```

如果用户不知道 LS-PrePost 路径，AI IDE 应先帮助用户定位真实存在的 `lsprepost*.exe`，不要编造路径。

## 启动后应给用户的场景选项

完成环境检查后，AI IDE 应先给用户下面这类简洁选项，而不是直接生成模型：

```text
当前项目支持这些可控场景：

1. 钢筋自由落体冲击头盔
   可填写：钢筋长度/直径、下落高度、头盔尺寸/厚度、材料、是否导出预览。

2. 圆柱杆冲击钢板
   可填写：杆长度/直径、冲击速度、钢板长宽厚、材料、是否导出预览。

3. 立方体顶面四角受压
   可填写：立方体尺寸、四角向下载荷大小、材料、网格尺寸。

4. 壳板受均布压力
   可填写：板长宽厚、压力大小、固定边界、材料、网格尺寸。

请选择一个场景，并补充你已经确定的数据；不确定的数据可以先留空，我会继续追问。
```

AI IDE 不应把这些选项描述成开放式任意建模能力。

## 对 AI IDE 的硬性要求

在用户明确要求修改代码之前，AI IDE 必须遵守：

- 不得修改 `lsprepost_mcp\` 下的源代码。
- 不得修改 `scripts\` 下的脚本。
- 不得修改 `resources\`、`tests\`。
- 不得删除、覆盖或重排项目文件。
- 不得直接创建、编辑、覆盖或拼接任何 `.k` / `.key` / `.dyn` keyword 文件。
- 允许读取项目文件、运行诊断脚本、生成配置文件。
- 允许写入 `var\generated_configs\`。
- 允许在用户要求生成模型时，通过本项目脚本或 Python 模块写入 `workspace\projects\`。
- 如果需要安装依赖、修改系统配置、写入 AI IDE 配置目录，必须先向用户确认。

本项目是一个 MCP Server。AI IDE 的任务不是改造项目，而是把它配置成可运行的本地工具。

## keyword 文件生成规则

AI IDE 必须遵守：

- `model.k` 必须由本项目生成流程产生，例如 `generate_model`、`generate_scene_from_prompt` 或本项目脚本。
- AI IDE 不得自己手写 LS-DYNA keyword。
- 如果需要修改模型，只能修改输入参数，然后重新运行本项目生成流程。
- 生成后必须运行校验，并向用户报告 `model.k`、`model.json`、`checks.json` 的路径。
- 如果用户要求确认 `model.k` 是否由本项目生成，必须运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<PROJECT_DIR>\scripts\verify_generated_k.ps1" -ProjectDir "<PROJECT_DIR>\workspace\projects\<PROJECT_NAME>"
```

只有该脚本返回 `ok: true` 且 `classification: generated_by_lsprepost_mcp` 时，才能声称该 `model.k` 是本项目按 `model.json` 重新生成一致的 keyword deck。

## LS-PrePost 预览导出失败处理

不同 LS-PrePost 版本的 cfile 命令和图片导出行为可能不同。

如果出现 PNG/GIF 自动导出失败：

- 不要直接判断模型生成失败。
- 先确认 `model.k`、`model.json`、`checks.json` 是否生成。
- 运行 `validate_model` 或相应脚本检查静态校验。
- 如果是 GIF 导出失败，先查看 `doctor.ps1` 的 `pillow_optional` 结果；Pillow 未安装时应提示用户 GIF 是可选能力。
- 如果静态校验通过，应提示用户自行打开 LS-PrePost 进行人工验证。
- 可以继续报告：自动预览导出失败可能与 LS-PrePost 版本差异有关。

## AI IDE 应执行的流程

### 1. 确认项目根目录

项目根目录应包含：

```text
README.zh-CN.md
scripts\doctor.ps1
scripts\setup.ps1
scripts\start_mcp_server.cmd
lsprepost_mcp\server.py
```

后续命令可以直接使用绝对路径，不需要用户手动 `cd` 到项目目录。

### 2. 获取 LS-PrePost 路径

如果用户没有提供 LS-PrePost 可执行文件路径，先询问用户。

路径应指向真实存在的 `lsprepost*.exe`，例如：

```text
<LS_PREPOST_INSTALL_DIR>\lsprepost4.12.exe
```

不要把文档中的占位符当作真实路径。

### 3. 运行诊断

把下面的 `<PROJECT_DIR>` 和 `<LS_PREPOST_EXE>` 替换为真实绝对路径后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<PROJECT_DIR>\scripts\doctor.ps1" -LsppExe "<LS_PREPOST_EXE>" -RequireLsPrePost
```

如果诊断失败，停止配置并把失败信息报告给用户。不要继续生成配置。

### 4. 生成 AI IDE MCP 配置

诊断通过后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<PROJECT_DIR>\scripts\setup.ps1" -LsppExe "<LS_PREPOST_EXE>"
```

生成结果位于：

```text
<PROJECT_DIR>\var\generated_configs\
```

常见输出：

- `codex.mcp.json`
- `cursor.mcp.json`
- `claude_desktop_config.fragment.json`
- `windsurf.mcp.json`
- `vscode.mcp.json`
- `visualstudio.mcp.json`

### 5. 指导用户接入 AI IDE

AI IDE 应告诉用户：

1. 打开 `var\generated_configs\`。
2. 选择与当前 IDE 对应的配置文件。
3. 按该 IDE 的 MCP 配置方式复制配置。
4. 重启或刷新 AI IDE 的 MCP 工具列表。

如果 AI IDE 有权限直接写入自己的项目级 MCP 配置，可以在用户确认后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<PROJECT_DIR>\scripts\install_to_cursor.ps1" -TargetDir "<TARGET_PROJECT_DIR>" -LsppExe "<LS_PREPOST_EXE>"
```

或：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<PROJECT_DIR>\scripts\install_to_vscode.ps1" -TargetDir "<TARGET_PROJECT_DIR>" -LsppExe "<LS_PREPOST_EXE>"
```

### 6. 接入后验证

AI IDE 刷新 MCP 后，应优先调用：

```text
server_info
```

确认 `lspp_doctor` 正常后，再生成一个小模型或使用用户指定工况。

## 用户可直接给 AI IDE 的一句话

```text
请先阅读本项目根目录的 AI_IDE_START_HERE.zh-CN.md。严格按里面的只读配置流程操作：不要修改项目源代码，不要修改 scripts/resources/tests；只允许运行诊断、生成 var/generated_configs，并在我确认后帮我接入 MCP。我的 LS-PrePost 路径是：<LS_PREPOST_EXE>。
```

如果用户暂时不知道 LS-PrePost 路径，AI IDE 应先帮助用户查找或询问，不要编造路径。
如果用户希望通过图形界面操作，可以启动 `scripts\start_web_app.ps1`。Web App 和 AI IDE 都必须复用本项目后端生成流程，不得直接手写 keyword。
