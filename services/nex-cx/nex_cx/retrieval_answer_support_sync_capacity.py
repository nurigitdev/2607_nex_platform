from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = "cx_answer_support_sync_capacity_design.v1"
RECEIPT_SCHEMA_VERSION = "cx_answer_support_sync_capacity_receipt.v1"
MANIFEST_SCHEMA_VERSION = "cx_answer_support_sync_capacity_manifest.v1"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "capacity_experiment",
    "decision_policy",
    "rollout_boundary",
    "safety",
}
_SOURCE_FIELDS = {
    "artifact_evidence_hash",
    "case_set_hash",
    "extended_shadow_design_hash",
    "extended_shadow_receipt_hash",
    "latency_slo_receipt_hash",
    "provider_binding_hash",
    "readiness_manifest_hash",
    "request_profile_hash",
    "runtime_profile_hash",
    "signal_design_hash",
}
_EXPECTED_EXPERIMENT = {
    "execution_mode": "SYNCHRONOUS",
    "concurrency_profiles": [1, 2, 4],
    "baseline_concurrency": 1,
    "baseline_receipt_reuse_required": True,
    "live_profiles_to_execute": [2, 4],
    "sample_count_per_profile": 30,
    "maximum_additional_provider_calls": 60,
    "provider_timeout_ms": 60_000,
    "operator_declared_vllm_max_num_seqs": 4,
    "co_resident_provider_ports": [9112, 9113, 9116],
    "co_resident_evidence_level": "BOUND_ENDPOINT_REACHABILITY_PROXY",
}
_EXPECTED_POLICY = {
    "interactive_e2e_p95_latency_ms": 8_000,
    "background_provider_p95_latency_ms": 45_000,
    "maximum_profile_p95_latency_ms": 60_000,
    "maximum_error_count_per_profile": 0,
    "recommended_profile_rule": (
        "HIGHEST_THROUGHPUT_AMONG_ZERO_ERROR_TIMEOUT_BOUND_PROFILES"
    ),
    "runtime_activation_from_this_evidence_permitted": False,
}
_EXPECTED_ROLLOUT = {
    "current_runtime_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
    "synchronous_execution_preselected": False,
    "asynchronous_execution_preselected": False,
    "production_cutover_requires_new_operator_decision": True,
    "next_boundary": "EXECUTION_MODE_OPERATOR_DECISION",
}
_EXPECTED_SAFETY = {
    "holdout_access_permitted": False,
    "database_call_permitted": False,
    "private_text_persistence_permitted": False,
    "runtime_activation_permitted": False,
    "production_cutover_permitted": False,
}
_RECEIPT_FIELDS = {
    "receipt_schema_version",
    "status",
    "design_hash",
    "source_binding",
    "environment_observation",
    "profiles",
    "provider_http_requests",
    "database_calls",
    "holdout_accessed",
    "runtime_activation_permitted",
    "production_cutover_permitted",
    "receipt_hash",
}
_ENVIRONMENT_FIELDS = {
    "evidence_level",
    "operator_declared_vllm_max_num_seqs",
    "port_reachability",
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


class AnswerSupportSyncCapacityError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_sync_capacity_design(design: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(_mapping(design, "design"))
    supplied_hash = normalized.pop("design_hash", None)
    _exact(normalized, _DESIGN_FIELDS, "design")
    if (
        normalized.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or normalized.get("status") != "FROZEN_PRE_OBSERVATION"
    ):
        raise _invalid("design_identity")
    _text(normalized.get("design_id"), "design_id")
    source = _exact(normalized.get("source_binding"), _SOURCE_FIELDS, "source")
    normalized["source_binding"] = {
        key: _hash_ref(source.get(key), key) for key in sorted(_SOURCE_FIELDS)
    }
    if dict(_mapping(normalized.get("capacity_experiment"), "experiment")) != (
        _EXPECTED_EXPERIMENT
    ):
        raise _invalid("capacity_experiment")
    if dict(_mapping(normalized.get("decision_policy"), "policy")) != (
        _EXPECTED_POLICY
    ):
        raise _invalid("decision_policy")
    if dict(_mapping(normalized.get("rollout_boundary"), "rollout")) != (
        _EXPECTED_ROLLOUT
    ):
        raise _invalid("rollout_boundary")
    if dict(_mapping(normalized.get("safety"), "safety")) != _EXPECTED_SAFETY:
        raise _invalid("safety")
    calculated_hash = semantic_sha256_hash_ref(normalized)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "design_hash") != calculated_hash
    ):
        raise _integrity("design")
    normalized["design_hash"] = calculated_hash
    return normalized


