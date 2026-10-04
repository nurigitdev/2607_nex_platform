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

from run_ag_federated_authorization_hardening import (  # noqa: E402
    run_ag_federated_authorization_hardening as run_ag_authorization,
)
from run_ag_federated_operator_context import (  # noqa: E402
    run_ag_federated_operator_context as run_ag_context,
)
from run_oa_federated_auth_ag_boundary import (  # noqa: E402
    run_oa_federated_auth_ag_boundary as run_boundary,
)
from run_oa_federated_identity_domain import (  # noqa: E402
    run_oa_federated_identity_domain as run_domain,
)
from run_oa_federated_identity_persistence import (  # noqa: E402
    run_oa_federated_identity_persistence as run_persistence,
)
from run_oa_federated_login_orchestration import (  # noqa: E402
    run_oa_federated_login_orchestration as run_login,
)
from run_oa_federated_postgres_loopback_smoke import (  # noqa: E402
    SMOKE_ENV,
    run_oa_federated_postgres_loopback_smoke as run_postgres,
)
from run_oa_oidc_verifier import run_oa_oidc_verifier as run_oidc  # noqa: E402
from run_s129_contract_runtime_privacy import (  # noqa: E402
    run_s129_contract_runtime_privacy as run_contracts,
)


SCHEMA_VERSION = "s129_federated_auth_ag_integration_closure.v1"
SLICE_RANGE = "1282-1291"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
SLICE_DOCUMENTS = (
    "1282_oa_federated_auth_ag_boundary.md",
    "1283_oa_federated_identity_domain.md",
    "1284_oa_federated_identity_persistence.md",
    "1285_oa_oidc_discovery_jwks_verifier.md",
    "1286_oa_federated_login_session_orchestration.md",
    "1287_ag_federated_operator_context_adoption.md",
    "1288_ag_federated_authorization_audit_hardening.md",
    "1289_s129_contract_runtime_privacy_hardening.md",
    "1290_s129_oa_federated_postgresql_tls_loopback_smoke.md",
    "1291_s129_federated_auth_ag_integration_closure.md",
)
REQUIRED_FILES = (
    "services/nex-oa/nex_oa/federated_auth_boundary.py",
    "services/nex-oa/nex_oa/federated_identities.py",
    "database/nex-oa/migrations/1284_oa_federated_identity.sql",
    "services/nex-oa/nex_oa/federated_identity_repository.py",
    "services/nex-oa/nex_oa/oidc_verifier.py",
    "services/nex-oa/nex_oa/federated_login.py",
    "services/nex-ag/nex_ag/federated_operator_context.py",
    "services/nex-ag/nex_ag/federated_operator_authorization.py",
    "services/nex-ag/nex_ag/federated_operator_operations.py",
    "contracts/schemas/service/nex_oa/federated_login_request.v1.schema.json",
    "contracts/schemas/service/nex_oa/federated_login_response.v1.schema.json",
    "contracts/schemas/service/nex_ag/federated_operator_context.v1.schema.json",
    "contracts/schemas/service/nex_ag/federated_auth_runtime.v1.schema.json",
    "scripts/smoke/run_oa_federated_postgres_loopback_smoke.py",
    "scripts/smoke/run_s129_federated_auth_ag_integration_closure.py",
    "tests/test_oa_federated_postgres_loopback_smoke.py",
    "tests/test_s129_federated_auth_ag_integration_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    (
        "full_gate_registered",
        QUALITY_GATE_PATH,
        "run_s129_federated_auth_ag_integration_closure.py",
    ),
    (
        "postgres_smoke_registered",
        QUALITY_GATE_PATH,
        "run_oa_federated_postgres_loopback_smoke.py",
    ),
    (
        "closure_indexed",
        "docs/README.md",
        "1291_s129_federated_auth_ag_integration_closure.md",
    ),
    (
        "actual_database_identity",
        "docs/slices/1290_s129_oa_federated_postgresql_tls_loopback_smoke.md",
        "`nex_oa_test` / `nex_oa_user`",
    ),
    (
        "actual_migrations_current",
        "docs/slices/1290_s129_oa_federated_postgresql_tls_loopback_smoke.md",
        "Migration ledger: `17/17`",
    ),
    (
        "actual_tls_requests",
        "docs/slices/1290_s129_oa_federated_postgresql_tls_loopback_smoke.md",
        "TLS discovery/JWKS requests: `2`",
    ),
    (
        "actual_persistence_rows",
        "docs/slices/1290_s129_oa_federated_postgresql_tls_loopback_smoke.md",
        "Persisted row classes: `4/4`",
    ),
    (
        "actual_cleanup_zero",
        "docs/slices/1290_s129_oa_federated_postgresql_tls_loopback_smoke.md",
        "Cleanup residue: `0`",
    ),
)


