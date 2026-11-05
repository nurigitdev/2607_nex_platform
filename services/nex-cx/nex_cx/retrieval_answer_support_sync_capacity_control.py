from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = "cx_answer_support_sync_capacity_control_design.v1"
RECEIPT_SCHEMA_VERSION = "cx_answer_support_sync_capacity_control_receipt.v1"
MANIFEST_SCHEMA_VERSION = "cx_answer_support_sync_capacity_control_manifest.v1"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "control_experiment",
    "comparison_policy",
    "safety",
}
_SOURCE_FIELDS = {
    "artifact_evidence_hash",
    "capacity_design_hash",
    "capacity_receipt_hash",
    "case_set_hash",
    "provider_binding_hash",
    "request_profile_hash",
    "signal_design_hash",
}
_EXPERIMENT = {
    "concurrency": 1,
    "environment_precondition": ("OPERATOR_CONFIRMED_NO_KNOWN_COMPETING_VLLM_REQUESTS"),
    "maximum_provider_calls": 30,
    "provider_timeout_ms": 60_000,
    "sample_count": 30,
    "temporal_position": "TRAILING_AFTER_CONCURRENCY_2_AND_4",
}
_POLICY = {
    "background_provider_p95_latency_ms": 45_000,
    "capacity_effect_ratio_min": 1.5,
    "maximum_error_count": 0,
    "maximum_profile_p95_latency_ms": 60_000,
    "near_live_profile_ratio_max": 1.25,
    "original_baseline_improvement_ratio_max": 0.5,
}
_SAFETY = {
    "causal_concurrency_attribution_permitted": False,
    "database_call_permitted": False,
    "holdout_access_permitted": False,
    "private_text_persistence_permitted": False,
    "production_cutover_permitted": False,
    "runtime_activation_permitted": False,
}
_PROFILE_FIELDS = {
    "concurrency",
    "source",
    "request_count",
    "provider_request_count",
    "error_count",
    "latency_sample_count",
    "p95_latency_ms",
    "maximum_latency_ms",
    "elapsed_seconds",
    "throughput_rps",
    "total_tokens",
}
_RECEIPT_FIELDS = {
    "receipt_schema_version",
    "status",
    "control_design_hash",
    "capacity_receipt_hash",
    "source_binding",
    "operator_observation",
    "control_profile",
    "provider_http_requests",
    "database_calls",
    "holdout_accessed",
    "runtime_activation_permitted",
    "production_cutover_permitted",
    "receipt_hash",
}


class SyncCapacityControlError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_sync_capacity_control_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(_mapping(design, "design"))
    supplied_hash = normalized.pop("design_hash", None)
    _exact(normalized, _DESIGN_FIELDS, "design")
    if (
        normalized.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or normalized.get("status") != "FROZEN_PRE_OBSERVATION"
        or not isinstance(normalized.get("design_id"), str)
        or not normalized["design_id"]
    ):
        raise _invalid("design_identity")
    source = _exact(normalized.get("source_binding"), _SOURCE_FIELDS, "source")
    normalized["source_binding"] = {
        key: _hash_ref(source.get(key), key) for key in sorted(_SOURCE_FIELDS)
    }
    if dict(_mapping(normalized.get("control_experiment"), "experiment")) != (
        _EXPERIMENT
    ):
        raise _invalid("control_experiment")
    if dict(_mapping(normalized.get("comparison_policy"), "policy")) != _POLICY:
        raise _invalid("comparison_policy")
    if dict(_mapping(normalized.get("safety"), "safety")) != _SAFETY:
        raise _invalid("safety")
    calculated = semantic_sha256_hash_ref(normalized)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "design_hash") != calculated
    ):
        raise _integrity("design")
    normalized["design_hash"] = calculated
    return normalized


def validate_sync_capacity_control_entry(
    *,
    design: Mapping[str, Any],
    capacity_receipt: Mapping[str, Any],
    artifact_evidence_hash: str,
) -> dict[str, Any]:
    normalized = validate_sync_capacity_control_design(design)
    source = normalized["source_binding"]
    if (
        capacity_receipt.get("status") != "PASS"
        or capacity_receipt.get("receipt_hash") != source["capacity_receipt_hash"]
        or capacity_receipt.get("design_hash") != source["capacity_design_hash"]
        or capacity_receipt.get("source_binding", {}).get("artifact_evidence_hash")
        != source["artifact_evidence_hash"]
        or _hash_ref(artifact_evidence_hash, "artifact_evidence_hash")
        != source["artifact_evidence_hash"]
    ):
        raise _integrity("entry_source")
    return normalized


