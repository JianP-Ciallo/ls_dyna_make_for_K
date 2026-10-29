# Special Pages Rod Impact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a GitHub Pages-ready special version that statically demonstrates `rod_impact_plate` and offers a complete local package download.

**Architecture:** Add a self-contained `special_pages_rod_impact/` folder. `site/` contains static GitHub Pages files, `downloads/` contains the local package zip, and `README.zh-CN.md` explains publishing and local execution. A local PowerShell verification script checks that the static page, README, and download link remain coherent.

**Tech Stack:** Static HTML/CSS, PowerShell verification, existing `scripts/pack.ps1` package workflow.

---

## File Structure

- Create: `special_pages_rod_impact/README.zh-CN.md`
  - Documents the special version, GitHub Pages limits, local download flow, and publish instructions.
- Create: `special_pages_rod_impact/site/index.html`
  - Static Chinese landing page for `rod_impact_plate`.
- Create: `special_pages_rod_impact/site/styles.css`
  - Visual styling and responsive schematic for the landing page.
- Create: `special_pages_rod_impact/downloads/lsprepost-mcp-special-rod-impact.zip`
  - Complete local package for users who need backend, model generation, and LS-PrePost integration.
- Create: `special_pages_rod_impact/verify_special_pages.ps1`
  - Local verification script that fails if required files, copy, or download links are missing.

## Task 1: Verification Script First

**Files:**
- Create: `special_pages_rod_impact/verify_special_pages.ps1`

- [ ] **Step 1: Write the failing verification script**

Create `special_pages_rod_impact/verify_special_pages.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$SiteDir = Join-Path $Root "site"
$DownloadsDir = Join-Path $Root "downloads"
$IndexPath = Join-Path $SiteDir "index.html"
$StylesPath = Join-Path $SiteDir "styles.css"
$ReadmePath = Join-Path $Root "README.zh-CN.md"
$ZipName = "lsprepost-mcp-special-rod-impact.zip"
$ZipPath = Join-Path $DownloadsDir $ZipName

function Assert-FileExists {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing required file: $Path"
    }
}

Assert-FileExists $IndexPath
Assert-FileExists $StylesPath
Assert-FileExists $ReadmePath
Assert-FileExists $ZipPath

$index = Get-Content -LiteralPath $IndexPath -Raw -Encoding UTF8
$readme = Get-Content -LiteralPath $ReadmePath -Raw -Encoding UTF8

$requiredIndexText = @(
    "rod_impact_plate",
    "downloads/$ZipName",
    "GitHub Pages",
    "Python",
    "LS-PrePost",
    "start_web_app.cmd"
)

foreach ($text in $requiredIndexText) {
    if (-not $index.Contains($text)) {
        throw "index.html is missing required text: $text"
    }
}

$requiredReadmeText = @(
    "GitHub Pages",
    "不能运行 Python",
    "start_web_app.cmd",
    $ZipName
)

foreach ($text in $requiredReadmeText) {
    if (-not $readme.Contains($text)) {
        throw "README.zh-CN.md is missing required text: $text"
    }
}

if ($index -notmatch '<meta charset="utf-8"') {
    throw "index.html must declare UTF-8 charset."
}

$zip = Get-Item -LiteralPath $ZipPath
if ($zip.Length -le 0) {
    throw "Download zip is empty: $ZipPath"
}

Write-Output "Special Pages verification passed."
```

