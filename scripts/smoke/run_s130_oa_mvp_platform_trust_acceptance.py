#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "scripts/smoke", ROOT / "services/nex-oa"):
    sys.path.insert(0, str(path))

from nex_oa.mvp_acceptance import (  # noqa: E402
    evaluate_oa_mvp_acceptance_inputs,
)
import run_oa_cross_service_trust_smoke as cross_service  # noqa: E402
import run_oa_identity_session_authorization_restart_smoke as identity  # noqa: E402
import run_oa_key_rotation_restart_smoke as rotation  # noqa: E402
import run_oa_revocation_introspection_restart_smoke as revocation  # noqa: E402
from run_oa_mvp_acceptance_policy_traceability import (  # noqa: E402
    run_oa_mvp_acceptance_policy_traceability,
)
from run_oa_mvp_contract_privacy_runbook import (  # noqa: E402
    run_oa_mvp_contract_privacy_runbook,
)
from run_oa_signed_token_failure_audit import (  # noqa: E402
    run_oa_signed_token_failure_audit,
)


SMOKE_ENV = "NEX_OA_MVP_ACCEPTANCE_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "s130_oa_mvp_platform_trust_acceptance.v1"
EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
EXPECTED_MIGRATION_COUNT = 17
ACTUAL_POSTGRES_ARTIFACTS = (
    "identity_restart",
    "key_rotation",
    "revocation_restart",
    "cross_service",
)


def run_s130_oa_mvp_platform_trust_acceptance(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )

    child_env = {**env, DATABASE_ENV: database_url}
    artifacts = _execute_evidence_pack(child_env)
    return _evaluate_evidence_pack(artifacts)


