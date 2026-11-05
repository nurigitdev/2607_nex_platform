from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest
from nex_cx.retrieval_answer_support_interactive_slo_policy import (
    build_interactive_slo_operator_decision,
    decide_interactive_slo_runtime_policy,
)
from nex_cx.retrieval_answer_support_synchronous_runtime import (
    ACCEPTED_DECISION,
    REJECTED_DECISION,
    BoundedSynchronousGenerationClient,
    SynchronousRuntimeAcceptanceError,
    _exact,
    _hash_ref,
    _mapping,
    build_bounded_synchronous_answer_support_runtime,
    evaluate_synchronous_runtime_e2e_receipt,
    validate_synchronous_runtime_e2e_design,
    validate_synchronous_runtime_policy,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_interactive_slo_policy import (
    NOW,
)
from test_nex_cx_retrieval_answer_support_interactive_slo_policy import (
    _fixtures as policy_fixtures,
)
from test_nex_cx_retrieval_answer_support_shadow_runtime import (
    FakeGenerationClient,
    RecordingSink,
    _context,
    _evidence_items,
    _manifest,
    _package,
    _request_profile,
    _signal_design,
)

ROOT = Path(__file__).resolve().parents[1]


def test_bounded_runtime_emits_progress_and_observes_answer_support() -> None:
    progress = RecordingSink()
    runtime = build_bounded_synchronous_answer_support_runtime(
        policy=_selected_policy(),
        readiness_manifest=_manifest(),
        signal_design=_signal_design(),
        request_profile=_request_profile(),
        generation_client=FakeGenerationClient(),
        progress_sink=progress,
        outcome_sink=RecordingSink(),
    )
    outcome = runtime.observe(
        query_text="정산 기준을 알려줘",
        evidence_items=_evidence_items(),
        primary_package=_package(),
        access_context=_context(),
    )
    snapshot = runtime.generation_client.snapshot()
    assert outcome["status"] == "OBSERVED"
    assert [event["event_type"] for event in progress.outcomes] == [
        "REQUEST_ADMITTED",
        "REQUEST_COMPLETED",
    ]
    assert snapshot["admitted_count"] == 1
    assert snapshot["completed_count"] == 1
    assert snapshot["in_flight"] == 0
    assert snapshot["pending_request_count"] == 0
    assert snapshot["feedback_latencies_ms"] == [pytest.approx(0.0, abs=1.0)]


def test_bounded_client_rejects_overload_retryably_and_recovers_capacity() -> None:
    entered = Event()
    release = Event()

    class BlockingClient:
        def create_generation(self, *_args, **_kwargs):
            entered.set()
            assert release.wait(timeout=2)
            return {"ok": True}

    progress = RecordingSink()
    gateway = BoundedSynchronousGenerationClient(
        BlockingClient(), progress_sink=progress, maximum_in_flight=1
    )
    gateway.begin_request("one")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            gateway.create_generation,
            {},
            request_id="one",
            trace_id="1" * 32,
        )
        assert entered.wait(timeout=1)
        gateway.begin_request("two")
        with pytest.raises(SynchronousRuntimeAcceptanceError) as raised:
            gateway.create_generation({}, request_id="two", trace_id="2" * 32)
        assert raised.value.retryable is True
        assert raised.value.error_code == "cx.answer_support_sync.capacity_exhausted"
        release.set()
        assert future.result() == {"ok": True}
    snapshot = gateway.snapshot()
    assert snapshot["peak_in_flight"] == 1
    assert snapshot["rejected_count"] == 1
    assert snapshot["completed_count"] == 1


def test_bounded_client_releases_after_provider_or_progress_failure() -> None:
    provider_gateway = BoundedSynchronousGenerationClient(
        FakeGenerationClient(error=RuntimeError("provider")),
        progress_sink=RecordingSink(),
        maximum_in_flight=1,
    )
    provider_gateway.begin_request("provider-failure")
    with pytest.raises(RuntimeError):
        provider_gateway.create_generation(
            {}, request_id="provider-failure", trace_id="3" * 32
        )
    assert provider_gateway.snapshot()["in_flight"] == 0
    assert provider_gateway.snapshot()["failed_count"] == 1

    progress_gateway = BoundedSynchronousGenerationClient(
        FakeGenerationClient(),
        progress_sink=RecordingSink(error=RuntimeError("sink")),
        maximum_in_flight=1,
    )
    progress_gateway.begin_request("progress-failure")
    with pytest.raises(SynchronousRuntimeAcceptanceError) as raised:
        progress_gateway.create_generation(
            {}, request_id="progress-failure", trace_id="4" * 32
        )
    assert raised.value.error_code == "cx.answer_support_sync.progress_unavailable"
    assert progress_gateway.snapshot()["in_flight"] == 0
    assert progress_gateway.snapshot()["progress_failure_count"] == 1

    class CompletionFailingSink:
        def __init__(self) -> None:
            self.calls = 0

        def record(self, _event) -> None:
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("completion sink")

    class SuccessfulClient:
        def create_generation(self, *_args, **_kwargs):
            return {"ok": True}

    completion_gateway = BoundedSynchronousGenerationClient(
        SuccessfulClient(),
        progress_sink=CompletionFailingSink(),
        maximum_in_flight=1,
    )
    completion_gateway.begin_request("completion-failure")
    completion_gateway.create_generation(
        {}, request_id="completion-failure", trace_id="5" * 32
    )
    assert completion_gateway.snapshot()["completed_count"] == 1
    assert completion_gateway.snapshot()["progress_failure_count"] == 1


