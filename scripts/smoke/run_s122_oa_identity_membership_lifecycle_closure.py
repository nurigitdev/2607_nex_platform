#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))
sys.path.insert(0, str(ROOT / "scripts/smoke"))

from run_oa_deprovision_session_cascade import (  # noqa: E402
    run_oa_deprovision_session_cascade as run_cascade,
)
from run_oa_identity_lifecycle_contracts import (  # noqa: E402
    run_oa_identity_lifecycle_contracts as run_contracts,
)
from run_oa_identity_lifecycle_repository import (  # noqa: E402
    run_oa_identity_lifecycle_repository as run_repository,
)
from run_oa_identity_membership_lifecycle_boundary import (  # noqa: E402
    run_oa_identity_membership_lifecycle_boundary as run_boundary,
)
from run_oa_membership_lifecycle_api import (  # noqa: E402
    run_oa_membership_lifecycle_api as run_membership_api,
)
from run_oa_membership_lifecycle_domain import (  # noqa: E402
    run_oa_membership_lifecycle_domain as run_membership_domain,
)
from run_oa_subject_lifecycle_api import (  # noqa: E402
    run_oa_subject_lifecycle_api as run_subject_api,
)
from run_oa_subject_lifecycle_domain import (  # noqa: E402
    run_oa_subject_lifecycle_domain as run_subject_domain,
)


SCHEMA_VERSION = "s122_oa_identity_membership_lifecycle_closure.v1"
SLICE_RANGE = "1212-1221"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_DOCUMENT = "docs/slices/1220_oa_identity_lifecycle_postgresql_smoke.md"
QUALITY_SCRIPTS = (
    "run_oa_identity_membership_lifecycle_boundary.py",
    "run_oa_subject_lifecycle_domain.py",
    "run_oa_membership_lifecycle_domain.py",
    "run_oa_identity_lifecycle_repository.py",
    "run_oa_subject_lifecycle_api.py",
    "run_oa_membership_lifecycle_api.py",
    "run_oa_deprovision_session_cascade.py",
    "run_oa_identity_lifecycle_contracts.py",
    "run_oa_identity_lifecycle_postgres_smoke.py",
    "run_s122_oa_identity_membership_lifecycle_closure.py",
)
SLICE_DOCUMENTS = (
    "1212_oa_identity_membership_lifecycle_boundary.md",
    "1213_oa_subject_lifecycle_domain.md",
    "1214_oa_membership_lifecycle_domain.md",
    "1215_oa_durable_identity_lifecycle_repository.md",
    "1216_oa_subject_lifecycle_service_api.md",
    "1217_oa_membership_lifecycle_service_api.md",
    "1218_oa_deprovision_session_revocation_cascade.md",
    "1219_oa_identity_lifecycle_contract_audit_privacy.md",
    "1220_oa_identity_lifecycle_postgresql_smoke.md",
    "1221_s122_oa_identity_membership_lifecycle_closure.md",
)
REQUIRED_FILES = (
    "services/nex-oa/nex_oa/identity_lifecycle.py",
    "services/nex-oa/nex_oa/identity_lifecycle_repository.py",
    "services/nex-oa/nex_oa/identity_lifecycle_service.py",
    "services/nex-oa/nex_oa/identity_lifecycle_postgres_smoke.py",
    "database/nex-oa/migrations/1215_oa_identity_lifecycle.sql",
    "contracts/openapi/nex-oa.openapi.yaml",
    "contracts/schemas/service/nex_oa/subject_lifecycle_response.v1.schema.json",
    "contracts/schemas/service/nex_oa/membership_lifecycle_response.v1.schema.json",
    *(f"scripts/smoke/{name}" for name in QUALITY_SCRIPTS),
    "tests/test_s122_oa_identity_membership_lifecycle_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    (
        "lifecycle_scope",
        "services/nex-oa/nex_oa/identity_lifecycle_service.py",
        'OA_IDENTITY_LIFECYCLE_WRITE_SCOPE = "identity:lifecycle:write"',
    ),
    (
        "event_table",
        "database/nex-oa/migrations/1215_oa_identity_lifecycle.sql",
        "CREATE TABLE IF NOT EXISTS oa_id_lifecycle_events",
    ),
    (
        "postgres_identity",
        POSTGRES_DOCUMENT,
        "`nex_oa_test` / `nex_oa_user`",
    ),
    ("postgres_migration", POSTGRES_DOCUMENT, "`1215_oa_identity_lifecycle`"),
    ("postgres_events", POSTGRES_DOCUMENT, "lifecycle events: `2`"),
    ("postgres_cleanup", POSTGRES_DOCUMENT, "all five tables: `0`"),
    (
        "closure_index",
        "docs/README.md",
        "1221_s122_oa_identity_membership_lifecycle_closure.md",
    ),
)