def evaluate_sync_capacity_control_receipt(
    receipt: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    capacity_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_design = validate_sync_capacity_control_design(design)
    normalized = _validate_receipt(receipt, design=normalized_design)
    source_profiles = capacity_receipt.get("profiles")
    if not isinstance(source_profiles, list):
        raise _invalid("capacity_profiles")
    profiles = {
        row.get("concurrency"): row
        for row in source_profiles
        if isinstance(row, Mapping)
    }
    if set(profiles) != {1, 2, 4}:
        raise _invalid("capacity_profiles")
    control = normalized["control_profile"]
    for row in profiles.values():
        _profile(
            row,
            expected_concurrency=int(row["concurrency"]),
            expected_sources={"P_V_BASELINE_RECEIPT", "SYNCHRONOUS_LIVE_REPLAY"},
        )

    original_ratio = _ratio(control["p95_latency_ms"], profiles[1]["p95_latency_ms"])
    c2_ratio = _ratio(control["p95_latency_ms"], profiles[2]["p95_latency_ms"])
    c4_ratio = _ratio(control["p95_latency_ms"], profiles[4]["p95_latency_ms"])
    live_reference = max(profiles[2]["p95_latency_ms"], profiles[4]["p95_latency_ms"])
    policy = normalized_design["comparison_policy"]
    if control["error_count"] > policy["maximum_error_count"]:
        observation = "TRAILING_CONTROL_FAILED"
    elif (
        control["p95_latency_ms"]
        <= (live_reference * policy["near_live_profile_ratio_max"])
        and original_ratio <= policy["original_baseline_improvement_ratio_max"]
    ):
        observation = "ORIGINAL_C1_TEMPORAL_CONFOUND_LIKELY"
    elif control["p95_latency_ms"] >= (
        live_reference * policy["capacity_effect_ratio_min"]
    ):
        observation = "CONCURRENCY_OR_BATCHING_EFFECT_PLAUSIBLE"
    else:
        observation = "MIXED_OR_INCONCLUSIVE"

    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "observation": observation,
        "control_design_hash": normalized_design["design_hash"],
        "source_capacity_receipt_hash": normalized["capacity_receipt_hash"],
        "source_capacity_profiles": source_profiles,
        "trailing_control_profile": control,
        "p95_ratio_trailing_to_original_c1": original_ratio,
        "p95_ratio_trailing_to_c2": c2_ratio,
        "p95_ratio_trailing_to_c4": c4_ratio,
        "background_slo_met": (
            control["p95_latency_ms"] <= policy["background_provider_p95_latency_ms"]
        ),
        "timeout_bound_met": (
            control["p95_latency_ms"] <= policy["maximum_profile_p95_latency_ms"]
        ),
        "causal_concurrency_attribution_permitted": False,
        "execution_mode_selected": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": "SYNCHRONOUS_CAPACITY_OPERATOR_INTERPRETATION",
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _validate_receipt(
    receipt: Mapping[str, Any], *, design: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = dict(_exact(receipt, _RECEIPT_FIELDS, "receipt"))
    receipt_hash = _hash_ref(normalized.pop("receipt_hash", None), "receipt_hash")
    if semantic_sha256_hash_ref(normalized) != receipt_hash:
        raise _integrity("receipt")
    normalized["receipt_hash"] = receipt_hash
    observation = _mapping(normalized.get("operator_observation"), "observation")
    profile = _profile(normalized.get("control_profile"), expected_concurrency=1)
    experiment = design["control_experiment"]
    if (
        normalized.get("receipt_schema_version") != RECEIPT_SCHEMA_VERSION
        or normalized.get("status") != "PASS"
        or normalized.get("control_design_hash") != design["design_hash"]
        or normalized.get("capacity_receipt_hash")
        != design["source_binding"]["capacity_receipt_hash"]
        or normalized.get("source_binding") != design["source_binding"]
        or observation.get("dgx_idle_confirmed") is not True
        or not isinstance(observation.get("operator_id_hash"), str)
        or profile["request_count"] != experiment["sample_count"]
        or normalized.get("provider_http_requests")
        != experiment["maximum_provider_calls"]
        or normalized.get("database_calls") != 0
        or normalized.get("holdout_accessed") is not False
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("production_cutover_permitted") is not False
    ):
        raise _invalid("receipt_boundary")
    normalized["control_profile"] = profile
    return normalized


def _profile(
    value: object,
    *,
    expected_concurrency: int,
    expected_sources: set[str] | None = None,
) -> dict[str, Any]:
    row = dict(_exact(value, _PROFILE_FIELDS, "profile"))
    integer_fields = {
        "concurrency",
        "request_count",
        "provider_request_count",
        "error_count",
        "latency_sample_count",
        "total_tokens",
    }
    numeric_fields = {
        "p95_latency_ms",
        "maximum_latency_ms",
        "elapsed_seconds",
        "throughput_rps",
    }
    if (
        row.get("concurrency") != expected_concurrency
        or row.get("source")
        not in (expected_sources or {"SYNCHRONOUS_LIVE_TRAILING_CONTROL"})
        or any(
            not isinstance(row.get(key), int) or isinstance(row.get(key), bool)
            for key in integer_fields
        )
        or any(
            not isinstance(row.get(key), (int, float))
            or isinstance(row.get(key), bool)
            or row[key] <= 0
            for key in numeric_fields
        )
        or row["request_count"] != row["provider_request_count"]
        or row["request_count"] != row["latency_sample_count"]
        or row["error_count"] < 0
        or row["maximum_latency_ms"] < row["p95_latency_ms"]
    ):
        raise _invalid("profile")
    return row


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        raise _invalid("ratio_denominator")
    return round(numerator / denominator, 6)


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


def _invalid(detail: str) -> SyncCapacityControlError:
    return SyncCapacityControlError("SYNC_CAPACITY_CONTROL_INVALID", detail)


def _integrity(detail: str) -> SyncCapacityControlError:
    return SyncCapacityControlError("SYNC_CAPACITY_CONTROL_INTEGRITY", detail)
