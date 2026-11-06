#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_policy_controlled_steady_state_baseline_maintenance import (
    build_controlled_steady_state_baseline_maintenance,
)

SCHEMA_VERSION = (
    "gb2_s20qpat_answer_support_policy_controlled_steady_state_baseline_maintenance.v1"
)
SMOKE_ENV = "NEX_GB2_S20QPAT_CONTROLLED_BASELINE_MAINTENANCE"
CLOSURE_REPORT_ENV = "NEX_GB2_S20QPAT_CLOSURE_REPORT_PATH"
LAST_REVIEWED_AT_ENV = "NEX_GB2_S20QPAT_LAST_REVIEWED_AT"
EVALUATED_AT_ENV = "NEX_GB2_S20QPAT_EVALUATED_AT"

POLICY_PATH = (
    ROOT / "services/nex-cx/nex_cx/data/"
    "answer_support_policy_controlled_steady_state_baseline_maintenance.v1.json"
)
CLOSURE_REPORT_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpas_answer_support_policy_steady_state_operations_"
    "continuation_closure.json"
)
OUTPUT_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpat_answer_support_policy_controlled_steady_state_"
    "baseline_maintenance.json"
)


def run_gb2_s20qpat_controlled_steady_state_baseline_maintenance(
    environ: Mapping[str, str] | None = None,
    *,
    policy: Mapping[str, Any] | None = None,
    closure_report: Mapping[str, Any] | None = None,
    current_identity: Mapping[str, Any] | None = None,
    observed_reopen_events: tuple[str, ...] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    default_timestamp = instant.isoformat().replace("+00:00", "Z")
    try:
        snapshot = build_controlled_steady_state_baseline_maintenance(
            policy=dict(_load(POLICY_PATH) if policy is None else policy),
            closure_report=dict(
                _load_private(
                    Path(env.get(CLOSURE_REPORT_ENV, str(CLOSURE_REPORT_PATH)))
                )
                if closure_report is None
                else closure_report
            ),
            current_identity=current_identity,
            observed_reopen_events=observed_reopen_events,
            last_reviewed_at=env.get(LAST_REVIEWED_AT_ENV, default_timestamp),
            evaluated_at=env.get(EVALUATED_AT_ENV, default_timestamp),
        )
    except Exception as exc:  # noqa: BLE001 - protected maintenance boundary
        return _failure(
            "controlled_steady_state_baseline_maintenance_failed",
            detail={"exception": exc.__class__.__name__},
        )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AT",
        **snapshot,
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document must be an object")
    return value


def _load_private(path: Path) -> dict[str, Any]:
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError(f"{path.name} must be owner-private")
    return _load(path)


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AT",
        "status": "FAIL",
        "failure_code": code,
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_changed": False,
        "rollback_contract_preserved": True,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        return (
            "gb2_s20qpat_controlled_baseline_maintenance=pass "
            f"maintenance={result.get('maintenance_status')} "
            f"admission={result.get('admission_status')} "
            f"next={result.get('next_boundary')}"
        )
    if status == "skipped":
        return "gb2_s20qpat_controlled_baseline_maintenance=skipped"
    return (
        "gb2_s20qpat_controlled_baseline_maintenance=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpat_controlled_steady_state_baseline_maintenance()
    if result.get("status") != "SKIPPED" or not args.output.exists():
        _write_private_json(args.output, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
