from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


AE_MVP_ACCEPTANCE_POLICY_SCHEMA_VERSION = "ae_mvp_acceptance_policy.v1"
AE_MVP_ACCEPTANCE_POLICY_ID = "ae-mvp-acceptance-v1"
MIN_STATEMENT_COVERAGE_FLOOR = 95.0
MIN_BRANCH_COVERAGE_FLOOR = 85.0
MAX_EVIDENCE_AGE_HOURS = 168
MAX_REQUIRED_REGRESSION_TESTS = 1_000_000


@dataclass(frozen=True)
class AeMvpAcceptancePolicyError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_ae_mvp_acceptance_policy(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    statement_min = _bounded_float_env(
        env,
        "NEX_AE_MVP_MIN_STATEMENT_COVERAGE",
        98.0,
        minimum=MIN_STATEMENT_COVERAGE_FLOOR,
        maximum=100.0,
    )
    branch_min = _bounded_float_env(
        env,
        "NEX_AE_MVP_MIN_BRANCH_COVERAGE",
        96.0,
        minimum=MIN_BRANCH_COVERAGE_FLOOR,
        maximum=100.0,
    )
    if branch_min > statement_min:
        raise AeMvpAcceptancePolicyError(
            error_code="ae.mvp_acceptance.branch_exceeds_statement_threshold",
            detail=(
                "Branch coverage threshold cannot exceed the statement "
                "coverage threshold."
            ),
        )
    max_age_hours = _bounded_int_env(
        env,
        "NEX_AE_MVP_EVIDENCE_MAX_AGE_HOURS",
        24,
        minimum=1,
        maximum=MAX_EVIDENCE_AGE_HOURS,
    )
    required_regression_tests = _bounded_int_env(
        env,
        "NEX_AE_MVP_REQUIRED_REGRESSION_TESTS",
        8500,
        minimum=1,
        maximum=MAX_REQUIRED_REGRESSION_TESTS,
    )
    return {
        "policy_schema_version": AE_MVP_ACCEPTANCE_POLICY_SCHEMA_VERSION,
        "policy_id": AE_MVP_ACCEPTANCE_POLICY_ID,
        "service_id": "nex-ae-api",
        "web_service_id": "nex-ae-web",
        "acceptance_scope": "nex_ae_service_mvp",
        "evidence": {
            "max_age_hours": max_age_hours,
            "server_derived_required": True,
            "raw_evidence_in_projection": False,
        },
        "coverage": {
            "statement_min_percent": statement_min,
            "branch_min_percent": branch_min,
            "project_floor_statement_percent": MIN_STATEMENT_COVERAGE_FLOOR,
            "project_floor_branch_percent": MIN_BRANCH_COVERAGE_FLOOR,
        },
        "regression": {
            "minimum_passed_tests": required_regression_tests,
            "failed_tests_allowed": 0,
        },
        "databases": {
            "required_backend": "postgresql",
            "required_databases": ["nex_ae_test", "nex_cx_test"],
            "zero_residue_required": True,
        },
        "live_providers": {
            "required_models": {
                "embedding": "Qwen3-Embedding-4B",
                "reranking": "Qwen3-Reranker-4B",
                "generation": "Qwen3.5-4B",
            },
            "failed_calls_allowed": 0,
        },
        "browser": {
            "required_engine": "chromium",
            "required_display_state": "VERIFIED_RESPONSE",
            "server_secret_header_allowed": False,
        },
        "gates": _blocking_gates(),
        "advisory_deferrals": [
            "product_wide_release_approval",
            "production_deployment_certification",
            "production_identity_provider_activation",
            "object_storage_activation",
            "distributed_load_and_disaster_recovery_certification",
        ],
        "operations": {
            "all_blocking_gates_must_pass": True,
            "advisory_deferrals_block_acceptance": False,
            "ready_status": "READY_FOR_OPERATIONS",
            "blocked_status": "BLOCKED",
        },
    }


def acceptance_gate_by_id(
    policy: Mapping[str, Any], gate_id: str
) -> Mapping[str, Any]:
    normalized = gate_id.strip() if isinstance(gate_id, str) else ""
    if not normalized:
        raise AeMvpAcceptancePolicyError(
            error_code="ae.mvp_acceptance.gate_id_required",
            detail="Acceptance gate ID is required.",
        )
    gates = policy.get("gates")
    if not isinstance(gates, list):
        raise AeMvpAcceptancePolicyError(
            error_code="ae.mvp_acceptance.policy_gates_invalid",
            detail="Acceptance policy gates are invalid.",
        )
    for gate in gates:
        if isinstance(gate, Mapping) and gate.get("gate_id") == normalized:
            return gate
    raise AeMvpAcceptancePolicyError(
        error_code="ae.mvp_acceptance.gate_unknown",
        detail="Acceptance gate is not registered.",
    )


def _blocking_gates() -> list[dict[str, Any]]:
    return [
        _gate("ae_requirement_closures", "repository"),
        _gate("contract_validation", "repository"),
        _gate("unit_regression", "test_runner"),
        _gate("statement_coverage", "coverage_report"),
        _gate("branch_coverage", "coverage_report"),
        _gate("postgres_smoke", "nex_ae_test+nex_cx_test"),
        _gate("live_grounded_generation", "protected_live_smoke"),
        _gate("privacy_failure_runbooks", "repository"),
        _gate("operations_handoff", "repository"),
    ]


def _gate(gate_id: str, evidence_source: str) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "severity": "BLOCKING",
        "required_status": "PASS",
        "skipped_allowed": False,
        "evidence_source": evidence_source,
    }


def _bounded_float_env(
    env: Mapping[str, str],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = env.get(key)
    try:
        value = default if raw is None else float(raw)
    except (TypeError, ValueError) as exc:
        raise AeMvpAcceptancePolicyError(
            error_code="ae.mvp_acceptance.config_invalid",
            detail=f"{key} must be a number.",
        ) from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise AeMvpAcceptancePolicyError(
            error_code="ae.mvp_acceptance.config_out_of_range",
            detail=f"{key} must be between {minimum:g} and {maximum:g}.",
        )
    return value


def _bounded_int_env(
    env: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = env.get(key)
    try:
        value = default if raw is None else int(raw)
    except (TypeError, ValueError) as exc:
        raise AeMvpAcceptancePolicyError(
            error_code="ae.mvp_acceptance.config_invalid",
            detail=f"{key} must be an integer.",
        ) from exc
    if value < minimum or value > maximum:
        raise AeMvpAcceptancePolicyError(
            error_code="ae.mvp_acceptance.config_out_of_range",
            detail=f"{key} must be between {minimum} and {maximum}.",
        )
    return value
