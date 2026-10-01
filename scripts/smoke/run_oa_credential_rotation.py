#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_oa.credential_security import InMemoryOaCredentialSecurityRepository  # noqa: E402
from nex_oa.credentials import InMemoryOaCredentialRegistry, verify_password  # noqa: E402
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry  # noqa: E402
from nex_oa.sessions import InMemoryOaSessionRegistry  # noqa: E402


def run_oa_credential_rotation() -> dict[str, Any]:
    credentials = InMemoryOaCredentialRegistry()
    credentials.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "employee_id": "EMP-001",
            "password": "Current1004!",
        }
    )
    memberships = InMemoryOaTenantMembershipRegistry(
        subject_registry=credentials.subject_registry
    )
    sessions = InMemoryOaSessionRegistry(membership_registry=memberships)
    sessions.sessions["opaque"] = {
        "status": "ACTIVE",
        "tenant_ref": {"id": "tenant-a"},
        "subject_ref": {"id": "user-a"},
        "revoked_at": None,
        "updated_at": "2026-10-01T00:00:00Z",
    }
    repository = InMemoryOaCredentialSecurityRepository(credentials, sessions)
    reset = repository.reset_password(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "temporary_password": "Temporary1004!",
            "reason_code": "operator.recovery",
        }
    )
    sessions.sessions["second-opaque"] = {
        **sessions.sessions["opaque"],
        "status": "ACTIVE",
        "revoked_at": None,
    }
    changed = repository.change_password(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "current_password": "Temporary1004!",
            "new_password": "Final1004!",
        }
    )
    record = credentials.credentials[("tenant-a", "emp-001")]
    checks = {
        "reset_requires_change": reset["credential_status"] == "PASSWORD_RESET_REQUIRED",
        "reset_revokes_session": reset["revoked_session_count"] == 1,
        "change_activates_credential": changed["credential_status"] == "ACTIVE",
        "change_revokes_session": changed["revoked_session_count"] == 1,
        "new_password_verifies": verify_password(
            "Final1004!", password_hash=record["password_hash"]
        ),
        "response_hides_hash": "password_hash" not in changed,
        "response_hides_session_ids": "session_ids" not in changed,
    }
    return {
        "evidence_schema_version": "oa_credential_rotation_evidence.v1",
        "slice": "1227",
        "requirement": "S123",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "reset_revoked": reset["revoked_session_count"],
            "change_revoked": changed["revoked_session_count"],
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        f"oa_credential_rotation={str(evidence.get('status')).lower()} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"revoked={summary.get('reset_revoked', 0)}+{summary.get('change_revoked', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_credential_rotation()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