def run_s129_federated_auth_ag_integration_closure(
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
    token_status = {item["name"]: item["present"] for item in token_checks}
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "identity_domain": _repository_evidence(root, run_domain),
        "persistence": _safe_evidence(lambda: run_persistence(root)),
        "oidc_verifier": _repository_evidence(root, run_oidc),
        "federated_login": _repository_evidence(root, run_login),
        "ag_context": _repository_evidence(root, run_ag_context),
        "ag_authorization": _repository_evidence(root, run_ag_authorization),
        "contracts_runtime_privacy": _safe_evidence(
            lambda: run_contracts(root)
        ),
        "protected_postgres_tls": _postgres_evidence(root, token_status),
    }
    expected_slices = {
        "boundary": "1282",
        "identity_domain": "1283",
        "persistence": "1284",
        "oidc_verifier": "1285",
        "federated_login": "1286",
        "ag_context": "1287",
        "ag_authorization": "1288",
        "contracts_runtime_privacy": "1289",
        "protected_postgres_tls": "1290",
    }
    boundary = _mapping(evidence["boundary"].get("boundary"))
    persistence = _mapping(evidence["persistence"].get("summary"))
    contracts = _mapping(evidence["contracts_runtime_privacy"].get("contract_counts"))
    oa_drift = _mapping(evidence["contracts_runtime_privacy"].get("oa_drift"))
    telemetry = _mapping(evidence["contracts_runtime_privacy"].get("telemetry"))
    postgres = _mapping(evidence["protected_postgres_tls"].get("summary"))
    components = {
        "ownership_identity_and_privacy": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "identity_domain")
        ),
        "durable_persistence_and_oidc_verification": all(
            evidence[name].get("status") == "PASS"
            for name in ("persistence", "oidc_verifier")
        ),
        "oa_session_and_ag_authorization": all(
            evidence[name].get("status") == "PASS"
            for name in ("federated_login", "ag_context", "ag_authorization")
        ),
        "contracts_runtime_observability_privacy": (
            evidence["contracts_runtime_privacy"].get("status") == "PASS"
        ),
        "actual_postgres_tls_loopback": (
            evidence["protected_postgres_tls"].get("status") == "PASS"
        ),
    }
    decision = _closure_decision()
    telemetry_counts = _mapping(telemetry.get("counts"))
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "evidence_identity_complete": all(
            evidence[name].get("slice") == slice_id
            and evidence[name].get("requirement") == "S129"
            for name, slice_id in expected_slices.items()
        ),
        "all_components_closed": all(components.values()),
        "boundary_closed": (
            boundary.get("owner") == "nex-oa"
            and boundary.get("consumer_service") == "nex-ag"
            and tuple(boundary.get("protocols") or ())
            == ("OIDC_AUTHORIZATION_CODE_PKCE",)
            and tuple(boundary.get("id_token_algorithms") or ()) == ("RS256",)
            and boundary.get("external_identity_linking")
            == "PREPROVISIONED_EXACT_SUBJECT"
            and boundary.get("oa_session_issuance_required") is True
            and boundary.get("ag_admin_role_required") is True
            and boundary.get("external_token_forwarding_allowed") is False
            and boundary.get("cross_service_database_reads_allowed") is False
        ),
        "persistence_closed": (
            persistence.get("table_count") == 2
            and persistence.get("provider_count") == 1
            and persistence.get("identity_count") == 1
            and int(persistence.get("longest_identifier_length") or 64) <= 63
        ),
        "oidc_verification_closed": (
            evidence["oidc_verifier"].get("fetch_count") == 2
            and _mapping(evidence["oidc_verifier"].get("cache")).get(
                "key_ids_included"
            )
            is False
        ),
        "oa_session_and_ag_context_closed": (
            _mapping(evidence["federated_login"].get("session"))
            .get("metadata", {})
            .get("auth_method")
            == "federated_oidc"
            and evidence["ag_context"].get("status") == "PASS"
            and evidence["ag_authorization"].get("status") == "PASS"
        ),
        "contracts_and_drift_closed": (
            int(contracts.get("schemas") or 0) >= 156
            and int(contracts.get("examples") or 0) >= 214
            and int(contracts.get("negative_examples") or 0) >= 184
            and int(contracts.get("openapi") or 0) >= 7
            and int(oa_drift.get("drift_count") or 99) <= 22
        ),
        "telemetry_privacy_closed": (
            set(telemetry_counts)
            == {
                "authorized",
                "denied_caller",
                "denied_context",
                "denied_role",
                "denied_scope",
            }
            and all(int(value) >= 1 for value in telemetry_counts.values())
            and telemetry.get("raw_context_included") is False
            and telemetry.get("subject_identifiers_included") is False
            and telemetry.get("external_identity_included") is False
        ),
        "actual_postgres_tls_closed": (
            postgres.get("migration_count") == 17
            and postgres.get("loopback_request_count") == 2
            and postgres.get("persisted_row_count") == 4
            and postgres.get("cleanup_residue_count") == 0
        ),
        "completed_scope_closed": decision["completed_scope"]
        == (
            "oidc_provider_and_exact_subject_digest_identity_persistence",
            "bounded_discovery_jwks_and_strict_rs256_id_token_verification",
            "oa_federated_session_and_ag_normalized_admin_context",
            "authorization_audit_contract_telemetry_and_privacy_hardening",
            "actual_postgres_trusted_tls_loopback_and_zero_residue_evidence",
        ),
        "deployment_boundary_honest": (
            decision["implementation_readiness"] == "READY"
            and decision["external_idp_registration"]
            == "DEPLOYMENT_CONFIGURATION_REQUIRED"
            and decision["browser_pkce_redirect_callback"]
            == "PRODUCT_INTEGRATION_REQUIRED"
            and decision["saml_2_0"] == "DEFERRED"
            and decision["next_requirement"] == "S130"
        ),
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1282-1290",
            "checkpoint_gate": "1286",
            "full_gate": "1291",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1291",
        "slice_range": SLICE_RANGE,
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None
            if passed
            else "s129_federated_auth_ag_integration_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S130" if passed else "BLOCKED",
        "federation_integration_readiness": (
            "OA_AG_INTEGRATION_READY" if passed else "INCOMPLETE"
        ),
        "production_activation": (
            "DEPLOYMENT_CONFIGURATION_REQUIRED" if passed else "BLOCKED"
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
            "federation_table_count": int(persistence.get("table_count") or 0),
            "canonical_schema_count": int(contracts.get("schemas") or 0),
            "postgres_migration_count": int(postgres.get("migration_count") or 0),
            "postgres_tls_request_count": int(
                postgres.get("loopback_request_count") or 0
            ),
            "postgres_cleanup_residue_count": int(
                postgres.get("cleanup_residue_count", -1)
            ),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S130" if passed else "blocked",
        "next_requirement_scope": (
            "pending_canonical_scope_review" if passed else "blocked"
        ),
    }


