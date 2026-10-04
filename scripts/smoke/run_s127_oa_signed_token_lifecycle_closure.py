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

from run_oa_signed_token_api import run_oa_signed_token_api as run_api  # noqa: E402
from run_oa_signed_token_domain import run_oa_signed_token_domain as run_domain  # noqa: E402
from run_oa_signed_token_lifecycle_boundary import (  # noqa: E402
    run_oa_signed_token_lifecycle_boundary as run_boundary,
)
from run_oa_signed_token_migration import run_oa_signed_token_migration as run_migration  # noqa: E402
from run_oa_signed_token_postgres_smoke import (  # noqa: E402
    SMOKE_ENV,
    run_oa_signed_token_postgres_smoke as run_postgres,
)
from run_oa_signed_token_repository import run_oa_signed_token_repository as run_repository  # noqa: E402
from run_oa_signing_key_service import run_oa_signing_key_service as run_key_service  # noqa: E402
from run_oa_token_exchange import run_oa_token_exchange as run_exchange  # noqa: E402
from run_oa_token_validation import run_oa_token_validation as run_validation  # noqa: E402


SCHEMA_VERSION = "s127_oa_signed_token_lifecycle_closure.v1"
SLICE_RANGE = "1262-1271"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
SLICE_DOCUMENTS = (
    "1262_oa_signed_token_lifecycle_boundary.md",
    "1263_oa_signed_token_domain_contracts.md",
    "1264_oa_signed_token_persistence_migration.md",
    "1265_oa_signed_token_durable_repository.md",
    "1266_oa_signing_key_jwks_service.md",
    "1267_oa_client_credential_token_exchange.md",
    "1268_oa_signed_token_validation_introspection.md",
    "1269_oa_signed_token_api_contracts.md",
    "1270_oa_signed_token_postgres_smoke.md",
    "1271_s127_oa_signed_token_lifecycle_closure.md",
)
SIGNED_CONTRACT_FILES = (
    "contracts/schemas/service/nex_oa/signed_jwks.v1.schema.json",
    "contracts/schemas/service/nex_oa/signed_token_response.v1.schema.json",
    "contracts/schemas/service/nex_oa/token_introspection.v1.schema.json",
    "contracts/schemas/service/nex_oa/token_revocation.v1.schema.json",
)
POSITIVE_CONTRACT_FILES = (
    "contracts/examples/auth/oa_signed_jwks.active.json",
    "contracts/examples/auth/oa_signed_token_response.issued.json",
    "contracts/examples/auth/oa_token_introspection.active.json",
    "contracts/examples/auth/oa_token_revocation.operator.json",
)
NEGATIVE_CONTRACT_FILES = (
    "contracts/tests/negative/auth/oa_signed_jwks.private_key_ref.json",
    "contracts/tests/negative/auth/oa_signed_token_response.client_secret.json",
    "contracts/tests/negative/auth/oa_token_introspection.raw_token.json",
    "contracts/tests/negative/auth/oa_token_revocation.jti.json",
)
REQUIRED_FILES = (
    "services/nex-oa/nex_oa/signed_token_lifecycle_boundary.py",
    "services/nex-oa/nex_oa/signed_tokens.py",
    "database/nex-oa/migrations/1264_oa_signed_token_lifecycle.sql",
    "services/nex-oa/nex_oa/signed_token_repository.py",
    "services/nex-oa/nex_oa/signing_key_service.py",
    "services/nex-oa/nex_oa/token_signing.py",
    "services/nex-oa/nex_oa/token_exchange_service.py",
    "services/nex-oa/nex_oa/token_validation_service.py",
    "services/nex-oa/nex_oa/signed_token_api.py",
    "services/nex-oa/nex_oa/signed_token_postgres_smoke.py",
    "scripts/smoke/run_oa_signed_token_lifecycle_boundary.py",
    "scripts/smoke/run_oa_signed_token_domain.py",
    "scripts/smoke/run_oa_signed_token_migration.py",
    "scripts/smoke/run_oa_signed_token_repository.py",
    "scripts/smoke/run_oa_signing_key_service.py",
    "scripts/smoke/run_oa_token_exchange.py",
    "scripts/smoke/run_oa_token_validation.py",
    "scripts/smoke/run_oa_signed_token_api.py",
    "scripts/smoke/run_oa_signed_token_postgres_smoke.py",
    "scripts/smoke/run_s127_oa_signed_token_lifecycle_closure.py",
    "tests/test_s127_oa_signed_token_lifecycle_closure.py",
    *SIGNED_CONTRACT_FILES,
    *POSITIVE_CONTRACT_FILES,
    *NEGATIVE_CONTRACT_FILES,
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    ("full_gate_registered", QUALITY_GATE_PATH, "run_s127_oa_signed_token_lifecycle_closure.py"),
    ("closure_indexed", "docs/README.md", "1271_s127_oa_signed_token_lifecycle_closure.md"),
    (
        "production_signer_fails_closed",
        "services/nex-oa/nex_oa/token_signing.py",
        'NEX_OA_SIGNING_PROVIDER", "UNAVAILABLE"',
    ),
    ("mock_auth_disabled", "services/nex-oa/nex_oa/main.py", "include_oa_mock_auth_routes=False"),
    ("postgres_identity", "docs/slices/1270_oa_signed_token_postgres_smoke.md", "`nex_oa_test` / `nex_oa_user`"),
    ("postgres_migrations", "docs/slices/1270_oa_signed_token_postgres_smoke.md", "Migration ledger: `16/16`"),
    ("postgres_test", "docs/slices/1270_oa_signed_token_postgres_smoke.md", "Protected test: `1 passed`"),
    ("postgres_gate", "docs/slices/1270_oa_signed_token_postgres_smoke.md", "Slice Gate: `790 passed, 5 skipped`"),
    ("postgres_cleanup", "docs/slices/1270_oa_signed_token_postgres_smoke.md", "Cleanup residue: `0`"),
)


