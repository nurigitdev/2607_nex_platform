from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nex_cx.retrieval_answer_support_holdout_execution as target
import pytest
from nex_cx.retrieval_answer_support_holdout_execution import (
    build_holdout_receipt_reservation,
    collect_answer_support_holdout,
    complete_holdout_receipt,
    evaluate_answer_support_holdout,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"
LIVE = ROOT / "reports" / "live"
REVISION = "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a"
ARTIFACT_HASH = "sha256:50135139c4271768dde60328dd46ddceab663b8e66928746e21affe82ff7955e"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    dataset = _load(DATA / "s136_retrieval_package_calibration_v4.json")
    return [case for case in dataset["cases"] if case["partition"] == "HOLDOUT"]


def _freeze() -> dict:
    return _load(LIVE / "gb2_ca00_s20qpp_pre_holdout_freeze.json")["freeze"]


def _profile() -> dict:
    return _load(LIVE / "gb2_ca00_s20qpl_canonical_profile_freeze.json")["freeze"][
        "canonical_profile"
    ]


def _provider_result(payload, request_id: str, trace_id: str, *, drift=False) -> dict:
    user = json.loads(payload["messages"][1]["content"])
    items = []
    for candidate in user["candidates"]:
        candidate_id = candidate["candidate_id"]
        if candidate_id in {"primary-answer", "supporting-answer"}:
            classification = (
                "DIRECT_ANSWER"
                if candidate_id == "primary-answer"
                else "SUPPORTING_EVIDENCE"
            )
            support = 0.95 if candidate_id == "primary-answer" else 0.85
            contradiction = 0.02
        elif candidate_id == "contradictory-non-answer":
            classification = "CONTRADICTORY_EVIDENCE"
            support = 0.05
            contradiction = 0.95
        else:
            classification = "TOPICAL_NON_ANSWER"
            support = 0.1
            contradiction = 0.05
        items.append(
            {
                "candidate_id": candidate_id,
                "classification": classification,
                "answer_support_score": support,
                "contradiction_score": contradiction,
            }
        )
    return {
        "alias": "general-llm-default",
        "provider_type": "vllm",
        "model_revision": REVISION,
        "deployment_id": "drift" if drift else "dgx-qwen3-5-9b-9116",
        "output": {"type": "text", "text": json.dumps({"items": items})},
        "finish_reason": "STOP",
        "runtime_metadata": {"request_id": request_id, "trace_id": trace_id},
    }


def _collection(*, evaluator=None, concurrency=1) -> dict:
    return collect_answer_support_holdout(
        _cases(),
        dataset_id="s136-retrieval-package-confidence-public-v4",
        dataset_sha256=(
            "sha256:594209203d25b0a87e6fd136b6794bdc30058a5eb45b7e2c8ff27523bd7f1757"
        ),
        design=_load(DATA / "s136_answer_support_signal_v1_design.json"),
        profile=_load(DATA / "s136_answer_support_generation_profile_v1.json"),
        artifact_revision=REVISION,
        artifact_evidence_hash=ARTIFACT_HASH,
        evaluator=evaluator or _provider_result,
        maximum_concurrency=concurrency,
        request_namespace="s20qpq-test",
    )


def test_collect_and_evaluate_frozen_holdout_candidate() -> None:
    collection = _collection(concurrency=4)
    freeze = _freeze()
    evaluation = evaluate_answer_support_holdout(
        collection,
        _cases(),
        canonical_profile=_profile(),
        frozen_candidate=freeze["authorization"]["candidate"],
        admission=freeze["admission"],
    )

    assert collection["dataset"]["package_count"] == 40
    assert collection["dataset"]["candidate_count"] == 160
    assert collection["privacy"]["candidate_truth_persisted"] is False
    assert evaluation["status"] == "HOLDOUT_ADMITTED"
    assert evaluation["terminal_status"] == "PASS"
    assert evaluation["metrics"]["false_ready_rate"] == 0.0
    assert evaluation["metrics"]["ready_recall"] == 1.0
    assert evaluation["package_auc"] == 1.0
    assert evaluation["runtime_activation_permitted"] is False


def test_holdout_rejection_does_not_reselect_threshold() -> None:
    def weak(payload, request_id, trace_id):
        result = _provider_result(payload, request_id, trace_id)
        output = json.loads(result["output"]["text"])
        for item in output["items"]:
            item["classification"] = "INSUFFICIENT_CONTEXT"
            item["answer_support_score"] = 0.0
            item["contradiction_score"] = 0.0
        result["output"]["text"] = json.dumps(output)
        return result

    freeze = _freeze()
    evaluation = evaluate_answer_support_holdout(
        _collection(evaluator=weak),
        _cases(),
        canonical_profile=_profile(),
        frozen_candidate=freeze["authorization"]["candidate"],
        admission=freeze["admission"],
    )

    assert evaluation["status"] == "HOLDOUT_REJECTED"
    assert evaluation["terminal_status"] == "FAIL"
    assert evaluation["threshold_reselected"] is False
    assert evaluation["profile_reselected"] is False


def test_collection_rejects_partition_duplicate_drift_and_invalid_inputs() -> None:
    cases = _cases()
    kwargs = {
        "dataset_id": "dataset",
        "dataset_sha256": "sha256:" + "1" * 64,
        "design": _load(DATA / "s136_answer_support_signal_v1_design.json"),
        "profile": _load(DATA / "s136_answer_support_generation_profile_v1.json"),
        "artifact_revision": REVISION,
        "artifact_evidence_hash": ARTIFACT_HASH,
        "evaluator": _provider_result,
        "maximum_concurrency": 1,
        "request_namespace": "test",
    }
    with pytest.raises(TypeError, match="cases"):
        collect_answer_support_holdout("bad", **kwargs)
    with pytest.raises(ValueError, match="empty"):
        collect_answer_support_holdout([], **kwargs)
    with pytest.raises(ValueError, match="concurrency"):
        collect_answer_support_holdout(cases, **{**kwargs, "maximum_concurrency": 0})
    wrong = deepcopy(cases[:1])
    wrong[0]["partition"] = "CALIBRATION"
    with pytest.raises(ValueError, match="HOLDOUT only"):
        collect_answer_support_holdout(wrong, **kwargs)
    with pytest.raises(ValueError, match="duplicated"):
        collect_answer_support_holdout([cases[0], cases[0]], **kwargs)
    empty_candidates = deepcopy(cases[:1])
    empty_candidates[0]["candidates"] = []
    with pytest.raises(ValueError, match="candidates are empty"):
        collect_answer_support_holdout(empty_candidates, **kwargs)

    calls = 0

    def drift(payload, request_id, trace_id):
        nonlocal calls
        calls += 1
        return _provider_result(
            payload, request_id, trace_id, drift=calls == len(cases)
        )

    with pytest.raises(ValueError, match="binding drifted"):
        collect_answer_support_holdout(cases, **{**kwargs, "evaluator": drift})


def test_evaluation_rejects_integrity_profile_and_coverage_drift() -> None:
    collection = _collection()
    freeze = _freeze()
    candidate = freeze["authorization"]["candidate"]
    admission = freeze["admission"]

    tampered = deepcopy(collection)
    tampered["dataset"]["package_count"] = 39
    with pytest.raises(ValueError, match="integrity"):
        evaluate_answer_support_holdout(
            tampered,
            _cases(),
            canonical_profile=_profile(),
            frozen_candidate=candidate,
            admission=admission,
        )
    profile = _profile()
    profile["profile_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="binding drifted"):
        evaluate_answer_support_holdout(
            collection,
            _cases(),
            canonical_profile=profile,
            frozen_candidate=candidate,
            admission=admission,
        )
    with pytest.raises(ValueError, match="coverage"):
        evaluate_answer_support_holdout(
            collection,
            _cases()[:-1],
            canonical_profile=_profile(),
            frozen_candidate=candidate,
            admission=admission,
        )
    duplicate = _cases()
    duplicate[-1] = duplicate[0]
    with pytest.raises(ValueError, match="duplicated"):
        evaluate_answer_support_holdout(
            collection,
            duplicate,
            canonical_profile=_profile(),
            frozen_candidate=candidate,
            admission=admission,
        )
    wrong = deepcopy(_cases())
    wrong[0]["partition"] = "CALIBRATION"
    with pytest.raises(ValueError, match="another partition"):
        evaluate_answer_support_holdout(
            collection,
            wrong,
            canonical_profile=_profile(),
            frozen_candidate=candidate,
            admission=admission,
        )


def test_receipt_lifecycle_consumes_all_terminal_outcomes() -> None:
    reservation = build_holdout_receipt_reservation(
        _freeze(), started_at="2026-11-05T00:00:00Z"
    )
    passed = complete_holdout_receipt(
        reservation,
        terminal_status="PASS",
        completed_at="2026-11-05T00:01:00Z",
        provider_evaluation_count=40,
        provider_http_request_count=40,
        evaluation_hash="sha256:" + "2" * 64,
    )
    inconclusive = complete_holdout_receipt(
        reservation,
        terminal_status="INCONCLUSIVE",
        completed_at="2026-11-05T00:01:00Z",
        provider_evaluation_count=1,
        provider_http_request_count=1,
        terminal_reason="ProviderRouteError",
    )

    assert reservation["status"] == "STARTED"
    assert passed["status"] == "PASS"
    assert passed["terminal_reason"] is None
    assert inconclusive["status"] == "INCONCLUSIVE"
    assert inconclusive["evaluation_hash"] is None


def test_receipt_rejects_tamper_invalid_terminal_and_budget() -> None:
    reservation = build_holdout_receipt_reservation(
        _freeze(), started_at="2026-11-05T00:00:00Z"
    )
    tampered = {**reservation, "execution_id": "other"}
    with pytest.raises(ValueError, match="integrity"):
        complete_holdout_receipt(
            tampered,
            terminal_status="FAIL",
            completed_at="now",
            provider_evaluation_count=0,
            provider_http_request_count=0,
            evaluation_hash="sha256:" + "2" * 64,
        )
    with pytest.raises(ValueError, match="terminal status"):
        complete_holdout_receipt(
            reservation,
            terminal_status="STARTED",
            completed_at="now",
            provider_evaluation_count=0,
            provider_http_request_count=0,
        )
    with pytest.raises(ValueError, match="budget"):
        complete_holdout_receipt(
            reservation,
            terminal_status="PASS",
            completed_at="now",
            provider_evaluation_count=41,
            provider_http_request_count=0,
            evaluation_hash="sha256:" + "2" * 64,
        )
    with pytest.raises(ValueError, match="evaluation hash"):
        complete_holdout_receipt(
            reservation,
            terminal_status="INCONCLUSIVE",
            completed_at="now",
            provider_evaluation_count=0,
            provider_http_request_count=0,
            evaluation_hash="sha256:" + "2" * 64,
            terminal_reason="error",
        )


def test_freeze_integrity_and_primitive_guards() -> None:
    freeze = deepcopy(_freeze())
    freeze["execution_id"] = "changed"
    with pytest.raises(ValueError, match="integrity|authorization"):
        build_holdout_receipt_reservation(freeze, started_at="now")
    with pytest.raises(ValueError, match="started_at"):
        build_holdout_receipt_reservation(_freeze(), started_at=" ")

    invalid = deepcopy(_freeze())
    invalid.pop("freeze_hash")
    invalid["status"] = "NOT_ARMED"
    invalid["freeze_hash"] = target.semantic_sha256_hash_ref(invalid)
    with pytest.raises(ValueError, match="authorization"):
        build_holdout_receipt_reservation(invalid, started_at="now")

    with pytest.raises(TypeError, match="candidates"):
        target._provider_candidates("bad")
    with pytest.raises(TypeError, match="mapping"):
        target._mapping([], "mapping")
    with pytest.raises(TypeError, match="flag"):
        target._required_bool("true", "flag")
    with pytest.raises(TypeError, match="score"):
        target._bounded(True, "score")
    with pytest.raises(ValueError, match="score"):
        target._bounded(2.0, "score")
    with pytest.raises(ValueError, match="count"):
        target._non_negative_int(-1, "count")
