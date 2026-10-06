from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from .release_candidate import RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION


RELEASE_CANDIDATE_OPERATIONS_SCHEMA_VERSION = (
    "platform_release_candidate_browser_ag_operations.v1"
)


def build_release_candidate_browser_ag_evidence(
    browser_source: Mapping[str, Any],
    ag_source: Mapping[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    browser_checks = _bool_mapping(browser_source.get("checks"))
    browser_summary = _mapping(browser_source.get("summary"))
    browser_residue = _count_mapping(browser_source.get("residue"))
    browser_actual = all(
        browser_source.get(field) is True
        for field in ("actual_postgres", "actual_browser", "actual_service_processes")
    )
    browser_gate_checks = {
        "source_passed": browser_source.get("status") == "PASS",
        "actual_browser_postgres_and_processes": browser_actual,
        "all_browser_checks_passed": bool(browser_checks)
        and all(browser_checks.values()),
        "two_viewports_completed": browser_summary.get("viewport_count") == 2,
        "nine_journey_stages_completed": browser_summary.get("journey_stage_count")
        == 9,
        "deterministic_provider_isolation": (
            browser_source.get("provider_mode") == "deterministic_mock"
            and browser_source.get("remote_provider_required") is False
        ),
        "browser_residue_free": bool(browser_residue)
        and sum(browser_residue.values()) == 0,
    }
    browser_passed = all(browser_gate_checks.values())
    browser_metrics = {
        "viewport_count": _safe_count(browser_summary.get("viewport_count")),
        "passed_viewport_count": 2 if browser_passed else 0,
        "journey_stage_count": _safe_count(
            browser_summary.get("journey_stage_count")
        ),
        "service_process_count": _safe_count(
            browser_summary.get("service_process_count")
        ),
        "database_count": _safe_count(browser_summary.get("database_count")),
        "residue_count": sum(browser_residue.values()),
    }
    browser_gate = _gate(
        gate_id="korean_browser_journey",
        passed=browser_passed,
        actual_execution=browser_actual,
        metrics=browser_metrics,
        checks=browser_gate_checks,
        observed_at=observed_at,
    )

    ag_checks = _bool_mapping(ag_source.get("checks"))
    ag_summary = _mapping(ag_source.get("summary"))
    ag_residue = _count_mapping(ag_source.get("cleanup_residue"))
    ag_actual = (
        ag_source.get("actual_postgresql") is True
        and ag_source.get("actual_service_api") is True
    )
    ag_gate_checks = {
        "source_passed": ag_source.get("status") == "PASS",
        "actual_five_database_service_api_journey": ag_actual,
        "all_ag_checks_passed": bool(ag_checks) and all(ag_checks.values()),
        "five_services_observed": ag_summary.get("service_count") == 5,
        "eight_trace_families_observed": ag_summary.get("stage_family_count") == 8,
        "audit_survived_restart": ag_checks.get("ag_audit_survived_store_restart")
        is True,
        "service_api_only_boundary": ag_checks.get("service_api_only_boundary")
        is True,
        "ag_residue_free": bool(ag_residue) and sum(ag_residue.values()) == 0,
    }
    ag_passed = all(ag_gate_checks.values())
    ag_metrics = {
        "trace_stage_count": _safe_count(ag_summary.get("stage_family_count")),
        "audit_export_count": 1
        if ag_checks.get("ag_audit_survived_store_restart") is True
        else 0,
        "source_service_count": _safe_count(ag_summary.get("service_count")),
        "migration_count": _safe_count(ag_summary.get("migration_count")),
        "projected_stage_count": _safe_count(ag_summary.get("stage_count")),
        "residue_count": sum(ag_residue.values()),
    }
    ag_gate = _gate(
        gate_id="ag_trace_operations",
        passed=ag_passed,
        actual_execution=ag_actual,
        metrics=ag_metrics,
        checks=ag_gate_checks,
        observed_at=observed_at,
    )
    passed = browser_passed and ag_passed
    return {
        "schema_version": RELEASE_CANDIDATE_OPERATIONS_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "release_candidate_browser_ag_operations_failed",
        "checks": {
            "korean_browser_journey": browser_passed,
            "ag_trace_operations": ag_passed,
        },
        "gate_evidence": [browser_gate, ag_gate],
    }


def _gate(
    *,
    gate_id: str,
    passed: bool,
    actual_execution: bool,
    metrics: Mapping[str, Any],
    checks: Mapping[str, bool],
    observed_at: datetime | None,
) -> dict[str, Any]:
    evidence = {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "gate_id": gate_id,
        "status": "PASS" if passed else "FAIL",
        "execution_mode": "protected",
        "actual_execution": actual_execution,
        "private_payload_included": False,
        "observed_at": _utc_timestamp(observed_at),
        "metrics": dict(metrics),
        "checks": dict(checks),
    }
    evidence["evidence_digest"] = _digest(evidence)
    return evidence


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bool_mapping(value: object) -> dict[str, bool]:
    return {
        str(key): item is True for key, item in _mapping(value).items()
    }


def _count_mapping(value: object) -> dict[str, int]:
    return {
        str(key): _safe_count(item) for key, item in _mapping(value).items()
    }


def _safe_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _utc_timestamp(value: datetime | None) -> str:
    observed_at = value or datetime.now(UTC)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
