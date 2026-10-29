param(
    [string]$OutputPath = "",
    [string]$BuildLabel = "",
    [switch]$LatestCopy,
    [switch]$Pure,
    [string]$PortableRuntimeDir = ""
)

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [System.IO.File]::Open(
            $LiteralPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
        $hashBytes = $sha256.ComputeHash($stream)
        return (-join ($hashBytes | ForEach-Object { $_.ToString("X2") }))
    } finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        $sha256.Dispose()
    }
}

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Dist = Join-Path $Root "dist"
$RuntimeSource = $null
if ($PortableRuntimeDir) {
    $RuntimeManifest = Join-Path $PortableRuntimeDir 'runtime-manifest.json'
    if (-not (Test-Path -LiteralPath $RuntimeManifest -PathType Leaf)) {
        throw 'Prepared runtime-manifest.json is required for a portable package.'
    }
    $RuntimeManifest = (Resolve-Path -LiteralPath $RuntimeManifest).ProviderPath
    $RuntimeSource = (Resolve-Path -LiteralPath $PortableRuntimeDir).ProviderPath
    $runtimeFiles = @((Get-Item -LiteralPath $RuntimeSource -Force); Get-ChildItem -LiteralPath $RuntimeSource -Recurse -Force)
    if (@($runtimeFiles | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw 'Linked portable runtime entries are not supported.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RuntimeSource 'python/python.exe') -PathType Leaf)) {
        throw 'Prepared runtime/python/python.exe is missing.'
    }
    $runtimeManifestData = Get-Content -LiteralPath $RuntimeManifest -Raw | ConvertFrom-Json
    if ($runtimeManifestData.schema_version -ne 'portable.runtime@1' -or $runtimeManifestData.platform -ne 'win_amd64' -or
        @($runtimeManifestData.files.PSObject.Properties).Count -lt 3) {
        throw 'Invalid prepared runtime-manifest.json.'
    }
    $runtimeActualNames = @($runtimeFiles | Where-Object { -not $_.PSIsContainer -and $_.FullName -ne $RuntimeManifest } |
        ForEach-Object { $_.FullName.Substring($RuntimeSource.Length+1).Replace('\','/') })
    $runtimeExpectedNames = @($runtimeManifestData.files.PSObject.Properties.Name)
    if (@(Compare-Object $runtimeActualNames $runtimeExpectedNames).Count) { throw 'Portable runtime manifest member mismatch.' }
    foreach ($runtimeMember in $runtimeManifestData.files.PSObject.Properties) {
        $runtimePath = [IO.Path]::GetFullPath((Join-Path $RuntimeSource $runtimeMember.Name))
        if (-not $runtimePath.StartsWith($RuntimeSource+'\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Portable runtime manifest path escapes its root.'
        }
        if ((Get-Sha256Hex -LiteralPath $runtimePath).ToLowerInvariant() -ne $runtimeMember.Value) {
            throw "Portable runtime checksum mismatch: $($runtimeMember.Name)"
        }
    }
}
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ")
$SafeLabel = ""
if ($BuildLabel) {
    $SafeLabel = ($BuildLabel -replace "[^A-Za-z0-9_.-]", "-").Trim("-")
}
if (-not $SafeLabel) {
    throw "BuildLabel is required. Use a phase/optimization label such as -BuildLabel phase6-preview-export."
}
$PackageBaseName = "lsprepost-mcp_${SafeLabel}_$Timestamp"
$StageRoot = Join-Path $Dist ".pack"
$Stage = Join-Path $StageRoot $PackageBaseName
$stageBoundary = [IO.Path]::GetFullPath($StageRoot).TrimEnd('\') + '\'
if (-not [IO.Path]::GetFullPath($Stage).StartsWith($stageBoundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Package staging path escapes the package workspace.'
}

if (-not $OutputPath) {
    $OutputPath = Join-Path $Dist "$PackageBaseName.zip"
}
$OutputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)

New-Item -ItemType Directory -Path $Dist -Force | Out-Null
New-Item -ItemType Directory -Path $StageRoot -Force | Out-Null
if (Test-Path $Stage) {
    throw "Refusing to reuse existing package staging directory: $Stage"
}
New-Item -ItemType Directory -Path $Stage | Out-Null

$includedDirs = @(
    "docs",
    "examples",
    "lsprepost_mcp",
    "packages",
    "resources",
    "scripts",
    "tests",
    "web"
)
$includedFiles = @(
    ".gitignore",
    "AGENTS.md",
    "pytest.ini",
    "conftest.py",
    "AI_IDE_START_HERE.zh-CN.md",
    "README.md",
    "README.zh-CN.md",
    "start_web_app.cmd"
)
$excludedFilePatterns = @(
    "*.pyc",
    "lspost.cfile",
    "lspost.msg"
)
$textExtensions = @(
    ".cfile", ".cfg", ".cmd", ".css", ".html", ".ini", ".js", ".json",
    ".jsonl", ".jsx", ".md", ".ps1", ".py", ".sh", ".toml", ".txt",
    ".xml", ".yaml", ".yml"
)

try {
    if ($RuntimeSource) {
        Copy-Item -LiteralPath $RuntimeSource -Destination (Join-Path $Stage 'runtime') -Recurse -Force
    }
    foreach ($name in $includedDirs) {
        $source = Join-Path $Root $name
        if (Test-Path -LiteralPath $source -PathType Container) {
            $destination = Join-Path $Stage $name
            if ($name -eq "web") {
                New-Item -ItemType Directory -Path $destination -Force | Out-Null
                Get-ChildItem -LiteralPath $source -Force | Where-Object {
                    $_.Name -notin @("node_modules", "dist")
                } | ForEach-Object {
                    Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force
                }
            } else {
                Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
            }
        }
    }

    foreach ($name in $includedFiles) {
        $source = Join-Path $Root $name
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination $Stage -Force
        }
    }

    Get-ChildItem -Path $Stage -Recurse -Force -Directory | Where-Object {
        $_.Name -in @("__pycache__", ".pytest_cache", ".venv", "venv", "var") -or
        ($_.Name -in @("build", "dist") -and
            $_.FullName.StartsWith((Join-Path $Stage "packages") + [IO.Path]::DirectorySeparatorChar)) -or
        $_.Name -like "*.egg-info"
    } | Remove-Item -Recurse -Force
    Get-ChildItem -Path $Stage -Recurse -Force -File -Include $excludedFilePatterns | Remove-Item -Force

    $docsDir = Join-Path $Stage "docs"
    if (Test-Path $docsDir) {
        Get-ChildItem -LiteralPath $docsDir -Recurse -File -Filter "*.docx" | Remove-Item -Force
        Get-ChildItem -LiteralPath $docsDir -Recurse -Directory | Where-Object {
            $_.Name -in @(
                "patent_figures",
                "patent_figures_v2",
                "qa_fig6_render",
                "rendered_word_qa",
                "internal",
                "superpowers"
            )
        } | Sort-Object FullName -Descending | Remove-Item -Recurse -Force
    }

    if ($Pure) {
        if (Test-Path $docsDir) {
            Get-ChildItem -LiteralPath $docsDir -Directory | Remove-Item -Recurse -Force
        }
        $examplesDir = Join-Path $Stage "examples"
        if (Test-Path $examplesDir) {
            Get-ChildItem -LiteralPath $examplesDir -Directory | Where-Object {
                $_.Name -like "phase*"
            } | Remove-Item -Recurse -Force
        }
    }

    $forbidden = Get-ChildItem -Path $Stage -Recurse -Force | Where-Object {
        $_.Name -eq "__pycache__" -or
        $_.Name -like "*.pyc" -or
        $_.Name -eq "lspost.cfile" -or
        $_.Name -eq "lspost.msg" -or
        $_.Name -eq "node_modules" -or
        $_.FullName -like "*\workspace\*" -or
        $_.FullName -like "*\projects\*"
    }
    if ($forbidden) {
        $forbidden | Select-Object -ExpandProperty FullName
        throw "Package contains forbidden runtime artifacts."
    }

    $localPathHits = Get-ChildItem -Path $Stage -Recurse -Force -File | Where-Object {
        (-not $_.FullName.StartsWith((Join-Path $Stage 'runtime')+'\', [StringComparison]::OrdinalIgnoreCase)) -and
        ($_.Extension.ToLowerInvariant() -in $textExtensions -or $_.Name -eq ".gitignore") -and
        $_.FullName -ne (Join-Path $Stage 'scripts/pack.ps1')
    } | Select-String -Pattern '[A-Za-z]:\\|workplace' -List
    if ($localPathHits) {
        $localPathHits | ForEach-Object { "$($_.Path):$($_.LineNumber): $($_.Line.Trim())" }
        throw "Package contains local absolute path examples. Replace them with placeholders before distribution."
    }

    $manifestPath = Join-Path $Stage "PACKAGE_MANIFEST.txt"
    $manifestLines = New-Object System.Collections.Generic.List[string]
    foreach ($manifestHeaderLine in @(
        "lsprepost-mcp package manifest",
        "PackageName=$([System.IO.Path]::GetFileName($OutputPath))",
        "BuildLabel=$BuildLabel",
        "GeneratedAtUtc=$((Get-Date).ToUniversalTime().ToString('o'))",
        "ImmutablePackage=true",
        "PurePackage=$([bool]$Pure)",
        "PortablePackage=$([bool]$RuntimeSource)",
        ""
    )) { $manifestLines.Add($manifestHeaderLine) }
    $files = Get-ChildItem -Path $Stage -Recurse -Force -File | Sort-Object FullName
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($Stage.Length).TrimStart("\", "/").Replace("\", "/")
        $hash = Get-Sha256Hex -LiteralPath $file.FullName
        $manifestLines.Add("$hash  $relative")
    }
    $manifestLines | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    if (Test-Path $OutputPath) {
        throw "Refusing to overwrite existing package: $OutputPath"
    }
    # Compress-Archive uses update mode and buffers an entire directory in
    # memory. Stream directly for the portable runtime's many small files.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory(
        $Stage, [IO.Path]::GetFullPath($OutputPath),
        [IO.Compression.CompressionLevel]::Optimal, $false
    )
} finally {
    if (Test-Path -LiteralPath $Stage) {
        Remove-Item -LiteralPath $Stage -Recurse -Force
    }
}

if ($LatestCopy) {
    $latestPath = Join-Path $Dist "lsprepost-mcp_latest.zip"
    Copy-Item -LiteralPath $OutputPath -Destination $latestPath -Force
    Write-Output "Updated latest package copy: $latestPath"
}

Write-Output "Created package: $OutputPath"
