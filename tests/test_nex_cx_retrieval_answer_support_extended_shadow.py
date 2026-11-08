from __future__ import annotations

from copy import deepcopy

import pytest
from nex_cx.retrieval_answer_support_extended_shadow import (
    BACKGROUND_SLO_MET_DECISION,
    BACKGROUND_SLO_MISSED_DECISION,
    AnswerSupportExtendedShadowError,
    evaluate_extended_shadow_slo,
    validate_extended_shadow_entry,
    validate_extended_shadow_slo_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


def test_extended_shadow_slo_records_met_without_permitting_cutover() -> None:
    cutover, extended, design, policy, cases = _fixtures()

    admitted = validate_extended_shadow_entry(
        cutover,
        policy=policy,
        cases_document=cases,
        design=design,
    )
    result = evaluate_extended_shadow_slo(cutover, extended, design=admitted)

    assert result["status"] == "PASS"
    assert result["decision"] == BACKGROUND_SLO_MET_DECISION
    assert result["background_slo_status"] == "MET"
    assert result["observed_metrics"] == {
        "sample_count": 30,
        "failed_count": 0,
        "latency_sample_count": 30,
        "p95_latency_ms": 40_000.0,
        "maximum_latency_ms": 42_000.0,
        "disagreement_count": 4,
        "disagreement_rate": 4 / 30,
        "total_tokens": 9_000,
    }
    assert result["failed_checks"] == []
    assert result["provider_calls_during_evaluation"] == 0
    assert result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["runtime_activation_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert result["next_boundary"] == "ASYNC_SHADOW_EXECUTION_AND_CAPACITY_HARDENING"
    assert result["manifest_hash"].startswith("sha256:")


def test_extended_shadow_slo_preserves_miss_as_terminal_observation() -> None:
    cutover, extended, design, _policy, _cases = _fixtures(p95=46_000.0)

    result = evaluate_extended_shadow_slo(cutover, extended, design=design)

    assert result["status"] == "PASS"
    assert result["decision"] == BACKGROUND_SLO_MISSED_DECISION
    assert result["background_slo_status"] == "MISSED"
    assert result["failed_checks"] == ["background_provider_p95_slo_met"]
    assert result["production_cutover_permitted"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("status"),
        lambda value: value.__setitem__("status", "ACTIVE"),
        lambda value: value.__setitem__("design_id", " "),
        lambda value: value["latency_slo"].__setitem__(
            "background_provider_p95_latency_ms", 60_000
        ),
        lambda value: value["rollout_boundary"].__setitem__("candidate_mode", "ACTIVE"),
        lambda value: value["safety"].__setitem__("runtime_activation_permitted", True),
        lambda value: value["source_binding"].__setitem__(
            "runtime_profile_hash", "invalid"
        ),
    ],
)
def test_design_rejects_contract_drift(mutation) -> None:
    design = _fixtures()[2]
    mutation(design)
    with pytest.raises(AnswerSupportExtendedShadowError):
        validate_extended_shadow_slo_design(design)


def test_design_accepts_matching_embedded_hash_and_rejects_stale_hash() -> None:
    design = _fixtures()[2]
    design["design_hash"] = semantic_sha256_hash_ref(design)
    assert (
        validate_extended_shadow_slo_design(design)["design_hash"]
        == design["design_hash"]
    )

    design["design_id"] = "changed-but-valid-design-id"
    with pytest.raises(AnswerSupportExtendedShadowError, match="integrity"):
        validate_extended_shadow_slo_design(design)


def test_entry_rejects_policy_case_and_cutover_binding_drift() -> None:
    cutover, _extended, design, policy, cases = _fixtures()

    tampered_policy = {**policy, "maximum_provider_calls": 31}
    with pytest.raises(AnswerSupportExtendedShadowError, match="integrity"):
        validate_extended_shadow_entry(
            cutover,
            policy=tampered_policy,
            cases_document=cases,
            design=design,
        )

    tampered_cases = deepcopy(cases)
    tampered_cases["cases"][0]["query"] = "changed"
    with pytest.raises(AnswerSupportExtendedShadowError, match="integrity"):
        validate_extended_shadow_entry(
            cutover,
            policy=policy,
            cases_document=tampered_cases,
            design=design,
        )

    tampered_cutover = {**cutover, "decision": "CUTOVER_APPROVED"}
    with pytest.raises(AnswerSupportExtendedShadowError):
        validate_extended_shadow_entry(
            tampered_cutover,
            policy=policy,
            cases_document=cases,
            design=design,
        )


def test_cutover_document_and_boundary_drift_fail_closed() -> None:
    cutover, extended, design, _policy, _cases = _fixtures()
    design["source_binding"]["cutover_decision_receipt_document_hash"] = _hash(
        "wrong-document"
    )
    with pytest.raises(AnswerSupportExtendedShadowError, match="integrity"):
        evaluate_extended_shadow_slo(cutover, extended, design=design)

    cutover, extended, design, _policy, _cases = _fixtures()
    cutover["decision"] = "CUTOVER_APPROVED"
    cutover.pop("receipt_hash")
    cutover["receipt_hash"] = semantic_sha256_hash_ref(cutover)
    source = design["source_binding"]
    source["cutover_decision_receipt_hash"] = cutover["receipt_hash"]
    source["cutover_decision_receipt_document_hash"] = semantic_sha256_hash_ref(cutover)
    with pytest.raises(AnswerSupportExtendedShadowError, match="invalid"):
        evaluate_extended_shadow_slo(cutover, extended, design=design)


def test_non_mapping_and_extended_receipt_integrity_fail_closed() -> None:
    design = _fixtures()[2]
    design["source_binding"] = []
    with pytest.raises(AnswerSupportExtendedShadowError, match="invalid"):
        validate_extended_shadow_slo_design(design)

    cutover, extended, design, _policy, _cases = _fixtures()
    extended["status"] = "FAIL"
    with pytest.raises(AnswerSupportExtendedShadowError, match="integrity"):
        evaluate_extended_shadow_slo(cutover, extended, design=design)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("status"),
        lambda value: value.__setitem__("status", "FAIL"),
        lambda value: value.__setitem__("maximum_provider_calls", 29),
        lambda value: value["provider_http_requests"].__setitem__("total", 29),
        lambda value: value["checks"].__setitem__("provider_calls_exact", False),
        lambda value: value["snapshot"].__setitem__("failed_count", 1),
        lambda value: value["snapshot"].__setitem__("maximum_latency_ms", 39_000.0),
        lambda value: value["snapshot"].__setitem__("latency_sample_count", True),
        lambda value: value["snapshot"].__setitem__("error_rate", -1.0),
    ],
)
def test_extended_receipt_rejects_incomplete_or_invalid_evidence(mutation) -> None:
    cutover, extended, design, _policy, _cases = _fixtures()
    mutation(extended)
    _rehash_extended(extended)

    with pytest.raises(AnswerSupportExtendedShadowError):
        evaluate_extended_shadow_slo(cutover, extended, design=design)


