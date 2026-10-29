param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PackageRoot = Join-Path $Root "packages\blast_damage_assessment"

if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot "pyproject.toml") -PathType Leaf)) {
    throw "Standalone damage assessment package is missing: $PackageRoot"
}

$UseBundled = (Test-Path -LiteralPath (Join-Path $Root 'runtime')) -and -not $PSBoundParameters.ContainsKey('PythonExe')
if ($UseBundled) {
    . (Join-Path $PSScriptRoot 'python_runtime.ps1')
    $PythonPath = Resolve-ProjectPython -Root $Root
} else {
    $PythonCommand = Get-Command $PythonExe -ErrorAction Stop
    $PythonPath = $PythonCommand.Source
    if ([string]::IsNullOrWhiteSpace($PythonPath)) { $PythonPath = $PythonCommand.Path }
    & $PythonPath -m pip install --disable-pip-version-check $PackageRoot
    if ($LASTEXITCODE -ne 0) { throw "Damage assessment package installation failed with exit code $LASTEXITCODE" }
}

$ProbeScript = @'
import json
from blast_damage_assessment.api import capabilities

payload = capabilities()
if payload.get("dependencies", {}).get("lasso_python") != "2.0.4":
    raise SystemExit("accepted lasso-python version 2.0.4 is unavailable")
schemas = payload.get("schemas", {})
if "blast_damage.assessment_request@1" not in schemas.get("request", []):
    raise SystemExit("assessment request v1 capability is unavailable")
if "blast_damage.assessment_result@1" not in schemas.get("result", []):
    raise SystemExit("assessment result v1 capability is unavailable")
rules = {item.get("id") for item in payload.get("rule_packs", [])}
required = {"building_research_reference@1", "ground_research_reference@1"}
if not required <= rules:
    raise SystemExit("required research rule packs are unavailable")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
'@

& $PythonPath -B -X utf8 -c $ProbeScript
if ($LASTEXITCODE -ne 0) {
    throw "Damage assessment capability verification failed with exit code $LASTEXITCODE"
}
