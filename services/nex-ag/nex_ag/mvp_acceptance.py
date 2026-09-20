from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


AG_MVP_ACCEPTANCE_POLICY_SCHEMA_VERSION = "ag_mvp_acceptance_policy.v1"
AG_MVP_ACCEPTANCE_POLICY_ID = "ag-mvp-acceptance-v1"
MIN_STATEMENT_COVERAGE_FLOOR = 95.0
MIN_BRANCH_COVERAGE_FLOOR = 85.0
MAX_EVIDENCE_AGE_HOURS = 168
MAX_REQUIRED_REGRESSION_TESTS = 1_000_000


@dataclass(frozen=True)
class AgMvpAcceptancePolicyError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_ag_mvp_acceptance_policy(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    statement_min = _bounded_float_env(
        env,
        "NEX_AG_MVP_MIN_STATEMENT_COVERAGE",
        98.0,
        minimum=MIN_STATEMENT_COVERAGE_FLOOR,
        maximum=100.0,
    )
    branch_min = _bounded_float_env(
        env,
        "NEX_AG_MVP_MIN_BRANCH_COVERAGE",
        96.0,
        minimum=MIN_BRANCH_COVERAGE_FLOOR,
        maximum=100.0,
    )
    if branch_min > statement_min:
        raise AgMvpAcceptancePolicyError(
            error_code="ag.mvp_acceptance.branch_exceeds_statement_threshold",
            detail=(
                "Branch coverage threshold cannot exceed the statement "
                "coverage threshold."
            ),
        )
    max_age_hours = _bounded_int_env(
        env,
        "NEX_AG_MVP_EVIDENCE_MAX_AGE_HOURS",
        24,
        minimum=1,
        maximum=MAX_EVIDENCE_AGE_HOURS,
    )
    required_regression_tests = _bounded_int_env(
        env,
        "NEX_AG_MVP_REQUIRED_REGRESSION_TESTS",
        6000,
        minimum=1,
        maximum=MAX_REQUIRED_REGRESSION_TESTS,
    )
    return {
        "policy_schema_version": AG_MVP_ACCEPTANCE_POLICY_SCHEMA_VERSION,
        "policy_id": AG_MVP_ACCEPTANCE_POLICY_ID,
        "service_id": "nex-ag",
        "acceptance_scope": "nex_ag_service_mvp",
        "transition_target": "nex-cx",
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
            "known_warning_count": 1,
        },
        "database": {
            "required_backend": "postgresql",
            "required_database": "nex_ag_test",
            "skipped_when_required_is_pass": False,
            "zero_residue_required": True,
        },
        "gates": _blocking_gates(),
        "advisory_deferrals": [
            "product_wide_mvp_release_approval",
            "production_deployment_certification",
            "production_identity_and_external_notification_integration",
            "distributed_load_and_disaster_recovery_certification",
        ],
        "transition": {
            "all_blocking_gates_must_pass": True,
            "advisory_deferrals_block_transition": False,
            "ready_status": "READY_FOR_CX",
            "blocked_status": "BLOCKED",
        },
    }


def acceptance_gate_by_id(
    policy: Mapping[str, Any], gate_id: str
) -> Mapping[str, Any]:
    normalized = gate_id.strip() if isinstance(gate_id, str) else ""
    if not normalized:
        raise AgMvpAcceptancePolicyError(
            error_code="ag.mvp_acceptance.gate_id_required",
            detail="Acceptance gate ID is required.",
        )
    gates = policy.get("gates")
    if not isinstance(gates, list):
        raise AgMvpAcceptancePolicyError(
            error_code="ag.mvp_acceptance.policy_gates_invalid",
            detail="Acceptance policy gates are invalid.",
        )
    for gate in gates:
        if isinstance(gate, Mapping) and gate.get("gate_id") == normalized:
            return gate
    raise AgMvpAcceptancePolicyError(
        error_code="ag.mvp_acceptance.gate_unknown",
        detail="Acceptance gate is not registered.",
    )


def _blocking_gates() -> list[dict[str, Any]]:
    return [
        _gate("ag_requirement_closures", "repository"),
        _gate("contract_validation", "repository"),
        _gate("unit_regression", "test_runner"),
        _gate("statement_coverage", "coverage_report"),
        _gate("branch_coverage", "coverage_report"),
        _gate("postgres_smoke", "nex_ag_test"),
        _gate("privacy_failure_runbooks", "repository"),
        _gate("cx_transition_handoff", "repository"),
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
        raise AgMvpAcceptancePolicyError(
            error_code="ag.mvp_acceptance.config_invalid",
            detail=f"{key} must be a number.",
        ) from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise AgMvpAcceptancePolicyError(
            error_code="ag.mvp_acceptance.config_out_of_range",
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
        raise AgMvpAcceptancePolicyError(
            error_code="ag.mvp_acceptance.config_invalid",
            detail=f"{key} must be an integer.",
        ) from exc
    if value < minimum or value > maximum:
        raise AgMvpAcceptancePolicyError(
            error_code="ag.mvp_acceptance.config_out_of_range",
            detail=f"{key} must be between {minimum} and {maximum}.",
        )
    return value
