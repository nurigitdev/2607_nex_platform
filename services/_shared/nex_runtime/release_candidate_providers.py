from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from .release_candidate import RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION


RELEASE_CANDIDATE_PROVIDER_SCHEMA_VERSION = (
    "platform_release_candidate_live_providers.v1"
)
EXPECTED_CAPABILITIES = ("embedding", "reranking", "generation")


def build_release_candidate_live_provider_evidence(
    provider_source: Mapping[str, Any],
    retrieval_source: Mapping[str, Any],
    grounded_source: Mapping[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    provider_payload = _mapping(provider_source.get("provider_evidence"))
    providers = _mapping(provider_payload.get("providers"))
    telemetry = _mapping_sequence(provider_payload.get("telemetry"))
    stages = _mapping(provider_source.get("stage_status"))
    calibration = _mapping(retrieval_source.get("calibration"))
    retrieval_checks = _bool_mapping(retrieval_source.get("checks"))
    grounded_checks = _bool_mapping(grounded_source.get("checks"))
    grounded_summary = _mapping(grounded_source.get("summary"))
    residue = _mapping(grounded_source.get("post_journey_residue"))
    database_identity = _mapping(retrieval_source.get("database_identity"))

    observed_capabilities = tuple(sorted(providers))
    failed_provider_count = sum(
        1
        for capability in EXPECTED_CAPABILITIES
        if stages.get(capability) != "PASS"
    )
    telemetry_failure_count = sum(
        _safe_count(item.get("failure_count")) for item in telemetry
    )
    model_revisions = {
        capability: _mapping(providers.get(capability)).get("model_revision")
        for capability in EXPECTED_CAPABILITIES
    }
    stable_model_bindings = all(
        isinstance(value, str) and bool(value.strip())
        for value in model_revisions.values()
    )
    actual_execution = (
        _mapping(provider_source.get("activation")).get("enabled") is True
        and database_identity.get("database") == "nex_cx_test"
        and grounded_source.get("actual_postgres") is True
        and grounded_source.get("live_provider_required") is True
    )
    checks = {
        "provider_source_passed": provider_source.get("status") == "PASS",
        "three_capabilities_observed": observed_capabilities
        == tuple(sorted(EXPECTED_CAPABILITIES)),
        "provider_stages_passed": failed_provider_count == 0,
        "provider_telemetry_failure_free": telemetry_failure_count == 0,
        "model_bindings_observed_not_pinned": stable_model_bindings,
        "retrieval_source_passed": retrieval_source.get("status") == "PASS",
        "actual_cx_test_database": database_identity
        == {"database": "nex_cx_test", "role": "nex_cx_user"},
        "retrieval_checks_passed": bool(retrieval_checks)
        and all(retrieval_checks.values()),
        "multisignal_calibration_passed": (
            calibration.get("status") == "PASSED"
            and _safe_count(calibration.get("sample_count")) >= 20
            and isinstance(calibration.get("profile_hash"), str)
            and bool(calibration.get("profile_hash"))
        ),
        "grounded_source_passed": grounded_source.get("status") == "PASS",
        "grounded_checks_passed": bool(grounded_checks)
        and all(grounded_checks.values()),
        "grounded_three_capabilities": (
            grounded_summary.get("provider_capability_count") == 3
        ),
        "grounded_residue_free": bool(residue)
        and all(_safe_count(value) == 0 for value in residue.values()),
        "protected_execution_observed": actual_execution,
    }
    passed = all(checks.values())
    metrics = {
        "provider_capability_count": len(observed_capabilities),
        "failed_provider_count": failed_provider_count,
        "provider_telemetry_failure_count": telemetry_failure_count,
        "calibration_sample_count": _safe_count(calibration.get("sample_count")),
        "calibration_positive_count": _safe_count(
            calibration.get("positive_count")
        ),
        "calibration_negative_count": _safe_count(
            calibration.get("negative_count")
        ),
        "retrieval_check_count": len(retrieval_checks),
        "grounded_check_count": len(grounded_checks),
        "grounded_database_count": _safe_count(
            grounded_summary.get("database_count")
        ),
        "residue_count": sum(_safe_count(value) for value in residue.values()),
    }
    binding_projection = {
        "capability_count": len(model_revisions),
        "binding_sha256": _digest(model_revisions) if stable_model_bindings else None,
        "model_identity_controls_acceptance": False,
        "calibration_profile_sha256": calibration.get("profile_hash"),
        "selected_threshold": calibration.get("selected_threshold"),
    }
    gate_evidence = {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "gate_id": "live_provider_matrix",
        "status": "PASS" if passed else "FAIL",
        "execution_mode": "protected",
        "actual_execution": actual_execution,
        "private_payload_included": False,
        "observed_at": _utc_timestamp(observed_at),
        "metrics": metrics,
        "checks": checks,
        "model_binding": binding_projection,
    }
    gate_evidence["evidence_digest"] = _digest(gate_evidence)
    return {
        "schema_version": RELEASE_CANDIDATE_PROVIDER_SCHEMA_VERSION,
        "status": gate_evidence["status"],
        "failure_code": None if passed else "release_candidate_live_provider_failed",
        "checks": dict(checks),
        "gate_evidence": gate_evidence,
    }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_sequence(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_mapping(item) for item in value if isinstance(item, Mapping))


def _bool_mapping(value: object) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item is True for key, item in value.items()}


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
