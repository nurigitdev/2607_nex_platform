from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import re
from typing import Any


RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION = "platform_release_candidate_evidence.v1"
RELEASE_CANDIDATE_GATE_MATRIX_VERSION = "platform_release_candidate_gate_matrix.v1"
DEFAULT_MAX_EVIDENCE_AGE_HOURS = 24
MAX_FUTURE_SKEW_SECONDS = 300
SAFE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_KEY_PARTS = (
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "cookie",
    "database_url",
    "document_text",
    "evidence_text",
    "file_payload",
    "generated_text",
    "password",
    "private_key",
    "prompt",
    "provider_endpoint",
    "raw_token",
    "source_text",
    "storage_ref",
)


@dataclass(frozen=True)
class ReleaseCandidateGateSpec:
    gate_id: str
    category: str
    execution_mode: str
    evidence_source: str


RELEASE_CANDIDATE_GATE_SPECS = (
    ReleaseCandidateGateSpec(
        "golden_scenarios",
        "functional",
        "deterministic",
        "GEN-E2E-001..010",
    ),
    ReleaseCandidateGateSpec(
        "five_database_restart",
        "durability",
        "protected",
        "OA/AE/CX/MO/AG test PostgreSQL",
    ),
    ReleaseCandidateGateSpec(
        "live_provider_matrix",
        "provider",
        "protected",
        "MO embedding/reranking/generation aliases",
    ),
    ReleaseCandidateGateSpec(
        "korean_browser_journey",
        "browser",
        "protected",
        "AE Web desktop/mobile Chromium",
    ),
    ReleaseCandidateGateSpec(
        "ag_trace_operations",
        "operations",
        "protected",
        "AG service-API trace and audit",
    ),
    ReleaseCandidateGateSpec(
        "contract_privacy",
        "contract",
        "deterministic",
        "schema/OpenAPI/privacy validation",
    ),
    ReleaseCandidateGateSpec(
        "full_regression",
        "quality",
        "deterministic",
        "repository Full Gate",
    ),
    ReleaseCandidateGateSpec(
        "zero_residue",
        "cleanup",
        "protected",
        "owned database/file/process cleanup",
    ),
    ReleaseCandidateGateSpec(
        "deployment_deferrals",
        "release",
        "deterministic",
        "explicit production-only deferral inventory",
    ),
)


def build_release_candidate_gate_matrix() -> dict[str, Any]:
    return {
        "gate_matrix_schema_version": RELEASE_CANDIDATE_GATE_MATRIX_VERSION,
        "requirement": "S140",
        "all_gates_blocking": True,
        "skipped_allowed": False,
        "max_evidence_age_hours": DEFAULT_MAX_EVIDENCE_AGE_HOURS,
        "gates": [asdict(spec) for spec in RELEASE_CANDIDATE_GATE_SPECS],
    }


def evaluate_release_candidate_evidence(
    payload: Mapping[str, Any],
    *,
    evaluated_at: datetime | None = None,
    max_age_hours: int = DEFAULT_MAX_EVIDENCE_AGE_HOURS,
) -> dict[str, Any]:
    if not isinstance(max_age_hours, int) or isinstance(max_age_hours, bool) or max_age_hours < 1:
        raise ValueError("max_age_hours must be a positive integer")
    now = _aware_utc(evaluated_at or datetime.now(UTC))
    records, duplicate_ids = _indexed_records(payload.get("evidence"))
    privacy_violations = sorted(set(_privacy_violations(payload)))
    expected_ids = tuple(spec.gate_id for spec in RELEASE_CANDIDATE_GATE_SPECS)
    gate_checks = {
        spec.gate_id: _evaluate_gate(
            spec,
            records.get(spec.gate_id),
            now=now,
            max_age_hours=max_age_hours,
        )
        for spec in RELEASE_CANDIDATE_GATE_SPECS
    }
    checks = {
        "gate_inventory_exact": set(records) == set(expected_ids),
        "gate_ids_unique": not duplicate_ids,
        "all_gates_passed": all(item["passed"] for item in gate_checks.values()),
        "no_skipped_gate": all(
            item["status"] != "SKIPPED" for item in gate_checks.values()
        ),
        "privacy_safe": not privacy_violations,
        "release_candidate_only": payload.get("production_deployment_approved") is False,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "decision": "RELEASE_CANDIDATE" if passed else "BLOCKED",
        "failure_code": None if passed else "platform_release_candidate_evidence_failed",
        "checks": checks,
        "failed_checks": failed_checks,
        "duplicate_gate_ids": sorted(duplicate_ids),
        "privacy_violations": privacy_violations,
        "gate_checks": gate_checks,
        "evidence": [
            _safe_evidence(records[gate_id])
            for gate_id in expected_ids
            if gate_id in records
        ],
        "summary": {
            "required_gate_count": len(expected_ids),
            "observed_gate_count": len(records),
            "passed_gate_count": sum(
                item["passed"] for item in gate_checks.values()
            ),
            "protected_gate_count": sum(
                spec.execution_mode == "protected"
                for spec in RELEASE_CANDIDATE_GATE_SPECS
            ),
            "actual_protected_gate_count": sum(
                spec.execution_mode == "protected"
                and gate_checks[spec.gate_id]["actual_execution"]
                for spec in RELEASE_CANDIDATE_GATE_SPECS
            ),
            "privacy_violation_count": len(privacy_violations),
        },
    }


