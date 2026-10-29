function Resolve-ProjectPython {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [switch]$AllowMissing
    )
    $runtimeRoot = Join-Path $Root 'runtime'
    $bundled = Join-Path $runtimeRoot 'python\python.exe'
    if (Test-Path -LiteralPath $runtimeRoot) {
        if (-not (Test-Path -LiteralPath $bundled -PathType Leaf)) {
            throw 'Bundled runtime is incomplete: runtime/python/python.exe is missing. Extract the portable ZIP again.'
        }
        # The embedded interpreter also uses a relative ._pth file. Remove
        # inherited settings so helpers cannot accidentally select a host venv.
        $env:PYTHONHOME = $null
        $env:PYTHONPATH = $null
        $env:PYTHONNOUSERSITE = '1'
        $env:PYTHONDONTWRITEBYTECODE = '1'
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        $global:OutputEncoding = $utf8
        [Console]::InputEncoding = $utf8
        [Console]::OutputEncoding = $utf8
        return (Resolve-Path -LiteralPath $bundled).ProviderPath
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $command) { return $command.Source }
    if ($AllowMissing) { return $null }
    throw 'Python was not found. Use the portable ZIP, or install Python for the source package.'
}
