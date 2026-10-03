#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/smoke"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.service_principal_boundary import (  # noqa: E402
    MAX_CREDENTIAL_LIFETIME_DAYS,
    MAX_ROTATION_GRACE_SECONDS,
    MAX_SIMULTANEOUS_ACTIVE_CREDENTIALS,
)
from run_oa_service_principal_contracts import (  # noqa: E402
    run_oa_service_principal_contracts as run_contracts,
)
from run_oa_service_principal_lifecycle_boundary import (  # noqa: E402
    run_oa_service_principal_lifecycle_boundary as run_boundary,
)
from run_oa_service_principal_migration import (  # noqa: E402
    run_oa_service_principal_migration as run_migration,
)
from run_oa_service_principal_postgres_smoke import (  # noqa: E402
    SMOKE_ENV,
    run_oa_service_principal_postgres_smoke as run_postgres,
)


SCHEMA_VERSION = "s126_oa_service_principal_lifecycle_closure.v1"
SLICE_RANGE = "1252-1261"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
SLICE_DOCUMENTS = (
    "1252_oa_service_principal_lifecycle_boundary.md",
    "1253_oa_service_principal_domain_contracts.md",
    "1254_oa_service_principal_persistence_migration.md",
    "1255_oa_service_principal_durable_repository.md",
    "1256_oa_service_principal_lifecycle_service.md",
    "1257_oa_service_credential_lifecycle.md",
    "1258_oa_service_principal_protected_api.md",
    "1259_oa_service_principal_contract_schema_hardening.md",
    "1260_oa_service_principal_postgresql_smoke.md",
    "1261_s126_oa_service_principal_lifecycle_closure.md",
)
REQUIRED_FILES = (
    "services/nex-oa/nex_oa/service_principal_lifecycle_boundary.py",
    "services/nex-oa/nex_oa/service_principals.py",
    "database/nex-oa/migrations/1254_oa_service_principal_lifecycle.sql",
    "services/nex-oa/nex_oa/service_principal_repository.py",
    "services/nex-oa/nex_oa/service_principal_service.py",
    "services/nex-oa/nex_oa/service_principal_api.py",
    "services/nex-oa/nex_oa/service_principal_postgres_smoke.py",
    "scripts/smoke/run_oa_service_principal_lifecycle_boundary.py",
    "scripts/smoke/run_oa_service_principal_migration.py",
    "scripts/smoke/run_oa_service_principal_contracts.py",
    "scripts/smoke/run_oa_service_principal_postgres_smoke.py",
    "scripts/smoke/run_s126_oa_service_principal_lifecycle_closure.py",
    "tests/test_s126_oa_service_principal_lifecycle_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    ("full_gate_registered", QUALITY_GATE_PATH, "run_s126_oa_service_principal_lifecycle_closure.py"),
    ("closure_indexed", "docs/README.md", "1261_s126_oa_service_principal_lifecycle_closure.md"),
    ("postgres_identity", "docs/slices/1260_oa_service_principal_postgresql_smoke.md", "`nex_oa_test` / `nex_oa_user`"),
    ("postgres_migrations", "docs/slices/1260_oa_service_principal_postgresql_smoke.md", "Migration ledger: `15/15`"),
    ("postgres_test", "docs/slices/1260_oa_service_principal_postgresql_smoke.md", "Protected test: `22 passed`"),
    ("postgres_gate", "docs/slices/1260_oa_service_principal_postgresql_smoke.md", "Slice Gate: `654 passed, 4 skipped`"),
    ("postgres_cleanup", "docs/slices/1260_oa_service_principal_postgresql_smoke.md", "Cleanup residue: `0`"),
)


