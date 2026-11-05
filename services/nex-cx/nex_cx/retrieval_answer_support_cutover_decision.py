from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

CUTOVER_DECISION_DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_runtime_cutover_decision_design.v1"
)
CUTOVER_OPERATOR_DECISION_SCHEMA_VERSION = (
    "cx_answer_support_runtime_cutover_operator_decision.v1"
)
CUTOVER_DECISION_MANIFEST_SCHEMA_VERSION = (
    "cx_answer_support_runtime_cutover_decision_manifest.v1"
)
CUTOVER_DECISION = "CUTOVER_DEFERRED_CONTINUE_SHADOW"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "decision_policy",
    "rollout_boundary",
    "invalid_evidence_policy",
    "safety",
}
_SOURCE_FIELDS = {
    "shadow_canary_receipt_document_hash",
    "shadow_canary_receipt_hash",
    "shadow_canary_policy_hash",
    "readiness_manifest_hash",
    "runtime_profile_hash",
    "provider_binding_hash",
}
_EXPECTED_DECISION_POLICY = {
    "minimum_completed_shadow_samples": 30,
    "maximum_provider_failures": 0,
    "complete_latency_samples_required": True,
    "production_p95_slo_status": "NOT_FROZEN",
    "production_p95_latency_ms": None,
    "disagreement_policy_status": "EXTENDED_OBSERVATION_REQUIRED",
    "automatic_cutover_permitted": False,
}
_EXPECTED_ROLLOUT_BOUNDARY = {
    "current_runtime_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
    "candidate_mode": "SHADOW_ONLY",
    "fallback_policy_preserved": True,
    "operator_decision_required": True,
    "next_boundary": "EXTENDED_SHADOW_OBSERVATION_AND_LATENCY_SLO_FREEZE",
}
_EXPECTED_INVALID_EVIDENCE_POLICY = {
    "exact_receipt_binding_required": True,
    "latency_samples_complete_check_required": True,
    "latency_sample_count_required": True,
    "zero_latency_without_samples_rejected": True,
}
_EXPECTED_SAFETY = {
    "holdout_reexecution_permitted": False,
    "provider_call_permitted": False,
    "database_call_permitted": False,
    "runtime_activation_permitted": False,
    "production_cutover_permitted": False,
}
_RECEIPT_FIELDS = {
    "approval_hash",
    "checks",
    "completed_at",
    "decision",
    "manifest_hash",
    "maximum_provider_calls",
    "policy_hash",
    "production_cutover_permitted",
    "profile_hash",
    "provider_binding_hash",
    "provider_http_requests",
    "receipt_hash",
    "receipt_schema_version",
    "runtime_activation_permitted",
    "snapshot",
    "started_at",
    "status",
}
_REQUIRED_RECEIPT_CHECKS = {
    "holdout_not_accessed",
    "latency_budget_passed",
    "latency_samples_complete",
    "no_provider_failures",
    "one_shot_budget_completed",
    "operator_approval_bound",
    "production_cutover_prohibited",
    "provider_calls_exact",
    "runtime_activation_prohibited",
    "shadow_not_user_visible",
    "token_budget_passed",
}
_SNAPSHOT_FIELDS = {
    "approval_hash",
    "disagreement_count",
    "disagreement_rate",
    "error_rate",
    "failed_count",
    "latency_sample_count",
    "maximum_latency_ms",
    "maximum_provider_calls",
    "observed_count",
    "p95_latency_ms",
    "policy_hash",
    "production_cutover_permitted",
    "provider_calls",
    "runtime_activation_permitted",
    "snapshot_hash",
    "snapshot_schema_version",
    "status",
    "terminal_reason",
    "total_tokens",
    "user_visible",
}
_OPERATOR_DECISION_FIELDS = {
    "decision_schema_version",
    "status",
    "decision",
    "operator_id",
    "decided_at",
    "design_hash",
    "source_receipt_hash",
    "reason_codes",
    "runtime_activation_approved",
    "production_cutover_approved",
    "decision_hash",
}


