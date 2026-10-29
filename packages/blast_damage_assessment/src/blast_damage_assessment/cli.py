"""Command-line interface for standalone assessment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from .adapters.contracts import ResultAdapter
from .api import assess, capabilities
from .contracts import AssessmentResult
from .errors import AssessmentError, ContractError


def _result_record(result: AssessmentResult) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "assessment_id": result.assessment_id,
        "execution_status": result.execution_status,
        "gate": result.gate.value,
        "severity": result.severity,
        "assessment_fingerprint": result.assessment_fingerprint,
        "artifacts": {
            name: {
                "path": reference.path.as_posix(),
                "sha256": reference.sha256,
                "media_type": reference.media_type,
                "size_bytes": reference.size_bytes,
                "schema_version": reference.schema_version,
            }
            for name, reference in sorted(result.artifacts.items())
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blast-damage-assessment")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--request", required=True, type=Path)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    adapter: ResultAdapter | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "capabilities":
            json.dump(capabilities(), out, ensure_ascii=False, sort_keys=True)
            out.write("\n")
            return 0
        raw = arguments.request.read_bytes()
        result = assess(raw, adapter=adapter)
        json.dump(_result_record(result), out, ensure_ascii=False, sort_keys=True)
        out.write("\n")
        return 0
    except ContractError as exc:
        err.write(f"request error: {exc}\n")
        return 2
    except (AssessmentError, OSError, RuntimeError, ValueError, KeyError) as exc:
        err.write(f"assessment failed: {exc}\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
