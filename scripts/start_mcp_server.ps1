$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$ProjectPython = Resolve-ProjectPython -Root $root
$env:PYTHONDONTWRITEBYTECODE = "1"
& $ProjectPython -B -X utf8 (Join-Path $root "lsprepost_mcp\server.py")
exit $LASTEXITCODE
