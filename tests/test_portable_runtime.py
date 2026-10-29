"""Portable startup selection, without downloading or launching a solver."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT/'scripts/python_runtime.ps1'
POWERSHELL = shutil.which('powershell')


def test_server_health_identifies_the_actual_interpreter():
    from lsprepost_mcp.tool_server import tool_server_info
    assert tool_server_info({})['python_executable'] == sys.executable


def ps_literal(path):
    return "'"+str(path).replace("'", "''")+"'"


def select_python(root, *, allow_missing=False, environment=None):
    command = (
        "$ErrorActionPreference='Stop'; . "+ps_literal(HELPER)+"; "
        "$selected=Resolve-ProjectPython -Root "+ps_literal(root)
        + (' -AllowMissing' if allow_missing else '')
        + "; @{python=$selected;pythonhome=$env:PYTHONHOME;pythonpath=$env:PYTHONPATH} | ConvertTo-Json -Compress"
    )
    return subprocess.run([POWERSHELL,'-NoProfile','-ExecutionPolicy','Bypass','-Command',command],
                          env=environment, text=True,encoding='utf8',errors='replace',
                          capture_output=True,timeout=20)


def test_bundled_python_wins_and_clears_inherited_python_environment(tmp_path):
    project = tmp_path/'portable project'
    bundled = project/'runtime/python/python.exe'
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b'path-selection fixture; not an executable')
    env = os.environ.copy()
    env.update(PYTHONHOME='invalid-parent-environment',PYTHONPATH='invalid-site-packages')
    result = select_python(project,environment=env)
    assert result.returncode == 0,result.stdout+result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload['python']) == bundled
    assert not payload['pythonhome'] and not payload['pythonpath']


def test_incomplete_portable_runtime_does_not_silently_use_system_python(tmp_path):
    (tmp_path/'runtime').mkdir()
    result = select_python(tmp_path)
    assert result.returncode != 0
    assert 'runtime' in result.stderr.lower() and 'python.exe' in result.stderr.lower()


def test_source_checkout_can_report_missing_python_without_installed_python(tmp_path):
    env = os.environ.copy()
    env['PATH'] = str(tmp_path)
    result = select_python(tmp_path,allow_missing=True,environment=env)
    assert result.returncode == 0,result.stdout+result.stderr
    assert json.loads(result.stdout)['python'] is None


def test_source_checkout_can_use_system_python_when_no_runtime_is_bundled(tmp_path):
    result = select_python(tmp_path)
    assert result.returncode == 0,result.stdout+result.stderr
    assert Path(json.loads(result.stdout)['python']).is_file()


def test_portable_pack_rejects_an_unprepared_runtime_before_creating_zip(tmp_path):
    output = tmp_path/'portable.zip'
    incomplete = tmp_path/'incomplete-runtime'
    incomplete.mkdir()
    result = subprocess.run([POWERSHELL,'-NoProfile','-ExecutionPolicy','Bypass','-File',
        str(ROOT/'scripts/pack.ps1'),'-BuildLabel','portable-invalid-fixture',
        '-PortableRuntimeDir',str(incomplete),'-OutputPath',str(output),'-Pure'],
        text=True,encoding='utf8',errors='replace',capture_output=True,timeout=20)
    assert result.returncode != 0
    assert 'runtime-manifest.json' in result.stdout+result.stderr
    assert not output.exists()


def test_pack_relative_output_uses_the_powershell_current_directory(tmp_path):
    filename='portable-relative-'+uuid.uuid4().hex+'.zip'
    unintended=ROOT/filename
    command=("$ErrorActionPreference='Stop'; Set-Location -LiteralPath "+ps_literal(tmp_path)
             + "; & "+ps_literal(ROOT/'scripts/pack.ps1')
             + " -BuildLabel portable-relative-fixture -Pure -OutputPath "+ps_literal(filename))
    try:
        result=subprocess.run([POWERSHELL,'-NoProfile','-ExecutionPolicy','Bypass','-Command',command],
                              cwd=ROOT,text=True,encoding='utf8',errors='replace',
                              capture_output=True,timeout=90)
        assert result.returncode == 0,result.stdout+result.stderr
        assert (tmp_path/filename).is_file(),'Archive was written outside the requested PowerShell directory'
        assert not unintended.exists()
    finally:
        # This unique test-owned file is the old implementation's regression.
        unintended.unlink(missing_ok=True)
