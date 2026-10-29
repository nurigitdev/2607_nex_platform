from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from .semantic_hashes import semantic_sha256_hash_ref

HIDDEN_GAP_MATRIX_SCHEMA_VERSION = "platform_hidden_gap_matrix.v1"
HIDDEN_GAP_EVIDENCE_SCHEMA_VERSION = "platform_hidden_gap_evidence.v1"
_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "database_url",
        "password",
        "private_key",
        "raw_token",
        "secret",
        "service_token",
    }
)


@dataclass(frozen=True)
class HiddenGapScenarioSpec:
    scenario_id: str
    name: str
    required_signals: tuple[str, ...]
    protected_execution_required: bool


HIDDEN_GAP_SCENARIOS = (
    HiddenGapScenarioSpec(
        "N01",
        "ae_runtime_worker_unavailable",
        (
            "pending_job_visible",
            "false_completion_prevented",
            "restart_recovered",
            "duplicate_settlement_prevented",
        ),
        True,
    ),
    HiddenGapScenarioSpec(
        "N02",
        "wc_delivery_worker_unavailable",
        (
            "pending_event_visible",
            "false_resume_prevented",
            "restart_recovered",
            "duplicate_delivery_prevented",
        ),
        True,
    ),
    HiddenGapScenarioSpec(
        "N03",
        "eos_publisher_unavailable",
        (
            "pending_outbox_visible",
            "false_publication_prevented",
            "restart_recovered",
            "duplicate_transaction_prevented",
        ),
        True,
    ),
    HiddenGapScenarioSpec(
        "N04",
        "openbao_readiness_absent",
        ("required_dependency_missing", "startup_readiness_blocked"),
        False,
    ),
    HiddenGapScenarioSpec(
        "N05",
        "object_storage_not_admitted",
        ("required_dependency_missing", "storage_path_blocked"),
        False,
    ),
    HiddenGapScenarioSpec(
        "N06",
        "generation_provider_readiness_absent",
        ("required_dependency_missing", "live_planning_blocked"),
        False,
    ),
    HiddenGapScenarioSpec(
        "N07",
        "required_domain_activator_unknown",
        ("required_activator_missing", "activation_rejected"),
        False,
    ),
    HiddenGapScenarioSpec(
        "N08",
        "stale_duplicate_worker_restart",
        (
            "ae_duplicate_prevented",
            "wc_duplicate_prevented",
            "eos_duplicate_prevented",
        ),
        True,
    ),
    HiddenGapScenarioSpec(
        "N09",
        "forbidden_golden_journey_transition",
        ("forbidden_fixture_detected", "audit_failed_closed"),
        False,
    ),
)


def build_hidden_gap_matrix() -> dict[str, Any]:
    return {
        "matrix_schema_version": HIDDEN_GAP_MATRIX_SCHEMA_VERSION,
        "slice": "GB2-CA00-S19",
        "scenarios": [asdict(spec) for spec in HIDDEN_GAP_SCENARIOS],
    }


def build_hidden_gap_evidence(
    scenario_id: str,
    *,
    checks: Mapping[str, bool],
    components: Sequence[str],
    protected_execution: bool,
) -> dict[str, Any]:
    spec = _scenario_spec(scenario_id)
    normalized_checks = {
        str(name): value is True for name, value in sorted(checks.items())
    }
    normalized_components = sorted({str(item) for item in components if str(item)})
    passed = (
        set(normalized_checks) == set(spec.required_signals)
        and all(normalized_checks.values())
        and bool(normalized_components)
        and protected_execution is spec.protected_execution_required
    )
    evidence = {
        "evidence_schema_version": HIDDEN_GAP_EVIDENCE_SCHEMA_VERSION,
        "scenario_id": spec.scenario_id,
        "scenario_name": spec.name,
        "status": "PASS" if passed else "FAIL",
        "protected_execution": protected_execution,
        "private_payload_included": False,
        "checks": normalized_checks,
        "components": normalized_components,
    }
    evidence["evidence_hash"] = _evidence_hash(evidence)
    return evidence