class AnswerSupportCutoverDecisionError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_cutover_decision_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the frozen, fail-closed post-canary decision contract."""
    normalized = dict(design)
    supplied_hash = normalized.pop("design_hash", None)
    _exact_mapping(normalized, _DESIGN_FIELDS, "design")
    if (
        normalized.get("design_schema_version")
        != CUTOVER_DECISION_DESIGN_SCHEMA_VERSION
        or normalized.get("status") != "FROZEN_OPERATOR_DECISION"
    ):
        raise _invalid("design_identity")
    _required_text(normalized.get("design_id"), "design_id")
    source = _exact_mapping(
        normalized.get("source_binding"), _SOURCE_FIELDS, "source_binding"
    )
    normalized["source_binding"] = {
        key: validate_hash_ref(source.get(key)) for key in sorted(_SOURCE_FIELDS)
    }
    if dict(_mapping(normalized.get("decision_policy"), "decision_policy")) != (
        _EXPECTED_DECISION_POLICY
    ):
        raise _invalid("decision_policy")
    if dict(_mapping(normalized.get("rollout_boundary"), "rollout_boundary")) != (
        _EXPECTED_ROLLOUT_BOUNDARY
    ):
        raise _invalid("rollout_boundary")
    if dict(
        _mapping(normalized.get("invalid_evidence_policy"), "invalid_evidence_policy")
    ) != _EXPECTED_INVALID_EVIDENCE_POLICY:
        raise _invalid("invalid_evidence_policy")
    if dict(_mapping(normalized.get("safety"), "safety")) != _EXPECTED_SAFETY:
        raise _invalid("safety")
    calculated_hash = semantic_sha256_hash_ref(normalized)
    if supplied_hash is not None and validate_hash_ref(supplied_hash) != calculated_hash:
        raise _integrity("design")
    normalized["design_hash"] = calculated_hash
    return normalized


def assess_runtime_cutover_blockers(
    receipt: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Validate terminal canary evidence and return deterministic blockers."""
    normalized_design = validate_cutover_decision_design(design)
    normalized_receipt = _validate_terminal_canary_receipt(
        receipt, source=normalized_design["source_binding"]
    )
    snapshot = normalized_receipt["snapshot"]
    policy = normalized_design["decision_policy"]
    blockers: list[str] = []
    if snapshot["provider_calls"] < policy["minimum_completed_shadow_samples"]:
        blockers.append("SHADOW_SAMPLE_COUNT_BELOW_MINIMUM")
    blockers.append("PRODUCTION_LATENCY_SLO_NOT_FROZEN")
    if (
        policy["disagreement_policy_status"] == "EXTENDED_OBSERVATION_REQUIRED"
        and snapshot["disagreement_count"] > 0
    ):
        blockers.append("DISAGREEMENT_REQUIRES_EXTENDED_OBSERVATION")
    return normalized_receipt, tuple(blockers)