- [ ] **Step 2: Run verification to confirm RED**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\special_pages_rod_impact\verify_special_pages.ps1
```

Expected: FAIL with `Missing required file` because the static page and package have not been created yet.

## Task 2: Static GitHub Pages Site

**Files:**
- Create: `special_pages_rod_impact/site/index.html`
- Create: `special_pages_rod_impact/site/styles.css`

- [ ] **Step 1: Create `index.html`**

Create `special_pages_rod_impact/site/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LS-PrePost 圆柱杆冲击钢板演示</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="page-shell">
    <section class="hero" aria-labelledby="page-title">
      <div class="hero-copy">
        <p class="eyebrow">GitHub Pages 静态演示 · 场景 rod_impact_plate</p>
        <h1 id="page-title">LS-PrePost 圆柱杆冲击钢板演示</h1>
        <p class="lead">
          本页面展示一个受控 LS-DYNA 建模场景：实心圆柱杆以初速度冲击固定钢板。
          如果需要生成 keyword、运行 Python 后端、打开 LS-PrePost 或导出预览，请下载完整本地版。
        </p>
        <div class="actions">
          <a class="button primary" href="../downloads/lsprepost-mcp-special-rod-impact.zip">下载完整本地版</a>
          <a class="button secondary" href="#local-run">查看本地运行步骤</a>
        </div>
      </div>
      <div class="schematic" aria-label="圆柱杆冲击固定钢板示意图">
        <div class="velocity">v₀</div>
        <div class="rod"></div>
        <div class="impact-line"></div>
        <div class="plate"></div>
        <div class="fixture left"></div>
        <div class="fixture right"></div>
      </div>
    </section>

    <section class="band two-column">
      <div>
        <h2>网页端能展示什么</h2>
        <p>
          这里是可部署到 GitHub Pages 的静态展示页，用于说明场景、参数和工作流。
          它不依赖服务器，也不会尝试在浏览器中运行 Python。
        </p>
      </div>
      <div>
        <h2>完整功能在哪里运行</h2>
        <p>
          模型生成、MCP 工具、workspace 文件写入、LS-PrePost 启动和预览导出都在用户本机运行。
          下载包解压后使用 <code>start_web_app.cmd</code> 启动。
        </p>
      </div>
    </section>

    <section class="band">
      <h2>默认演示参数</h2>
      <div class="parameter-grid">
        <div><span>场景 ID</span><strong>rod_impact_plate</strong></div>
        <div><span>冲击体</span><strong>实心圆柱杆</strong></div>
        <div><span>目标件</span><strong>固定钢板</strong></div>
        <div><span>载荷</span><strong>初始速度冲击</strong></div>
        <div><span>材料</span><strong>受控材料库</strong></div>
        <div><span>输出</span><strong>model.k / checks.json / 预览</strong></div>
      </div>
    </section>

    <section class="band warning">
      <h2>GitHub Pages 功能边界</h2>
      <p>
        GitHub Pages 只能托管 HTML、CSS、JavaScript 和下载文件，不能运行 Python 后端，
        不能启动 MCP Server，不能写入你的本地项目目录，也不能调用本机 LS-PrePost。
      </p>
    </section>

    <section class="band" id="local-run">
      <h2>本地完整运行步骤</h2>
      <ol class="steps">
        <li>下载 <code>lsprepost-mcp-special-rod-impact.zip</code>。</li>
        <li>解压到本机普通目录，不要直接在压缩包内运行。</li>
        <li>双击 <code>start_web_app.cmd</code>。</li>
        <li>按页面提示设置本机 <code>lsprepost*.exe</code> 路径。</li>
        <li>在本地 Web App 中生成、校验并打开 LS-PrePost 预览。</li>
      </ol>
    </section>
  </main>
</body>
</html>
```

- [ ] **Step 2: Create `styles.css`**

Create `special_pages_rod_impact/site/styles.css`:

```css
:root {
  color-scheme: light;
  --ink: #142033;
  --muted: #5b6575;
  --line: #d7dde6;
  --panel: #ffffff;
  --page: #f4f7fb;
  --accent: #0d766e;
  --accent-dark: #084f49;
  --steel: #9aa6b2;
  --warning: #fff4d7;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: Arial, "Microsoft YaHei", sans-serif;
  color: var(--ink);
  background: var(--page);
}

.page-shell {
  width: min(1120px, calc(100% - 32px));
  margin: 0 auto;
  padding: 32px 0 48px;
}

