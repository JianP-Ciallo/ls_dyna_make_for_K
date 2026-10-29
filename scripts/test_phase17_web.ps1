param(
    [string]$NodeExe = "",
    [string]$NodeModules = "",
    [string]$BrowserExe = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

if (-not $NodeExe) {
    $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
    if ($nodeCommand) {
        $NodeExe = $nodeCommand.Source
    }
}
if (-not $NodeExe -or -not (Test-Path -LiteralPath $NodeExe -PathType Leaf)) {
    throw "Node.js was not found. Pass -NodeExe or install the Web development dependencies."
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
    $env:PHASE17_BROWSER_EXE = $BrowserExe
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $Root "workspace\phase17_web_e2e"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    0
)
$listener.Start()
$port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
$listener.Stop()

$pythonCommand = Get-Command python -ErrorAction Stop
$logDir = Join-Path $OutputDir "server"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stdoutPath = Join-Path $logDir "stdout.log"
$stderrPath = Join-Path $logDir "stderr.log"
$server = $null
$stdoutTask = $null
$stderrTask = $null

try {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $pythonCommand.Source
    $startInfo.Arguments = (
        "-m lsprepost_mcp.web.app --host 127.0.0.1 --port {0}" -f $port
    )
    $startInfo.WorkingDirectory = $Root.Path
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $server = [System.Diagnostics.Process]::new()
    $server.StartInfo = $startInfo
    if (-not $server.Start()) {
        throw "Phase 17 Web server process could not be started."
    }
    $stdoutTask = $server.StandardOutput.ReadToEndAsync()
    $stderrTask = $server.StandardError.ReadToEndAsync()

    $baseUrl = "http://127.0.0.1:$port/"
    $deadline = (Get-Date).AddSeconds(30)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($server.HasExited) {
            throw "Phase 17 Web server exited before becoming ready."
        }
        try {
            $response = Invoke-WebRequest `
                -Uri $baseUrl `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ready) {
        throw "Phase 17 Web server did not become ready within 30 seconds."
    }

    $env:PHASE17_BASE_URL = $baseUrl
    $env:PHASE17_EVIDENCE_DIR = $OutputDir
    & $NodeExe (Join-Path $Root "web\tests\phase17-editor.e2e.cjs")
    if ($LASTEXITCODE -ne 0) {
        throw "Phase 17 browser acceptance failed with exit code $LASTEXITCODE."
    }
} finally {
    if ($server -and -not $server.HasExited) {
        $server.Kill()
        $server.WaitForExit()
    }
    if ($stdoutTask) {
        [System.IO.File]::WriteAllText($stdoutPath, $stdoutTask.Result)
    }
    if ($stderrTask) {
        [System.IO.File]::WriteAllText($stderrPath, $stderrTask.Result)
    }
    if ($server) {
        $server.Dispose()
    }
}
