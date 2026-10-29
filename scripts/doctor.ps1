param(
    [string]$LsppExe = $env:LSPP_EXE,
    [switch]$RequireLsPrePost,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$RootPath = Resolve-Path (Join-Path $PSScriptRoot "..")
$Root = $RootPath.Path
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$ProjectPython = Resolve-ProjectPython -Root $Root -AllowMissing
$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Message,
        [object]$Detail = $null
    )
    $checks.Add([ordered]@{
        name = $Name
        status = $Status
        message = $Message
        detail = $Detail
    }) | Out-Null
}

function Test-Command {
    param([string]$CommandName)
    if ($CommandName -eq 'python') { return $null -ne $ProjectPython }
    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    return $null -ne $cmd
}

if (Test-Command "python") {
    try {
        $pythonVersion = (& $ProjectPython -B -X utf8 --version 2>&1) -join "`n"
        Add-Check "python_available" "ok" $pythonVersion
    } catch {
        Add-Check "python_available" "error" "python exists but failed to run" $_.Exception.Message
    }
} else {
    Add-Check "python_available" "error" "python command not found"
}

if (Test-Command "python") {
    try {
        $assessmentOutput = (& $ProjectPython -B -X utf8 -c "import json; from blast_damage_assessment.api import capabilities; print(json.dumps(capabilities(), sort_keys=True))" 2>&1) -join "`n"
        if ($LASTEXITCODE -eq 0) {
            $assessment = $assessmentOutput | ConvertFrom-Json
            if ($assessment.dependencies.lasso_python -eq "2.0.4") {
                Add-Check "damage_assessment_optional" "ok" "optional damage assessment is available" $assessment
            } else {
                Add-Check "damage_assessment_optional" "warning" "damage assessment is installed but the accepted LASSO version is unavailable" $assessment
            }
        } else {
            Add-Check "damage_assessment_optional" "warning" "optional damage assessment is not installed; modeling remains available" $assessmentOutput
        }
    } catch {
        Add-Check "damage_assessment_optional" "warning" "optional damage assessment capability check failed; modeling remains available" $_.Exception.Message
    }
} else {
    Add-Check "damage_assessment_optional" "warning" "python command not found; optional damage assessment was not checked"
}

$requiredFiles = @(
    "lsprepost_mcp\server.py",
    "lsprepost_mcp\tools.py",
    "lsprepost_mcp\web\app.py",
    "lsprepost_mcp\web\static\index.html",
    "start_web_app.cmd",
    "scripts\start_mcp_server.cmd",
    "scripts\start_web_app.ps1",
    "scripts\generate_mcp_configs.py"
)
$missingRequired = @()
foreach ($relative in $requiredFiles) {
    if (-not (Test-Path (Join-Path $Root $relative))) {
        $missingRequired += $relative
    }
}
if ($missingRequired.Count -eq 0) {
    Add-Check "required_files" "ok" "required project files are present"
} else {
    Add-Check "required_files" "error" "required project files are missing" $missingRequired
}

$webFiles = @(
    "lsprepost_mcp\web\app.py",
    "lsprepost_mcp\web\http_utils.py",
    "lsprepost_mcp\web\scenes.py",
    "lsprepost_mcp\web\static\index.html",
    "lsprepost_mcp\web\static\app.js",
    "lsprepost_mcp\web\static\styles.css",
    "start_web_app.cmd",
    "scripts\start_web_app.ps1"
)
$missingWebFiles = @()
foreach ($relative in $webFiles) {
    if (-not (Test-Path (Join-Path $Root $relative))) {
        $missingWebFiles += $relative
    }
}
if ($missingWebFiles.Count -eq 0) {
    Add-Check "web_app_files" "ok" "local Web App files are present" $webFiles
} else {
    Add-Check "web_app_files" "error" "local Web App files are missing" $missingWebFiles
}

if (Test-Command "node") {
    try {
        $nodeVersion = (& node --version 2>&1) -join "`n"
        Add-Check "node_optional" "ok" "Node.js is available for optional React/Vite builds" $nodeVersion.Trim()
    } catch {
        Add-Check "node_optional" "warning" "node exists but failed to run; fallback Web UI remains available" $_.Exception.Message
    }
} else {
    Add-Check "node_optional" "warning" "Node.js not found; fallback Web UI remains available"
}