def evaluate_sync_capacity_receipt(
    receipt: Mapping[str, Any], *, design: Mapping[str, Any]
) -> dict[str, Any]:
    normalized_design = validate_sync_capacity_design(design)
    normalized = _validate_receipt(receipt, design=normalized_design)
    policy = normalized_design["decision_policy"]
    profiles = sorted(normalized["profiles"], key=lambda row: row["concurrency"])
    assessments = []
    eligible = []
    for profile in profiles:
        timeout_bound = (
            profile["p95_latency_ms"] <= policy["maximum_profile_p95_latency_ms"]
        )
        zero_error = profile["error_count"] == 0
        row = {
            **profile,
            "interactive_slo_met": (
                profile["p95_latency_ms"] <= policy["interactive_e2e_p95_latency_ms"]
            ),
            "background_slo_met": (
                profile["p95_latency_ms"]
                <= policy["background_provider_p95_latency_ms"]
            ),
            "timeout_bound_met": timeout_bound,
            "capacity_eligible": zero_error and timeout_bound,
        }
        assessments.append(row)
        if row["capacity_eligible"]:
            eligible.append(row)
    recommended = (
        max(eligible, key=lambda row: (row["throughput_rps"], -row["concurrency"]))
        if eligible
        else None
    )
    if recommended is None:
        decision = "SYNCHRONOUS_CAPACITY_INSUFFICIENT"
    elif recommended["interactive_slo_met"]:
        decision = "SYNCHRONOUS_INTERACTIVE_CANDIDATE_OPERATOR_REVIEW_REQUIRED"
    elif recommended["background_slo_met"]:
        decision = "SYNCHRONOUS_BACKGROUND_CANDIDATE_OPERATOR_REVIEW_REQUIRED"
    else:
        decision = "SYNCHRONOUS_TIMEOUT_BOUND_ONLY_OPERATOR_REVIEW_REQUIRED"
    baseline = profiles[0]
    throughput_gain = {
        str(row["concurrency"]): round(
            row["throughput_rps"] / baseline["throughput_rps"], 6
        )
        for row in profiles
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": decision,
        "design_hash": normalized_design["design_hash"],
        "source_receipt_hash": normalized["receipt_hash"],
        "profile_assessments": assessments,
        "throughput_gain_vs_concurrency_1": throughput_gain,
        "recommended_synchronous_concurrency": (
            recommended["concurrency"] if recommended is not None else None
        ),
        "co_resident_evidence_level": normalized["environment_observation"][
            "evidence_level"
        ],
        "all_bound_endpoints_reachable": all(
            normalized["environment_observation"]["port_reachability"].values()
        ),
        "execution_mode_selected": False,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": normalized_design["rollout_boundary"]["next_boundary"],
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def validate_sync_capacity_entry(
    *,
    design: Mapping[str, Any],
    cases_document: Mapping[str, Any],
    signal_design: Mapping[str, Any],
    request_profile: Mapping[str, Any],
    baseline_receipt: Mapping[str, Any],
    latency_slo_receipt: Mapping[str, Any],
    artifact_evidence_hash: str,
) -> dict[str, Any]:
    normalized = validate_sync_capacity_design(design)
    source = normalized["source_binding"]
    observed = {
        "case_set_hash": semantic_sha256_hash_ref(dict(cases_document)),
        "signal_design_hash": semantic_sha256_hash_ref(dict(signal_design)),
        "request_profile_hash": semantic_sha256_hash_ref(dict(request_profile)),
        "extended_shadow_receipt_hash": _document_hash(baseline_receipt),
        "latency_slo_receipt_hash": _document_hash(latency_slo_receipt),
        "artifact_evidence_hash": _hash_ref(
            artifact_evidence_hash, "artifact_evidence_hash"
        ),
    }
    if any(source[key] != value for key, value in observed.items()):
        raise _integrity("entry_source")
    if (
        baseline_receipt.get("status") != "PASS"
        or baseline_receipt.get("receipt_hash")
        != source["extended_shadow_receipt_hash"]
        or baseline_receipt.get("provider_binding_hash")
        != source["provider_binding_hash"]
        or baseline_receipt.get("manifest_hash") != source["readiness_manifest_hash"]
        or baseline_receipt.get("profile_hash") != source["runtime_profile_hash"]
        or latency_slo_receipt.get("status") != "PASS"
        or latency_slo_receipt.get("extended_shadow_receipt_hash")
        != source["extended_shadow_receipt_hash"]
    ):
        raise _invalid("entry_receipts")
    return normalized


def _validate_receipt(
    receipt: Mapping[str, Any], *, design: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = dict(_exact(receipt, _RECEIPT_FIELDS, "receipt"))
    receipt_hash = _hash_ref(normalized.pop("receipt_hash", None), "receipt_hash")
    if semantic_sha256_hash_ref(normalized) != receipt_hash:
        raise _integrity("receipt")
    normalized["receipt_hash"] = receipt_hash
    environment = dict(
        _exact(
            normalized.get("environment_observation"),
            _ENVIRONMENT_FIELDS,
            "environment",
        )
    )
    reachability = _mapping(environment.get("port_reachability"), "reachability")
    expected_ports = {
        str(port)
        for port in design["capacity_experiment"]["co_resident_provider_ports"]
    }
    if (
        set(reachability) != expected_ports
        or any(value is not True for value in reachability.values())
        or environment.get("evidence_level")
        != design["capacity_experiment"]["co_resident_evidence_level"]
        or environment.get("operator_declared_vllm_max_num_seqs")
        != design["capacity_experiment"]["operator_declared_vllm_max_num_seqs"]
    ):
        raise _invalid("environment")
    profiles = _profiles(normalized.get("profiles"))
    if (
        normalized.get("receipt_schema_version") != RECEIPT_SCHEMA_VERSION
        or normalized.get("status") != "PASS"
        or normalized.get("design_hash") != design["design_hash"]
        or normalized.get("source_binding") != design["source_binding"]
        or [row["concurrency"] for row in profiles]
        != design["capacity_experiment"]["concurrency_profiles"]
        or normalized.get("provider_http_requests")
        != design["capacity_experiment"]["maximum_additional_provider_calls"]
        or normalized.get("database_calls") != 0
        or normalized.get("holdout_accessed") is not False
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("production_cutover_permitted") is not False
    ):
        raise _invalid("receipt_boundary")
    normalized["environment_observation"] = environment
    normalized["profiles"] = profiles
    return normalized


def _profiles(value: object) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("profiles")
    rows = []
    for item in value:
        row = dict(_exact(item, _PROFILE_FIELDS, "profile"))
        integer_fields = (
            "concurrency",
            "request_count",
            "provider_request_count",
            "error_count",
            "latency_sample_count",
            "total_tokens",
        )
        numeric_fields = (
            "p95_latency_ms",
            "maximum_latency_ms",
            "elapsed_seconds",
            "throughput_rps",
        )
        if any(not _nonnegative_int(row.get(name)) for name in integer_fields):
            raise _invalid("profile_counts")
        if any(not _positive_number(row.get(name)) for name in numeric_fields):
            raise _invalid("profile_metrics")
        if (
            row["source"] not in {"P_V_BASELINE_RECEIPT", "SYNCHRONOUS_LIVE_REPLAY"}
            or row["request_count"] != 30
            or row["provider_request_count"] != 30
            or row["latency_sample_count"] != 30
            or row["maximum_latency_ms"] < row["p95_latency_ms"]
        ):
            raise _invalid("profile_boundary")
        rows.append(row)
    rows.sort(key=lambda row: row["concurrency"])
    return rows


def _document_hash(value: Mapping[str, Any]) -> str:
    receipt_hash = value.get("receipt_hash")
    if receipt_hash is not None and _hash_ref(receipt_hash, "receipt_hash") != (
        semantic_sha256_hash_ref(
            {key: item for key, item in value.items() if key != "receipt_hash"}
        )
    ):
        raise _integrity("source_receipt")
    return _hash_ref(receipt_hash, "receipt_hash")


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) > 0.0
    )


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(name)
    return value.strip()


def _hash_ref(value: object, name: str) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(name) from exc


def _exact(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    normalized = _mapping(value, name)
    if set(normalized) != fields:
        raise _invalid(name)
    return normalized


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _invalid(name: str) -> AnswerSupportSyncCapacityError:
    return AnswerSupportSyncCapacityError(
        "cx.answer_support_sync_capacity.contract_invalid", f"{name} is invalid."
    )


def _integrity(name: str) -> AnswerSupportSyncCapacityError:
    return AnswerSupportSyncCapacityError(
        "cx.answer_support_sync_capacity.integrity_invalid",
        f"{name} integrity validation failed.",
    )
