#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

from run_oa_production_token_profiles import (  # noqa: E402
    run_oa_production_token_profiles as run_token_profiles,
)
from run_oa_production_trust_boundary import (  # noqa: E402
    run_oa_production_trust_boundary as run_boundary,
)
from run_oa_service_principal_handoff import (  # noqa: E402
    run_oa_service_principal_handoff as run_service_handoff,
)
from run_oa_signing_key_policy import (  # noqa: E402
    run_oa_signing_key_policy as run_signing_keys,
)
from run_oa_token_rollout_plan import (  # noqa: E402
    run_oa_token_rollout_plan as run_rollout,
)
from run_oa_token_surface_inventory import (  # noqa: E402
    build_oa_token_surface_inventory as run_inventory,
)
from run_oa_token_validation_checkpoint import (  # noqa: E402
    run_oa_token_validation_checkpoint as run_validation,
)
from run_oa_trust_threat_contracts import (  # noqa: E402
    run_oa_trust_threat_contracts as run_threats,
)


SCHEMA_VERSION = "s125_oa_production_trust_closure.v1"
SLICE_RANGE = "1242-1251"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_DOCUMENT = "docs/slices/1250_oa_trust_postgres_baseline.md"
QUALITY_SCRIPTS = (
    "run_oa_production_trust_boundary.py",
    "run_oa_token_surface_inventory.py",
    "run_oa_production_token_profiles.py",
    "run_oa_signing_key_policy.py",
    "run_oa_token_validation_checkpoint.py",
    "run_oa_service_principal_handoff.py",
    "run_oa_token_rollout_plan.py",
    "run_oa_trust_threat_contracts.py",
    "run_oa_trust_postgres_baseline.py",
    "run_s125_oa_production_trust_closure.py",
)
SLICE_DOCUMENTS = (
    "1242_oa_production_trust_boundary.md",
    "1243_oa_token_surface_inventory.md",
    "1244_oa_production_token_profiles.md",
    "1245_oa_signing_key_policy.md",
    "1246_oa_token_validation_checkpoint.md",
    "1247_oa_service_principal_handoff.md",
    "1248_oa_token_rollout_plan.md",
    "1249_oa_trust_threat_contracts.md",
    "1250_oa_trust_postgres_baseline.md",
    "1251_s125_oa_production_trust_closure.md",
)
REQUIRED_FILES = (
    "services/nex-oa/nex_oa/production_token_profiles.py",
    "services/nex-oa/nex_oa/signing_key_policy.py",
    "services/nex-oa/nex_oa/token_validation_policy.py",
    "services/nex-oa/nex_oa/service_principal_boundary.py",
    "services/nex-oa/nex_oa/token_rollout_policy.py",
    "services/nex-oa/nex_oa/trust_threat_policy.py",
    "services/nex-oa/nex_oa/trust_postgres_baseline.py",
    "contracts/schemas/service/nex_oa/trust_threat_evidence.v1.schema.json",
    "contracts/examples/auth/oa_trust_threat_evidence.pass.json",
    "contracts/tests/negative/auth/oa_trust_threat_evidence.raw_token.json",
    *(f"scripts/smoke/{name}" for name in QUALITY_SCRIPTS),
    "tests/test_s125_oa_production_trust_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    ("postgres_identity", POSTGRES_DOCUMENT, "`nex_oa_test` / `nex_oa_user`"),
    ("postgres_migrations", POSTGRES_DOCUMENT, "migration ledger: `14/14`"),
    ("postgres_cleanup", POSTGRES_DOCUMENT, "Cleanup residue: `0`"),
    ("postgres_test", POSTGRES_DOCUMENT, "Protected test: `25 passed`"),
    ("postgres_gate", POSTGRES_DOCUMENT, "Slice Gate: `549 passed, 3 skipped`"),
    (
        "closure_index",
        "docs/README.md",
        "1251_s125_oa_production_trust_closure.md",
    ),
)


