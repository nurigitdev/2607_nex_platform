from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_sync_capacity import (
    AnswerSupportSyncCapacityError,
    evaluate_sync_capacity_receipt,
    validate_sync_capacity_design,
    validate_sync_capacity_entry,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]


def test_capacity_evaluator_recommends_highest_throughput_background_profile() -> None:
    design, receipt, *_ = _fixtures()

    result = evaluate_sync_capacity_receipt(receipt, design=design)

    assert result["status"] == "PASS"
    assert result["decision"] == (
        "SYNCHRONOUS_BACKGROUND_CANDIDATE_OPERATOR_REVIEW_REQUIRED"
    )
    assert result["recommended_synchronous_concurrency"] == 4
    assert result["throughput_gain_vs_concurrency_1"] == {
        "1": 1.0,
        "2": 2.0,
        "4": 3.0,
    }
    assert result["profile_assessments"][2]["background_slo_met"] is True
    assert result["profile_assessments"][2]["interactive_slo_met"] is False
    assert result["all_bound_endpoints_reachable"] is True
    assert result["execution_mode_selected"] is False
    assert result["runtime_activation_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert result["next_boundary"] == "EXECUTION_MODE_OPERATOR_DECISION"
    assert result["manifest_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("p95", "expected"),
    [
        (7_500.0, "SYNCHRONOUS_INTERACTIVE_CANDIDATE_OPERATOR_REVIEW_REQUIRED"),
        (50_000.0, "SYNCHRONOUS_TIMEOUT_BOUND_ONLY_OPERATOR_REVIEW_REQUIRED"),
        (61_000.0, "SYNCHRONOUS_CAPACITY_INSUFFICIENT"),
    ],
)
def test_capacity_evaluator_distinguishes_latency_classes(
    p95: float, expected: str
) -> None:
    design, receipt, *_ = _fixtures()
    for profile in receipt["profiles"]:
        profile["p95_latency_ms"] = p95
        profile["maximum_latency_ms"] = max(p95, p95 + 500)
    _rehash(receipt)

    result = evaluate_sync_capacity_receipt(receipt, design=design)

    assert result["decision"] == expected
    if expected == "SYNCHRONOUS_CAPACITY_INSUFFICIENT":
        assert result["recommended_synchronous_concurrency"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("status"),
        lambda value: value.__setitem__("status", "ACTIVE"),
        lambda value: value.__setitem__("design_id", " "),
        lambda value: value["capacity_experiment"].__setitem__(
            "concurrency_profiles", [1, 4]
        ),
        lambda value: value["decision_policy"].__setitem__(
            "maximum_profile_p95_latency_ms", 45_000
        ),
        lambda value: value["rollout_boundary"].__setitem__(
            "synchronous_execution_preselected", True
        ),
        lambda value: value["safety"].__setitem__("runtime_activation_permitted", True),
        lambda value: value["source_binding"].__setitem__(
            "provider_binding_hash", "invalid"
        ),
    ],
)
def test_capacity_design_rejects_drift(mutation) -> None:
    design = _fixtures()[0]
    mutation(design)
    with pytest.raises(AnswerSupportSyncCapacityError):
        validate_sync_capacity_design(design)


def test_capacity_design_embedded_hash_is_checked() -> None:
    design = _fixtures()[0]
    design["design_hash"] = semantic_sha256_hash_ref(design)
    assert validate_sync_capacity_design(design)["design_hash"] == design["design_hash"]
    design["design_id"] = "changed-valid-id"
    with pytest.raises(AnswerSupportSyncCapacityError, match="integrity"):
        validate_sync_capacity_design(design)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("status"),
        lambda value: value.__setitem__("status", "FAIL"),
        lambda value: value.__setitem__("provider_http_requests", 59),
        lambda value: value["environment_observation"]["port_reachability"].__setitem__(
            "9112", False
        ),
        lambda value: value["profiles"].pop(),
        lambda value: value["profiles"][0].__setitem__("request_count", 29),
        lambda value: value["profiles"][0].__setitem__("total_tokens", True),
        lambda value: value["profiles"][0].__setitem__("maximum_latency_ms", 1_000.0),
        lambda value: value["profiles"][0].__setitem__("throughput_rps", 0.0),
        lambda value: value["profiles"][0].__setitem__("source", "UNKNOWN"),
    ],
)
def test_capacity_receipt_rejects_invalid_evidence(mutation) -> None:
    design, receipt, *_ = _fixtures()
    mutation(receipt)
    _rehash(receipt)
    with pytest.raises(AnswerSupportSyncCapacityError):
        evaluate_sync_capacity_receipt(receipt, design=design)


def test_capacity_receipt_integrity_and_non_mapping_fail_closed() -> None:
    design, receipt, *_ = _fixtures()
    receipt["status"] = "FAIL"
    with pytest.raises(AnswerSupportSyncCapacityError, match="integrity"):
        evaluate_sync_capacity_receipt(receipt, design=design)

    design["source_binding"] = []
    with pytest.raises(AnswerSupportSyncCapacityError):
        validate_sync_capacity_design(design)

    design, receipt, *_ = _fixtures()
    receipt["profiles"] = "invalid"
    _rehash(receipt)
    with pytest.raises(AnswerSupportSyncCapacityError):
        evaluate_sync_capacity_receipt(receipt, design=design)