def test_extended_receipt_rejects_tampered_snapshot_hash_and_source_binding() -> None:
    cutover, extended, design, _policy, _cases = _fixtures()
    extended["snapshot"]["total_tokens"] += 1
    _rehash_receipt_only(extended)
    with pytest.raises(AnswerSupportExtendedShadowError, match="integrity"):
        evaluate_extended_shadow_slo(cutover, extended, design=design)

    cutover, extended, design, _policy, _cases = _fixtures()
    extended["profile_hash"] = _hash("different-profile")
    _rehash_receipt_only(extended)
    with pytest.raises(AnswerSupportExtendedShadowError):
        evaluate_extended_shadow_slo(cutover, extended, design=design)


def _fixtures(*, p95: float = 40_000.0) -> tuple[dict, dict, dict, dict, dict]:
    policy = {
        "policy_schema_version": "cx_answer_support_shadow_canary_policy.v1",
        "policy_id": "test-extended-shadow",
        "status": "FROZEN_LIMITED_LIVE_CANARY",
        "maximum_provider_calls": 30,
        "maximum_concurrency": 1,
        "maximum_provider_failures": 0,
        "maximum_error_rate": 0.0,
        "maximum_single_latency_ms": 60_000,
        "maximum_p95_latency_ms": 60_000,
        "maximum_total_tokens": 60_000,
        "disagreement_is_observation_only": True,
        "fallback_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
        "user_visible": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    cases = {
        "case_schema_version": "cx_answer_support_shadow_canary_cases.v1",
        "case_set_id": "test-cases",
        "status": "FROZEN_PUBLIC_SYNTHETIC",
        "cases": [{"case_id": f"case-{index}"} for index in range(30)],
    }
    source = {
        "cutover_decision_manifest_hash": _hash("cutover-manifest"),
        "operator_decision_hash": _hash("operator-decision"),
        "readiness_manifest_hash": _hash("readiness"),
        "runtime_profile_hash": _hash("profile"),
        "provider_binding_hash": _hash("provider"),
        "extended_shadow_policy_hash": semantic_sha256_hash_ref(policy),
        "extended_case_set_hash": semantic_sha256_hash_ref(cases),
    }
    cutover = {
        "receipt_schema_version": (
            "cx_answer_support_runtime_cutover_decision_receipt.v1"
        ),
        "status": "PASS",
        "decision": "CUTOVER_DEFERRED_CONTINUE_SHADOW",
        "operator_decision_hash": source["operator_decision_hash"],
        "manifest_hash": source["cutover_decision_manifest_hash"],
        "source_receipt_hash": _hash("source-receipt"),
        "reason_codes": ["PRODUCTION_LATENCY_SLO_NOT_FROZEN"],
        "decided_at": "2026-11-05T03:00:00Z",
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    cutover["receipt_hash"] = semantic_sha256_hash_ref(cutover)
    source["cutover_decision_receipt_hash"] = cutover["receipt_hash"]
    source["cutover_decision_receipt_document_hash"] = semantic_sha256_hash_ref(cutover)
    design = {
        "design_schema_version": ("cx_answer_support_extended_shadow_slo_design.v1"),
        "design_id": "test-extended-shadow-slo",
        "status": "FROZEN_PRE_OBSERVATION",
        "source_binding": source,
        "latency_slo": {
            "minimum_completed_shadow_samples": 30,
            "interactive_e2e_p95_latency_ms": 8_000,
            "background_provider_p95_latency_ms": 45_000,
            "provider_timeout_ms": 60_000,
            "synchronous_inline_provider_call_permitted": False,
            "async_isolation_required": True,
        },
        "rollout_boundary": {
            "candidate_mode": "SHADOW_ONLY",
            "current_runtime_policy": ("CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY"),
            "latency_slo_source": ("S149_PROTECTED_LIVE_AND_S20QPT_SHADOW_BUDGET"),
            "production_cutover_requires_new_operator_decision": True,
            "next_boundary": "ASYNC_SHADOW_EXECUTION_AND_CAPACITY_HARDENING",
        },
        "safety": {
            "holdout_access_permitted": False,
            "database_call_permitted": False,
            "private_text_persistence_permitted": False,
            "disagreement_is_observation_only": True,
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
        },
    }
    approval_hash = _hash("approval")
    snapshot = {
        "snapshot_schema_version": "cx_answer_support_shadow_canary_snapshot.v1",
        "status": "COMPLETED",
        "terminal_reason": None,
        "policy_hash": source["extended_shadow_policy_hash"],
        "approval_hash": approval_hash,
        "provider_calls": 30,
        "maximum_provider_calls": 30,
        "observed_count": 30,
        "failed_count": 0,
        "error_rate": 0.0,
        "disagreement_count": 4,
        "disagreement_rate": 4 / 30,
        "latency_sample_count": 30,
        "p95_latency_ms": p95,
        "maximum_latency_ms": max(p95, 42_000.0),
        "total_tokens": 9_000,
        "user_visible": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    snapshot["snapshot_hash"] = semantic_sha256_hash_ref(snapshot)
    extended = {
        "receipt_schema_version": "cx_answer_support_shadow_canary_receipt.v1",
        "status": "PASS",
        "approval_hash": approval_hash,
        "policy_hash": source["extended_shadow_policy_hash"],
        "manifest_hash": source["readiness_manifest_hash"],
        "profile_hash": source["runtime_profile_hash"],
        "provider_binding_hash": source["provider_binding_hash"],
        "maximum_provider_calls": 30,
        "started_at": "2026-11-05T04:00:00Z",
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "completed_at": "2026-11-05T04:20:00Z",
        "snapshot": snapshot,
        "provider_http_requests": {"total": 30, "generation": 30},
        "checks": {
            "operator_approval_bound": True,
            "one_shot_budget_completed": True,
            "provider_calls_exact": True,
            "no_provider_failures": True,
            "latency_samples_complete": True,
            "latency_budget_passed": True,
            "token_budget_passed": True,
            "holdout_not_accessed": True,
            "shadow_not_user_visible": True,
            "runtime_activation_prohibited": True,
            "production_cutover_prohibited": True,
        },
        "decision": "SHADOW_CANARY_ACCEPTED_OPERATOR_REVIEW_REQUIRED",
    }
    extended["receipt_hash"] = semantic_sha256_hash_ref(extended)
    return cutover, extended, design, policy, cases


def _rehash_extended(value: dict) -> None:
    snapshot = value.get("snapshot")
    if isinstance(snapshot, dict):
        snapshot.pop("snapshot_hash", None)
        snapshot["snapshot_hash"] = semantic_sha256_hash_ref(snapshot)
    _rehash_receipt_only(value)


def _rehash_receipt_only(value: dict) -> None:
    value.pop("receipt_hash", None)
    value["receipt_hash"] = semantic_sha256_hash_ref(value)


def _hash(seed: str) -> str:
    return semantic_sha256_hash_ref({"seed": seed})