def test_bounded_client_rejects_invalid_or_duplicate_request_identity() -> None:
    with pytest.raises(ValueError):
        BoundedSynchronousGenerationClient(
            FakeGenerationClient(),
            progress_sink=RecordingSink(),
            maximum_in_flight=0,
        )
    gateway = BoundedSynchronousGenerationClient(
        FakeGenerationClient(), progress_sink=RecordingSink(), maximum_in_flight=1
    )
    gateway.begin_request("duplicate")
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        gateway.begin_request("duplicate")
    gateway.finish_request("duplicate")
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        gateway.begin_request("")


def test_runtime_policy_and_design_reject_drift_and_integrity_failures() -> None:
    policy = _selected_policy()
    assert (
        validate_synchronous_runtime_policy(policy)["policy_hash"]
        == policy["policy_hash"]
    )
    drifted_policy = deepcopy(policy)
    drifted_policy["runtime_policy"]["maximum_in_flight_provider_requests"] = 8
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        validate_synchronous_runtime_policy(drifted_policy)
    stale_policy = deepcopy(policy)
    stale_policy["policy_hash"] = "sha256:" + "f" * 64
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        validate_synchronous_runtime_policy(stale_policy)

    fixtures = _acceptance_fixtures()
    normalized = validate_synchronous_runtime_e2e_design(fixtures["design"])
    assert normalized["design_hash"].startswith("sha256:")
    drifted_design = deepcopy(fixtures["design"])
    drifted_design["acceptance_policy"]["sample_count"] = 29
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        validate_synchronous_runtime_e2e_design(drifted_design)
    identity_drift = deepcopy(fixtures["design"])
    identity_drift["status"] = "DRAFT"
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        validate_synchronous_runtime_e2e_design(identity_drift)
    safety_drift = deepcopy(fixtures["design"])
    safety_drift["safety"]["runtime_activation_permitted"] = True
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        validate_synchronous_runtime_e2e_design(safety_drift)
    stale_design = deepcopy(fixtures["design"])
    stale_design["design_hash"] = "sha256:" + "f" * 64
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        validate_synchronous_runtime_e2e_design(stale_design)


def test_e2e_receipt_accepts_slos_and_rejects_slo_miss() -> None:
    fixtures = _acceptance_fixtures()
    accepted = evaluate_synchronous_runtime_e2e_receipt(
        fixtures["receipt"],
        design=fixtures["design"],
        decision_receipt=fixtures["decision_receipt"],
    )
    assert accepted["decision"] == ACCEPTED_DECISION
    assert not accepted["failed_checks"]
    assert accepted["runtime_activation_permitted"] is False

    missed_receipt = deepcopy(fixtures["receipt"])
    missed_receipt["metrics"]["e2e_p95_latency_ms"] = 20_001.0
    _rehash(missed_receipt)
    rejected = evaluate_synchronous_runtime_e2e_receipt(
        missed_receipt,
        design=fixtures["design"],
        decision_receipt=fixtures["decision_receipt"],
    )
    assert rejected["decision"] == REJECTED_DECISION
    assert rejected["failed_checks"] == ["interactive_e2e_p95_slo_met"]


def test_e2e_receipt_rejects_receipt_and_decision_tamper() -> None:
    fixtures = _acceptance_fixtures()
    receipt = deepcopy(fixtures["receipt"])
    receipt["database_calls"] = 1
    with pytest.raises(SynchronousRuntimeAcceptanceError) as raised:
        evaluate_synchronous_runtime_e2e_receipt(
            receipt,
            design=fixtures["design"],
            decision_receipt=fixtures["decision_receipt"],
        )
    assert raised.value.error_code == "SYNCHRONOUS_RUNTIME_ACCEPTANCE_INTEGRITY"

    invalid_receipt = deepcopy(fixtures["receipt"])
    invalid_receipt["runtime_activation_permitted"] = True
    _rehash(invalid_receipt)
    with pytest.raises(SynchronousRuntimeAcceptanceError) as raised:
        evaluate_synchronous_runtime_e2e_receipt(
            invalid_receipt,
            design=fixtures["design"],
            decision_receipt=fixtures["decision_receipt"],
        )
    assert raised.value.error_code == "SYNCHRONOUS_RUNTIME_ACCEPTANCE_INVALID"

    stale_decision = deepcopy(fixtures["decision_receipt"])
    stale_decision["status"] = "FAIL"
    with pytest.raises(SynchronousRuntimeAcceptanceError) as raised:
        evaluate_synchronous_runtime_e2e_receipt(
            fixtures["receipt"],
            design=fixtures["design"],
            decision_receipt=stale_decision,
        )
    assert raised.value.error_code == "SYNCHRONOUS_RUNTIME_ACCEPTANCE_INTEGRITY"

    decision_receipt = deepcopy(fixtures["decision_receipt"])
    decision_receipt["runtime_activation_permitted"] = True
    _rehash(decision_receipt)
    design = deepcopy(fixtures["design"])
    design["source_binding"]["interactive_slo_decision_receipt_hash"] = (
        decision_receipt["receipt_hash"]
    )
    design["source_binding"]["interactive_slo_decision_receipt_document_hash"] = (
        semantic_sha256_hash_ref(decision_receipt)
    )
    receipt = deepcopy(fixtures["receipt"])
    normalized = validate_synchronous_runtime_e2e_design(design)
    receipt["design_hash"] = normalized["design_hash"]
    receipt["source_binding"] = normalized["source_binding"]
    _rehash(receipt)
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        evaluate_synchronous_runtime_e2e_receipt(
            receipt, design=design, decision_receipt=decision_receipt
        )


