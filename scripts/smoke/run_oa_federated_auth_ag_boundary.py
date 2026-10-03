#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.federated_auth_boundary import (  # noqa: E402
    S129_FEDERATED_AUTH_AG_BOUNDARY,
    S129_OA_TABLES,
    validate_federated_auth_ag_boundary,
)


REQUIRED_EVIDENCE = (
    (
        "oa_existing_deferred_boundary",
        "services/nex-oa/nex_oa/auth_boundary.py",
        '"oidc_or_sso_provider_integration"',
    ),
    (
        "oa_session_authority",
        "services/nex-oa/nex_oa/sessions.py",
        "class SqlAlchemyOaSessionRegistry",
    ),
    (
        "oa_authorization_resolution",
        "services/nex-oa/nex_oa/authorization_resolver.py",
        "class OaEffectiveAuthorizationResolver",
    ),
    (
        "ag_user_boundary",
        "services/nex-ag/nex_ag/service_auth.py",
        "validate_user_authorization_header",
    ),
    (
        "s128_signed_service_boundary",
        "docs/slices/1281_s128_platform_signed_token_adoption_closure.md",
        "S128 closes platform-wide",
    ),
    (
        "full_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_oa_federated_auth_ag_boundary.py",
    ),
    (
        "docs_index",
        "docs/README.md",
        "1282_oa_federated_auth_ag_boundary.md",
    ),
    (
        "slice_document",
        "docs/slices/1282_oa_federated_auth_ag_boundary.md",
        "# Slice 1282:",
    ),
)


def run_oa_federated_auth_ag_boundary(root: Path = ROOT) -> dict[str, Any]:
    boundary = S129_FEDERATED_AUTH_AG_BOUNDARY
    evidence = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in REQUIRED_EVIDENCE
    ]
    table_lengths = {name: len(name) for name in boundary.oa_tables}
    checks = {
        "boundary_contract_valid": (
            validate_federated_auth_ag_boundary(boundary.to_wire()) == ()
        ),
        "required_evidence_present": all(item["present"] for item in evidence),
        "oidc_first_and_saml_deferred": (
            boundary.protocols == ("OIDC_AUTHORIZATION_CODE_PKCE",)
            and boundary.deferred_protocols == ("SAML_2_0",)
        ),
        "exact_preprovisioned_linking": (
            boundary.external_identity_linking == "PREPROVISIONED_EXACT_SUBJECT"
            and not boundary.automatic_email_linking_allowed
            and not boundary.automatic_employee_id_linking_allowed
        ),
        "oa_remains_session_authority": boundary.oa_session_issuance_required,
        "ag_consumes_normalized_context_only": (
            not boundary.ag_direct_idp_validation_allowed
            and not boundary.external_token_forwarding_allowed
            and boundary.ag_admin_role_required
        ),
        "cross_service_database_reads_forbidden": (
            not boundary.cross_service_database_reads_allowed
        ),
        "provider_secrets_not_persisted": not boundary.provider_secrets_persisted,
        "table_names_bounded": (
            boundary.oa_tables == S129_OA_TABLES
            and max(table_lengths.values()) <= 30
        ),
        "external_live_idp_not_required": (
            not boundary.live_external_idp_required
            and boundary.protected_loopback_smoke_required
        ),
    }
    issues = [
        {"category": "evidence_missing", "name": item["name"], "path": item["path"]}
        for item in evidence
        if not item["present"]
    ]
    passed = all(checks.values()) and not issues
    return {
        "boundary_schema_version": "oa_federated_auth_ag_boundary.v1",
        "slice": "1282",
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_federated_auth_ag_boundary_failed",
        "boundary": boundary.to_wire(),
        "table_name_lengths": table_lengths,
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
        "slice_plan": (
            "1282_boundary_audit_and_refactoring_checkpoint",
            "1283_oidc_provider_and_external_identity_domain",
            "1284_federation_persistence_migration_and_repository",
            "1285_oidc_discovery_jwks_and_id_token_verifier",
            "1286_federated_login_session_orchestration_and_checkpoint",
            "1287_ag_federated_operator_context_adoption",
            "1288_ag_federated_authorization_and_audit_hardening",
            "1289_contract_observability_and_privacy_hardening",
            "1290_actual_postgres_and_loopback_oidc_smoke",
            "1291_s129_closure_and_full_gate",
        ),
        "next_slice": "1283" if passed else "blocked",
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    return (
        "oa_federated_auth_ag_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"tables={len((evidence.get('boundary') or {}).get('oa_tables') or ())} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_federated_auth_ag_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