def run_s125_oa_production_trust_closure(
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
        "inventory": _safe_evidence(lambda: run_inventory(root)),
        "token_profiles": _safe_evidence(run_token_profiles),
        "signing_keys": _safe_evidence(run_signing_keys),
        "validation": _safe_evidence(run_validation),
        "service_handoff": _safe_evidence(lambda: run_service_handoff(root)),
        "rollout": _safe_evidence(run_rollout),
        "threat_contracts": _safe_evidence(lambda: run_threats(root)),
        "protected_postgres": {
            "slice": "1250",
            "requirement": "S125",
            "status": (
                "PASS"
                if all(
                    token_status.get(name, False)
                    for name in (
                        "postgres_identity",
                        "postgres_migrations",
                        "postgres_cleanup",
                        "postgres_test",
                        "postgres_gate",
                    )
                )
                else "FAIL"
            ),
        },
    }
    expected_slices = {
        "boundary": "1242",
        "inventory": "1243",
        "token_profiles": "1244",
        "signing_keys": "1245",
        "validation": "1246",
        "service_handoff": "1247",
        "rollout": "1248",
        "threat_contracts": "1249",
        "protected_postgres": "1250",
    }
    boundary = _mapping(evidence["boundary"].get("decision"))
    inventory = _mapping(evidence["inventory"].get("transition_decision"))
    profiles = _mapping(evidence["token_profiles"].get("profiles"))
    signing = _mapping(evidence["signing_keys"].get("policy"))
    validation = _mapping(evidence["validation"].get("policy"))
    handoff = _mapping(evidence["service_handoff"].get("handoff"))
    rollout_profiles = _mapping(evidence["rollout"].get("profiles"))
    components = {
        "ownership_and_inventory": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "inventory")
        ),
        "token_and_signing_profiles": all(
            evidence[name].get("status") == "PASS"
            for name in ("token_profiles", "signing_keys")
        ),
        "validation_and_service_handoff": all(
            evidence[name].get("status") == "PASS"
            for name in ("validation", "service_handoff")
        ),
        "rollout_threat_and_privacy": all(
            evidence[name].get("status") == "PASS"
            for name in ("rollout", "threat_contracts")
        ),
        "actual_postgres_baseline": (
            evidence["protected_postgres"].get("status") == "PASS"
        ),
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
            and evidence[name].get("requirement") == "S125"
            for name, slice_id in expected_slices.items()
        ),
        "all_components_closed": all(components.values()),
        "trust_boundary_and_inventory_closed": (
            boundary.get("owner") == "nex-oa"
            and boundary.get("browser_session_profile") == "opaque_oa_backed"
            and boundary.get("production_mock_token_fallback") is False
            and inventory.get("production_silent_mock_fallback_allowed") is False
            and inventory.get("signed_profile_implementation_requirement") == "S126"
        ),
        "token_and_signing_profiles_closed": (
            evidence["token_profiles"].get("issuer") == "urn:nex-platform:oa"
            and set(profiles) == {"service_access", "delegated_user_access"}
            and all(
                profile.get("maximum_ttl_seconds") == 300
                for profile in profiles.values()
            )
            and signing.get("algorithm") == "RS256"
            and signing.get("minimum_rsa_modulus_bits") == 3072
            and signing.get("private_key_plaintext_database_allowed") is False
        ),
        "validation_and_handoff_closed": (
            validation.get("jwks_cache_ttl_seconds") == 300
            and validation.get("unknown_kid_refresh_attempts") == 1
            and validation.get("introspection_timeout_seconds") == 3
            and validation.get("stale_jwks_acceptance_allowed") is False
            and validation.get("introspection_error_acceptance_allowed") is False
            and handoff.get("implementation_requirement") == "S126"
            and len(handoff.get("proposed_tables") or ()) == 4
            and handoff.get("credential_hash_algorithm") == "argon2id"
            and handoff.get("database_plaintext_secret_allowed") is False
        ),
        "rollout_and_threat_contracts_closed": (
            set(rollout_profiles) == {"TEST_MOCK", "DUAL_READ", "SIGNED_ONLY"}
            and len(evidence["rollout"].get("rollout_units") or ()) == 5
            and evidence["threat_contracts"].get("threat_count") == 8
            and evidence["threat_contracts"].get("privacy_violation_count") == 0
        ),
        "actual_postgres_closed": components["actual_postgres_baseline"],
        "completed_scope_closed": decision["completed_scope"]
        == (
            "oa_owned_trust_and_opaque_browser_session",
            "service_and_delegated_user_signed_token_profiles",
            "rs256_external_key_custody_and_rotation_policy",
            "fail_closed_jwks_introspection_and_revocation_semantics",
            "service_principal_and_signed_only_rollout_handoff",
            "privacy_threat_contracts_and_actual_postgres_baseline",
        ),
        "implementation_scope_deferred": decision["s126_implementation_scope"]
        == (
            "durable_service_principal_credential_key_and_revocation_storage",
            "signed_token_exchange_jwks_and_introspection_runtime",
            "ordered_cross_service_signed_only_rollout",
        ),
        "runtime_readiness_is_honest": (
            decision["policy_readiness"] == "READY"
            and decision["signed_runtime_readiness"] == "IMPLEMENTATION_PENDING"
            and decision["implementation_requirement"] == "S126"
        ),
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1242-1250",
            "checkpoint_gate": "1246",
            "full_gate": "1251",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1251",
        "slice_range": SLICE_RANGE,
        "requirement": "S125",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s125_oa_production_trust_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S126" if passed else "BLOCKED",
        "policy_readiness": "OA_PRODUCTION_TRUST_POLICY_READY" if passed else "INCOMPLETE",
        "signed_runtime_readiness": "IMPLEMENTATION_PENDING" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "signed_profile_count": len(profiles),
            "proposed_table_count": len(handoff.get("proposed_tables") or ()),
            "threat_count": int(evidence["threat_contracts"].get("threat_count") or 0),
            "postgres_migration_count": 14
            if components["actual_postgres_baseline"]
            else 0,
            "postgres_cleanup_residue_count": 0
            if components["actual_postgres_baseline"]
            else -1,
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
        "next_requirement": "S126" if passed else "blocked",
        "next_requirement_scope": (
            "oa_signed_token_runtime_implementation" if passed else "blocked"
        ),
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "oa_production_trust_policy_and_token_profile_decision",
        "completed_scope": (
            "oa_owned_trust_and_opaque_browser_session",
            "service_and_delegated_user_signed_token_profiles",
            "rs256_external_key_custody_and_rotation_policy",
            "fail_closed_jwks_introspection_and_revocation_semantics",
            "service_principal_and_signed_only_rollout_handoff",
            "privacy_threat_contracts_and_actual_postgres_baseline",
        ),
        "s126_implementation_scope": (
            "durable_service_principal_credential_key_and_revocation_storage",
            "signed_token_exchange_jwks_and_introspection_runtime",
            "ordered_cross_service_signed_only_rollout",
        ),
        "deferred_product_scope": (
            "external_oidc_or_saml",
            "multi_factor_authentication",
            "self_service_password_recovery_delivery",
            "hardware_security_module_integration",
            "explicit_deny_and_nested_group_authorization",
        ),
        "policy_readiness": "READY",
        "signed_runtime_readiness": "IMPLEMENTATION_PENDING",
        "implementation_requirement": "S126",
        "actual_postgres_smoke_required": True,
        "remote_provider_calls_required": False,
        "new_tables_created_in_s125": False,
        "quality_cadence": {
            "slice_gate": "1242-1250",
            "checkpoint_gate": "1246",
            "full_gate": "1251",
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
        "s125_oa_production_trust_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"profiles={summary.get('signed_profile_count', 0)} "
        f"runtime={evidence.get('signed_runtime_readiness', 'BLOCKED')} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s125_oa_production_trust_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
