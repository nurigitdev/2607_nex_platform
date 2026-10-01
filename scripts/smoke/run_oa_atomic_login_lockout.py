#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_oa.credentials import (  # noqa: E402
    InMemoryOaCredentialRegistry,
    MAX_FAILED_LOGIN_ATTEMPTS,
    OaCredentialError,
)


def run_oa_atomic_login_lockout() -> dict[str, Any]:
    registry = InMemoryOaCredentialRegistry()
    registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
        }
    )
    errors: list[str] = []
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        try:
            registry.verify_credential(
                {
                    "tenant_id": "tenant-a",
                    "employee_id": "EMP-001",
                    "password": "Wrong1004!",
                }
            )
        except OaCredentialError as exc:
            errors.append(exc.error_code)
    record = registry.credentials[("tenant-a", "emp-001")]
    locked_snapshot = dict(record)
    locked_error = None
    try:
        registry.verify_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
            }
        )
    except OaCredentialError as exc:
        locked_error = exc.error_code
    record["locked_at"] = (
        datetime.now(UTC) - timedelta(seconds=901)
    ).isoformat().replace("+00:00", "Z")
    registry.verify_credential(
        {"tenant_id": "tenant-a", "employee_id": "EMP-001", "password": "Nuri1004!"}
    )
    checks = {
        "all_failures_are_enumeration_safe": set(errors) == {"oa.credential_not_verified"},
        "threshold_reached": locked_snapshot["failed_attempt_count"]
        == MAX_FAILED_LOGIN_ATTEMPTS,
        "credential_locked": locked_snapshot["status"] == "LOCKED"
        and locked_snapshot["locked_at"] is not None,
        "locked_correct_password_rejected_generically": locked_error
        == "oa.credential_not_verified",
        "expired_lock_accepts_correct_password": record["status"] == "ACTIVE",
        "success_resets_counter": record["failed_attempt_count"] == 0
        and record["locked_at"] is None,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_atomic_login_lockout.v1",
        "slice": "1224",
        "requirement": "S123",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_atomic_login_lockout_failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "threshold": MAX_FAILED_LOGIN_ATTEMPTS,
            "duration_seconds": 900,
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        f"oa_atomic_login_lockout={str(evidence.get('status')).lower()} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"threshold={summary.get('threshold')} duration={summary.get('duration_seconds')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_atomic_login_lockout()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
