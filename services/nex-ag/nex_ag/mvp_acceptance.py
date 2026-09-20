from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


AG_MVP_ACCEPTANCE_POLICY_SCHEMA_VERSION = "ag_mvp_acceptance_policy.v1"
AG_MVP_ACCEPTANCE_POLICY_ID = "ag-mvp-acceptance-v1"
MIN_STATEMENT_COVERAGE_FLOOR = 95.0
MIN_BRANCH_COVERAGE_FLOOR = 85.0
MAX_EVIDENCE_AGE_HOURS = 168
MAX_REQUIRED_REGRESSION_TESTS = 1_000_000
ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AgMvpAcceptancePolicyError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AgMvpEvidenceSpec:
    requirement: str
    capability_group: str
    closure_slice: str


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


def build_ag_mvp_evidence_inventory(root: Path = ROOT) -> dict[str, Any]:
    specs = ag_mvp_evidence_specs()
    entries = [_inspect_evidence_spec(root, spec) for spec in specs]
    requirements = [spec.requirement for spec in specs]
    issues = [
        issue
        for entry in entries
        for issue in entry["issues"]
    ]
    checks = {
        "requirement_count_complete": len(entries) == 33,
        "requirements_unique": len(requirements) == len(set(requirements)),
        "closure_runners_present": all(
            entry["closure_runner_count"] == 1 for entry in entries
        ),
        "closure_docs_present": all(
            entry["closure_document_count"] == 1 for entry in entries
        ),
        "closure_identity_tokens_present": all(
            entry["identity_tokens_present"] for entry in entries
        ),
    }
    passed = all(checks.values()) and not issues
    return {
        "inventory_schema_version": "ag_mvp_evidence_inventory.v1",
        "service_id": "nex-ag",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "ag.mvp_acceptance.evidence_inventory_invalid"
        ),
        "scope": {
            "first_requirement": "S34",
            "last_requirement": "S89",
            "included_requirement_count": len(entries),
            "ae_only_s39_s62_included": False,
        },
        "entries": entries,
        "checks": checks,
        "issues": issues,
    }


def ag_mvp_evidence_specs() -> tuple[AgMvpEvidenceSpec, ...]:
    groups = (
        ("shared_generation_quality", range(34, 39)),
        ("ag_operations_foundation", (53,)),
        ("ag_operator_governance", range(63, 82)),
        ("ag_mvp_hardening", range(82, 90)),
    )
    return tuple(
        AgMvpEvidenceSpec(
            requirement=f"S{number}",
            capability_group=group,
            closure_slice=("0711" if number == 71 else f"{number * 10:04d}"),
        )
        for group, numbers in groups
        for number in numbers
    )


def _inspect_evidence_spec(
    root: Path, spec: AgMvpEvidenceSpec
) -> dict[str, Any]:
    number = int(spec.requirement[1:])
    runners = sorted(
        (root / "scripts/smoke").glob(
            f"run_s{number}_*_closure.py"
        )
    )
    documents = sorted(
        (root / "docs/slices").glob(
            f"{spec.closure_slice}_*closure*.md"
        )
    )
    runner_text = _single_file_text(runners)
    document_text = _single_file_text(documents)
    identity_tokens_present = (
        len(runners) == 1
        and len(documents) == 1
        and "SCHEMA_VERSION" in runner_text
        and f"s{number}_" in runner_text.lower()
        and "closure.v1" in runner_text
        and f"# Slice {spec.closure_slice}" in document_text
    )
    issues: list[dict[str, Any]] = []
    if len(runners) != 1:
        issues.append(
            {
                "category": "closure_runner_count_invalid",
                "requirement": spec.requirement,
                "observed_count": len(runners),
            }
        )
    if len(documents) != 1:
        issues.append(
            {
                "category": "closure_document_count_invalid",
                "requirement": spec.requirement,
                "observed_count": len(documents),
            }
        )
    if len(runners) == 1 and len(documents) == 1 and not identity_tokens_present:
        issues.append(
            {
                "category": "closure_identity_token_missing",
                "requirement": spec.requirement,
            }
        )
    return {
        "requirement": spec.requirement,
        "capability_group": spec.capability_group,
        "closure_slice": spec.closure_slice,
        "closure_runner": _relative_path(root, runners),
        "closure_document": _relative_path(root, documents),
        "closure_runner_count": len(runners),
        "closure_document_count": len(documents),
        "identity_tokens_present": identity_tokens_present,
        "status": "READY" if not issues else "INVALID",
        "issues": issues,
    }


def _single_file_text(paths: list[Path]) -> str:
    if len(paths) != 1:
        return ""
    return paths[0].read_text(encoding="utf-8")


def _relative_path(root: Path, paths: list[Path]) -> str | None:
    if len(paths) != 1:
        return None
    return paths[0].relative_to(root).as_posix()


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
