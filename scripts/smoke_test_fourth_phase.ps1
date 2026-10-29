$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$messages = Join-Path $root "examples\fourth_phase_loads.jsonl"
$server = Join-Path $root "scripts\start_mcp_server.cmd"

Get-Content -LiteralPath $messages | cmd /c $server