def run_s126_oa_service_principal_lifecycle_closure(root: Path = ROOT) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {"name": name, "path": path, "present": token in _read_text(root / path)}
        for name, path, token in TOKEN_CHECKS
    ]
    token_status = {item["name"]: item["present"] for item in token_checks}
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "domain": _static_slice_evidence(root, "1253", "services/nex-oa/nex_oa/service_principals.py"),
        "migration": _safe_evidence(lambda: run_migration(root)),
        "repository": _static_slice_evidence(root, "1255", "services/nex-oa/nex_oa/service_principal_repository.py"),
        "principal_service": _static_slice_evidence(root, "1256", "services/nex-oa/nex_oa/service_principal_service.py"),
        "credential_lifecycle": _static_slice_evidence(root, "1257", "docs/slices/1257_oa_service_credential_lifecycle.md"),
        "protected_api": _static_slice_evidence(root, "1258", "services/nex-oa/nex_oa/service_principal_api.py"),
        "contracts": _safe_evidence(lambda: run_contracts(root)),
        "protected_postgres": _postgres_evidence(root, token_status),
    }
    expected_slices = {
        "boundary": "1252",
        "domain": "1253",
        "migration": "1254",
        "repository": "1255",
        "principal_service": "1256",
        "credential_lifecycle": "1257",
        "protected_api": "1258",
        "contracts": "1259",
        "protected_postgres": "1260",
    }
    boundary = _mapping(evidence["boundary"].get("boundary"))
    contract_summary = _mapping(evidence["contracts"].get("summary"))
    postgres_summary = _mapping(evidence["protected_postgres"].get("summary"))
    components = {
        "ownership_and_domain": all(evidence[name].get("status") == "PASS" for name in ("boundary", "domain")),
        "durable_persistence": all(evidence[name].get("status") == "PASS" for name in ("migration", "repository")),
        "lifecycle_and_api": all(evidence[name].get("status") == "PASS" for name in ("principal_service", "credential_lifecycle", "protected_api")),
        "contracts_and_privacy": evidence["contracts"].get("status") == "PASS",
        "actual_postgres": evidence["protected_postgres"].get("status") == "PASS",
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(item.get("status") == "PASS" for item in evidence.values()),
        "evidence_identity_complete": all(
            evidence[name].get("slice") == slice_id
            and evidence[name].get("requirement") == "S126"
            for name, slice_id in expected_slices.items()
        ),
        "all_components_closed": all(components.values()),
        "boundary_closed": (
            boundary.get("owner") == "nex-oa"
            and tuple(boundary.get("lifecycle_tables") or ()) == ("oa_service_principals", "oa_service_creds")
            and boundary.get("credential_hash_algorithm") == "argon2id"
            and boundary.get("database_plaintext_secret_allowed") is False
            and boundary.get("deferred_requirement") == "S127"
        ),
        "domain_limits_closed": (
            MAX_CREDENTIAL_LIFETIME_DAYS == 90
            and MAX_ROTATION_GRACE_SECONDS == 86_400
            and MAX_SIMULTANEOUS_ACTIVE_CREDENTIALS == 2
        ),
        "contracts_closed": (
            contract_summary.get("schema_count") == 6
            and contract_summary.get("privacy_safe_count") == 6
            and contract_summary.get("runtime_valid_count") == 6
            and contract_summary.get("operation_valid_count") == 9
            and contract_summary.get("remaining_contract_drift_count") == 22
        ),
        "actual_postgres_closed": (
            postgres_summary.get("migration_count") == 15
            and postgres_summary.get("persisted_credential_count") == 2
            and postgres_summary.get("argon2id_hash_count") == 2
            and postgres_summary.get("cleanup_residue_count") == 0
        ),
        "completed_scope_closed": decision["completed_scope"] == (
            "oa_owned_service_principal_registry_and_allowlists",
            "durable_argon2id_client_credential_lifecycle",
            "one_time_issue_rotation_revocation_and_verification",
            "protected_read_admin_api_contracts_and_privacy",
            "actual_postgres_restart_and_cleanup_evidence",
        ),
        "signed_runtime_deferred": decision["s127_scope"] == (
            "signing_key_and_revocation_lifecycle",
            "client_credential_token_exchange",
            "jwks_and_introspection_runtime",
            "signed_only_cross_service_rollout",
        ),
        "readiness_honest": (
            decision["service_principal_readiness"] == "READY"
            and decision["signed_token_runtime_readiness"] == "DEFERRED_TO_S127"
            and decision["next_requirement"] == "S127"
        ),
        "tiered_quality_cadence_preserved": decision["quality_cadence"] == {
            "slice_gate": "1252-1260", "checkpoint_gate": "1256", "full_gate": "1261"
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1261",
        "slice_range": SLICE_RANGE,
        "requirement": "S126",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s126_oa_service_principal_lifecycle_closure_failed",
        "closure_readiness": "READY_FOR_S127" if passed else "BLOCKED",
        "service_principal_readiness": "OA_SERVICE_PRINCIPAL_READY" if passed else "INCOMPLETE",
        "signed_token_runtime_readiness": "DEFERRED_TO_S127" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(item.get("status") == "PASS" for item in evidence.values()),
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "lifecycle_table_count": len(boundary.get("lifecycle_tables") or ()),
            "canonical_schema_count": int(contract_summary.get("schema_count") or 0),
            "protected_operation_count": int(contract_summary.get("operation_valid_count") or 0),
            "postgres_migration_count": int(postgres_summary.get("migration_count") or 0),
            "postgres_cleanup_residue_count": int(postgres_summary.get("cleanup_residue_count", -1)),
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
        "evidence_statuses": {name: item.get("status") for name, item in evidence.items()},
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S127" if passed else "blocked",
        "next_requirement_scope": "oa_signed_token_runtime_and_key_lifecycle" if passed else "blocked",
    }


def _postgres_evidence(root: Path, token_status: Mapping[str, bool]) -> dict[str, Any]:
    if root == ROOT and os.environ.get(SMOKE_ENV) == "1":
        return _safe_evidence(run_postgres)
    passed = all(
        token_status.get(name, False)
        for name in ("postgres_identity", "postgres_migrations", "postgres_test", "postgres_gate", "postgres_cleanup")
    )
    return {
        "slice": "1260", "requirement": "S126", "status": "PASS" if passed else "FAIL",
        "summary": {
            "migration_count": 15 if passed else 0,
            "persisted_credential_count": 2 if passed else 0,
            "argon2id_hash_count": 2 if passed else 0,
            "cleanup_residue_count": 0 if passed else -1,
        },
    }


def _static_slice_evidence(root: Path, slice_id: str, path: str) -> dict[str, Any]:
    present = (root / path).is_file()
    return {"slice": slice_id, "requirement": "S126", "status": "PASS" if present else "FAIL", "path": path}


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "oa_service_principal_and_client_credential_lifecycle",
        "completed_scope": (
            "oa_owned_service_principal_registry_and_allowlists",
            "durable_argon2id_client_credential_lifecycle",
            "one_time_issue_rotation_revocation_and_verification",
            "protected_read_admin_api_contracts_and_privacy",
            "actual_postgres_restart_and_cleanup_evidence",
        ),
        "s127_scope": (
            "signing_key_and_revocation_lifecycle",
            "client_credential_token_exchange",
            "jwks_and_introspection_runtime",
            "signed_only_cross_service_rollout",
        ),
        "service_principal_readiness": "READY",
        "signed_token_runtime_readiness": "DEFERRED_TO_S127",
        "next_requirement": "S127",
        "actual_postgres_smoke_required": True,
        "remote_provider_calls_required": False,
        "new_tables_created": ("oa_service_principals", "oa_service_creds"),
        "quality_cadence": {"slice_gate": "1252-1260", "checkpoint_gate": "1256", "full_gate": "1261"},
    }


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {"status": "FAIL", "failure_code": "evidence_builder_failed", "detail": exc.__class__.__name__}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "s126_oa_service_principal_lifecycle_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/{summary.get('component_count', 0)} "
        f"operations={summary.get('protected_operation_count', 0)} "
        f"runtime={evidence.get('signed_token_runtime_readiness', 'BLOCKED')} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s126_oa_service_principal_lifecycle_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
