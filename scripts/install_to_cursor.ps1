param(
    [string]$TargetDir = ".",
    [string]$LsppExe = "",
    [switch]$Force,
    [switch]$SkipLsppValidation
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TargetRoot = (Resolve-Path $TargetDir -ErrorAction SilentlyContinue)
if ($null -eq $TargetRoot) {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    $TargetRoot = Resolve-Path $TargetDir
}
$TargetRoot = $TargetRoot.Path

if ([string]::IsNullOrWhiteSpace($LsppExe)) {
    $LsppExe = $env:LSPP_EXE
}
if ([string]::IsNullOrWhiteSpace($LsppExe)) {
    throw "LsppExe is required. Use -LsppExe '<LS_PREPOST_EXE>' or set LSPP_EXE."
}

if (-not $SkipLsppValidation -and ($LsppExe -notlike "*<LS_PREPOST_EXE>*")) {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "doctor.ps1") -LsppExe $LsppExe -RequireLsPrePost | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "doctor.ps1 failed; refusing to install Cursor MCP config."
    }
}

$configDir = Join-Path $TargetRoot ".cursor"
$configPath = Join-Path $configDir "mcp.json"
if ((Test-Path -LiteralPath $configPath) -and (-not $Force)) {
    throw "Target config already exists: $configPath. Re-run with -Force to overwrite."
}

New-Item -ItemType Directory -Path $configDir -Force | Out-Null
$payload = [ordered]@{
    mcpServers = [ordered]@{
        lsprepost = [ordered]@{
            command = "cmd"
            args = @("/c", (Join-Path $Root "scripts\start_mcp_server.cmd"))
            env = [ordered]@{
                LSPP_EXE = $LsppExe
            }
        }
    }
}
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configPath -Encoding UTF8
Write-Output "Installed Cursor MCP config: $configPath"