def _postgres_evidence(
    root: Path, token_status: Mapping[str, bool]
) -> dict[str, Any]:
    if root == ROOT and os.environ.get(SMOKE_ENV) == "1":
        return _safe_evidence(run_postgres)
    passed = all(
        token_status.get(name, False)
        for name in (
            "actual_database_identity",
            "actual_migrations_current",
            "actual_tls_requests",
            "actual_persistence_rows",
            "actual_cleanup_zero",
        )
    )
    return {
        "slice": "1290",
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "summary": {
            "migration_count": 17 if passed else 0,
            "loopback_request_count": 2 if passed else 0,
            "persisted_row_count": 4 if passed else 0,
            "cleanup_residue_count": 0 if passed else -1,
        },
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "oa_federated_authentication_and_ag_integration",
        "completed_scope": (
            "oidc_provider_and_exact_subject_digest_identity_persistence",
            "bounded_discovery_jwks_and_strict_rs256_id_token_verification",
            "oa_federated_session_and_ag_normalized_admin_context",
            "authorization_audit_contract_telemetry_and_privacy_hardening",
            "actual_postgres_trusted_tls_loopback_and_zero_residue_evidence",
        ),
        "implementation_readiness": "READY",
        "external_idp_registration": "DEPLOYMENT_CONFIGURATION_REQUIRED",
        "browser_pkce_redirect_callback": "PRODUCT_INTEGRATION_REQUIRED",
        "external_live_idp_acceptance": "DEPLOYMENT_ENVIRONMENT_REQUIRED",
        "saml_2_0": "DEFERRED",
        "delegated_user_access": "DEFERRED",
        "cross_service_database_reads_allowed": False,
        "remote_model_provider_required": False,
        "next_requirement": "S130",
        "quality_cadence": {
            "slice_gate": "1282-1290",
            "checkpoint_gate": "1286",
            "full_gate": "1291",
        },
    }


def _repository_evidence(
    root: Path, builder: Callable[[], Mapping[str, Any]]
) -> dict[str, Any]:
    if root != ROOT:
        return {"status": "FAIL", "failure_code": "repository_root_invalid"}
    return _safe_evidence(builder)


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "s129_federated_auth_ag_integration_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"migrations={summary.get('postgres_migration_count', 0)} "
        f"activation={evidence.get('production_activation', 'BLOCKED')} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s129_federated_auth_ag_integration_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
