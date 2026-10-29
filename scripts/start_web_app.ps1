param(
    [string]$LsppExe = $env:LSPP_EXE,
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$OpenBrowser,
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"
$RootPath = Resolve-Path (Join-Path $PSScriptRoot "..")
$Root = $RootPath.Path
. (Join-Path $PSScriptRoot 'python_runtime.ps1')
$ProjectPython = Resolve-ProjectPython -Root $Root
$UsingBundledPython = Test-Path -LiteralPath (Join-Path $Root 'runtime')

if ($LsppExe) {
    $env:LSPP_EXE = $LsppExe
}

$AppUrl = "http://${HostName}:$Port/"
$fingerprintCommand = "from lsprepost_mcp.tool_server import source_fingerprint; print(source_fingerprint())"
Push-Location $Root
try {
    $CurrentSourceFingerprint = (& $ProjectPython -B -X utf8 -c $fingerprintCommand)
} finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) {
    throw "Unable to calculate the current Web App source fingerprint."
}
$CurrentSourceFingerprint = ([string]$CurrentSourceFingerprint).Trim()
if (-not $CurrentSourceFingerprint) {
    throw "The current Web App source fingerprint is empty."
}

if ($Port -ge 1 -and $Port -le 65535 -and $HostName -in @("127.0.0.1", "localhost")) {
    try {
        $existing = Invoke-RestMethod `
            -UseBasicParsing `
            -Uri ($AppUrl + "api/server-info") `
            -TimeoutSec 2
        $existingRoot = ([System.IO.Path]::GetFullPath([string]$existing.result.workspace_root)).TrimEnd("\", "/")
        $currentRoot = ([System.IO.Path]::GetFullPath($Root)).TrimEnd("\", "/")
        $sameApp = (
            $existing.ok -eq $true -and
            $existing.result.name -eq "lsprepost-mcp" -and
            $existingRoot.Equals($currentRoot, [System.StringComparison]::OrdinalIgnoreCase)
        )
        if ($sameApp) {
            $existingFingerprint = [string]$existing.result.source_fingerprint
            $runtimeMatches = -not $UsingBundledPython
            if ($UsingBundledPython -and $existing.result.python_executable) {
                $existingPython = [IO.Path]::GetFullPath([string]$existing.result.python_executable)
                $runtimeMatches = $existingPython.Equals($ProjectPython, [StringComparison]::OrdinalIgnoreCase)
            }
            if ($existingFingerprint -eq $CurrentSourceFingerprint -and $runtimeMatches) {
                Write-Host "lsprepost-mcp Web App is already running: $AppUrl"
                if ($OpenBrowser) {
                    Start-Process $AppUrl
                }
                exit 0
            }

            $listener = Get-NetTCPConnection `
                -LocalPort $Port `
                -State Listen `
                -ErrorAction Stop |
                Where-Object { $_.LocalAddress -in @("127.0.0.1", "::1") } |
                Select-Object -First 1
            if (-not $listener) {
                throw "The stale Web App listener could not be identified."
            }
            $process = Get-CimInstance Win32_Process `
                -Filter "ProcessId=$($listener.OwningProcess)" `
                -ErrorAction Stop
            $expectedCommand = (
                $process.Name -like "python*.exe" -and
                [string]$process.CommandLine -match "(^|\s)-m\s+lsprepost_mcp\.web\.app(\s|$)"
            )
            if (-not $expectedCommand) {
                throw "Refusing to stop port $Port because its owner is not lsprepost_mcp.web.app."
            }

            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                Start-Sleep -Milliseconds 100
                $remaining = Get-NetTCPConnection `
                    -LocalPort $Port `
                    -State Listen `
                    -ErrorAction SilentlyContinue
                if (-not $remaining) {
                    break
                }
            }
            if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
                throw "The stale Web App did not release port $Port."
            }
            Write-Host "Stopped stale lsprepost-mcp Web App on port $Port."
        }
    } catch {
        if ($sameApp) {
            throw
        }
        # No healthy instance from this workspace is currently listening.
    }
}

if (-not $SkipDoctor) {
    $doctorArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $Root "scripts\doctor.ps1")
    )
    if ($LsppExe) {
        $doctorArgs += @("-LsppExe", $LsppExe)
    }

    & powershell @doctorArgs
    if ($LASTEXITCODE -ne 0) {
        throw "doctor.ps1 failed; Web App startup aborted."
    }
}

Push-Location $Root
try {
    $args = @(
        "-m",
        "lsprepost_mcp.web.app",
        "--host",
        $HostName,
        "--port",
        [string]$Port
    )
    if ($LsppExe) {
        $args += @("--lspp-exe", $LsppExe)
    }
    if ($OpenBrowser) {
        $args += "--open-browser"
    }

    & $ProjectPython -B -X utf8 @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
