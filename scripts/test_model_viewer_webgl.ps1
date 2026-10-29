param(
    [string]$NodeExe = "",
    [string]$NodeModules = "",
    [string]$BrowserExe = "",
    [string]$ProjectName = "web_phase17_city_ground_crater_validation_v5_v2"
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
    $env:MODEL_VIEWER_BROWSER_EXE = $BrowserExe
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    0
)
$listener.Start()
$port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
$listener.Stop()

$evidenceDir = Join-Path $Root "workspace\ui_evidence\model-viewer-webgl"
New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
$server = $null
$stdoutTask = $null
$stderrTask = $null
$previousBaseUrl = $env:MODEL_VIEWER_BASE_URL
$previousProject = $env:MODEL_VIEWER_PROJECT
$previousEvidence = $env:MODEL_VIEWER_EVIDENCE_DIR

try {
    $pythonCommand = Get-Command python -ErrorAction Stop
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
        throw "WebGL viewer test server could not be started."
    }
    $stdoutTask = $server.StandardOutput.ReadToEndAsync()
    $stderrTask = $server.StandardError.ReadToEndAsync()

    $baseUrl = "http://127.0.0.1:$port/"
    $deadline = (Get-Date).AddSeconds(30)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($server.HasExited) {
            throw "WebGL viewer test server exited before becoming ready."
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
        throw "WebGL viewer test server did not become ready within 30 seconds."
    }

    $env:MODEL_VIEWER_BASE_URL = $baseUrl
    $env:MODEL_VIEWER_PROJECT = $ProjectName
    $env:MODEL_VIEWER_EVIDENCE_DIR = $evidenceDir
    & $NodeExe (Join-Path $Root "web\tests\model-viewer-webgl.e2e.cjs")
    if ($LASTEXITCODE -ne 0) {
        throw "WebGL viewer browser test failed with exit code $LASTEXITCODE."
    }
} finally {
    if ($server -and -not $server.HasExited) {
        $server.Kill()
        $server.WaitForExit()
    }
    if ($stdoutTask) {
        [System.IO.File]::WriteAllText(
            (Join-Path $evidenceDir "server-stdout.log"),
            $stdoutTask.Result
        )
    }
    if ($stderrTask) {
        [System.IO.File]::WriteAllText(
            (Join-Path $evidenceDir "server-stderr.log"),
            $stderrTask.Result
        )
    }
    if ($server) {
        $server.Dispose()
    }
    $env:MODEL_VIEWER_BASE_URL = $previousBaseUrl
    $env:MODEL_VIEWER_PROJECT = $previousProject
    $env:MODEL_VIEWER_EVIDENCE_DIR = $previousEvidence
}
