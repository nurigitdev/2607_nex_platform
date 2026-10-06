from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from .release_candidate import RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION


RELEASE_CANDIDATE_ASSURANCE_SCHEMA_VERSION = (
    "platform_release_candidate_assurance.v1"
)
DEPLOYMENT_DEFERRALS = (
    "external_signing_key_custody",
    "managed_tls_certificate_lifecycle",
    "production_secret_injection_rotation",
    "enterprise_idp_registration",
    "production_object_storage_lifecycle",
    "production_postgresql_backup_ha_dr",
    "external_notification_incident_endpoints",
    "production_gpu_scheduling_capacity",
    "production_monitoring_paging_slo_approval",
)
RECOVERY_SCENARIOS = ("GEN-E2E-006", "GEN-E2E-007", "GEN-E2E-008")
PRIVACY_SCENARIO = "GEN-E2E-010"


def build_release_candidate_assurance_evidence(
    contract_source: Mapping[str, Any],
    golden_source: Mapping[str, Any],
    residue_source: Mapping[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    scenario_checks = _mapping(golden_source.get("scenario_checks"))
    contract_failures = _sequence(contract_source.get("failures"))
    privacy_violations = _sequence(golden_source.get("privacy_violations"))
    recovery_passed = all(
        _mapping(scenario_checks.get(scenario_id)).get("passed") is True
        for scenario_id in RECOVERY_SCENARIOS
    )
    privacy_scenario_passed = (
        _mapping(scenario_checks.get(PRIVACY_SCENARIO)).get("passed") is True
    )
    contract_checks = {
        "contract_validation_passed": contract_source.get("ok") is True,
        "schema_inventory_present": _positive_count(contract_source.get("schema_count")),
        "positive_examples_present": _positive_count(
            contract_source.get("example_count")
        ),
        "negative_examples_present": _positive_count(
            contract_source.get("negative_example_count")
        ),
        "openapi_inventory_present": _positive_count(
            contract_source.get("openapi_count")
        ),
        "contract_failures_absent": not contract_failures,
        "golden_scenarios_passed": golden_source.get("status") == "PASS",
        "failure_recovery_scenarios_passed": recovery_passed,
        "privacy_export_scenario_passed": privacy_scenario_passed,
        "privacy_violations_absent": not privacy_violations,
    }
    contract_passed = all(contract_checks.values())
    contract_metrics = {
        "contract_validation_passed": contract_passed,
        "privacy_violation_count": len(privacy_violations),
        "schema_count": _safe_count(contract_source.get("schema_count")),
        "example_count": _safe_count(contract_source.get("example_count")),
        "negative_example_count": _safe_count(
            contract_source.get("negative_example_count")
        ),
        "openapi_count": _safe_count(contract_source.get("openapi_count")),
        "recovery_scenario_count": len(RECOVERY_SCENARIOS)
        if recovery_passed
        else 0,
    }
    contract_gate = _gate(
        gate_id="contract_privacy",
        passed=contract_passed,
        execution_mode="deterministic",
        actual_execution=False,
        metrics=contract_metrics,
        checks=contract_checks,
        observed_at=observed_at,
    )

    database_residue_count = _safe_count(
        residue_source.get("database_residue_count")
    )
    file_residue_count = _safe_count(residue_source.get("file_residue_count"))
    running_process_count = _safe_count(
        residue_source.get("running_process_count")
    )
    residue_checks = {
        "protected_execution_observed": residue_source.get("actual_execution")
        is True,
        "five_database_cleanup_observed": residue_source.get("database_count") == 5,
        "database_residue_absent": database_residue_count == 0,
        "file_cleanup_probe_absent": (
            residue_source.get("file_cleanup_probe") is True
            and file_residue_count == 0
        ),
        "thirteen_processes_stopped": (
            residue_source.get("stopped_process_count") == 13
            and running_process_count == 0
        ),
    }
    residue_passed = all(residue_checks.values())
    residue_metrics = {
        "database_residue_count": database_residue_count,
        "file_residue_count": file_residue_count,
        "running_process_count": running_process_count,
        "database_count": _safe_count(residue_source.get("database_count")),
        "stopped_process_count": _safe_count(
            residue_source.get("stopped_process_count")
        ),
    }
    residue_gate = _gate(
        gate_id="zero_residue",
        passed=residue_passed,
        execution_mode="protected",
        actual_execution=residue_source.get("actual_execution") is True,
        metrics=residue_metrics,
        checks=residue_checks,
        observed_at=observed_at,
    )

    deferrals = _sequence(residue_source.get("deployment_deferrals"))
    deferral_checks = {
        "inventory_exact": tuple(deferrals) == DEPLOYMENT_DEFERRALS,
        "production_deployment_not_approved": residue_source.get(
            "production_deployment_approved"
        )
        is False,
        "release_candidate_scope_only": residue_source.get("release_scope")
        == "MVP_RELEASE_CANDIDATE",
    }
    deferrals_passed = all(deferral_checks.values())
    deferral_gate = _gate(
        gate_id="deployment_deferrals",
        passed=deferrals_passed,
        execution_mode="deterministic",
        actual_execution=False,
        metrics={
            "deferral_count": len(deferrals),
            "production_deployment_approved": residue_source.get(
                "production_deployment_approved"
            ),
        },
        checks=deferral_checks,
        observed_at=observed_at,
    )
    passed = contract_passed and residue_passed and deferrals_passed
    return {
        "schema_version": RELEASE_CANDIDATE_ASSURANCE_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "release_candidate_assurance_failed",
        "checks": {
            "contract_privacy": contract_passed,
            "failure_recovery": recovery_passed,
            "zero_residue": residue_passed,
            "deployment_deferrals": deferrals_passed,
        },
        "gate_evidence": [contract_gate, residue_gate, deferral_gate],
    }


def _gate(
    *,
    gate_id: str,
    passed: bool,
    execution_mode: str,
    actual_execution: bool,
    metrics: Mapping[str, Any],
    checks: Mapping[str, bool],
    observed_at: datetime | None,
) -> dict[str, Any]:
    evidence = {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "gate_id": gate_id,
        "status": "PASS" if passed else "FAIL",
        "execution_mode": execution_mode,
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


def _sequence(value: object) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(value)


def _positive_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


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