.hero {
  min-height: 520px;
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(320px, 0.95fr);
  gap: 36px;
  align-items: center;
}

.eyebrow {
  margin: 0 0 14px;
  color: var(--accent-dark);
  font-weight: 700;
}

h1,
h2,
p {
  margin-top: 0;
}

h1 {
  margin-bottom: 18px;
  font-size: 44px;
  line-height: 1.12;
}

h2 {
  margin-bottom: 12px;
  font-size: 24px;
}

.lead {
  max-width: 680px;
  color: var(--muted);
  font-size: 18px;
  line-height: 1.7;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 28px;
}

.button {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  padding: 0 18px;
  border: 1px solid var(--accent);
  border-radius: 6px;
  text-decoration: none;
  font-weight: 700;
}

.button.primary {
  color: #ffffff;
  background: var(--accent);
}

.button.secondary {
  color: var(--accent-dark);
  background: transparent;
}

.schematic {
  position: relative;
  height: 360px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(255,255,255,0.95), rgba(230,236,243,0.92)),
    repeating-linear-gradient(90deg, transparent 0 23px, rgba(20,32,51,0.05) 24px);
  overflow: hidden;
}

.rod {
  position: absolute;
  left: 50%;
  top: 44px;
  width: 74px;
  height: 168px;
  transform: translateX(-50%);
  border-radius: 37px 37px 10px 10px;
  background: linear-gradient(90deg, #6f7d8c, #d8dde3 46%, #7d8997);
  border: 1px solid #6e7985;
}

.velocity {
  position: absolute;
  left: calc(50% + 56px);
  top: 88px;
  color: var(--accent-dark);
  font-weight: 800;
  font-size: 28px;
}

.impact-line {
  position: absolute;
  left: 50%;
  top: 222px;
  width: 2px;
  height: 44px;
  background: repeating-linear-gradient(180deg, var(--accent) 0 7px, transparent 7px 13px);
}

.plate {
  position: absolute;
  left: 16%;
  right: 16%;
  bottom: 72px;
  height: 42px;
  border-radius: 4px;
  background: linear-gradient(180deg, #c5cbd3, #7e8894);
  border: 1px solid #697481;
}

.fixture {
  position: absolute;
  bottom: 38px;
  width: 52px;
  height: 34px;
  background: repeating-linear-gradient(135deg, #66717d 0 8px, #a6afb9 8px 16px);
  border-radius: 4px;
}

.fixture.left {
  left: 18%;
}

.fixture.right {
  right: 18%;
}

.band {
  margin-top: 24px;
  padding: 26px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
}

.two-column {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 28px;
}

.parameter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.parameter-grid div {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #f8fafc;
}

.parameter-grid span {
  display: block;
  color: var(--muted);
  font-size: 13px;
  margin-bottom: 6px;
}

.parameter-grid strong {
  display: block;
  overflow-wrap: anywhere;
}

.warning {
  background: var(--warning);
}

.steps {
  margin: 0;
  padding-left: 22px;
  line-height: 1.9;
}

code {
  padding: 2px 5px;
  border-radius: 4px;
  background: #e8edf3;
  font-family: Consolas, "Courier New", monospace;
}

@media (max-width: 820px) {
  .hero,
  .two-column,
  .parameter-grid {
    grid-template-columns: 1fr;
  }

  h1 {
    font-size: 34px;
  }

  .schematic {
    height: 300px;
  }
}
```

- [ ] **Step 3: Run verification**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\special_pages_rod_impact\verify_special_pages.ps1
```

Expected: FAIL with `Missing required file` for the README or zip, proving the site files satisfy part of the verification but the package is still missing.

## Task 3: README and Local Package

**Files:**
- Create: `special_pages_rod_impact/README.zh-CN.md`
- Create: `special_pages_rod_impact/downloads/lsprepost-mcp-special-rod-impact.zip`

- [ ] **Step 1: Create README**

Create `special_pages_rod_impact/README.zh-CN.md`:

```markdown
# LS-PrePost 圆柱杆冲击钢板特供版

这个文件夹用于发布 GitHub Pages 静态演示页，并提供完整本地运行包下载。

## 页面内容

`site/` 是可以上传到 GitHub Pages 的静态站点。首页展示 `rod_impact_plate` 场景：实心圆柱杆以初始速度冲击固定钢板。

GitHub Pages 只能展示 HTML、CSS、JavaScript 和下载文件，不能运行 Python，不能启动 MCP Server，也不能调用本机 LS-PrePost。

## 完整功能

完整功能在下载包中运行：

```text
downloads/lsprepost-mcp-special-rod-impact.zip
```

用户下载并解压后，在 Windows 上双击：

```text
start_web_app.cmd
```

然后按页面提示设置本机 `lsprepost*.exe` 路径。模型生成、静态校验、workspace 文件写入、MCP 工具和 LS-PrePost 预览都在用户本机完成。

## 发布方式

把 `site/` 目录作为 GitHub Pages 的发布目录。为了让下载按钮可用，发布时需要同时保留相对路径：

```text
downloads/lsprepost-mcp-special-rod-impact.zip
```

如果 GitHub Pages 只允许选择一个发布目录，可以把 `site/index.html`、`site/styles.css` 和 `downloads/` 一起复制到实际 Pages 根目录，并把下载链接保持为 `downloads/lsprepost-mcp-special-rod-impact.zip`。

## 本地校验

在项目根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\special_pages_rod_impact\verify_special_pages.ps1
```

看到 `Special Pages verification passed.` 表示静态页、README 和下载包路径一致。
```

- [ ] **Step 2: Create package directory**

Run:

```powershell
New-Item -ItemType Directory -Path .\special_pages_rod_impact\downloads -Force
```

Expected: command succeeds and the directory exists.

- [ ] **Step 3: Generate or copy the local package**

Preferred command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pack.ps1 -BuildLabel "special-rod-impact" -Pure -OutputPath ".\special_pages_rod_impact\downloads\lsprepost-mcp-special-rod-impact.zip"
```

Expected: creates `special_pages_rod_impact/downloads/lsprepost-mcp-special-rod-impact.zip`.

If `pack.ps1` refuses to package because the new special folder introduces a nested zip or local path issue, use the latest existing package from `dist/` as the download artifact:

```powershell
Copy-Item -LiteralPath ".\dist\lsprepost-mcp_phase11.7-workflow-reliability_20260622T082254Z.zip" -Destination ".\special_pages_rod_impact\downloads\lsprepost-mcp-special-rod-impact.zip" -Force
```

Expected: the destination zip exists and has nonzero size.

- [ ] **Step 4: Run verification to confirm GREEN**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\special_pages_rod_impact\verify_special_pages.ps1
```

Expected: PASS with `Special Pages verification passed.`

## Task 4: Final Review

**Files:**
- Inspect: `special_pages_rod_impact/site/index.html`
- Inspect: `special_pages_rod_impact/site/styles.css`
- Inspect: `special_pages_rod_impact/README.zh-CN.md`
- Inspect: `special_pages_rod_impact/downloads/lsprepost-mcp-special-rod-impact.zip`

- [ ] **Step 1: Open the static HTML locally**

Run:

```powershell
Start-Process ".\special_pages_rod_impact\site\index.html"
```

Expected: browser opens the static page. If browser launch is unavailable, skip visual browser launch and inspect the file contents.

- [ ] **Step 2: Confirm no backend claim appears**

Run:

```powershell
Select-String -Path ".\special_pages_rod_impact\site\index.html",".\special_pages_rod_impact\README.zh-CN.md" -Pattern "直接运行 Python|Pages 可以运行|在线生成 keyword"
```

Expected: no matches.

- [ ] **Step 3: Check final git status**

Run:

```powershell
git status --short
```

Expected: new `special_pages_rod_impact/` files and plan file are visible. Existing unrelated repository changes may still be present and should not be reverted.
