param(
    [ValidateSet("default", "critical", "packaging", "assessment", "snapshots", "errors", "paths", "gui", "web", "web-e2e", "refined-api", "web-runtime", "full", "heavy", "all")]
    [string]$Group = "default",
    [switch]$List,
    [switch]$DryRun,
    [switch]$RunFull,
    [switch]$RunHeavy
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

$groups = [ordered]@{
    default = @{
        description = "Small smoke checks only; select additional tests relevant to the change before acceptance."
        command = @("python", "-m", "pytest", "tests/test_jsonrpc.py", "tests/test_phase10_error_inputs.py", "-q")
    }
    critical = @{
        description = "Critical regression tests for JSON-RPC, tools, provenance, phase 9 refactor, and packaging boundaries."
        command = @(
            "python", "-m", "pytest",
            "tests/test_jsonrpc.py",
            "tests/test_tools.py",
            "tests/test_generated_keyword_provenance.py",
            "tests/test_phase9_refactor.py",
            "tests/test_phase10_error_inputs.py",
            "tests/test_phase10_paths.py",
            "tests/test_packaging_and_integration_boundaries.py"
        )
    }
    packaging = @{
        description = "Distribution and installer boundary tests."
        command = @(
            "python", "-m", "pytest",
            "tests/test_packaging_and_integration_boundaries.py",
            "tests/test_phase8_distribution.py"
        )
    }
    assessment = @{
        description = "Standalone blast damage assessment package tests. Requires its optional dependencies."
        command = @(
            "python", "-m", "pytest", "packages/blast_damage_assessment/tests", "-q"
        )
    }
    snapshots = @{
        description = "Stable keyword snapshot hash tests for representative generated decks."
        command = @("python", "-m", "pytest", "tests/test_keyword_snapshots.py")
    }
    errors = @{
        description = "Focused invalid-input tests for schema, materials, contacts, and numeric guards."
        command = @("python", "-m", "pytest", "tests/test_phase10_error_inputs.py")
    }
    paths = @{
        description = "Path robustness tests for script entry points from directories with spaces and Unicode."
        command = @("python", "-m", "pytest", "tests/test_phase10_paths.py")
    }
    gui = @{
        description = "Real LS-PrePost GUI integration tests. Requires LSPP_INTEGRATION=1 and LSPP_EXE."
        command = @("python", "-m", "pytest", "tests/test_integration_lsprepost.py")
    }
    web = @{
        description = "Local Web App API, static UI, and startup tests."
        command = @(
            "python", "-m", "pytest",
            "tests/test_web_api.py",
            "tests/test_web_static.py",
            "tests/test_web_startup.py"
        )
    }
    "web-e2e" = @{
        description = "Real Chromium acceptance for the Phase 17 city scene editor. Does not launch external engineering applications."
        command = @(
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ".\scripts\test_phase17_web.ps1"
        )
    }
    "refined-api" = @{
        description = "Refined workbench API creation, persistence and recovery using small fixtures."
        command = @("python", "-m", "pytest", "tests/test_phase18f_api.py", "-q")
    }
    "web-runtime" = @{
        description = "Workbench state and validation runtime contracts; no real solver or heavy provider cases."
        command = @("python", "-m", "pytest", "tests/test_phase18f_state_contract.py", "tests/test_phase18f_validation_flow.py", "tests/test_web_static.py", "-q")
    }
    full = @{
        description = "Full main test suite; requires -RunFull after user approval. Heavy cases remain skipped without -RunHeavy."
        command = @("python", "-m", "pytest", "tests", "--run-full")
    }
    heavy = @{
        description = "Three heavy provider cases; requires -RunHeavy after user approval. Prefer selecting one affected case directly with pytest."
        command = @("python", "-m", "pytest", "tests/test_phase18f_web_e2e_contract.py", "-m", "heavy_provider_e2e", "--run-heavy")
    }
    all = @{
        description = "Full main test suite plus compileall; requires -RunFull after user approval."
        command = @("python", "-m", "pytest", "tests", "--run-full")
    }
}

if ($List) {
    foreach ($name in $groups.Keys) {
        Write-Output ("{0}: {1}" -f $name, $groups[$name].description)
    }
    exit 0
}

$requiresFull = $Group -in @("full", "all")
$requiresHeavy = ($Group -eq "heavy") -or ($requiresFull -and $RunHeavy)
$selected = $groups[$Group]
if ($requiresFull -and $RunHeavy) {
    $selected.command += "--run-heavy"
}

if ($DryRun) {
    [ordered]@{
        group = $Group
        command = $selected.command
        requires_full = $requiresFull
        requires_heavy = $requiresHeavy
        compileall_after_success = ($Group -eq "all")
    } | ConvertTo-Json -Depth 3
    exit 0
}
if ($requiresFull -and -not $RunFull) {
    Write-Error "Full regression is not a default merge gate. Obtain explicit user approval, then pass -RunFull."
    exit 2
}
if ($requiresHeavy -and -not $RunHeavy) {
    Write-Error "Heavy cases require explicit user approval, then -RunHeavy. Prefer only the affected case."
    exit 2
}

Set-Location $Root
$env:PYTHONDONTWRITEBYTECODE = "1"

if ($Group -eq "assessment") {
    $assessmentSource = Join-Path $Root "packages\blast_damage_assessment\src"
    if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
        $env:PYTHONPATH = $assessmentSource
    } else {
        $env:PYTHONPATH = "$assessmentSource$([IO.Path]::PathSeparator)$env:PYTHONPATH"
    }
}

Write-Output ("Running test matrix group: {0}" -f $Group)
Write-Output ($selected.description)
& $selected.command[0] $selected.command[1..($selected.command.Count - 1)]
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($Group -eq "all") {
    python -m compileall -q .\lsprepost_mcp
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
