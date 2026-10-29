"""Project test execution policy: focused by default, expensive lanes opt-in."""
from pathlib import Path

import pytest


def pytest_addoption(parser):
    group = parser.getgroup("execution policy")
    group.addoption("--run-full", action="store_true", help="Allow broad test discovery after explicit user approval.")
    group.addoption("--run-heavy", action="store_true", help="Enable marked heavy provider cases after explicit user approval.")


def pytest_configure(config):
    root = Path(__file__).resolve().parent
    if config.getoption("--run-full"):
        if not config.option.file_or_dir:
            config.args = [str(root / "tests")]
        return
    if config.option.collectonly:
        return
    for argument in config.args:
        target = (config.invocation_params.dir / argument.split("::", 1)[0]).resolve()
        if target in (root, root / "tests"):
            raise pytest.UsageError(
                "Broad discovery requires --run-full and explicit user approval. "
                "Select relevant test files instead; bare pytest at the project root runs only smoke checks. "
                "--collect-only is available for inspection."
            )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-heavy"):
        return
    skip = pytest.mark.skip(reason="Heavy provider case disabled: obtain user approval, then add --run-heavy.")
    for item in items:
        if item.get_closest_marker("heavy_provider_e2e") is not None:
            item.add_marker(skip)