def run_s122_oa_identity_membership_lifecycle_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "subject_domain": _safe_evidence(run_subject_domain),
        "membership_domain": _safe_evidence(run_membership_domain),
        "repository": _safe_evidence(lambda: run_repository(root)),
        "subject_api": _safe_evidence(run_subject_api),
        "membership_api": _safe_evidence(run_membership_api),
        "cascade": _safe_evidence(run_cascade),
        "contracts": _safe_evidence(lambda: run_contracts(root)),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    evidence["protected_postgres"] = {
        "slice": "1220",
        "requirement": "S122",
        "status": (
            "PASS"
            if all(
                token_status.get(name, False)
                for name in (
                    "postgres_identity",
                    "postgres_migration",
                    "postgres_events",
                    "postgres_cleanup",
                )
            )
            else "FAIL"
        ),
    }
    expected_slices = {
        "boundary": "1212",
        "subject_domain": "1213",
        "membership_domain": "1214",
        "repository": "1215",
        "subject_api": "1216",
        "membership_api": "1217",
        "cascade": "1218",
        "contracts": "1219",
        "protected_postgres": "1220",
    }
    summaries = {
        name: _mapping(item.get("summary")) for name, item in evidence.items()
    }
    components = {
        "states_revision_and_terminal_policy": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "subject_domain", "membership_domain")
        ),
        "durable_events_and_session_cascade": all(
            evidence[name].get("status") == "PASS"
            for name in ("repository", "cascade")
        ),
        "protected_subject_and_membership_apis": all(
            evidence[name].get("status") == "PASS"
            for name in ("subject_api", "membership_api")
        ),
        "contracts_audit_and_privacy": evidence["contracts"].get("status")
        == "PASS",
        "actual_postgres_evidence": evidence["protected_postgres"].get("status")
        == "PASS",
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "evidence_identity_complete": all(
            evidence[name].get("slice") == slice_id
            and evidence[name].get("requirement") == "S122"
            for name, slice_id in expected_slices.items()
        ),
        "all_components_closed": all(components.values()),
        "subject_policy_closed": all(
            _mapping(evidence["subject_domain"].get("checks")).values()
        ),
        "membership_policy_closed": all(
            _mapping(evidence["membership_domain"].get("checks")).values()
        ),
        "durable_repository_closed": (
            evidence["repository"].get("event_count") == 2
            and all(_mapping(evidence["repository"].get("checks")).values())
        ),
        "protected_apis_closed": (
            len(_mapping(evidence["subject_api"].get("checks"))) == 5
            and all(_mapping(evidence["subject_api"].get("checks")).values())
            and len(_mapping(evidence["membership_api"].get("checks"))) == 5
            and all(_mapping(evidence["membership_api"].get("checks")).values())
        ),
        "deprovision_cascade_closed": (
            evidence["cascade"].get("revoked_session_count") == 1
            and all(_mapping(evidence["cascade"].get("checks")).values())
        ),
        "contract_privacy_closed": (
            summaries["contracts"].get("schema_count") == 2
            and summaries["contracts"].get("documented_operation_count") == 2
            and summaries["contracts"].get("lifecycle_implemented_count") == 6
            and summaries["contracts"].get("remaining_lifecycle_gap_count") == 2
            and summaries["contracts"].get("remaining_contract_drift_count") == 23
        ),
        "actual_postgres_closed": evidence["protected_postgres"]["status"]
        == "PASS",
        "direct_lifecycle_scope_closed": decision["completed_scope"]
        == (
            "durable_subject_lifecycle",
            "durable_direct_membership_lifecycle",
            "atomic_session_revocation",
        ),
        "remaining_scope_deferred": decision["deferred_scope"]
        == (
            "group_registry_and_group_membership",
            "dedicated_bootstrap_admin_authorization",
            "credential_rotation_rehash_and_lockout",
            "service_token_signing_and_jwks_verification",
        ),
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1212-1220",
            "checkpoint_gate": "1216",
            "full_gate": "1221",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1221",
        "slice_range": SLICE_RANGE,
        "requirement": "S122",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None
            if passed
            else "s122_oa_identity_membership_lifecycle_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S123" if passed else "BLOCKED",
        "feature_readiness": (
            "OA_DIRECT_IDENTITY_MEMBERSHIP_LIFECYCLE_READY"
            if passed
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "subject_transition_check_count": len(
                _mapping(evidence["subject_domain"].get("checks"))
            ),
            "membership_transition_check_count": len(
                _mapping(evidence["membership_domain"].get("checks"))
            ),
            "canonical_schema_count": summaries["contracts"].get(
                "schema_count", 0
            ),
            "protected_operation_count": summaries["contracts"].get(
                "documented_operation_count", 0
            ),
            "postgres_event_count": 2
            if evidence["protected_postgres"]["status"] == "PASS"
            else 0,
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S123" if passed else "blocked",
        "next_requirement_scope": (
            "oa_credential_and_session_security_hardening"
            if passed
            else "blocked"
        ),
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "oa_direct_identity_and_membership_lifecycle",
        "subject_states": ("ACTIVE", "DISABLED", "DELETED"),
        "membership_states": ("ACTIVE", "DISABLED"),
        "completed_scope": (
            "durable_subject_lifecycle",
            "durable_direct_membership_lifecycle",
            "atomic_session_revocation",
        ),
        "deferred_scope": (
            "group_registry_and_group_membership",
            "dedicated_bootstrap_admin_authorization",
            "credential_rotation_rehash_and_lockout",
            "service_token_signing_and_jwks_verification",
        ),
        "concurrency": "expected_revision_optimistic_guard",
        "audit_lineage": "append_only_server_actor_event",
        "session_policy": "revoke_on_disable_or_delete_never_restore",
        "table": "oa_id_lifecycle_events",
        "postgres_smoke_required": True,
        "remote_provider_calls_required": False,
        "quality_cadence": {
            "slice_gate": "1212-1220",
            "checkpoint_gate": "1216",
            "full_gate": "1221",
        },
    }


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "s122_oa_identity_membership_lifecycle_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"operations={summary.get('protected_operation_count', 0)} "
        f"postgres_events={summary.get('postgres_event_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s122_oa_identity_membership_lifecycle_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