def build_runtime_cutover_operator_decision(
    *,
    operator_id: str,
    decided_at: str,
    receipt: Mapping[str, Any],
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an immutable operator deferral bound to the admitted receipt."""
    normalized_design = validate_cutover_decision_design(design)
    normalized_receipt, blockers = assess_runtime_cutover_blockers(
        receipt, design=normalized_design
    )
    decision = {
        "decision_schema_version": CUTOVER_OPERATOR_DECISION_SCHEMA_VERSION,
        "status": "DECIDED",
        "decision": CUTOVER_DECISION,
        "operator_id": _required_text(operator_id, "operator_id"),
        "decided_at": _timestamp(decided_at, "decided_at"),
        "design_hash": normalized_design["design_hash"],
        "source_receipt_hash": normalized_receipt["receipt_hash"],
        "reason_codes": list(blockers),
        "runtime_activation_approved": False,
        "production_cutover_approved": False,
    }
    decision["decision_hash"] = semantic_sha256_hash_ref(decision)
    return decision


def decide_answer_support_runtime_cutover(
    receipt: Mapping[str, Any],
    operator_decision: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Record a fail-closed cutover decision without provider or HOLDOUT access."""
    normalized_design = validate_cutover_decision_design(design)
    normalized_receipt, blockers = assess_runtime_cutover_blockers(
        receipt, design=normalized_design
    )
    normalized_operator = _validate_operator_decision(
        operator_decision,
        design=normalized_design,
        receipt=normalized_receipt,
        blockers=blockers,
    )
    snapshot = normalized_receipt["snapshot"]
    checks = {
        "terminal_receipt_integrity_verified": True,
        "corrected_latency_samples_complete": True,
        "zero_latency_defect_evidence_excluded": True,
        "exact_profile_provider_and_policy_binding_preserved": True,
        "shadow_sample_minimum_not_met": (
            "SHADOW_SAMPLE_COUNT_BELOW_MINIMUM" in blockers
        ),
        "production_latency_slo_not_frozen": (
            "PRODUCTION_LATENCY_SLO_NOT_FROZEN" in blockers
        ),
        "disagreement_extended_observation_required": (
            "DISAGREEMENT_REQUIRES_EXTENDED_OBSERVATION" in blockers
        ),
        "operator_deferral_integrity_verified": True,
        "current_runtime_policy_preserved": True,
        "runtime_activation_prohibited": True,
        "production_cutover_prohibited": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": CUTOVER_DECISION_MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": CUTOVER_DECISION,
        "design_hash": normalized_design["design_hash"],
        "operator_decision_hash": normalized_operator["decision_hash"],
        "source_receipt_hash": normalized_receipt["receipt_hash"],
        "source_receipt_document_hash": semantic_sha256_hash_ref(normalized_receipt),
        "observed_metrics": {
            "sample_count": snapshot["provider_calls"],
            "failed_count": snapshot["failed_count"],
            "latency_sample_count": snapshot["latency_sample_count"],
            "p95_latency_ms": snapshot["p95_latency_ms"],
            "maximum_latency_ms": snapshot["maximum_latency_ms"],
            "disagreement_count": snapshot["disagreement_count"],
            "disagreement_rate": snapshot["disagreement_rate"],
        },
        "reason_codes": list(blockers),
        "checks": checks,
        "failed_checks": [],
        "fallback_policy": normalized_design["rollout_boundary"][
            "current_runtime_policy"
        ],
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": normalized_design["rollout_boundary"]["next_boundary"],
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _validate_terminal_canary_receipt(
    receipt: Mapping[str, Any], *, source: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = dict(receipt)
    _exact_mapping(normalized, _RECEIPT_FIELDS, "receipt")
    receipt_hash = validate_hash_ref(normalized.pop("receipt_hash", None))
    if (
        semantic_sha256_hash_ref(normalized) != receipt_hash
        or receipt_hash != source["shadow_canary_receipt_hash"]
    ):
        raise _integrity("receipt")
    normalized["receipt_hash"] = receipt_hash
    if semantic_sha256_hash_ref(normalized) != source[
        "shadow_canary_receipt_document_hash"
    ]:
        raise _integrity("receipt_document")
    checks = _exact_mapping(
        normalized.get("checks"), _REQUIRED_RECEIPT_CHECKS, "receipt_checks"
    )
    counts = _exact_mapping(
        normalized.get("provider_http_requests"),
        {"generation", "total"},
        "provider_http_requests",
    )
    snapshot = _validate_snapshot(
        normalized.get("snapshot"), source=source, approval_hash=normalized.get("approval_hash")
    )
    maximum_calls = _positive_int(
        normalized.get("maximum_provider_calls"), "maximum_provider_calls"
    )
    if (
        normalized.get("receipt_schema_version")
        != "cx_answer_support_shadow_canary_receipt.v1"
        or normalized.get("status") != "PASS"
        or normalized.get("decision")
        != "SHADOW_CANARY_ACCEPTED_OPERATOR_REVIEW_REQUIRED"
        or normalized.get("policy_hash") != source["shadow_canary_policy_hash"]
        or normalized.get("manifest_hash") != source["readiness_manifest_hash"]
        or normalized.get("profile_hash") != source["runtime_profile_hash"]
        or normalized.get("provider_binding_hash") != source["provider_binding_hash"]
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("production_cutover_permitted") is not False
        or any(value is not True for value in checks.values())
        or counts.get("total") != maximum_calls
        or counts.get("generation") != maximum_calls
        or snapshot["provider_calls"] != maximum_calls
        or snapshot["latency_sample_count"] != maximum_calls
        or snapshot["observed_count"] != maximum_calls
        or snapshot["failed_count"] != 0
        or snapshot["error_rate"] != 0.0
    ):
        raise _invalid("receipt_boundary")
    if _parse_timestamp(normalized.get("completed_at"), "completed_at") <= (
        _parse_timestamp(normalized.get("started_at"), "started_at")
    ):
        raise _invalid("receipt_window")
    normalized["snapshot"] = snapshot
    return normalized


def _validate_snapshot(
    value: object, *, source: Mapping[str, Any], approval_hash: object
) -> dict[str, Any]:
    snapshot = dict(_exact_mapping(value, _SNAPSHOT_FIELDS, "snapshot"))
    snapshot_hash = validate_hash_ref(snapshot.pop("snapshot_hash", None))
    if semantic_sha256_hash_ref(snapshot) != snapshot_hash:
        raise _integrity("snapshot")
    snapshot["snapshot_hash"] = snapshot_hash
    numeric_fields = (
        "error_rate",
        "disagreement_rate",
        "p95_latency_ms",
        "maximum_latency_ms",
    )
    if any(not _nonnegative_number(snapshot.get(name)) for name in numeric_fields):
        raise _invalid("snapshot_metrics")
    integer_fields = (
        "provider_calls",
        "maximum_provider_calls",
        "observed_count",
        "failed_count",
        "disagreement_count",
        "latency_sample_count",
        "total_tokens",
    )
    if any(not _nonnegative_int(snapshot.get(name)) for name in integer_fields):
        raise _invalid("snapshot_counts")
    if (
        snapshot.get("snapshot_schema_version")
        != "cx_answer_support_shadow_canary_snapshot.v1"
        or snapshot.get("status") != "COMPLETED"
        or snapshot.get("terminal_reason") is not None
        or snapshot.get("policy_hash") != source["shadow_canary_policy_hash"]
        or snapshot.get("approval_hash") != approval_hash
        or snapshot.get("user_visible") is not False
        or snapshot.get("runtime_activation_permitted") is not False
        or snapshot.get("production_cutover_permitted") is not False
        or snapshot["maximum_latency_ms"] < snapshot["p95_latency_ms"]
    ):
        raise _invalid("snapshot_boundary")
    return snapshot


def _validate_operator_decision(
    decision: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    receipt: Mapping[str, Any],
    blockers: Sequence[str],
) -> dict[str, Any]:
    normalized = dict(decision)
    _exact_mapping(normalized, _OPERATOR_DECISION_FIELDS, "operator_decision")
    decision_hash = validate_hash_ref(normalized.pop("decision_hash", None))
    if semantic_sha256_hash_ref(normalized) != decision_hash:
        raise _integrity("operator_decision")
    reasons = normalized.get("reason_codes")
    if (
        normalized.get("decision_schema_version")
        != CUTOVER_OPERATOR_DECISION_SCHEMA_VERSION
        or normalized.get("status") != "DECIDED"
        or normalized.get("decision") != CUTOVER_DECISION
        or normalized.get("design_hash") != design["design_hash"]
        or normalized.get("source_receipt_hash") != receipt["receipt_hash"]
        or not isinstance(reasons, list)
        or tuple(reasons) != tuple(blockers)
        or normalized.get("runtime_activation_approved") is not False
        or normalized.get("production_cutover_approved") is not False
    ):
        raise _invalid("operator_decision_boundary")
    _required_text(normalized.get("operator_id"), "operator_id")
    _parse_timestamp(normalized.get("decided_at"), "decided_at")
    normalized["decision_hash"] = decision_hash
    return normalized


def _timestamp(value: object, name: str) -> str:
    parsed = _parse_timestamp(value, name)
    return parsed.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _invalid(name)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _invalid(name) from exc
    return parsed.astimezone(UTC)


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(name)
    return value


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _nonnegative_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) >= 0.0
    )


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(name)
    return value.strip()


def _exact_mapping(
    value: object, fields: set[str], name: str
) -> Mapping[str, Any]:
    normalized = _mapping(value, name)
    if set(normalized) != fields:
        raise _invalid(name)
    return normalized


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _invalid(name: str) -> AnswerSupportCutoverDecisionError:
    return AnswerSupportCutoverDecisionError(
        "cx.answer_support_runtime_cutover.contract_invalid",
        f"{name} is invalid.",
    )


def _integrity(name: str) -> AnswerSupportCutoverDecisionError:
    return AnswerSupportCutoverDecisionError(
        "cx.answer_support_runtime_cutover.integrity_invalid",
        f"{name} integrity validation failed.",
    )
