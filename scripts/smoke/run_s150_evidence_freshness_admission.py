#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_release import (  # noqa: E402
    evaluate_release_evidence_admission,
)


ACTIVATION_ENV = "NEX_S150_EVIDENCE_ADMISSION"
DEFAULT_MANIFEST = ROOT / "reports/deployment/s150-release-manifest.json"
DEFAULT_CLOSURE = ROOT / "reports/deployment/s149-closure.json"
DEFAULT_OUTPUT = ROOT / "reports/deployment/s150-evidence-admission.json"


def run_evidence_freshness_admission(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    closure_path: Path = DEFAULT_CLOSURE,
    output_path: Path = DEFAULT_OUTPUT,
    environ: Mapping[str, str] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "status": "SKIPPED",
            "reason": ACTIVATION_ENV,
            "slice": "1497",
            "requirement": "S150",
        }
    manifest = _load_json(manifest_path)
    closure = _load_json(closure_path)
    binding = _mapping(closure.get("release_binding"))
    if not manifest or not binding:
        return _failure("release evidence inputs are unavailable")
    try:
        admission = evaluate_release_evidence_admission(
            manifest,
            expected_release_candidate_id=str(
                binding.get("release_candidate_id") or ""
            ),
            expected_release_set_digest=str(binding.get("release_set_digest") or ""),
            evaluated_at=evaluated_at or datetime.now(UTC),
        )
    except ValueError as exc:
        return _failure(str(exc))
    result = {
        "evidence_schema_version": "s150_evidence_freshness_admission.v1",
        "slice": "1497",
        "requirement": "S150",
        "status": admission["status"],
        "failure_code": None
        if admission["status"] == "PASS"
        else "s150_evidence_freshness_admission_failed",
        "release_candidate_id": manifest.get("release_candidate_id"),
        "release_set_digest": manifest.get("release_set_digest"),
        "manifest_digest": manifest.get("manifest_digest"),
        "checks": admission["checks"],
        "failed_checks": admission["failed_checks"],
        "age_seconds": admission["age_seconds"],
        "max_age_seconds": admission["max_age_seconds"],
        "summary": admission["summary"],
        "next_slice": "1498" if admission["status"] == "PASS" else "blocked",
        "production_deployment_approved": False,
    }
    if result["status"] == "PASS":
        _write_json(output_path, result)
    return result


def _failure(reason: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "failure_code": "s150_evidence_freshness_admission_failed",
        "reason": reason,
        "slice": "1497",
        "requirement": "S150",
        "next_slice": "blocked",
        "production_deployment_approved": False,
    }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return _mapping(value)


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
        return "s150_evidence_admission=skipped"
    if result.get("status") != "PASS":
        return "s150_evidence_admission=fail"
    summary = _mapping(result.get("summary"))
    return (
        "s150_evidence_admission=pass "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"dependencies={summary.get('dependency_count', 0)} "
        f"window={summary.get('max_age_hours', 0)}h next=1498"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--closure", type=Path, default=DEFAULT_CLOSURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_evidence_freshness_admission(
        manifest_path=args.manifest,
        closure_path=args.closure,
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