def _execute_evidence_pack(env: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    return {
        "policy_traceability": _safe_evidence(
            "policy_traceability",
            run_oa_mvp_acceptance_policy_traceability,
        ),
        "failure_audit": _safe_evidence(
            "failure_audit",
            run_oa_signed_token_failure_audit,
        ),
        "identity_restart": _safe_evidence(
            "identity_restart",
            lambda: identity.run_oa_identity_session_authorization_restart_smoke(
                {**env, identity.SMOKE_ENV: "1"}
            ),
        ),
        "key_rotation": _safe_evidence(
            "key_rotation",
            lambda: rotation.run_oa_key_rotation_restart_smoke(
                {**env, rotation.SMOKE_ENV: "1"}
            ),
        ),
        "revocation_restart": _safe_evidence(
            "revocation_restart",
            lambda: revocation.run_oa_revocation_introspection_restart_smoke(
                {**env, revocation.SMOKE_ENV: "1"}
            ),
        ),
        "cross_service": _safe_evidence(
            "cross_service",
            lambda: cross_service.run_oa_cross_service_trust_smoke(
                {**env, cross_service.SMOKE_ENV: "1"}
            ),
        ),
        "contracts_privacy": _safe_evidence(
            "contracts_privacy",
            run_oa_mvp_contract_privacy_runbook,
        ),
    }


def _evaluate_evidence_pack(
    artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    statuses = {
        name: str(item.get("status") or "MISSING")
        for name, item in artifacts.items()
    }
    postgres_items = {
        name: artifacts.get(name, {}) for name in ACTUAL_POSTGRES_ARTIFACTS
    }
    acceptance = evaluate_oa_mvp_acceptance_inputs(
        {
            "repository": statuses.get("policy_traceability") == "PASS",
            "postgres_restart": statuses.get("identity_restart") == "PASS",
            "key_rotation": statuses.get("key_rotation") == "PASS",
            "revocation": statuses.get("revocation_restart") == "PASS",
            "cross_service": statuses.get("cross_service") == "PASS",
            "failure_audit": statuses.get("failure_audit") == "PASS",
            "contracts_privacy": statuses.get("contracts_privacy") == "PASS",
            "full_gate": False,
        }
    )
    checks = {
        "artifact_inventory_exact": set(artifacts)
        == {
            "policy_traceability",
            "failure_audit",
            *ACTUAL_POSTGRES_ARTIFACTS,
            "contracts_privacy",
        },
        "all_pre_full_artifacts_passed": bool(statuses)
        and all(status == "PASS" for status in statuses.values()),
        "actual_postgres_targets_exact": all(
            item.get("workflow", {}).get("database") == EXPECTED_DATABASE
            and item.get("workflow", {}).get("role") == EXPECTED_ROLE
            for item in postgres_items.values()
        ),
        "migration_inventory_current": all(
            item.get("summary", {}).get("migration_count")
            == EXPECTED_MIGRATION_COUNT
            for item in postgres_items.values()
        ),
        "restart_rotation_revocation_proven": (
            artifacts.get("identity_restart", {})
            .get("summary", {})
            .get("restart_read_count")
            == 4
            and artifacts.get("key_rotation", {})
            .get("summary", {})
            .get("jwks_key_count")
            == 2
            and artifacts.get("revocation_restart", {})
            .get("summary", {})
            .get("runtime_restart_count")
            == 2
        ),
        "cross_service_signed_only_proven": (
            artifacts.get("cross_service", {})
            .get("summary", {})
            .get("passed_consumer_count")
            == 4
            and artifacts.get("cross_service", {})
            .get("summary", {})
            .get("revoked_denial_count")
            == 4
        ),
        "failure_and_privacy_evidence_clean": (
            artifacts.get("failure_audit", {})
            .get("summary", {})
            .get("raw_material_exposure_count")
            == 0
            and artifacts.get("contracts_privacy", {})
            .get("summary", {})
            .get("privacy_violation_count")
            == 0
        ),
        "all_postgres_cleanup_zero": all(
            item.get("summary", {}).get("cleanup_residue_count") == 0
            for item in postgres_items.values()
        ),
        "only_full_gate_remains": (
            acceptance["status"] == "BLOCKED"
            and acceptance["passed_gate_count"] == 7
            and acceptance["failed_gates"] == ["full_gate"]
            and not acceptance["missing_gates"]
            and not acceptance["unexpected_gates"]
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1300",
        "requirement": "S130",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s130_oa_mvp_platform_trust_acceptance_failed"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "artifact_statuses": statuses,
        "gate_evaluation": acceptance,
        "summary": {
            "artifact_count": len(artifacts),
            "passed_artifact_count": sum(
                status == "PASS" for status in statuses.values()
            ),
            "actual_postgres_smoke_count": len(postgres_items),
            "passed_gate_count": acceptance["passed_gate_count"],
            "gate_count": acceptance["gate_count"],
            "cleanup_residue_count": sum(
                int(item.get("summary", {}).get("cleanup_residue_count") or 0)
                for item in postgres_items.values()
            ),
        },
        "next_slice": "1301" if passed else "blocked",
    }


def _safe_evidence(
    label: str,
    operation: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        return dict(operation())
    except Exception as exc:
        return {
            "status": "ERROR",
            "failure_code": f"{label}_execution_failed",
            "detail": exc.__class__.__name__,
        }


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(
            database_url.replace("postgresql+psycopg", "postgresql", 1)
        )
    except ValueError:
        return False
    return (
        parsed.scheme == "postgresql"
        and unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1300",
        "requirement": "S130",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"s130_oa_mvp_acceptance=skip reason={SMOKE_ENV}"
    if evidence.get("status") != "PASS":
        return (
            "s130_oa_mvp_acceptance=fail "
            f"code={evidence.get('failure_code')}"
        )
    summary = evidence.get("summary") or {}
    return (
        "s130_oa_mvp_acceptance=pass "
        f"artifacts={summary.get('passed_artifact_count', 0)}/"
        f"{summary.get('artifact_count', 0)} "
        f"postgres={summary.get('actual_postgres_smoke_count', 0)} "
        f"gates={summary.get('passed_gate_count', 0)}/"
        f"{summary.get('gate_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)} next=1301"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s130_oa_mvp_platform_trust_acceptance()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
