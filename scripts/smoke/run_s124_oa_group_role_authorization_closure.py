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

from run_oa_authorization_admin_api import (  # noqa: E402
    run_oa_authorization_admin_api as run_admin_api,
)
from run_oa_authorization_contracts import (  # noqa: E402
    run_oa_authorization_contracts as run_contracts,
)
from run_oa_authorization_persistence_migration import (  # noqa: E402
    run_oa_authorization_persistence_migration as run_migration,
)
from run_oa_authorization_repository import (  # noqa: E402
    run_oa_authorization_repository as run_repository,
)
from run_oa_authorization_scope_hardening import (  # noqa: E402
    run_oa_authorization_scope_hardening as run_scopes,
)
from run_oa_effective_authorization_session import (  # noqa: E402
    run_oa_effective_authorization_session as run_effective_session,
)
from run_oa_group_role_authorization_boundary import (  # noqa: E402
    run_oa_group_role_authorization_boundary as run_boundary,
)
from run_oa_group_role_authorization_domain import (  # noqa: E402
    run_oa_group_role_authorization_domain as run_domain,
)


SCHEMA_VERSION = "s124_oa_group_role_authorization_closure.v1"
SLICE_RANGE = "1232-1241"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_DOCUMENT = "docs/slices/1240_oa_authorization_postgresql_smoke.md"
QUALITY_SCRIPTS = (
    "run_oa_group_role_authorization_boundary.py",
    "run_oa_group_role_authorization_domain.py",
    "run_oa_authorization_persistence_migration.py",
    "run_oa_authorization_repository.py",
    "run_oa_effective_authorization_session.py",
    "run_oa_authorization_admin_api.py",
    "run_oa_authorization_scope_hardening.py",
    "run_oa_authorization_contracts.py",
    "run_oa_authorization_postgres_smoke.py",
    "run_s124_oa_group_role_authorization_closure.py",
)
SLICE_DOCUMENTS = (
    "1232_oa_group_role_authorization_boundary.md",
    "1233_oa_group_role_authorization_domain.md",
    "1234_oa_authorization_persistence_migration.md",
    "1235_oa_durable_authorization_repository.md",
    "1236_oa_effective_authorization_session_integration.md",
    "1237_oa_authorization_admin_service_api.md",
    "1238_oa_authorization_scope_hardening.md",
    "1239_oa_authorization_contract_privacy_hardening.md",
    "1240_oa_authorization_postgresql_smoke.md",
    "1241_s124_oa_group_role_authorization_closure.md",
)
SCHEMA_FILES = (
    "authorization_role_upsert.v1.schema.json",
    "authorization_group_upsert.v1.schema.json",
    "authorization_assignment_upsert.v1.schema.json",
    "authorization_mutation_response.v1.schema.json",
    "effective_authorization_response.v1.schema.json",
    "authorization_event_list.v1.schema.json",
)
REQUIRED_FILES = (
    "services/nex-oa/nex_oa/authorization.py",
    "services/nex-oa/nex_oa/authorization_repository.py",
    "services/nex-oa/nex_oa/authorization_resolver.py",
    "services/nex-oa/nex_oa/authorization_service.py",
    "services/nex-oa/nex_oa/identity_access.py",
    "services/nex-oa/nex_oa/authorization_postgres_smoke.py",
    "database/nex-oa/migrations/1234_oa_group_role_authorization.sql",
    "contracts/openapi/nex-oa.openapi.yaml",
    *(
        f"contracts/schemas/service/nex_oa/{name}"
        for name in SCHEMA_FILES
    ),
    *(f"scripts/smoke/{name}" for name in QUALITY_SCRIPTS),
    "tests/test_s124_oa_group_role_authorization_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    (
        "admin_scope",
        "services/nex-oa/nex_oa/authorization_service.py",
        'OA_AUTHORIZATION_ADMIN_SCOPE = "authorization:admin"',
    ),
    (
        "read_scope",
        "services/nex-oa/nex_oa/authorization_service.py",
        'OA_AUTHORIZATION_READ_SCOPE = "authorization:read"',
    ),
    (
        "bootstrap_scope",
        "services/nex-oa/nex_oa/identity_access.py",
        'OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE = "identity:bootstrap:write"',
    ),
    (
        "role_table",
        "database/nex-oa/migrations/1234_oa_group_role_authorization.sql",
        "CREATE TABLE IF NOT EXISTS oa_roles",
    ),
    (
        "event_table",
        "database/nex-oa/migrations/1234_oa_group_role_authorization.sql",
        "CREATE TABLE IF NOT EXISTS oa_authz_events",
    ),
    ("postgres_identity", POSTGRES_DOCUMENT, "`nex_oa_test` / `nex_oa_user`"),
    (
        "postgres_migration",
        POSTGRES_DOCUMENT,
        "`1234_oa_group_role_authorization`",
    ),
    ("postgres_events", POSTGRES_DOCUMENT, "Authorization events: `5`"),
    ("postgres_sessions", POSTGRES_DOCUMENT, "Revoked sessions: `2`"),
    ("postgres_cleanup", POSTGRES_DOCUMENT, "residue `0`"),
    (
        "closure_index",
        "docs/README.md",
        "1241_s124_oa_group_role_authorization_closure.md",
    ),
)


