#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_release import (  # noqa: E402
    build_release_evidence_manifest,
    validate_release_evidence_manifest,
)


ACTIVATION_ENV = "NEX_S150_RELEASE_MANIFEST"
DEFAULT_CLOSURE = ROOT / "reports/deployment/s149-closure.json"
DEFAULT_OUTPUT = ROOT / "reports/deployment/s150-release-manifest.json"


def run_release_evidence_manifest(
    *,
    root: Path = ROOT,
    closure_path: Path = DEFAULT_CLOSURE,
    output_path: Path = DEFAULT_OUTPUT,
    environ: Mapping[str, str] | None = None,
    source_revision: str | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "status": "SKIPPED",
            "reason": ACTIVATION_ENV,
            "slice": "1496",
            "requirement": "S150",
        }
    closure = _load_json(closure_path)
    if not closure:
        return _failure("s149_closure_unavailable")
    try:
        revision = source_revision or _git_revision(root)
        timestamp = observed_at or datetime.fromtimestamp(
            closure_path.stat().st_mtime,
            tz=UTC,
        )
        manifest = build_release_evidence_manifest(
            closure,
            source_revision=revision,
            observed_at=timestamp,
        )
    except (OSError, ValueError) as exc:
        return _failure(str(exc))
    validation = validate_release_evidence_manifest(manifest)
    result = {
        **manifest,
        "slice": "1496",
        "status": validation["status"],
        "checks": validation["checks"],
        "failed_checks": validation["failed_checks"],
        "summary": validation["summary"],
        "next_slice": "1497" if validation["status"] == "PASS" else "blocked",
    }
    if result["status"] == "PASS":
        _write_json(output_path, result)
    return result


def _failure(reason: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "failure_code": "s150_release_manifest_failed",
        "reason": reason,
        "slice": "1496",
        "requirement": "S150",
        "next_slice": "blocked",
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _git_revision(root: Path) -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise ValueError("Git source revision is unavailable")
    return completed.stdout.strip()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s150_release_manifest=skipped"
    if result.get("status") != "PASS":
        return "s150_release_manifest=fail"
    summary = dict(result.get("summary") or {})
    return (
        "s150_release_manifest=pass "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"dependencies={summary.get('dependency_count', 0)} "
        f"backlog={summary.get('backlog_count', 0)} next=1497"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", type=Path, default=DEFAULT_CLOSURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_release_evidence_manifest(
        closure_path=args.closure,
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