$templates = @(
    "resources\templates\cfile\open_keyword.cfile",
    "resources\templates\cfile\preview_image.cfile"
)
$missingTemplates = @()
foreach ($relative in $templates) {
    if (-not (Test-Path (Join-Path $Root $relative))) {
        $missingTemplates += $relative
    }
}
if ($missingTemplates.Count -eq 0) {
    Add-Check "templates_present" "ok" "cfile templates are present"
} else {
    Add-Check "templates_present" "error" "cfile templates are missing" $missingTemplates
}

$materialsDir = Join-Path $Root "resources\materials"
$materialFiles = @()
if (Test-Path $materialsDir) {
    $materialFiles = @(Get-ChildItem -Path $materialsDir -Filter "*.json" -File -Recurse)
}
if ($materialFiles.Count -gt 0) {
    Add-Check "materials_present" "ok" "material library files are present" ($materialFiles | Select-Object -ExpandProperty Name)
} else {
    Add-Check "materials_present" "error" "no material library JSON files found"
}

try {
    Push-Location $Root
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $importOutput = (& $ProjectPython -B -X utf8 -c "import lsprepost_mcp.server; print('ok')" 2>&1) -join "`n"
    if ($LASTEXITCODE -eq 0 -and $importOutput.Trim().EndsWith("ok")) {
        Add-Check "server_importable" "ok" "lsprepost_mcp.server imports successfully"
    } else {
        Add-Check "server_importable" "error" "server import failed" $importOutput
    }
} catch {
    Add-Check "server_importable" "error" "server import failed" $_.Exception.Message
} finally {
    Pop-Location
}

if (Test-Command "python") {
    try {
        $pillowOutput = (& $ProjectPython -B -X utf8 -c "import PIL; print(PIL.__version__)" 2>&1) -join "`n"
        if ($LASTEXITCODE -eq 0) {
            Add-Check "pillow_optional" "ok" "Pillow is available for export_preview_gif" $pillowOutput.Trim()
        } else {
            Add-Check "pillow_optional" "warning" "Pillow is not installed; PNG preview works, GIF export_preview_gif will be unavailable until Pillow is installed" $pillowOutput
        }
    } catch {
        Add-Check "pillow_optional" "warning" "Pillow check failed; GIF export_preview_gif may be unavailable" $_.Exception.Message
    }
} else {
    Add-Check "pillow_optional" "warning" "python command not found; could not check optional Pillow dependency"
}

if ([string]::IsNullOrWhiteSpace($LsppExe)) {
    if ($RequireLsPrePost) {
        Add-Check "lsprepost_exe" "error" "LSPP_EXE is required but was not provided"
    } else {
        Add-Check "lsprepost_exe" "warning" "LSPP_EXE not set; GUI automation will be unavailable until configured"
    }
} else {
    $leaf = Split-Path -Leaf $LsppExe
    if ((Test-Path -LiteralPath $LsppExe -PathType Leaf) -and ($leaf -like "lsprepost*.exe")) {
        Add-Check "lsprepost_exe" "ok" "LS-PrePost executable exists" $LsppExe
    } else {
        $status = "warning"
        if ($RequireLsPrePost) {
            $status = "error"
        }
        Add-Check "lsprepost_exe" $status "LS-PrePost executable was not found or does not look like lsprepost*.exe" $LsppExe
    }
}

$errors = @($checks | Where-Object { $_.status -eq "error" })
$warnings = @($checks | Where-Object { $_.status -eq "warning" })
$payload = [ordered]@{
    ok = ($errors.Count -eq 0)
    root = $Root
    checks = @($checks.ToArray())
    error_count = $errors.Count
    warning_count = $warnings.Count
}

if ($Json) {
    $payload | ConvertTo-Json -Depth 8
} else {
    Write-Output "lsprepost-mcp doctor"
    Write-Output "Root: $Root"
    foreach ($check in $checks) {
        Write-Output ("[{0}] {1}: {2}" -f $check.status.ToUpperInvariant(), $check.name, $check.message)
    }
    Write-Output ("Errors: {0}; Warnings: {1}" -f $errors.Count, $warnings.Count)
}

if ($errors.Count -gt 0) {
    exit 1
}
exit 0
