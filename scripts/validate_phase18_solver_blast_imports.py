from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lsprepost_mcp.cfile import render_cfile_template
from lsprepost_mcp.lspp.launcher import require_lsprepost_exe
from lsprepost_mcp.tool_helpers import (
    PREVIEW_VIEW_COMMANDS,
    verify_keyword_reader_messages,
    verify_png_artifact,
)


FOLDERS = (
    "01_commercial_supermarket",
    "02_residential_community",
    "03_subway_entrance",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_atomic(path: Path, value: object) -> None:
    _write_text_atomic(
        path,
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def _validated_model_dir(root: Path, folder: str) -> Path:
    model_dir = root / folder
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise ValueError(f"model directory must be a real directory: {folder}")
    resolved = model_dir.resolve()
    if resolved.parent != root:
        raise ValueError(f"model directory escaped output root: {folder}")
    keyword = resolved / "model.k"
    if keyword.is_symlink() or not keyword.is_file():
        raise ValueError(f"model.k must be a real file: {folder}")
    if keyword.resolve().parent != resolved:
        raise ValueError(f"model.k escaped model directory: {folder}")
    return resolved


def validate_imports(output_root: Path, timeout_s: float) -> dict[str, object]:
    root = Path(output_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("output root must be an existing real directory")
    root = root.resolve()
    exe = require_lsprepost_exe().resolve()
    exe_sha256 = _sha256(exe)
    rows: list[dict[str, object]] = []

    for folder in FOLDERS:
        model_dir = _validated_model_dir(root, folder)
        evidence_dir = model_dir / "lsprepost_import"
        if evidence_dir.exists():
            if evidence_dir.is_symlink() or not evidence_dir.is_dir() or any(evidence_dir.iterdir()):
                raise ValueError(f"import evidence directory must be empty: {folder}")
        else:
            evidence_dir.mkdir(exist_ok=False)

        cfile = evidence_dir / "validate_import.cfile"
        messages = evidence_dir / "keyword_reader_messages.xml"
        preview = evidence_dir / "preview_iso.png"
        cfile_text = render_cfile_template(
            "preview_image.cfile",
            {
                "keyword_path": "model.k",
                "output_path": "lsprepost_import/preview_iso.png",
                "view_command": PREVIEW_VIEW_COMMANDS["iso"],
                "display_commands": "",
                "fit_command": "ac",
                "kwdmsg_path": "lsprepost_import/keyword_reader_messages.xml",
            },
        )
        _write_text_atomic(cfile, cfile_text)
        started = time.monotonic()
        process = subprocess.Popen(
            [str(exe), f"c={cfile}"],
            cwd=str(model_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        try:
            returncode = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=30)
            raise TimeoutError(
                f"LS-PrePost import validation timed out for {folder}"
            )
        duration_s = time.monotonic() - started
        if returncode != 0:
            raise RuntimeError(
                f"LS-PrePost import validation failed for {folder}: returncode={returncode}"
            )
        keyword_reader = verify_keyword_reader_messages(messages)
        png = verify_png_artifact(preview)
        record = {
            "schema_version": "phase18.solver_blast.lsprepost_import@1",
            "folder": folder,
            "keyword_path": str(model_dir / "model.k"),
            "keyword_sha256": _sha256(model_dir / "model.k"),
            "lsprepost_exe": str(exe),
            "lsprepost_exe_sha256": exe_sha256,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": duration_s,
            "returncode": returncode,
            "keyword_reader": keyword_reader,
            "preview": png,
            "ok": True,
        }
        _write_json_atomic(evidence_dir / "run.json", record)
        rows.append(record)

    summary: dict[str, object] = {
        "schema_version": "phase18.solver_blast.lsprepost_import_summary@1",
        "output_root": str(root),
        "models": rows,
        "all_ok": all(bool(row["ok"]) for row in rows),
    }
    _write_json_atomic(root / "lsprepost_import_summary.json", summary)
    return summary


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Validate the three Phase 18 solver-blast models in LS-PrePost."
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.timeout_s <= 0 or args.timeout_s > 900:
        parser.error("--timeout-s must be greater than 0 and at most 900")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "folders": list(FOLDERS),
                    "output_root": str(args.output_root.resolve()),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    summary = validate_imports(args.output_root, args.timeout_s)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
