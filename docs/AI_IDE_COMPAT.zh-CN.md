# AI IDE 兼容说明

本项目使用 MCP 的 `stdio` 传输方式：AI IDE 启动本项目作为子进程，通过 stdin/stdout 发送和接收 JSON-RPC 消息。不同 IDE 的配置文件名字和外层 JSON 字段略有差异，但底层启动方式相同。

## 推荐启动方式

Windows 上推荐让 IDE 启动这个脚本：

```text
scripts\start_mcp_server.cmd
```

这个脚本会自动定位项目根目录，再启动：

```text
lsprepost_mcp\server.py
```

这样项目解压到不同目录时，只需要改配置里的脚本路径，不需要改 Python 代码。

## 生成配置

在项目根目录运行：

```powershell
$env:LSPP_EXE = "<LSPP_EXE>"
python .\scripts\generate_mcp_configs.py --lspp-exe "$env:LSPP_EXE"
```

脚本会生成：

```text
generated_configs\cursor.mcp.json
generated_configs\claude_desktop_config.fragment.json
generated_configs\codex.mcp.json
generated_configs\windsurf.mcp.json
generated_configs\vscode.mcp.json
generated_configs\visualstudio.mcp.json
```

把对应文件内容复制到目标 IDE 的 MCP 配置里即可。

## 配置格式差异

Codex、Cursor、Claude Desktop、Windsurf 常见格式：

```json
{
  "mcpServers": {
    "lsprepost": {
      "command": "cmd",
      "args": [
        "/c",
        "<PROJECT_ROOT>\\scripts\\start_mcp_server.cmd"
      ],
      "env": {
        "LSPP_EXE": "<LSPP_EXE>"
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
        "<PROJECT_ROOT>\\scripts\\start_mcp_server.cmd"
      ],
      "env": {
        "LSPP_EXE": "<LSPP_EXE>"
      }
    }
  }
}
```

## 放置位置参考

- Cursor：项目级通常是 `.cursor\mcp.json`，全局通常是用户目录下的 `.cursor\mcp.json`。
- VS Code：项目级通常是 `.vscode\mcp.json`，外层字段使用 `servers`。
- Visual Studio：可读取解决方案目录 `.mcp.json`、`.vscode\mcp.json`、`.cursor\mcp.json` 等位置，外层字段使用 `servers`。
- Claude Desktop：把 `mcpServers` 片段合并到 Claude Desktop 的配置文件中。
- Windsurf：在插件或 MCP 管理界面打开 raw config 后，合并 `mcpServers` 配置。

不同版本 IDE 的入口菜单可能会变化；如果 UI 入口不同，优先找 MCP、Tools、Plugins、Agent Tools 或 raw config。

## 兼容性策略

Server 侧做了这些兼容处理：

- 使用标准 stdio JSON-RPC，stdout 只输出协议消息。
- 支持 `initialize`、`tools/list`、`tools/call`。
- 支持 `notifications/initialized`。
- 支持 `ping`。
- 支持 JSON-RPC batch 消息。
- 不依赖第三方 Python 包，降低不同机器安装失败的概率。

## 快速测试

先测试生成模型：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_generate_model.ps1
```

再测试目标 IDE 是否能发现这些工具：

```text
server_info
generate_model
validate_model
open_in_lsprepost
```

如果 IDE 能列出工具，就说明 MCP 连接成功；如果 `open_in_lsprepost` 失败，优先检查 `LSPP_EXE` 是否指向真实的 `lsprepost*.exe`。
