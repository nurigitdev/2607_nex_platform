#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.identity_lifecycle import (
    OaIdentityLifecycleError,
    plan_subject_status_transition,
)


def run_oa_subject_lifecycle_domain() -> dict[str, Any]:
    subject = {
        "tenant_id": "tenant-1213",
        "subject_id": "employee-1213",
        "status": "ACTIVE",
        "revision": 3,
    }
    disable = plan_subject_status_transition(
        subject,
        target_status="DISABLED",
        expected_revision=3,
        reason_code="employment.leave",
    )
    unchanged = plan_subject_status_transition(
        subject,
        target_status="ACTIVE",
        expected_revision=3,
    )
    conflict_code = _error_code(
        lambda: plan_subject_status_transition(
            subject,
            target_status="DELETED",
            expected_revision=2,
            reason_code="employment.ended",
        )
    )
    terminal_code = _error_code(
        lambda: plan_subject_status_transition(
            {**subject, "status": "DELETED"},
            target_status="ACTIVE",
            expected_revision=3,
            reason_code="invalid.restore",
        )
    )
    checks = {
        "disable_transition_revisioned": disable["next_revision"] == 4,
        "disable_transition_requires_reason": disable["reason_code"] == "employment.leave",
        "same_state_is_idempotent": unchanged["changed"] is False
        and unchanged["next_revision"] == 3,
        "stale_writer_rejected": conflict_code == "oa.lifecycle_revision_conflict",
        "deleted_state_is_terminal": terminal_code == "oa.subject_transition_invalid",
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_subject_lifecycle_domain_evidence.v1",
        "slice": "1213",
        "requirement": "S122",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_subject_lifecycle_domain_failed",
        "checks": checks,
        "sample": {"disable": disable, "unchanged": unchanged},
    }


def _error_code(action: Any) -> str | None:
    try:
        action()
    except OaIdentityLifecycleError as exc:
        return exc.error_code
    return None


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_subject_lifecycle_domain=pass transitions=5/5"
        if evidence.get("status") == "PASS"
        else "oa_subject_lifecycle_domain=fail"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_subject_lifecycle_domain()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
