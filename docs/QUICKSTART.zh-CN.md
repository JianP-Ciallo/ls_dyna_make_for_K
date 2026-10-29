# 从 GitHub 安装与启动

本指南面向 Windows 10/11 64 位电脑上的源码使用者。仓库提供 Web 工作台、MCP 服务、受控模型模板和文档；LS-PrePost、LS-Run、LS-DYNA 及其许可证由使用者自行准备。

## 1. 获取源码

安装 Git for Windows，在 PowerShell 中运行：

```powershell
git clone https://github.com/JianP-Ciallo/ls_dyna_make_for_K.git
cd ls_dyna_make_for_K
```

仓库为私有，需要登录具有访问权限的 GitHub 账号。浏览器里能够访问仓库，不一定表示 Git 命令已完成登录；出现登录提示时，在 Git 打开的官方登录窗口中完成认证。不要把访问令牌写进源码、文档或仓库地址。

也可以在仓库页面点击 **Code → Download ZIP**，解压后打开包含 `README.md` 的项目根目录。

## 2. 准备 Python

主项目要求 Python 3.10 或更高版本；下面以 Python 3.12 为例。先安装对应版本，再在新克隆的项目根目录创建虚拟环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "numpy>=1.26,<3" Pillow
```

NumPy 用于固定建筑模板等功能，Pillow 用于 GIF 导出。后续始终使用同一个虚拟环境中的解释器，无需激活 PowerShell 脚本，也不会把依赖装入系统 Python。

正式工作台的静态界面与 Three.js 已放在 `lsprepost_mcp/web/static/`，直接运行无需安装 Node.js 或构建前端。

## 3. 启动 Web 工作台

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m lsprepost_mcp.web.app --open-browser
```

浏览器访问 <http://127.0.0.1:8765/>。保持启动窗口开启，按 `Ctrl+C` 停止服务。

若端口已被其他程序占用，改用另一个本机端口：

```powershell
.\.venv\Scripts\python.exe -m lsprepost_mcp.web.app --port 8766 --open-browser
```

在页面中选择本机的 LS-PrePost 可执行文件；需要求解交接时，再配置 LS-Run 与 LS-DYNA。文件选择和启动外部程序均发生在运行服务的本机。首次运行先查看页面和受控场景，不需要启动真实求解器。

如果 Python 和依赖已经安装在启动脚本可找到的环境中，也可以双击根目录的 `start_web_app.cmd`。源码虚拟环境未激活时，建议继续使用上面的显式解释器命令。

## 4. 按需安装可选能力

### 爆炸损伤评估

需要读取已保存的 LS-DYNA 结果并使用独立评估模块时，在相同环境中运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_damage_assessment.ps1 -PythonExe .\.venv\Scripts\python.exe
```

脚本安装并检查 `packages/blast_damage_assessment/`；该模块依赖固定版本的 `lasso-python` 等包。接口、证据来源及解释边界见[详细中文说明](../README.zh-CN.md#可选的爆炸损伤评估能力)。

### CPU 响应试算

这部分使用独立的 Windows Python/OpenSeesPy 环境。安装入口和已验证能力见[固定建筑 CPU 构件试算](../README.zh-CN.md#固定建筑-cpu-构件试算)。下载和环境验证由使用者显式执行，不属于启动工作台的必需步骤。依赖本机编译内核的扩展能力，还需要相应原生运行时；本仓库不携带开发电脑上的编译产物。

### AI IDE / MCP

按 [AI IDE 接入说明](../AI_IDE_START_HERE.zh-CN.md) 配置，使用当前项目实际所在的路径和相同 Python 环境。生成 keyword 文件应调用项目提供的受控工具。

## 5. 文件保存与更新

| 路径 | 保存内容 | 是否上传到 Git |
| --- | --- | --- |
| `lsprepost_mcp/`、`web/` | Python 与前端源码 | 是 |
| `packages/` | 独立损伤评估模块 | 是，构建产物除外 |
| `resources/` | 受控材料、模板与必要模型资产 | 是 |
| `docs/`、`examples/`、`tests/`、`scripts/` | 说明、示例、测试与维护脚本 | 是，本地输出除外 |
| `workspace/` | 本机项目与求解数据 | 否 |
| `var/` | 本机配置、缓存与运行记录 | 仅目录说明和占位文件 |
| `artifacts/`、`outputs/`、`output/` | 测试证据、浏览器缓存与计算输出 | 默认忽略新增产物；已纳管的验收资料保留 |
| `.venv/`、`runtime/`、`dist/` | 本机环境与发布包 | 否 |

本次 GitHub 上传采用当前源码快照，保留 GitHub 原有初始化提交；开发电脑上的历史 Git 提交、活动项目和大型运行产物不随快照上传。原工作目录与原 Git 历史保留在本机。

后续在从 GitHub 克隆的目录内维护代码：

```powershell
git status
git pull --ff-only
# 修改文件，并运行相关专项检查后：
git add <需要提交的文件>
git commit -m "docs: update project documentation"
git push
```

`git add <需要提交的文件>` 是占位示例，请替换为具体文件路径。本机计算结果应自行备份；忽略规则只控制 Git 上传，不会删除磁盘上的文件。历史设计和验收文档可能引用未随源码上传的本地结果目录，阅读时以对应说明的版本与证据范围为准。

## 6. 开发检查

安装测试工具：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
```

默认仅运行轻量 smoke：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

修改后另外选择相关测试文件；可先查看测试分组，不执行测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_test_matrix.ps1 -List
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_test_matrix.ps1 -Group packaging -DryRun
```

全量回归和真实重型案例都需要先说明范围、预计耗时，并取得用户当次明确同意。完整规则见 [AGENTS.md](../AGENTS.md) 和[按需测试与合并验收](../README.zh-CN.md#按需测试与合并验收)。

## 常见问题

- **`No module named numpy`**：确认安装依赖与启动服务使用的是同一个 `.venv\Scripts\python.exe`。
- **`No module named lsprepost_mcp`**：先切换到包含 `lsprepost_mcp/` 的项目根目录，再运行模块命令。
- **Git 提示没有权限或仓库不存在**：确认地址正确，且 Git 登录账号具有该私有仓库的访问权限。
- **页面能打开但外部工具不可用**：在页面配置当前电脑的程序路径；GitHub 不提供商业求解器或许可证。
- **静态检查通过但模型结果异常**：`checks.ok` 仅表示项目静态校验通过，仍需复核模型、实际求解状态和物理响应。