def _evaluate_gate(
    spec: ReleaseCandidateGateSpec,
    value: object,
    *,
    now: datetime,
    max_age_hours: int,
) -> dict[str, Any]:
    record = _mapping(value)
    observed_at = _parse_timestamp(record.get("observed_at"))
    age_seconds = (now - observed_at).total_seconds() if observed_at else None
    fresh = (
        age_seconds is not None
        and age_seconds >= -MAX_FUTURE_SKEW_SECONDS
        and age_seconds <= max_age_hours * 3600
    )
    status = str(record.get("status") or "MISSING")
    actual_execution = record.get("actual_execution") is True
    conditions = {
        "schema_valid": (
            record.get("evidence_schema_version")
            == RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION
        ),
        "status_pass": status == "PASS",
        "fresh": fresh,
        "digest_valid": bool(SAFE_DIGEST.fullmatch(str(record.get("evidence_digest") or ""))),
        "private_payload_excluded": record.get("private_payload_included") is False,
        "actual_execution_satisfied": (
            spec.execution_mode != "protected" or actual_execution
        ),
        "gate_metric_satisfied": _gate_metric_satisfied(spec.gate_id, record),
    }
    return {
        "gate_id": spec.gate_id,
        "status": status,
        "passed": all(conditions.values()),
        "actual_execution": actual_execution,
        "conditions": conditions,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
    }


def _gate_metric_satisfied(gate_id: str, record: Mapping[str, Any]) -> bool:
    metrics = _mapping(record.get("metrics"))
    if gate_id == "golden_scenarios":
        return metrics.get("scenario_count") == 10 and metrics.get("passed_scenario_count") == 10
    if gate_id == "five_database_restart":
        return metrics.get("database_count") == 5 and metrics.get("restored_database_count") == 5
    if gate_id == "live_provider_matrix":
        return metrics.get("provider_capability_count") == 3 and metrics.get("failed_provider_count") == 0
    if gate_id == "korean_browser_journey":
        return metrics.get("viewport_count") == 2 and metrics.get("passed_viewport_count") == 2
    if gate_id == "ag_trace_operations":
        return metrics.get("trace_stage_count") == 8 and metrics.get("audit_export_count", 0) >= 1
    if gate_id == "contract_privacy":
        return metrics.get("contract_validation_passed") is True and metrics.get("privacy_violation_count") == 0
    if gate_id == "full_regression":
        return metrics.get("passed_test_count", 0) > 0 and metrics.get("failed_test_count") == 0
    if gate_id == "zero_residue":
        return metrics.get("database_residue_count") == 0 and metrics.get("file_residue_count") == 0 and metrics.get("running_process_count") == 0
    if gate_id == "deployment_deferrals":
        return metrics.get("deferral_count", 0) >= 1 and metrics.get("production_deployment_approved") is False
    return False


def _indexed_records(value: object) -> tuple[dict[str, dict[str, Any]], set[str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return {}, set()
    records: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for item in value:
        record = _mapping(item)
        gate_id = record.get("gate_id")
        if not isinstance(gate_id, str) or not gate_id:
            continue
        if gate_id in records:
            duplicates.add(gate_id)
            continue
        records[gate_id] = record
    return records, duplicates


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    return value.astimezone(UTC)


def _privacy_violations(value: object, *, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}"
            if any(part in name.lower() for part in FORBIDDEN_KEY_PARTS):
                violations.append(child)
            violations.extend(_privacy_violations(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            violations.extend(_privacy_violations(item, path=f"{path}[{index}]"))
    return violations


def _safe_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    names = (
        "gate_id",
        "evidence_schema_version",
        "status",
        "observed_at",
        "evidence_digest",
        "actual_execution",
        "private_payload_included",
        "metrics",
    )
    return {name: deepcopy(value[name]) for name in names if name in value}


def _mapping(value: object) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}
