from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from .release_candidate import (
    RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
    RELEASE_CANDIDATE_GATE_SPECS,
    evaluate_release_candidate_evidence,
)


RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION = (
    "platform_release_candidate_protected_matrix.v1"
)
FULL_REGRESSION_GATE_ID = "full_regression"
NON_REGRESSION_GATE_IDS = tuple(
    spec.gate_id
    for spec in RELEASE_CANDIDATE_GATE_SPECS
    if spec.gate_id != FULL_REGRESSION_GATE_ID
)


def build_release_candidate_protected_matrix(
    admission: Mapping[str, Any],
    golden: Mapping[str, Any],
    postgres: Mapping[str, Any],
    providers: Mapping[str, Any],
    operations: Mapping[str, Any],
    assurance: Mapping[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = _utc_timestamp(observed_at)
    evidence = [
        _golden_gate(golden, timestamp),
        *_gate_sequence(postgres.get("gate_evidence")),
        *_gate_sequence(providers.get("gate_evidence")),
        *_gate_sequence(operations.get("gate_evidence")),
        *_gate_sequence(assurance.get("gate_evidence")),
    ]
    evidence.append(_full_regression_placeholder(timestamp))
    payload = {
        "production_deployment_approved": False,
        "evidence": evidence,
    }
    evaluated_at = _parse_timestamp(timestamp)
    evaluation = evaluate_release_candidate_evidence(
        payload,
        evaluated_at=evaluated_at,
    )
    gate_checks = _mapping(evaluation.get("gate_checks"))
    observed_ids = tuple(
        item.get("gate_id") for item in evidence if isinstance(item, Mapping)
    )
    source_statuses = {
        "admission": admission.get("status"),
        "golden": golden.get("status"),
        "postgres": postgres.get("status"),
        "providers": providers.get("status"),
        "operations": operations.get("status"),
        "assurance": assurance.get("status"),
    }
    checks = {
        "protected_admission_passed": (
            admission.get("status") == "PASS" and admission.get("admitted") is True
        ),
        "all_source_runners_passed": all(
            status == "PASS" for name, status in source_statuses.items() if name != "admission"
        ),
        "gate_inventory_exact": set(observed_ids)
        == {spec.gate_id for spec in RELEASE_CANDIDATE_GATE_SPECS}
        and len(observed_ids) == len(set(observed_ids)),
        "eight_non_regression_gates_passed": all(
            _mapping(gate_checks.get(gate_id)).get("passed") is True
            for gate_id in NON_REGRESSION_GATE_IDS
        ),
        "five_protected_gates_actual": sum(
            _mapping(gate_checks.get(spec.gate_id)).get("actual_execution") is True
            for spec in RELEASE_CANDIDATE_GATE_SPECS
            if spec.execution_mode == "protected"
        )
        == 5,
        "full_regression_only_remaining_gate": (
            evaluation.get("status") == "FAIL"
            and _mapping(gate_checks.get(FULL_REGRESSION_GATE_ID)).get("passed")
            is False
            and all(
                _mapping(value).get("passed") is True
                for gate_id, value in gate_checks.items()
                if gate_id != FULL_REGRESSION_GATE_ID
            )
        ),
        "privacy_safe": _mapping(evaluation.get("checks")).get("privacy_safe")
        is True,
        "release_candidate_not_yet_declared": evaluation.get("decision")
        == "BLOCKED",
    }
    passed = all(checks.values())
    return {
        "schema_version": RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "release_candidate_protected_matrix_failed",
        "readiness": "READY_FOR_FULL_GATE" if passed else "BLOCKED",
        "checks": checks,
        "source_statuses": source_statuses,
        "evidence": evidence,
        "evaluation": evaluation,
        "summary": {
            "required_gate_count": 9,
            "passed_non_regression_gate_count": sum(
                _mapping(gate_checks.get(gate_id)).get("passed") is True
                for gate_id in NON_REGRESSION_GATE_IDS
            ),
            "actual_protected_gate_count": sum(
                _mapping(gate_checks.get(spec.gate_id)).get("actual_execution")
                is True
                for spec in RELEASE_CANDIDATE_GATE_SPECS
                if spec.execution_mode == "protected"
            ),
            "pending_full_gate_count": 1
            if not _mapping(gate_checks.get(FULL_REGRESSION_GATE_ID)).get("passed")
            else 0,
            "privacy_violation_count": len(
                _sequence(evaluation.get("privacy_violations"))
            ),
        },
    }


def _golden_gate(source: Mapping[str, Any], timestamp: str) -> dict[str, Any]:
    summary = _mapping(source.get("summary"))
    passed = (
        source.get("status") == "PASS"
        and summary.get("required_scenario_count") == 10
        and summary.get("passed_scenario_count") == 10
        and summary.get("privacy_violation_count") == 0
    )
    evidence = {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "gate_id": "golden_scenarios",
        "status": "PASS" if passed else "FAIL",
        "execution_mode": "deterministic",
        "actual_execution": False,
        "private_payload_included": False,
        "observed_at": timestamp,
        "metrics": {
            "scenario_count": _safe_count(summary.get("required_scenario_count")),
            "passed_scenario_count": _safe_count(
                summary.get("passed_scenario_count")
            ),
            "privacy_violation_count": _safe_count(
                summary.get("privacy_violation_count")
            ),
        },
    }
    evidence["evidence_digest"] = _digest(evidence)
    return evidence


def _full_regression_placeholder(timestamp: str) -> dict[str, Any]:
    evidence = {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "gate_id": FULL_REGRESSION_GATE_ID,
        "status": "SKIPPED",
        "execution_mode": "deterministic",
        "actual_execution": False,
        "private_payload_included": False,
        "observed_at": timestamp,
        "metrics": {"passed_test_count": 0, "failed_test_count": 0},
    }
    evidence["evidence_digest"] = _digest(evidence)
    return evidence


def _gate_sequence(value: object) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(value)


def _safe_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _utc_timestamp(value: datetime | None) -> str:
    observed_at = value or datetime.now(UTC)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