def run_s124_oa_group_role_authorization_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_FILES
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
        "domain": _safe_evidence(run_domain),
        "migration": _safe_evidence(lambda: run_migration(root)),
        "repository": _safe_evidence(run_repository),
        "effective_session": _safe_evidence(run_effective_session),
        "admin_api": _safe_evidence(run_admin_api),
        "scopes": _safe_evidence(run_scopes),
        "contracts": _safe_evidence(run_contracts),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    evidence["protected_postgres"] = {
        "slice": "1240",
        "requirement": "S124",
        "status": (
            "PASS"
            if all(
                token_status.get(name, False)
                for name in (
                    "postgres_identity",
                    "postgres_migration",
                    "postgres_events",
                    "postgres_sessions",
                    "postgres_cleanup",
                )
            )
            else "FAIL"
        ),
    }
    expected_slices = {
        "boundary": "1232",
        "domain": "1233",
        "migration": "1234",
        "repository": "1235",
        "effective_session": "1236",
        "admin_api": "1237",
        "scopes": "1238",
        "contracts": "1239",
        "protected_postgres": "1240",
    }
    summaries = {
        name: _mapping(item.get("summary")) for name, item in evidence.items()
    }
    components = {
        "tenant_policy_and_domain": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "domain")
        ),
        "durable_revisioned_persistence": all(
            evidence[name].get("status") == "PASS"
            for name in ("migration", "repository")
        ),
        "effective_grants_and_session_invalidation": all(
            evidence[name].get("status") == "PASS"
            for name in ("effective_session", "admin_api")
        ),
        "scoped_contract_and_privacy_surface": all(
            evidence[name].get("status") == "PASS"
            for name in ("scopes", "contracts")
        ),
        "actual_postgres_evidence": evidence["protected_postgres"].get("status")
        == "PASS",
    }
    decision = _closure_decision()
    boundary_decision = _mapping(evidence["boundary"].get("decision"))
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "evidence_identity_complete": all(
            evidence[name].get("slice") == slice_id
            and evidence[name].get("requirement") == "S124"
            for name, slice_id in expected_slices.items()
        ),
        "all_components_closed": all(components.values()),
        "tenant_allow_only_policy_closed": (
            boundary_decision.get("tenant_isolation") == "mandatory"
            and _mapping(boundary_decision.get("grant_model")).get("composition")
            == "set_union"
            and _mapping(boundary_decision.get("grant_model")).get(
                "explicit_deny_supported"
            )
            is False
        ),
        "domain_and_persistence_closed": (
            summaries["domain"].get("passed_check_count") == 6
            and summaries["migration"].get("passed_check_count") == 11
            and summaries["migration"].get("table_count") == 5
            and summaries["migration"].get("longest_identifier_length") == 31
            and summaries["repository"].get("passed_check_count") == 6
            and summaries["repository"].get("event_count") == 4
        ),
        "effective_session_and_admin_closed": (
            summaries["effective_session"].get("passed_check_count") == 6
            and summaries["effective_session"].get("claim_role_count") == 2
            and summaries["admin_api"].get("passed_check_count") == 8
            and summaries["admin_api"].get("event_count") == 4
        ),
        "scope_contract_privacy_closed": (
            summaries["scopes"].get("passed_check_count") == 11
            and summaries["scopes"].get("dedicated_scope_count") == 3
            and summaries["contracts"].get("schema_count") == 6
            and summaries["contracts"].get("positive_valid_count") == 6
            and summaries["contracts"].get("negative_rejected_count") == 6
            and summaries["contracts"].get("operation_valid_count") == 8
            and summaries["contracts"].get("runtime_response_count") == 6
        ),
        "actual_postgres_closed": evidence["protected_postgres"]["status"]
        == "PASS",
        "completed_scope_closed": decision["completed_scope"]
        == (
            "tenant_scoped_role_group_assignment_lifecycle",
            "allow_only_set_union_effective_authorization",
            "optimistic_revision_and_privacy_safe_events",
            "authorization_change_session_revocation",
            "dedicated_bootstrap_admin_and_read_scopes",
            "strict_contract_and_actual_postgres_evidence",
        ),
        "remaining_scope_deferred": decision["deferred_scope"]
        == (
            "explicit_deny_rules",
            "nested_groups",
            "signed_service_tokens_and_jwks_verification",
        ),
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1232-1240",
            "checkpoint_gate": "1236",
            "full_gate": "1241",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    deterministic_names = (
        "domain",
        "migration",
        "repository",
        "effective_session",
        "admin_api",
        "scopes",
    )
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1241",
        "slice_range": SLICE_RANGE,
        "requirement": "S124",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s124_oa_group_role_authorization_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S125" if passed else "BLOCKED",
        "feature_readiness": (
            "OA_GROUP_ROLE_AUTHORIZATION_READY" if passed else "INCOMPLETE"
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
            "deterministic_check_count": len(
                _mapping(evidence["boundary"].get("checks"))
            )
            + sum(
                int(summaries[name].get("check_count") or 0)
                for name in deterministic_names
            ),
            "canonical_schema_count": summaries["contracts"].get(
                "schema_count", 0
            ),
            "protected_operation_count": summaries["contracts"].get(
                "operation_valid_count", 0
            ),
            "postgres_event_count": 5
            if evidence["protected_postgres"]["status"] == "PASS"
            else 0,
            "postgres_revoked_session_count": 2
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
        "next_requirement": "S125" if passed else "blocked",
        "next_requirement_scope": (
            "pending_canonical_scope_review" if passed else "blocked"
        ),
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "oa_group_role_authorization",
        "completed_scope": (
            "tenant_scoped_role_group_assignment_lifecycle",
            "allow_only_set_union_effective_authorization",
            "optimistic_revision_and_privacy_safe_events",
            "authorization_change_session_revocation",
            "dedicated_bootstrap_admin_and_read_scopes",
            "strict_contract_and_actual_postgres_evidence",
        ),
        "deferred_scope": (
            "explicit_deny_rules",
            "nested_groups",
            "signed_service_tokens_and_jwks_verification",
        ),
        "grant_composition": "set_union",
        "explicit_deny_supported": False,
        "nested_groups_supported": False,
        "authorization_change_revokes_sessions": True,
        "admin_scope": "authorization:admin",
        "read_scope": "authorization:read",
        "bootstrap_scope": "identity:bootstrap:write",
        "authorization_tables": (
            "oa_roles",
            "oa_groups",
            "oa_group_members",
            "oa_group_roles",
            "oa_authz_events",
        ),
        "actual_postgres_smoke_required": True,
        "remote_provider_calls_required": False,
        "quality_cadence": {
            "slice_gate": "1232-1240",
            "checkpoint_gate": "1236",
            "full_gate": "1241",
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
    summary = evidence.get("summary") or {}
    return (
        "s124_oa_group_role_authorization_closure="
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
    evidence = run_s124_oa_group_role_authorization_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
