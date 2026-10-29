param(
    [string]$ProjectDir = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$ProjectPython = Resolve-ProjectPython -Root $Root.Path

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    throw "ProjectDir is required. Use -ProjectDir '<PROJECT_DIR_WITH_MODEL_K>'."
}

$resolvedProject = Resolve-Path -LiteralPath $ProjectDir

Push-Location $Root
try {
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHONPATH = $Root.Path
    $script = @"
import json
import sys
from pathlib import Path
from lsprepost_mcp.provenance import verify_generated_project

result = verify_generated_project(Path(sys.argv[1]))
print(json.dumps(result, ensure_ascii=False, indent=2))
sys.exit(0 if result.get("ok") else 2)
"@
    $tempScript = Join-Path $env:TEMP ("verify_generated_k_" + [guid]::NewGuid().ToString("N") + ".py")
    Set-Content -LiteralPath $tempScript -Value $script -Encoding UTF8
    try {
        & $ProjectPython -B -X utf8 $tempScript $resolvedProject.Path
        $exitCode = $LASTEXITCODE
    } finally {
        Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
    }
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    exit $exitCode
}