def test_contract_helpers_fail_closed_on_shapes_and_hashes() -> None:
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        _mapping([], "mapping")
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        _exact({"unexpected": True}, {"expected"}, "shape")
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        _hash_ref(None, "hash")
    with pytest.raises(SynchronousRuntimeAcceptanceError):
        _hash_ref("not-a-hash", "hash")


def _selected_policy() -> dict:
    fixtures = policy_fixtures()
    operator = build_interactive_slo_operator_decision(
        operator_id="operator",
        decided_at=NOW,
        design=fixtures["design"],
        capacity_manifest=fixtures["capacity_manifest"],
        control_manifest=fixtures["control_manifest"],
    )
    return decide_interactive_slo_runtime_policy(
        design=fixtures["design"],
        capacity_manifest=fixtures["capacity_manifest"],
        control_manifest=fixtures["control_manifest"],
        operator_decision=operator,
    )["selected_policy"]


def _acceptance_fixtures() -> dict:
    policy = _selected_policy()
    decision_receipt = {
        "receipt_schema_version": (
            "cx_answer_support_interactive_slo_policy_decision_receipt.v1"
        ),
        "status": "PASS",
        "decision": "SYNCHRONOUS_BOUNDED_C4_SELECTED_PENDING_E2E_ACCEPTANCE",
        "design_hash": "sha256:" + "1" * 64,
        "operator_decision_hash": "sha256:" + "2" * 64,
        "manifest_hash": "sha256:" + "3" * 64,
        "selected_policy_hash": policy["policy_hash"],
        "capacity_receipt_hash": "sha256:" + "4" * 64,
        "control_receipt_hash": "sha256:" + "5" * 64,
        "decided_at": NOW,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    _rehash(decision_receipt)
    design = json.loads(
        (
            ROOT
            / "scripts/smoke/data/s136_answer_support_sync_runtime_e2e_v1_design.json"
        ).read_text(encoding="utf-8")
    )
    design["source_binding"] = {
        key: "sha256:" + f"{index % 16:x}" * 64
        for index, key in enumerate(sorted(design["source_binding"]), start=6)
    }
    source = design["source_binding"]
    source["interactive_slo_decision_receipt_hash"] = decision_receipt["receipt_hash"]
    source["interactive_slo_decision_receipt_document_hash"] = semantic_sha256_hash_ref(
        decision_receipt
    )
    source["interactive_slo_manifest_hash"] = decision_receipt["manifest_hash"]
    source["selected_policy_hash"] = policy["policy_hash"]
    normalized = validate_synchronous_runtime_e2e_design(design)
    receipt = {
        "receipt_schema_version": "cx_answer_support_sync_runtime_e2e_receipt.v1",
        "status": "PASS",
        "design_hash": normalized["design_hash"],
        "selected_policy_hash": policy["policy_hash"],
        "source_binding": normalized["source_binding"],
        "execution": {
            "sample_count": 30,
            "accepted_count": 30,
            "provider_call_count": 30,
            "provider_error_count": 0,
            "rejected_count": 0,
            "maximum_in_flight": 4,
            "peak_in_flight": 4,
            "progress_failure_count": 0,
            "overload_probe_retryable": True,
            "progress_event_count": 60,
            "outcome_count": 30,
        },
        "metrics": {
            "feedback_sample_count": 30,
            "feedback_p95_latency_ms": 1.0,
            "feedback_maximum_latency_ms": 2.0,
            "provider_sample_count": 30,
            "provider_p95_latency_ms": 11_000.0,
            "provider_maximum_latency_ms": 11_500.0,
            "e2e_sample_count": 30,
            "e2e_p95_latency_ms": 12_000.0,
            "e2e_maximum_latency_ms": 12_500.0,
            "elapsed_seconds": 90.0,
            "throughput_rps": 0.333333333,
            "total_tokens": 900,
        },
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    _rehash(receipt)
    return {
        "policy": policy,
        "decision_receipt": decision_receipt,
        "design": design,
        "receipt": receipt,
    }


def _rehash(value: dict) -> None:
    value.pop("receipt_hash", None)
    value["receipt_hash"] = semantic_sha256_hash_ref(value)