def evaluate_hidden_gap_acceptance(payload: Mapping[str, Any]) -> dict[str, Any]:
    records, duplicate_ids = _indexed_records(payload.get("evidence"))
    expected_ids = tuple(spec.scenario_id for spec in HIDDEN_GAP_SCENARIOS)
    scenario_checks = {
        spec.scenario_id: _evaluate_scenario(spec, records.get(spec.scenario_id))
        for spec in HIDDEN_GAP_SCENARIOS
    }
    privacy_violations = sorted(set(_privacy_violations(payload)))
    checks = {
        "scenario_inventory_exact": set(records) == set(expected_ids),
        "scenario_ids_unique": not duplicate_ids,
        "all_scenarios_passed": all(
            item["passed"] for item in scenario_checks.values()
        ),
        "protected_restart_scenarios_present": all(
            scenario_checks[scenario_id]["protected_execution"]
            for scenario_id in ("N01", "N02", "N03", "N08")
        ),
        "privacy_safe": not privacy_violations,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "matrix_schema_version": HIDDEN_GAP_MATRIX_SCHEMA_VERSION,
        "slice": "GB2-CA00-S19",
        "status": "PASS" if not failed_checks else "FAIL",
        "failure_code": None if not failed_checks else "hidden_gap_acceptance_failed",
        "checks": checks,
        "failed_checks": failed_checks,
        "duplicate_scenario_ids": sorted(duplicate_ids),
        "privacy_violations": privacy_violations,
        "scenario_checks": scenario_checks,
        "evidence": [
            _safe_evidence(records[scenario_id])
            for scenario_id in expected_ids
            if scenario_id in records
        ],
        "summary": {
            "required_scenario_count": len(expected_ids),
            "observed_scenario_count": len(records),
            "passed_scenario_count": sum(
                item["passed"] for item in scenario_checks.values()
            ),
            "protected_scenario_count": sum(
                item["protected_execution"] for item in scenario_checks.values()
            ),
        },
        "secret_included": False,
    }


def _evaluate_scenario(
    spec: HiddenGapScenarioSpec,
    value: object,
) -> dict[str, Any]:
    record = _mapping(value)
    checks = _mapping(record.get("checks"))
    protected = record.get("protected_execution") is True
    conditions = {
        "schema_valid": (
            record.get("evidence_schema_version")
            == HIDDEN_GAP_EVIDENCE_SCHEMA_VERSION
        ),
        "name_matches": record.get("scenario_name") == spec.name,
        "status_pass": record.get("status") == "PASS",
        "signals_exact": set(checks) == set(spec.required_signals),
        "signals_pass": bool(checks)
        and all(value is True for value in checks.values()),
        "execution_class_matches": protected is spec.protected_execution_required,
        "private_payload_excluded": record.get("private_payload_included") is False,
        "components_present": bool(record.get("components")),
        "hash_valid": record.get("evidence_hash") == _evidence_hash(record),
    }
    return {
        "scenario_id": spec.scenario_id,
        "passed": all(conditions.values()),
        "protected_execution": protected,
        "conditions": conditions,
    }


def _scenario_spec(scenario_id: str) -> HiddenGapScenarioSpec:
    for spec in HIDDEN_GAP_SCENARIOS:
        if spec.scenario_id == scenario_id:
            return spec
    raise ValueError(f"unknown hidden-gap scenario: {scenario_id}")


def _indexed_records(value: object) -> tuple[dict[str, dict[str, Any]], set[str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return {}, set()
    records: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for item in value:
        record = _mapping(item)
        scenario_id = record.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            continue
        if scenario_id in records:
            duplicates.add(scenario_id)
            continue
        records[scenario_id] = record
    return records, duplicates


def _evidence_hash(record: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {key: deepcopy(value) for key, value in record.items() if key != "evidence_hash"}
    )


def _privacy_violations(value: object, *, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}"
            if name.casefold() in _FORBIDDEN_EVIDENCE_KEYS:
                violations.append(child)
            violations.extend(_privacy_violations(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            violations.extend(_privacy_violations(item, path=f"{path}[{index}]"))
    return violations


def _safe_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "evidence_schema_version",
        "scenario_id",
        "scenario_name",
        "status",
        "protected_execution",
        "private_payload_included",
        "checks",
        "components",
        "evidence_hash",
    )
    return {field: deepcopy(value[field]) for field in fields if field in value}


def _mapping(value: object) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}
