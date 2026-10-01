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

from nex_oa.identity_lifecycle import (  # noqa: E402
    OaIdentityLifecycleError,
    plan_membership_status_transition,
)


def run_oa_membership_lifecycle_domain() -> dict[str, Any]:
    membership = {
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-1214"},
        "subject_ref": {"type": "oa.user", "id": "employee-1214"},
        "status": "ACTIVE",
        "revision": 5,
    }
    disable = plan_membership_status_transition(
        membership,
        target_status="DISABLED",
        expected_revision=5,
        reason_code="access.suspended",
    )
    enable = plan_membership_status_transition(
        {**membership, "status": "DISABLED"},
        target_status="ACTIVE",
        expected_revision=5,
        reason_code="access.restored",
    )
    conflict = _error_code(
        lambda: plan_membership_status_transition(
            membership,
            target_status="DISABLED",
            expected_revision=4,
            reason_code="access.suspended",
        )
    )
    checks = {
        "disable_advances_revision": disable["next_revision"] == 6,
        "disable_revokes_sessions": disable["revoke_active_sessions"] is True,
        "enable_does_not_restore_sessions": enable["restore_prior_sessions"] is False,
        "stale_writer_rejected": conflict == "oa.lifecycle_revision_conflict",
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_membership_lifecycle_domain_evidence.v1",
        "slice": "1214",
        "requirement": "S122",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_membership_lifecycle_domain_failed",
        "checks": checks,
        "sample": {"disable": disable, "enable": enable},
    }


def _error_code(action: Any) -> str | None:
    try:
        action()
    except OaIdentityLifecycleError as exc:
        return exc.error_code
    return None


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_membership_lifecycle_domain=pass transitions=4/4"
        if evidence.get("status") == "PASS"
        else "oa_membership_lifecycle_domain=fail"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_membership_lifecycle_domain()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
