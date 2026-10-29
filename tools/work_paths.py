"""Shared locations for local document and screenshot work.

Generated output never defaults to the checkout root. Existing legacy inputs
remain readable; this module does not move, create or delete files.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def generated_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath("var", "tmp", *parts)


def existing_input(*parts: str) -> Path:
    current = generated_path(*parts)
    legacy = PROJECT_ROOT.joinpath(*parts)
    return current if current.exists() or not legacy.exists() else legacy
