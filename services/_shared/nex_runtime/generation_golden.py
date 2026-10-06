from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any


GENERATION_GOLDEN_MATRIX_SCHEMA_VERSION = "generation_golden_matrix.v1"
GENERATION_GOLDEN_EVIDENCE_SCHEMA_VERSION = "generation_golden_evidence.v1"
SAFE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_PRIVATE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "content_base64",
        "cookie",
        "database_url",
        "document_text",
        "evidence_text",
        "file_payload",
        "generated_text",
        "password",
        "private_key",
        "provider_endpoint",
        "raw_prompt",
        "raw_token",
        "source_text",
        "storage_ref",
        "user_message",
    }
)


@dataclass(frozen=True)
class GenerationGoldenScenarioSpec:
    scenario_id: str
    name: str
    required_signals: tuple[str, ...]


GENERATION_GOLDEN_SCENARIOS = (
    GenerationGoldenScenarioSpec(
        "GEN-E2E-001",
        "general_answer_without_retrieval",
        ("general_mode_selected", "retrieval_skipped", "citations_not_claimed"),
    ),
    GenerationGoldenScenarioSpec(
        "GEN-E2E-002",
        "grounded_answer_with_evidence",
        ("permission_filtered_retrieval", "grounded_generation", "trace_continuity"),
    ),
    GenerationGoldenScenarioSpec(
        "GEN-E2E-003",
        "report_generation_with_artifact_export",
        ("report_contract_selected", "md_created", "docx_created", "owner_only_links"),
    ),
    GenerationGoldenScenarioSpec(
        "GEN-E2E-004",
        "no_answer_guardrail",
        ("no_evidence_is_no_answer", "low_score_is_low_confidence", "generation_blocked"),
    ),
    GenerationGoldenScenarioSpec(
        "GEN-E2E-005",
        "template_prompt_mismatch",
        ("mismatch_rejected", "rejected_before_provider_call"),
    ),
    GenerationGoldenScenarioSpec(
        "GEN-E2E-006",
        "provider_timeout_retry",
        ("retryable_timeout_recorded", "input_hashes_preserved", "recovery_lineage_visible"),
    ),
    GenerationGoldenScenarioSpec(
        "GEN-E2E-007",
        "citation_repair",
        ("repair_binding_exact", "repair_bounded_once", "retrieval_package_preserved"),
    ),
    GenerationGoldenScenarioSpec(
        "GEN-E2E-008",
        "render_failure_retry",
        ("validated_draft_preserved", "retry_work_scheduled", "owner_scope_preserved"),
    ),
    GenerationGoldenScenarioSpec(
        "GEN-E2E-009",
        "artifact_download_permission",
        ("cross_owner_hidden", "owner_download_supported", "storage_reference_redacted"),
    ),
    GenerationGoldenScenarioSpec(
        "GEN-E2E-010",
        "ag_redacted_audit_export",
        ("audit_package_verified", "metadata_only_export", "private_values_excluded"),
    ),
)


def build_generation_golden_matrix() -> dict[str, Any]:
    return {
        "matrix_schema_version": GENERATION_GOLDEN_MATRIX_SCHEMA_VERSION,
        "requirement": "S140",
        "execution_mode": "deterministic",
        "protected_dependencies_required": False,
        "scenarios": [asdict(spec) for spec in GENERATION_GOLDEN_SCENARIOS],
    }


def build_generation_golden_evidence(
    scenario_id: str,
    *,
    checks: Mapping[str, bool],
    components: Sequence[str],
) -> dict[str, Any]:
    spec = _scenario_spec(scenario_id)
    normalized_checks = {
        str(name): value is True for name, value in sorted(checks.items())
    }
    expected_signals = set(spec.required_signals)
    passed = (
        set(normalized_checks) == expected_signals
        and all(normalized_checks.values())
    )
    evidence = {
        "evidence_schema_version": GENERATION_GOLDEN_EVIDENCE_SCHEMA_VERSION,
        "scenario_id": spec.scenario_id,
        "scenario_name": spec.name,
        "status": "PASS" if passed else "FAIL",
        "deterministic_execution": True,
        "protected_execution": False,
        "private_payload_included": False,
        "checks": normalized_checks,
        "components": sorted({str(item) for item in components if str(item)}),
    }
    evidence["evidence_digest"] = _evidence_digest(evidence)
    return evidence


