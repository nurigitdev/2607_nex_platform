from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from nex_ag.mvp_acceptance import build_ag_mvp_acceptance_policy


AG_MVP_ACCEPTANCE_REPORT_SCHEMA_VERSION = "ag_mvp_acceptance_report.v1"
FUTURE_CLOCK_SKEW_MINUTES = 5


def evaluate_ag_mvp_acceptance(
    evidence: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    active_policy = (
        build_ag_mvp_acceptance_policy({}) if policy is None else policy
    )
    observed_now = _normalize_now(now)
    max_age = int(_mapping(active_policy.get("evidence")).get("max_age_hours", 0))
    gate_specs = active_policy.get("gates")
    if not isinstance(gate_specs, list) or max_age < 1:
        raise ValueError("acceptance policy is invalid")

    gates = [
        _evaluate_gate(
            _mapping(spec),
            evidence.get(str(_mapping(spec).get("gate_id") or "")),
            policy=active_policy,
            now=observed_now,
            max_age_hours=max_age,
        )
        for spec in gate_specs
    ]
    blockers = [
        {
            "gate_id": gate["gate_id"],
            "reason_codes": gate["reason_codes"],
        }
        for gate in gates
        if gate["status"] != "PASS"
    ]
    accepted = not blockers
    report_body = {
        "policy_id": active_policy.get("policy_id"),
        "evaluated_at": _timestamp(observed_now),
        "gate_statuses": [
            {"gate_id": gate["gate_id"], "status": gate["status"]}
            for gate in gates
        ],
    }
    return {
        "report_schema_version": AG_MVP_ACCEPTANCE_REPORT_SCHEMA_VERSION,
        "acceptance_id": hashlib.sha256(
            _canonical_json(report_body).encode("utf-8")
        ).hexdigest(),
        "service_id": "nex-ag",
        "acceptance_scope": "nex_ag_service_mvp",
        "evaluated_at": report_body["evaluated_at"],
        "status": "ACCEPTED" if accepted else "BLOCKED",
        "transition_status": "READY_FOR_CX" if accepted else "BLOCKED",
        "gates": gates,
        "blockers": blockers,
        "summary": {
            "gate_count": len(gates),
            "passed_gate_count": sum(gate["status"] == "PASS" for gate in gates),
            "blocked_gate_count": len(blockers),
        },
        "advisory_deferrals": list(
            active_policy.get("advisory_deferrals") or []
        ),
        "raw_evidence_included": False,
    }


def _evaluate_gate(
    spec: Mapping[str, Any],
    raw_evidence: Any,
    *,
    policy: Mapping[str, Any],
    now: datetime,
    max_age_hours: int,
) -> dict[str, Any]:
    gate_id = str(spec.get("gate_id") or "")
    reasons: list[str] = []
    item = _mapping(raw_evidence)
    if not item:
        reasons.append("evidence_missing")
    else:
        if item.get("status") != "PASS":
            reasons.append("status_not_pass")
        observed_at = _parse_timestamp(item.get("observed_at"))
        if observed_at is None:
            reasons.append("observed_at_invalid")
        else:
            if observed_at > now + timedelta(minutes=FUTURE_CLOCK_SKEW_MINUTES):
                reasons.append("evidence_from_future")
            elif now - observed_at > timedelta(hours=max_age_hours):
                reasons.append("evidence_stale")
        reasons.extend(_gate_specific_reasons(gate_id, item, policy))
    return {
        "gate_id": gate_id,
        "severity": spec.get("severity"),
        "status": "PASS" if not reasons else "BLOCKED",
        "reason_codes": reasons,
    }


def _gate_specific_reasons(
    gate_id: str,
    item: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[str]:
    if gate_id == "ag_requirement_closures":
        reasons = []
        if item.get("requirement_count") != 33:
            reasons.append("requirement_count_incomplete")
        if item.get("issue_count") != 0:
            reasons.append("closure_inventory_has_issues")
        return reasons
    if gate_id == "contract_validation":
        return [
            "contract_family_empty"
            for field in ("schema_count", "openapi_count", "negative_fixture_count")
            if not _positive_number(item.get(field))
        ]
    if gate_id == "unit_regression":
        regression = _mapping(policy.get("regression"))
        reasons = []
        if not _number_at_least(
            item.get("passed_tests"), regression.get("minimum_passed_tests")
        ):
            reasons.append("regression_pass_count_below_minimum")
        if item.get("failed_tests") != regression.get("failed_tests_allowed"):
            reasons.append("regression_failures_present")
        return reasons
    if gate_id in {"statement_coverage", "branch_coverage"}:
        coverage = _mapping(policy.get("coverage"))
        threshold_key = (
            "statement_min_percent"
            if gate_id == "statement_coverage"
            else "branch_min_percent"
        )
        return [] if _number_at_least(
            item.get("percent"), coverage.get(threshold_key)
        ) else ["coverage_below_threshold"]
    if gate_id == "postgres_smoke":
        database = _mapping(policy.get("database"))
        reasons = []
        if item.get("backend") != database.get("required_backend"):
            reasons.append("postgres_backend_not_proven")
        if item.get("database") != database.get("required_database"):
            reasons.append("test_database_not_proven")
        if item.get("zero_residue") is not True:
            reasons.append("postgres_cleanup_not_proven")
        return reasons
    if gate_id == "privacy_failure_runbooks":
        return [] if _number_at_least(item.get("runbook_count"), 27) else [
            "runbook_inventory_incomplete"
        ]
    if gate_id == "cx_transition_handoff":
        reasons = []
        if item.get("target_service") != "nex-cx":
            reasons.append("handoff_target_invalid")
        if item.get("manifest_status") != "SEALED":
            reasons.append("handoff_manifest_not_sealed")
        return reasons
    return ["gate_evaluator_missing"]


def _normalize_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _number_at_least(value: Any, minimum: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isinstance(minimum, (int, float))
        and not isinstance(minimum, bool)
        and value >= minimum
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
