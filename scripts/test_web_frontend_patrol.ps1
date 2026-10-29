param(
    [string]$NodeExe = "",
    [string]$NodeModules = "",
    [string]$BrowserExe = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $NodeExe) {
    $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
    if ($nodeCommand) {
        $NodeExe = $nodeCommand.Source
    }
}
if (-not $NodeExe -or -not (Test-Path -LiteralPath $NodeExe -PathType Leaf)) {
    throw "Node.js was not found. Pass -NodeExe."
}
if ($NodeModules) {
    if (-not (Test-Path -LiteralPath $NodeModules -PathType Container)) {
        throw "NodeModules does not exist: $NodeModules"
    }
    $env:NODE_PATH = $NodeModules
}
if ($BrowserExe) {
    if (-not (Test-Path -LiteralPath $BrowserExe -PathType Leaf)) {
        throw "BrowserExe does not exist: $BrowserExe"
    }
    $env:UI_PATROL_BROWSER_EXE = $BrowserExe
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    0
)
$listener.Start()
$port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
$listener.Stop()

$prefix = "ui_patrol_{0}" -f ([Guid]::NewGuid().ToString("N").Substring(0, 10))
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) $prefix
$evidenceDir = Join-Path $tempRoot "evidence"
$logDir = Join-Path $tempRoot "server"
New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$pythonCommand = Get-Command python -ErrorAction Stop
$server = $null
$stdoutTask = $null
$stderrTask = $null
$reportText = ""
$previousDisableExport = $env:LSPP_WEB_DISABLE_USER_EXPORT
$previousBaseUrl = $env:UI_PATROL_BASE_URL
$previousEvidenceDir = $env:UI_PATROL_EVIDENCE_DIR
$previousPrefix = $env:UI_PATROL_PROJECT_PREFIX

try {
    $env:LSPP_WEB_DISABLE_USER_EXPORT = "1"
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $pythonCommand.Source
    $startInfo.Arguments = "-m lsprepost_mcp.web.app --host 127.0.0.1 --port $port"
    $startInfo.WorkingDirectory = $Root
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $server = [System.Diagnostics.Process]::new()
    $server.StartInfo = $startInfo
    if (-not $server.Start()) {
        throw "Frontend patrol Web server could not be started."
    }
    $stdoutTask = $server.StandardOutput.ReadToEndAsync()
    $stderrTask = $server.StandardError.ReadToEndAsync()

    $baseUrl = "http://127.0.0.1:$port/"
    $deadline = (Get-Date).AddSeconds(30)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($server.HasExited) {
            throw "Frontend patrol Web server exited before becoming ready."
        }
        try {
            $response = Invoke-WebRequest -Uri $baseUrl -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ready) {
        throw "Frontend patrol Web server did not become ready within 30 seconds."
    }

    $env:UI_PATROL_BASE_URL = $baseUrl
    $env:UI_PATROL_EVIDENCE_DIR = $evidenceDir
    $env:UI_PATROL_PROJECT_PREFIX = $prefix
    & $NodeExe (Join-Path $Root "web\tests\frontend-patrol.e2e.cjs")
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend browser patrol failed with exit code $LASTEXITCODE."
    }
    $reportPath = Join-Path $evidenceDir "frontend-patrol.json"
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        throw "Frontend patrol report was not produced."
    }
    $reportText = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8
} finally {
    if ($server -and -not $server.HasExited) {
        $server.Kill()
        $server.WaitForExit()
    }
    if ($stdoutTask) {
        [System.IO.File]::WriteAllText(
            (Join-Path $logDir "stdout.log"),
            $stdoutTask.Result
        )
    }
    if ($stderrTask) {
        [System.IO.File]::WriteAllText(
            (Join-Path $logDir "stderr.log"),
            $stderrTask.Result
        )
    }
    if ($server) {
        $server.Dispose()
    }

    $projectRoot = [System.IO.Path]::GetFullPath((Join-Path $Root "workspace\projects"))
    if (Test-Path -LiteralPath $projectRoot -PathType Container) {
        Get-ChildItem -LiteralPath $projectRoot -Directory |
            Where-Object { $_.Name.StartsWith($prefix, [System.StringComparison]::Ordinal) } |
            ForEach-Object {
                $candidate = [System.IO.Path]::GetFullPath($_.FullName)
                if ([System.IO.Path]::GetDirectoryName($candidate) -ne $projectRoot) {
                    throw "Refusing to clean unexpected project path: $candidate"
                }
                Remove-Item -LiteralPath $candidate -Recurse -Force
            }
    }
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot)
        $systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if (-not $resolvedTemp.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean patrol directory outside the system temp root."
        }
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }

    $env:LSPP_WEB_DISABLE_USER_EXPORT = $previousDisableExport
    $env:UI_PATROL_BASE_URL = $previousBaseUrl
    $env:UI_PATROL_EVIDENCE_DIR = $previousEvidenceDir
    $env:UI_PATROL_PROJECT_PREFIX = $previousPrefix
}

if ($reportText) {
    Write-Output $reportText
}