def test_capacity_entry_binds_all_pre_observation_sources() -> None:
    (
        design,
        _receipt,
        cases,
        signal,
        profile,
        baseline,
        slo,
        artifact_hash,
    ) = _fixtures()

    admitted = validate_sync_capacity_entry(
        design=design,
        cases_document=cases,
        signal_design=signal,
        request_profile=profile,
        baseline_receipt=baseline,
        latency_slo_receipt=slo,
        artifact_evidence_hash=artifact_hash,
    )
    assert admitted["design_hash"].startswith("sha256:")

    tampered = deepcopy(cases)
    tampered["cases"].append({"case_id": "extra"})
    with pytest.raises(AnswerSupportSyncCapacityError, match="integrity"):
        validate_sync_capacity_entry(
            design=design,
            cases_document=tampered,
            signal_design=signal,
            request_profile=profile,
            baseline_receipt=baseline,
            latency_slo_receipt=slo,
            artifact_evidence_hash=artifact_hash,
        )

    invalid_baseline = deepcopy(baseline)
    invalid_baseline["status"] = "FAIL"
    _rehash(invalid_baseline)
    changed_design = deepcopy(design)
    changed_design["source_binding"]["extended_shadow_receipt_hash"] = invalid_baseline[
        "receipt_hash"
    ]
    with pytest.raises(AnswerSupportSyncCapacityError, match="invalid"):
        validate_sync_capacity_entry(
            design=changed_design,
            cases_document=cases,
            signal_design=signal,
            request_profile=profile,
            baseline_receipt=invalid_baseline,
            latency_slo_receipt=slo,
            artifact_evidence_hash=artifact_hash,
        )


def test_capacity_entry_rejects_tampered_source_receipt() -> None:
    design, _receipt, cases, signal, profile, baseline, slo, artifact_hash = _fixtures()
    baseline["status"] = "FAIL"
    with pytest.raises(AnswerSupportSyncCapacityError, match="integrity"):
        validate_sync_capacity_entry(
            design=design,
            cases_document=cases,
            signal_design=signal,
            request_profile=profile,
            baseline_receipt=baseline,
            latency_slo_receipt=slo,
            artifact_evidence_hash=artifact_hash,
        )


def _fixtures() -> tuple[dict, dict, dict, dict, dict, dict, dict, str]:
    design = json.loads(
        (
            ROOT / "scripts/smoke/data/s136_answer_support_sync_capacity_v1_design.json"
        ).read_text()
    )
    cases = {
        "case_schema_version": "test.v1",
        "cases": [{"case_id": f"case-{index}"} for index in range(30)],
    }
    signal = {"signal": "test"}
    profile = {"profile": "test"}
    artifact_hash = _hash("artifact")
    baseline = {
        "status": "PASS",
        "provider_binding_hash": _hash("provider"),
        "manifest_hash": _hash("readiness"),
        "profile_hash": _hash("profile"),
    }
    _rehash(baseline)
    slo = {
        "status": "PASS",
        "extended_shadow_receipt_hash": baseline["receipt_hash"],
    }
    _rehash(slo)
    source = design["source_binding"]
    source.update(
        {
            "artifact_evidence_hash": artifact_hash,
            "case_set_hash": semantic_sha256_hash_ref(cases),
            "signal_design_hash": semantic_sha256_hash_ref(signal),
            "request_profile_hash": semantic_sha256_hash_ref(profile),
            "extended_shadow_receipt_hash": baseline["receipt_hash"],
            "latency_slo_receipt_hash": slo["receipt_hash"],
            "provider_binding_hash": baseline["provider_binding_hash"],
            "readiness_manifest_hash": baseline["manifest_hash"],
            "runtime_profile_hash": baseline["profile_hash"],
        }
    )
    normalized = validate_sync_capacity_design(design)
    profiles = [
        _profile(1, p95=40_000.0, throughput=0.03),
        _profile(2, p95=42_000.0, throughput=0.06),
        _profile(4, p95=44_000.0, throughput=0.09),
    ]
    receipt = {
        "receipt_schema_version": "cx_answer_support_sync_capacity_receipt.v1",
        "status": "PASS",
        "design_hash": normalized["design_hash"],
        "source_binding": dict(normalized["source_binding"]),
        "environment_observation": {
            "evidence_level": "BOUND_ENDPOINT_REACHABILITY_PROXY",
            "operator_declared_vllm_max_num_seqs": 4,
            "port_reachability": {"9112": True, "9113": True, "9116": True},
        },
        "profiles": profiles,
        "provider_http_requests": 60,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    _rehash(receipt)
    return design, receipt, cases, signal, profile, baseline, slo, artifact_hash


def _profile(concurrency: int, *, p95: float, throughput: float) -> dict:
    return {
        "concurrency": concurrency,
        "source": (
            "P_V_BASELINE_RECEIPT" if concurrency == 1 else "SYNCHRONOUS_LIVE_REPLAY"
        ),
        "request_count": 30,
        "provider_request_count": 30,
        "error_count": 0,
        "latency_sample_count": 30,
        "p95_latency_ms": p95,
        "maximum_latency_ms": p95 + 500,
        "elapsed_seconds": 1_000.0 / concurrency,
        "throughput_rps": throughput,
        "total_tokens": 10_000,
    }


def _rehash(value: dict) -> None:
    value.pop("receipt_hash", None)
    value["receipt_hash"] = semantic_sha256_hash_ref(value)


def _hash(seed: str) -> str:
    return semantic_sha256_hash_ref({"seed": seed})
