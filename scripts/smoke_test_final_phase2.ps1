$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$messages = Join-Path $root "examples\final_phase2_models.jsonl"
$server = Join-Path $root "scripts\start_mcp_server.cmd"

Get-Content -LiteralPath $messages | cmd /c $server
