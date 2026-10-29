param(
    [string]$Group = "default",
    [switch]$List,
    [switch]$DryRun,
    [switch]$RunFull,
    [switch]$RunHeavy
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "run_test_matrix.ps1") @PSBoundParameters
exit $LASTEXITCODE
