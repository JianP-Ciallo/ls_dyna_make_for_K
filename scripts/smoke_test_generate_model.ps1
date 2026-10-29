$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$ProjectPython = Resolve-ProjectPython -Root $root
$messages = Join-Path $root "examples\generate_model.jsonl"
$server = Join-Path $root "lsprepost_mcp\server.py"

Get-Content -LiteralPath $messages -Encoding UTF8 | & $ProjectPython -B -X utf8 $server
