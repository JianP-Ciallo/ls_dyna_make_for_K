"""Exercise execution guards with inert tests, never real model generation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox(tmp_path):
    shutil.copy2(ROOT / "pytest.ini", tmp_path / "pytest.ini")
    if (ROOT / "conftest.py").exists():
        shutil.copy2(ROOT / "conftest.py", tmp_path / "conftest.py")
    tests = tmp_path / "tests"
    tests.mkdir()
    for name in ("test_jsonrpc.py", "test_phase10_error_inputs.py", "test_other.py"):
        (tests / name).write_text("def test_small():\n    assert True\n", encoding="utf-8")
    (tests / "test_heavy.py").write_text(
        "import pytest\n@pytest.mark.heavy_provider_e2e\n"
        "def test_inert_heavy():\n    assert True\n", encoding="utf-8"
    )
    return tmp_path


def run_pytest(sandbox, *args, cwd=None):
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *args],
        cwd=cwd or sandbox, env=env, capture_output=True, text=True, timeout=30,
    )


def test_default_is_small_smoke(sandbox):
    result = run_pytest(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


@pytest.mark.parametrize("target", ["tests", "."])
def test_broad_discovery_requires_opt_in(sandbox, target):
    result = run_pytest(sandbox, target)
    assert result.returncode == 4, result.stdout + result.stderr
    assert "--run-full" in result.stderr


def test_default_from_tests_directory_cannot_expand_scope(sandbox):
    result = run_pytest(sandbox, cwd=sandbox / "tests")
    assert result.returncode == 4, result.stdout + result.stderr


def test_full_opt_in_does_not_enable_heavy(sandbox):
    result = run_pytest(sandbox, "--run-full")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed, 1 skipped" in result.stdout


def test_both_opt_ins_enable_inert_full_suite(sandbox):
    result = run_pytest(sandbox, "tests", "--run-full", "--run-heavy")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout


def test_direct_heavy_selection_still_skips(sandbox):
    result = run_pytest(sandbox, "tests/test_heavy.py", "-m", "heavy_provider_e2e")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout


def test_explicit_heavy_opt_in_can_run_only_selected_case(sandbox):
    result = run_pytest(sandbox, "tests/test_heavy.py::test_inert_heavy", "--run-heavy")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_explicit_small_file_remains_available(sandbox):
    result = run_pytest(sandbox, "tests/test_other.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_collection_only_can_inspect_full_suite(sandbox):
    result = run_pytest(sandbox, "tests", "--collect-only")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 tests collected" in result.stdout


@pytest.fixture
def script_sandbox(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("run_tests.ps1", "run_test_matrix.ps1"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    # Stub only the external runner boundary. Guards and dispatch remain real.
    runner = tmp_path / "bin"
    runner.mkdir()
    (runner / "python.cmd").write_text(
        "@echo TEST_RUNNER_CALLED %*\n@exit /b 0\n", encoding="ascii"
    )
    return tmp_path


def run_script(script_sandbox, *args, wrapper=False):
    env = os.environ.copy()
    env["PATH"] = str(script_sandbox / "bin") + os.pathsep + env["PATH"]
    name = "run_tests.ps1" if wrapper else "run_test_matrix.ps1"
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(script_sandbox / "scripts" / name), *args],
        cwd=script_sandbox, env=env, capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("wrapper", [False, True])
def test_script_default_dispatch_is_focused(script_sandbox, wrapper):
    result = run_script(script_sandbox, wrapper=wrapper)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TEST_RUNNER_CALLED -m pytest" in result.stdout
    assert "tests/test_jsonrpc.py" in result.stdout
    assert "discover" not in result.stdout


@pytest.mark.parametrize("group, flag", [("all", "-RunFull"), ("full", "-RunFull"), ("heavy", "-RunHeavy")])
def test_scripts_refuse_expensive_groups_without_approval(script_sandbox, group, flag):
    result = run_script(script_sandbox, "-Group", group)
    assert result.returncode != 0
    assert flag in result.stdout + result.stderr
    assert "TEST_RUNNER_CALLED" not in result.stdout


def test_dry_run_forwards_without_executing(script_sandbox):
    result = run_script(script_sandbox, "-Group", "full", "-DryRun", wrapper=True)
    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(result.stdout)
    assert plan["group"] == "full"
    assert "--run-full" in plan["command"]
    assert "--run-heavy" not in plan["command"]
    assert "TEST_RUNNER_CALLED" not in result.stdout


def test_explicit_heavy_script_opt_in_reaches_only_stub(script_sandbox):
    result = run_script(script_sandbox, "-Group", "heavy", "-RunHeavy", wrapper=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--run-heavy" in result.stdout
    assert "-m heavy_provider_e2e" in result.stdout
    assert "TEST_RUNNER_CALLED" in result.stdout


@pytest.mark.parametrize("group", ["full", "all"])
@pytest.mark.parametrize("include_heavy", [False, True])
def test_full_script_opt_in_keeps_heavy_independent(script_sandbox, group, include_heavy):
    args = ["-Group", group, "-RunFull"]
    if include_heavy:
        args.append("-RunHeavy")
    result = run_script(script_sandbox, *args, wrapper=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TEST_RUNNER_CALLED -m pytest tests --run-full" in result.stdout
    assert ("--run-heavy" in result.stdout) is include_heavy
    assert ("TEST_RUNNER_CALLED -m compileall" in result.stdout) is (group == "all")


def test_runner_failure_is_propagated(script_sandbox):
    (script_sandbox / "bin" / "python.cmd").write_text("@exit /b 7\n", encoding="ascii")
    result = run_script(script_sandbox, wrapper=True)
    assert result.returncode == 7, result.stdout + result.stderr


@pytest.mark.parametrize("group", ["critical", "packaging", "assessment", "snapshots", "errors", "paths", "gui", "web"])
def test_python_groups_collect_function_and_class_tests(script_sandbox, group):
    result = run_script(script_sandbox, "-Group", group, "-DryRun")
    assert result.returncode == 0, result.stdout + result.stderr
    command = json.loads(result.stdout)["command"]
    assert command[1:3] == ["-m", "pytest"]
    files = [target for target in command[3:] if target.endswith(".py")]
    if group == "assessment":
        files = ["packages/blast_damage_assessment/tests/test_contract.py"]
    for filename in files:
        target = script_sandbox / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "import unittest\n"
            "def test_function():\n    assert True\n"
            "class LegacyTest(unittest.TestCase):\n"
            "    def test_method(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    collected = subprocess.run(
        [sys.executable, *command[1:], "--collect-only", "-p", "no:cacheprovider"],
        cwd=script_sandbox, env=env, capture_output=True, text=True, timeout=30,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert f"{2 * len(files)} tests collected" in collected.stdout
