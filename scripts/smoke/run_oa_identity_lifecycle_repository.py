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
    plan_membership_status_transition,
    plan_subject_status_transition,
)
from nex_oa.identity_lifecycle_repository import (  # noqa: E402
    InMemoryOaIdentityLifecycleRepository,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry  # noqa: E402
from nex_oa.subjects import InMemoryOaSubjectRegistry  # noqa: E402


def run_oa_identity_lifecycle_repository(root: Path = ROOT) -> dict[str, Any]:
    subjects = InMemoryOaSubjectRegistry()
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    snapshot = memberships.ensure_membership(
        {"tenant_id": "tenant-1215", "subject_id": "employee-1215"}
    )
    repository = InMemoryOaIdentityLifecycleRepository(subjects, memberships)
    context = {
        "actor_ref_type": "nex.service",
        "actor_ref_id": "nex-ag",
        "request_id": "request-1215",
        "trace_id": "1234567890abcdef1234567890abcdef",
    }
    subject_result = repository.transition_subject(
        plan_subject_status_transition(
            snapshot["subject_registry_snapshot"],
            target_status="DISABLED",
            expected_revision=1,
            reason_code="admin.subject-disable",
        ),
        context=context,
    )
    membership_result = repository.transition_membership(
        plan_membership_status_transition(
            snapshot,
            target_status="DISABLED",
            expected_revision=1,
            reason_code="admin.membership-disable",
        ),
        context=context,
    )
    migration = root / "database/nex-oa/migrations/1215_oa_identity_lifecycle.sql"
    migration_source = migration.read_text(encoding="utf-8") if migration.is_file() else ""
    events = repository.list_events(
        tenant_id="tenant-1215", subject_id="employee-1215"
    )
    checks = {
        "subject_revision_persisted": subject_result["revision"] == 2,
        "membership_revision_persisted": membership_result["revision"] == 2,
        "append_only_events_recorded": len(events) == 2,
        "short_event_table_present": "oa_id_lifecycle_events" in migration_source,
        "migration_registered": "1215_oa_identity_lifecycle" in migration_source,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_identity_lifecycle_repository_evidence.v1",
        "slice": "1215",
        "requirement": "S122",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_identity_lifecycle_repository_failed",
        "checks": checks,
        "event_count": len(events),
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        f"oa_identity_lifecycle_repository=pass events={evidence.get('event_count')}"
        if evidence.get("status") == "PASS"
        else "oa_identity_lifecycle_repository=fail"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_identity_lifecycle_repository()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
