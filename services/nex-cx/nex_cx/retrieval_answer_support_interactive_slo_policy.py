from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = "cx_answer_support_interactive_slo_policy_design.v1"
OPERATOR_DECISION_SCHEMA_VERSION = (
    "cx_answer_support_interactive_slo_operator_decision.v1"
)
MANIFEST_SCHEMA_VERSION = "cx_answer_support_interactive_slo_policy_manifest.v1"
DECISION = "SYNCHRONOUS_BOUNDED_C4_SELECTED_PENDING_E2E_ACCEPTANCE"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "slo_profile",
    "runtime_policy",
    "decision_policy",
    "safety",
}
_SOURCE_FIELDS = {
    "capacity_design_hash",
    "capacity_manifest_hash",
    "capacity_receipt_hash",
    "control_design_hash",
    "control_manifest_hash",
    "control_receipt_hash",
    "provider_binding_hash",
}
_SLO_PROFILE = {
    "prompt_acceptance_feedback_p95_latency_ms": 2_000,
    "generation_provider_p95_latency_ms": 15_000,
    "interactive_final_response_e2e_p95_latency_ms": 20_000,
    "background_provider_p95_latency_ms": 45_000,
    "request_timeout_ms": 60_000,
}
_RUNTIME_POLICY = {
    "execution_mode": "SYNCHRONOUS",
    "maximum_in_flight_provider_requests": 4,
    "admission_strategy": "BOUNDED_SEMAPHORE",
    "overload_behavior": "DEFER_OR_REJECT_RETRYABLE",
    "generation_request_timeout_ms": 60_000,
    "reasoning_mode": "DISABLED",
    "selection_status": "SELECTED_PENDING_E2E_ACCEPTANCE",
}
_DECISION_POLICY = {
    "required_capacity_profiles": [1, 2, 4],
    "maximum_provider_errors": 0,
    "required_control_observation": "ORIGINAL_C1_TEMPORAL_CONFOUND_LIKELY",
    "selected_concurrency_rule": ("HIGHEST_THROUGHPUT_ZERO_ERROR_PROVIDER_SLO_PROFILE"),
    "automatic_runtime_activation_permitted": False,
}
_SAFETY = {
    "provider_call_permitted": False,
    "database_call_permitted": False,
    "holdout_access_permitted": False,
    "runtime_activation_permitted": False,
    "production_cutover_permitted": False,
}
_OPERATOR_FIELDS = {
    "decision_schema_version",
    "status",
    "decision",
    "operator_id",
    "decided_at",
    "design_hash",
    "capacity_receipt_hash",
    "control_receipt_hash",
    "selected_policy_hash",
    "reason_codes",
    "runtime_activation_approved",
    "production_cutover_approved",
    "decision_hash",
}


class InteractiveSloPolicyError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_interactive_slo_policy_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(_mapping(design, "design"))
    supplied_hash = normalized.pop("design_hash", None)
    _exact(normalized, _DESIGN_FIELDS, "design")
    if (
        normalized.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or normalized.get("status") != "FROZEN_OPERATOR_DECISION"
        or not _text(normalized.get("design_id"))
    ):
        raise _invalid("design_identity")
    source = _exact(normalized.get("source_binding"), _SOURCE_FIELDS, "source")
    normalized["source_binding"] = {
        key: _hash_ref(source.get(key), key) for key in sorted(_SOURCE_FIELDS)
    }
    for field, expected in (
        ("slo_profile", _SLO_PROFILE),
        ("runtime_policy", _RUNTIME_POLICY),
        ("decision_policy", _DECISION_POLICY),
        ("safety", _SAFETY),
    ):
        if dict(_mapping(normalized.get(field), field)) != expected:
            raise _invalid(field)
    calculated = semantic_sha256_hash_ref(normalized)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "design_hash") != calculated
    ):
        raise _integrity("design")
    normalized["design_hash"] = calculated
    return normalized