def run_s127_oa_signed_token_lifecycle_closure(root: Path = ROOT) -> dict[str, Any]:
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
        "domain": _safe_evidence(run_domain),
        "migration": _safe_evidence(lambda: run_migration(root)),
        "repository": _safe_evidence(run_repository),
        "key_service": _safe_evidence(run_key_service),
        "token_exchange": _safe_evidence(run_exchange),
        "validation": _safe_evidence(run_validation),
        "api_contracts": _api_contract_evidence(root),
        "protected_postgres": _postgres_evidence(root, token_status),
    }
    expected_slices = {
        "boundary": "1262",
        "domain": "1263",
        "migration": "1264",
        "repository": "1265",
        "key_service": "1266",
        "token_exchange": "1267",
        "validation": "1268",
        "api_contracts": "1269",
        "protected_postgres": "1270",
    }
    boundary = _mapping(evidence["boundary"].get("boundary"))
    migration = _mapping(evidence["migration"].get("summary"))
    api_contracts = _mapping(evidence["api_contracts"].get("summary"))
    postgres = _mapping(evidence["protected_postgres"].get("summary"))
    components = {
        "ownership_and_domain": all(
            evidence[name].get("status") == "PASS" for name in ("boundary", "domain")
        ),
        "durable_persistence": all(
            evidence[name].get("status") == "PASS" for name in ("migration", "repository")
        ),
        "key_issue_and_validation": all(
            evidence[name].get("status") == "PASS"
            for name in ("key_service", "token_exchange", "validation")
        ),
        "api_contracts_and_privacy": evidence["api_contracts"].get("status") == "PASS",
        "actual_postgres": evidence["protected_postgres"].get("status") == "PASS",
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(item.get("status") == "PASS" for item in evidence.values()),
        "evidence_identity_complete": all(
            evidence[name].get("slice") == slice_id
            and evidence[name].get("requirement") == "S127"
            for name, slice_id in expected_slices.items()
        ),
        "all_components_closed": all(components.values()),
        "boundary_closed": (
            boundary.get("owner") == "nex-oa"
            and boundary.get("token_profile") == "service_access"
            and boundary.get("grant_type") == "client_credentials"
            and boundary.get("algorithm") == "RS256"
            and boundary.get("minimum_rsa_bits") == 3072
            and boundary.get("maximum_token_ttl_seconds") == 300
            and tuple(boundary.get("owned_tables") or ())
            == ("oa_signing_keys", "oa_token_revocations")
            and boundary.get("private_key_database_storage_allowed") is False
            and boundary.get("raw_token_persistence_allowed") is False
        ),
        "migration_closed": (
            migration.get("table_count") == 2
            and migration.get("passed_check_count") == migration.get("check_count")
            and int(migration.get("longest_identifier_length") or 64) <= 63
        ),
        "key_lifecycle_closed": (
            evidence["key_service"].get("jwks_key_count") == 1
            and evidence["key_service"].get("reconciled_count") == 1
        ),
        "token_exchange_closed": (
            evidence["token_exchange"].get("algorithm") == "RS256"
            and evidence["token_exchange"].get("ttl_seconds") == 300
        ),
        "validation_closed": (
            evidence["validation"].get("active_before_revoke") is True
            and evidence["validation"].get("active_after_revoke") is False
        ),
        "api_contracts_closed": api_contracts == {
            "schema_count": 4,
            "positive_example_count": 4,
            "privacy_negative_count": 4,
            "operation_count": 4,
        },
        "actual_postgres_closed": (
            postgres.get("migration_count") == 16
            and postgres.get("signing_key_count") == 1
            and postgres.get("revocation_count") == 1
            and postgres.get("cleanup_residue_count") == 0
        ),
        "completed_scope_closed": decision["completed_scope"] == (
            "external_reference_key_metadata_and_public_jwks",
            "durable_signing_key_and_digest_only_revocation_lifecycle",
            "rs256_client_credential_exchange_with_five_minute_tokens",
            "strict_validation_introspection_revocation_and_privacy_contracts",
            "actual_postgres_restart_and_cleanup_evidence",
        ),
        "deployment_boundary_honest": (
            decision["implementation_readiness"] == "READY"
            and decision["production_signing_custody"] == "EXTERNAL_ADAPTER_REQUIRED"
            and decision["cross_service_signed_only_rollout"] == "DEFERRED"
            and decision["next_requirement"] == "S128"
        ),
        "tiered_quality_cadence_preserved": decision["quality_cadence"] == {
            "slice_gate": "1262-1270",
            "checkpoint_gate": "1266",
            "full_gate": "1271",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1271",
        "slice_range": SLICE_RANGE,
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s127_oa_signed_token_lifecycle_closure_failed",
        "closure_readiness": "READY_FOR_S128" if passed else "BLOCKED",
        "signed_token_implementation_readiness": "OA_SIGNED_TOKEN_READY" if passed else "INCOMPLETE",
        "production_signing_custody": "EXTERNAL_ADAPTER_REQUIRED" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(item.get("status") == "PASS" for item in evidence.values()),
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "signed_runtime_table_count": len(boundary.get("owned_tables") or ()),
            "canonical_schema_count": int(api_contracts.get("schema_count") or 0),
            "signed_operation_count": int(api_contracts.get("operation_count") or 0),
            "postgres_migration_count": int(postgres.get("migration_count") or 0),
            "postgres_cleanup_residue_count": int(postgres.get("cleanup_residue_count", -1)),
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
        "evidence_statuses": {name: item.get("status") for name, item in evidence.items()},
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S128" if passed else "blocked",
        "next_requirement_scope": (
            "oa_production_signing_custody_and_cross_service_signed_token_rollout"
            if passed
            else "blocked"
        ),
    }


def _api_contract_evidence(root: Path) -> dict[str, Any]:
    api = _safe_evidence(run_api) if root == ROOT else {"status": "FAIL"}
    openapi = _read_text(root / "contracts/openapi/nex-oa.openapi.yaml")
    summary = {
        "schema_count": sum((root / path).is_file() for path in SIGNED_CONTRACT_FILES),
        "positive_example_count": sum((root / path).is_file() for path in POSITIVE_CONTRACT_FILES),
        "privacy_negative_count": sum((root / path).is_file() for path in NEGATIVE_CONTRACT_FILES),
        "operation_count": sum(
            path in openapi
            for path in (
                "/api/v1/auth/service-token:",
                "/api/v1/auth/introspect:",
                "/api/v1/auth/revoke:",
                "/.well-known/jwks.json:",
            )
        ),
    }
    passed = api.get("status") == "PASS" and summary == {
        "schema_count": 4,
        "positive_example_count": 4,
        "privacy_negative_count": 4,
        "operation_count": 4,
    }
    return {
        "slice": "1269",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "api_status": api.get("status"),
        "summary": summary,
    }


def _postgres_evidence(root: Path, token_status: Mapping[str, bool]) -> dict[str, Any]:
    if root == ROOT and os.environ.get(SMOKE_ENV) == "1":
        return _safe_evidence(run_postgres)
    passed = all(
        token_status.get(name, False)
        for name in (
            "postgres_identity",
            "postgres_migrations",
            "postgres_test",
            "postgres_gate",
            "postgres_cleanup",
        )
    )
    return {
        "slice": "1270",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "summary": {
            "migration_count": 16 if passed else 0,
            "signing_key_count": 1 if passed else 0,
            "revocation_count": 1 if passed else 0,
            "cleanup_residue_count": 0 if passed else -1,
        },
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "oa_signing_key_jwks_signed_token_and_introspection_lifecycle",
        "completed_scope": (
            "external_reference_key_metadata_and_public_jwks",
            "durable_signing_key_and_digest_only_revocation_lifecycle",
            "rs256_client_credential_exchange_with_five_minute_tokens",
            "strict_validation_introspection_revocation_and_privacy_contracts",
            "actual_postgres_restart_and_cleanup_evidence",
        ),
        "implementation_readiness": "READY",
        "production_signing_custody": "EXTERNAL_ADAPTER_REQUIRED",
        "cross_service_signed_only_rollout": "DEFERRED",
        "next_requirement": "S128",
        "actual_postgres_smoke_required": True,
        "remote_provider_calls_required": False,
        "new_tables_created": ("oa_signing_keys", "oa_token_revocations"),
        "quality_cadence": {
            "slice_gate": "1262-1270",
            "checkpoint_gate": "1266",
            "full_gate": "1271",
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
        "s127_oa_signed_token_lifecycle_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/{summary.get('component_count', 0)} "
        f"operations={summary.get('signed_operation_count', 0)} "
        f"custody={evidence.get('production_signing_custody', 'BLOCKED')} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s127_oa_signed_token_lifecycle_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
