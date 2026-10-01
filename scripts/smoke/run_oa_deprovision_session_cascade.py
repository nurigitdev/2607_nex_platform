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

from nex_oa.identity_lifecycle import plan_subject_status_transition  # noqa: E402
from nex_oa.identity_lifecycle_repository import (  # noqa: E402
    InMemoryOaIdentityLifecycleRepository,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry  # noqa: E402
from nex_oa.sessions import InMemoryOaSessionRegistry  # noqa: E402
from nex_oa.subjects import InMemoryOaSubjectRegistry  # noqa: E402


def run_oa_deprovision_session_cascade() -> dict[str, Any]:
    subjects = InMemoryOaSubjectRegistry()
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    membership = memberships.ensure_membership(
        {"tenant_id": "tenant-1218", "subject_id": "employee-1218"}
    )
    sessions = InMemoryOaSessionRegistry(memberships)
    sessions.sessions = {
        "matching": _session("employee-1218", status="ACTIVE"),
        "already-expired": _session("employee-1218", status="EXPIRED"),
        "different-subject": _session("employee-other", status="ACTIVE"),
    }
    repository = InMemoryOaIdentityLifecycleRepository(
        subjects,
        memberships,
        session_registry=sessions,
    )
    result = repository.transition_subject(
        plan_subject_status_transition(
            membership["subject_registry_snapshot"],
            target_status="DISABLED",
            expected_revision=1,
            reason_code="admin.deprovision",
        ),
        context={
            "actor_ref_type": "nex.service",
            "actor_ref_id": "nex-ag",
            "request_id": "request-1218",
            "trace_id": "1234567890abcdef1234567890abcdef",
        },
    )
    checks = {
        "subject_disabled": result["status"] == "DISABLED",
        "one_active_session_revoked": result["revoked_session_count"] == 1,
        "matching_session_revoked": sessions.sessions["matching"]["status"] == "REVOKED",
        "expired_session_unchanged": sessions.sessions["already-expired"]["status"] == "EXPIRED",
        "other_subject_unchanged": sessions.sessions["different-subject"]["status"] == "ACTIVE",
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_deprovision_session_cascade_evidence.v1",
        "slice": "1218",
        "requirement": "S122",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_deprovision_session_cascade_failed",
        "checks": checks,
        "revoked_session_count": result["revoked_session_count"],
    }


def _session(subject_id: str, *, status: str) -> dict[str, Any]:
    return {
        "session_id": f"session-{subject_id}-{status.lower()}",
        "status": status,
        "tenant_ref": {"id": "tenant-1218"},
        "subject_ref": {"id": subject_id},
        "revoked_at": None,
        "updated_at": "2026-01-01T00:00:00Z",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        f"oa_deprovision_session_cascade=pass revoked={evidence.get('revoked_session_count')}"
        if evidence.get("status") == "PASS"
        else "oa_deprovision_session_cascade=fail"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_deprovision_session_cascade()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