def build_interactive_slo_operator_decision(
    *,
    operator_id: str,
    decided_at: str,
    design: Mapping[str, Any],
    capacity_manifest: Mapping[str, Any],
    control_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_interactive_slo_policy_design(design)
    evidence = _assess_evidence(
        normalized,
        capacity_manifest=capacity_manifest,
        control_manifest=control_manifest,
    )
    selected_policy = _selected_policy(normalized)
    decision: dict[str, Any] = {
        "decision_schema_version": OPERATOR_DECISION_SCHEMA_VERSION,
        "status": "DECIDED",
        "decision": DECISION,
        "operator_id": _required_text(operator_id, "operator_id"),
        "decided_at": _timestamp(decided_at, "decided_at"),
        "design_hash": normalized["design_hash"],
        "capacity_receipt_hash": normalized["source_binding"]["capacity_receipt_hash"],
        "control_receipt_hash": normalized["source_binding"]["control_receipt_hash"],
        "selected_policy_hash": selected_policy["policy_hash"],
        "reason_codes": list(evidence["reason_codes"]),
        "runtime_activation_approved": False,
        "production_cutover_approved": False,
    }
    decision["decision_hash"] = semantic_sha256_hash_ref(decision)
    return decision


def decide_interactive_slo_runtime_policy(
    *,
    design: Mapping[str, Any],
    capacity_manifest: Mapping[str, Any],
    control_manifest: Mapping[str, Any],
    operator_decision: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_interactive_slo_policy_design(design)
    evidence = _assess_evidence(
        normalized,
        capacity_manifest=capacity_manifest,
        control_manifest=control_manifest,
    )
    operator = _validate_operator_decision(
        operator_decision,
        design=normalized,
        reason_codes=evidence["reason_codes"],
    )
    policy = _selected_policy(normalized)
    checks = {
        "capacity_receipt_binding_verified": True,
        "control_receipt_binding_verified": True,
        "fresh_c1_c2_c4_profiles_complete": True,
        "zero_provider_errors_verified": True,
        "provider_p95_slo_met": True,
        "highest_throughput_profile_selected": True,
        "prompt_feedback_measurement_pending": True,
        "interactive_e2e_measurement_pending": True,
        "bounded_admission_wiring_pending": True,
        "runtime_activation_prohibited": True,
        "production_cutover_prohibited": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": DECISION,
        "design_hash": normalized["design_hash"],
        "operator_decision_hash": operator["decision_hash"],
        "selected_policy": policy,
        "observed_capacity": evidence["observed_capacity"],
        "reason_codes": list(evidence["reason_codes"]),
        "checks": checks,
        "pending_acceptance": [
            "PROMPT_ACCEPTANCE_FEEDBACK_P95_MEASUREMENT",
            "INTERACTIVE_FINAL_RESPONSE_E2E_P95_MEASUREMENT",
            "BOUNDED_IN_FLIGHT_ADMISSION_RUNTIME_WIRING",
        ],
        "execution_mode_selected": True,
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": "SYNCHRONOUS_RUNTIME_E2E_ACCEPTANCE",
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _assess_evidence(
    design: Mapping[str, Any],
    *,
    capacity_manifest: Mapping[str, Any],
    control_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    source = design["source_binding"]
    capacity = _verified_manifest(capacity_manifest, "capacity_manifest")
    control = _verified_manifest(control_manifest, "control_manifest")
    if (
        capacity.get("status") != "PASS"
        or capacity.get("manifest_hash") != source["capacity_manifest_hash"]
        or capacity.get("source_receipt_hash") != source["capacity_receipt_hash"]
        or capacity.get("design_hash") != source["capacity_design_hash"]
        or control.get("status") != "PASS"
        or control.get("manifest_hash") != source["control_manifest_hash"]
        or control.get("source_capacity_receipt_hash")
        != source["capacity_receipt_hash"]
        or control.get("control_design_hash") != source["control_design_hash"]
    ):
        raise _integrity("source_evidence")
    if (
        control.get("observation")
        != design["decision_policy"]["required_control_observation"]
    ):
        raise _invalid("control_observation")

    capacity_profiles = _profiles(capacity.get("profile_assessments"))
    control_profile = _profile(control.get("trailing_control_profile"), 1)
    profiles = {
        1: control_profile,
        2: capacity_profiles[2],
        4: capacity_profiles[4],
    }
    provider_slo = design["slo_profile"]["generation_provider_p95_latency_ms"]
    if any(
        row["error_count"] > design["decision_policy"]["maximum_provider_errors"]
        or row["p95_latency_ms"] > provider_slo
        for row in profiles.values()
    ):
        raise _invalid("provider_slo")
    selected = max(
        profiles.values(),
        key=lambda row: (row["throughput_rps"], -row["concurrency"]),
    )
    if (
        selected["concurrency"]
        != design["runtime_policy"]["maximum_in_flight_provider_requests"]
    ):
        raise _invalid("selected_concurrency")
    observed = {
        "profiles": [profiles[key] for key in sorted(profiles)],
        "selected_concurrency": selected["concurrency"],
        "maximum_fresh_provider_p95_latency_ms": max(
            row["p95_latency_ms"] for row in profiles.values()
        ),
        "selected_throughput_rps": selected["throughput_rps"],
        "provider_slo_met": True,
        "prompt_feedback_slo_measured": False,
        "interactive_e2e_slo_measured": False,
    }
    return {
        "observed_capacity": observed,
        "reason_codes": (
            "FRESH_PROVIDER_P95_WITHIN_15_SECONDS",
            "C4_HIGHEST_OBSERVED_ZERO_ERROR_THROUGHPUT",
            "ORIGINAL_C1_TEMPORAL_CONFOUND_EXCLUDED",
            "INTERACTIVE_E2E_ACCEPTANCE_REQUIRED_BEFORE_ACTIVATION",
        ),
    }


def _validate_operator_decision(
    value: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    reason_codes: Sequence[str],
) -> dict[str, Any]:
    normalized = dict(_exact(value, _OPERATOR_FIELDS, "operator_decision"))
    decision_hash = _hash_ref(normalized.pop("decision_hash", None), "decision_hash")
    if semantic_sha256_hash_ref(normalized) != decision_hash:
        raise _integrity("operator_decision")
    normalized["decision_hash"] = decision_hash
    policy_hash = _selected_policy(design)["policy_hash"]
    if (
        normalized.get("decision_schema_version") != OPERATOR_DECISION_SCHEMA_VERSION
        or normalized.get("status") != "DECIDED"
        or normalized.get("decision") != DECISION
        or normalized.get("design_hash") != design["design_hash"]
        or normalized.get("capacity_receipt_hash")
        != design["source_binding"]["capacity_receipt_hash"]
        or normalized.get("control_receipt_hash")
        != design["source_binding"]["control_receipt_hash"]
        or normalized.get("selected_policy_hash") != policy_hash
        or normalized.get("reason_codes") != list(reason_codes)
        or normalized.get("runtime_activation_approved") is not False
        or normalized.get("production_cutover_approved") is not False
    ):
        raise _invalid("operator_decision")
    _required_text(normalized.get("operator_id"), "operator_id")
    _timestamp(normalized.get("decided_at"), "decided_at")
    return normalized


def _selected_policy(design: Mapping[str, Any]) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "policy_schema_version": "cx_answer_support_interactive_slo_runtime_policy.v1",
        "status": "SELECTED_PENDING_E2E_ACCEPTANCE",
        "slo_profile": dict(design["slo_profile"]),
        "runtime_policy": dict(design["runtime_policy"]),
        "fallback_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
    return policy


def _verified_manifest(value: object, name: str) -> dict[str, Any]:
    manifest = dict(_mapping(value, name))
    manifest_hash = _hash_ref(manifest.pop("manifest_hash", None), "manifest_hash")
    if semantic_sha256_hash_ref(manifest) != manifest_hash:
        raise _integrity(name)
    manifest["manifest_hash"] = manifest_hash
    return manifest


def _profiles(value: object) -> dict[int, dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("capacity_profiles")
    rows = {}
    for item in value:
        if not isinstance(item, Mapping):
            continue
        concurrency = item.get("concurrency")
        if concurrency in {2, 4}:
            rows[int(concurrency)] = _profile(item, int(concurrency))
    if set(rows) != {2, 4}:
        raise _invalid("capacity_profiles")
    return rows


def _profile(value: object, expected_concurrency: int) -> dict[str, Any]:
    row = _mapping(value, "profile")
    required = {
        "concurrency",
        "error_count",
        "p95_latency_ms",
        "maximum_latency_ms",
        "throughput_rps",
        "request_count",
    }
    if not required.issubset(row):
        raise _invalid("profile_fields")
    if (
        row.get("concurrency") != expected_concurrency
        or not _nonnegative_int(row.get("error_count"))
        or not _positive_number(row.get("p95_latency_ms"))
        or not _positive_number(row.get("maximum_latency_ms"))
        or not _positive_number(row.get("throughput_rps"))
        or not _positive_int(row.get("request_count"))
        or row["maximum_latency_ms"] < row["p95_latency_ms"]
    ):
        raise _invalid("profile")
    return {
        "concurrency": expected_concurrency,
        "request_count": row["request_count"],
        "error_count": row["error_count"],
        "p95_latency_ms": row["p95_latency_ms"],
        "maximum_latency_ms": row["maximum_latency_ms"],
        "throughput_rps": row["throughput_rps"],
    }


def _timestamp(value: object, name: str) -> str:
    text = _required_text(value, name)
    if not text.endswith("Z"):
        raise _invalid(name)
    try:
        datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise _invalid(name) from exc
    return text


def _required_text(value: object, name: str) -> str:
    if not _text(value):
        raise _invalid(name)
    return str(value)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def _positive_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value > 0


def _positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _nonnegative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _exact(value: object, expected: set[str], name: str) -> Mapping[str, Any]:
    mapping = _mapping(value, name)
    if set(mapping) != expected:
        raise _invalid(f"{name}_fields")
    return mapping


def _hash_ref(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise _invalid(name)
    try:
        validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(name) from exc
    return value


def _invalid(detail: str) -> InteractiveSloPolicyError:
    return InteractiveSloPolicyError("INTERACTIVE_SLO_POLICY_INVALID", detail)


def _integrity(detail: str) -> InteractiveSloPolicyError:
    return InteractiveSloPolicyError("INTERACTIVE_SLO_POLICY_INTEGRITY", detail)
