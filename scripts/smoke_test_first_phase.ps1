$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$messages = Join-Path $root "examples\first_phase_tools.jsonl"
$server = Join-Path $root "scripts\start_mcp_server.cmd"

Get-Content -LiteralPath $messages | cmd /c $server