def evaluate_generation_golden_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    records, duplicate_ids = _indexed_records(payload.get("evidence"))
    expected_ids = tuple(spec.scenario_id for spec in GENERATION_GOLDEN_SCENARIOS)
    scenario_checks = {
        spec.scenario_id: _evaluate_scenario(spec, records.get(spec.scenario_id))
        for spec in GENERATION_GOLDEN_SCENARIOS
    }
    privacy_violations = sorted(set(_privacy_violations(payload)))
    checks = {
        "scenario_inventory_exact": set(records) == set(expected_ids),
        "scenario_ids_unique": not duplicate_ids,
        "all_scenarios_passed": all(
            item["passed"] for item in scenario_checks.values()
        ),
        "privacy_safe": not privacy_violations,
        "deterministic_only": all(
            item["deterministic_execution"]
            and not item["protected_execution"]
            for item in scenario_checks.values()
        ),
        "release_candidate_only": (
            payload.get("production_deployment_approved") is False
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "matrix_schema_version": GENERATION_GOLDEN_MATRIX_SCHEMA_VERSION,
        "requirement": "S140",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "generation_golden_evidence_failed",
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
            "protected_execution_count": sum(
                item["protected_execution"] for item in scenario_checks.values()
            ),
            "privacy_violation_count": len(privacy_violations),
        },
    }


def _evaluate_scenario(
    spec: GenerationGoldenScenarioSpec,
    value: object,
) -> dict[str, Any]:
    record = _mapping(value)
    checks = _mapping(record.get("checks"))
    deterministic = record.get("deterministic_execution") is True
    protected = record.get("protected_execution") is True
    conditions = {
        "schema_valid": (
            record.get("evidence_schema_version")
            == GENERATION_GOLDEN_EVIDENCE_SCHEMA_VERSION
        ),
        "name_matches": record.get("scenario_name") == spec.name,
        "status_pass": record.get("status") == "PASS",
        "signals_exact": set(checks) == set(spec.required_signals),
        "signals_pass": bool(checks) and all(value is True for value in checks.values()),
        "deterministic_execution": deterministic,
        "protected_execution_absent": not protected,
        "private_payload_excluded": record.get("private_payload_included") is False,
        "components_present": bool(record.get("components")),
        "digest_valid": _digest_valid(record),
    }
    return {
        "scenario_id": spec.scenario_id,
        "passed": all(conditions.values()),
        "deterministic_execution": deterministic,
        "protected_execution": protected,
        "conditions": conditions,
    }


def _scenario_spec(scenario_id: str) -> GenerationGoldenScenarioSpec:
    for spec in GENERATION_GOLDEN_SCENARIOS:
        if spec.scenario_id == scenario_id:
            return spec
    raise ValueError(f"unknown generation golden scenario: {scenario_id}")


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


def _digest_valid(record: Mapping[str, Any]) -> bool:
    digest = str(record.get("evidence_digest") or "")
    return bool(SAFE_DIGEST.fullmatch(digest)) and digest == _evidence_digest(record)


def _evidence_digest(record: Mapping[str, Any]) -> str:
    payload = {
        key: deepcopy(value)
        for key, value in record.items()
        if key != "evidence_digest"
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _privacy_violations(value: object, *, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}"
            if name.casefold() in FORBIDDEN_PRIVATE_KEYS:
                violations.append(child)
            violations.extend(_privacy_violations(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            violations.extend(_privacy_violations(item, path=f"{path}[{index}]"))
    return violations


def _safe_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    names = (
        "evidence_schema_version",
        "scenario_id",
        "scenario_name",
        "status",
        "deterministic_execution",
        "protected_execution",
        "private_payload_included",
        "checks",
        "components",
        "evidence_digest",
    )
    return {name: deepcopy(value[name]) for name in names if name in value}


def _mapping(value: object) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}
