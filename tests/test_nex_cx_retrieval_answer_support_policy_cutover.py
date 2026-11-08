from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_controlled_activation import (
    DEFAULT_ACTIVATION_BUNDLE_PATH,
    OperationalAnswerSupportProgressSink,
    load_controlled_activation_bundle,
)
from nex_cx.retrieval_answer_support_policy_cutover import (
    ACTIVE,
    CUTOVER_EVENT_TYPE,
    CUTOVER_MODE_CONTROLLED,
    CUTOVER_MODE_ENV,
    DEFAULT_AUTHORIZATION_PATH,
    ROLLBACK_PENDING_REVIEW,
    ROLLED_BACK,
    AnswerSupportPolicyCutoverError,
    ControlledAnswerSupportPolicyCutover,
    OperationalPolicyCutoverStateStore,
    _bounded_score,
    _mapping,
    _number,
    _numbers,
    _required_text,
    build_cutover_state,
    build_installed_answer_support_policy_cutover,
    load_cutover_authorization,
    validate_cutover_authorization,
    validate_cutover_state,
)
from nex_cx.retrieval_answer_support_synchronous_runtime import (
    build_bounded_synchronous_answer_support_runtime,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_hybrid_retrieval_package import (
    _assert_retrieval_package_contract,
    _context,
    _payload,
    _runtime,
)


class FakeGenerationClient:
    def __init__(self, *, ready: bool = True, error: Exception | None = None) -> None:
        self.ready = ready
        self.error = error
        self.calls = 0

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        del request_id, trace_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        request = json.loads(payload["messages"][1]["content"])
        return {
            "alias": "general-llm-default",
            "model_revision": "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "deployment_id": "dgx-qwen3-5-9b-9116",
            "provider_type": "vllm",
            "output": {
                "type": "text",
                "text": json.dumps(
                    {
                        "items": [
                            {
                                "candidate_id": row["candidate_id"],
                                "classification": (
                                    "SUPPORTING_EVIDENCE"
                                    if self.ready
                                    else "INSUFFICIENT_CONTEXT"
                                ),
                                "answer_support_score": 0.95 if self.ready else 0.05,
                                "contradiction_score": 0.02 if self.ready else 0.1,
                            }
                            for row in request["candidates"]
                        ]
                    }
                ),
            },
            "finish_reason": "STOP",
            "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        }


class RecordingOutcomeSink:
    def __init__(self) -> None:
        self.outcomes: list[dict[str, Any]] = []

    def record(self, outcome: dict[str, Any]) -> None:
        self.outcomes.append(dict(outcome))


class FailingProgressSink:
    def record(self, _event: object) -> None:
        raise RuntimeError("progress unavailable")


class FakeGateway:
    def __init__(self) -> None:
        self.values = {
            "maximum_in_flight": 4,
            "progress_failure_count": 0,
            "feedback_latencies_ms": [],
            "provider_latencies_ms": [],
        }

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.values)


class FakeDelegate:
    def __init__(self, outcome: object = None, error: Exception | None = None) -> None:
        self.generation_client = FakeGateway()
        self.outcome = outcome
        self.error = error

    def observe(self, **_kwargs: Any) -> object:
        if self.error is not None:
            raise self.error
        return self.outcome


def test_authorization_binds_exact_operator_receipt_and_activation_bundle() -> None:
    activation = _activation()
    authorization = load_cutover_authorization(
        DEFAULT_AUTHORIZATION_PATH, activation_bundle=activation
    )

    assert authorization["status"] == "APPROVED_FOR_CONTROLLED_CUTOVER"
    assert authorization["decision_receipt"]["policy_cutover_approved"] is True
    assert authorization["activation_bundle_hash"] == activation["bundle_hash"]
    assert (
        authorization["selected_policy_hash"]
        == activation["selected_policy"]["policy_hash"]
    )

    for field in (
        "authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
        "provider_binding_hash",
    ):
        drift = deepcopy(authorization)
        drift[field] = "sha256:" + "0" * 64
        with pytest.raises(AnswerSupportPolicyCutoverError):
            validate_cutover_authorization(drift, activation_bundle=activation)


def test_installed_cutover_is_disabled_by_default_and_rejects_unknown_mode() -> None:
    state_store, _events = _state_store()
    kwargs = {
        "generation_client": FakeGenerationClient(),
        "progress_sink": OperationalAnswerSupportProgressSink(state_store.emitter),
        "outcome_sink": RecordingOutcomeSink(),
        "state_store": state_store,
    }
    assert build_installed_answer_support_policy_cutover(environ={}, **kwargs) is None
    with pytest.raises(AnswerSupportPolicyCutoverError):
        build_installed_answer_support_policy_cutover(
            environ={CUTOVER_MODE_ENV: "unexpected"}, **kwargs
        )


@pytest.mark.parametrize(
    ("ready", "expected_status", "expected_reason"),
    [
        (True, "READY", None),
        (False, "LOW_CONFIDENCE", "answer_support_policy_below_threshold"),
    ],
)
def test_controlled_cutover_makes_only_answer_support_decision_authoritative(
    ready: bool, expected_status: str, expected_reason: str | None
) -> None:
    state_store, events = _state_store()
    runtime = _build_runtime(
        generation_client=FakeGenerationClient(ready=ready), state_store=state_store
    )
    original = _package()

    result = runtime.apply(**_application(original))

    assert result["status"] == expected_status
    assert result["no_answer_reason"] == expected_reason
    assert result["package_hash"] != original["package_hash"]
    assert result["retrieval_package_id"] != original["retrieval_package_id"]
    assert result["evidence_items"] == original["evidence_items"]
    assert result["permission_snapshot"] == original["permission_snapshot"]
    assert result["retrieval_profile"]["candidate_summary"] == {
        "fused_candidate_count": 1
    }
    assert result["score_summary"]["confidence_bucket"] == expected_status
    assert result["score_summary"]["calibration_profile_id"] == (
        "answer-support-contradiction-aware-v2"
    )
    assert len(result["score_summary"]["calibration_profile_hash"]) == 64
    assert runtime.snapshot()["cutover_state"] == ACTIVE
    assert runtime.snapshot()["user_visible_decision_change"] is True
    states = events.list_events(event_type=CUTOVER_EVENT_TYPE)
    assert [row["details"]["cutover_state"] for row in states] == [ACTIVE]


def test_cutover_result_preserves_retrieval_context_package_v1_contract() -> None:
    state_store, _events = _state_store()
    cutover = _build_runtime(
        generation_client=FakeGenerationClient(), state_store=state_store
    )

    package = _runtime(primary_policy=cutover).build_package(
        _payload(), access_context=_context()
    )

    assert package["status"] == "READY"
    assert package["score_summary"]["calibration_profile_id"] == (
        "answer-support-contradiction-aware-v2"
    )
    _assert_retrieval_package_contract(package)


def test_provider_failure_rolls_back_current_request_and_survives_restart() -> None:
    state_store, events = _state_store()
    failed = _build_runtime(
        generation_client=FakeGenerationClient(error=RuntimeError("provider")),
        state_store=state_store,
    )
    original = _package()

    assert failed.apply(**_application(original)) == original
    assert failed.snapshot()["cutover_state"] == ROLLED_BACK
    assert failed.snapshot()["rollback_reason"] == "PROVIDER_ERROR"

    restarted = _build_runtime(
        generation_client=FakeGenerationClient(), state_store=state_store
    )
    assert restarted.snapshot()["cutover_state"] == ROLLED_BACK
    assert restarted.apply(**_application(original)) == original
    assert restarted.delegate.generation_client.snapshot()["admitted_count"] == 0
    states = events.list_events(event_type=CUTOVER_EVENT_TYPE)
    assert {row["details"]["cutover_state"] for row in states} == {
        ACTIVE,
        ROLLED_BACK,
    }


def test_progress_failure_and_slo_breach_use_distinct_rollback_states() -> None:
    state_store, _events = _state_store()
    activation = _activation()
    authorization = _authorization(activation)
    delegate = build_bounded_synchronous_answer_support_runtime(
        policy=activation["selected_policy"],
        readiness_manifest=activation["readiness_manifest"],
        signal_design=activation["signal_design"],
        request_profile=activation["request_profile"],
        generation_client=FakeGenerationClient(),
        progress_sink=FailingProgressSink(),
        outcome_sink=RecordingOutcomeSink(),
    )
    runtime = ControlledAnswerSupportPolicyCutover(
        delegate,
        activation_bundle=activation,
        authorization=authorization,
        state_store=state_store,
    )
    assert runtime.apply(**_application(_package())) == _package()
    assert runtime.snapshot()["rollback_reason"] == "PROGRESS_SINK_FAILURE"

    state_store, _events = _state_store()
    runtime = _build_runtime(
        generation_client=FakeGenerationClient(), state_store=state_store
    )
    for _index in range(3):
        assert (
            runtime._latency_rollback_reason(
                {"provider_called": True, "elapsed_ms": 1.0},
                snapshot={
                    "feedback_latencies_ms": [1.0],
                    "provider_latencies_ms": [1.0],
                },
            )
            is None
        )
    reason = runtime._latency_rollback_reason(
        {"provider_called": True, "elapsed_ms": 20_001.0},
        snapshot={
            "feedback_latencies_ms": [1.0],
            "provider_latencies_ms": [1.0],
        },
    )
    assert reason == "INTERACTIVE_E2E_P95_SLO_BREACH"
    runtime._rollback(reason, pending_review=True)
    assert runtime.snapshot()["cutover_state"] == ROLLBACK_PENDING_REVIEW


def test_delegate_exception_skip_and_terminal_rollback_are_safe_fallbacks() -> None:
    activation = _activation()
    authorization = _authorization(activation)
    original = _package()

    state_store, _events = _state_store()
    failed = ControlledAnswerSupportPolicyCutover(
        FakeDelegate(error=RuntimeError("overload")),  # type: ignore[arg-type]
        activation_bundle=activation,
        authorization=authorization,
        state_store=state_store,
    )
    assert failed.apply(**_application(original)) == original
    assert failed.snapshot()["rollback_reason"] == "NON_RETRYABLE_OVERLOAD"
    failed._rollback("ignored", pending_review=False)
    assert failed.snapshot()["rollback_reason"] == "NON_RETRYABLE_OVERLOAD"

    state_store, _events = _state_store()
    skipped = ControlledAnswerSupportPolicyCutover(
        FakeDelegate(
            {
                "status": "SKIPPED",
                "provider_called": False,
                "outcome_hash": "sha256:" + "a" * 64,
            }
        ),  # type: ignore[arg-type]
        activation_bundle=activation,
        authorization=authorization,
        state_store=state_store,
    )
    assert skipped.apply(**_application(original)) == original
    assert (
        skipped._latency_rollback_reason({"provider_called": False}, snapshot={})
        is None
    )


def test_feedback_and_provider_latency_breaches_are_distinguished() -> None:
    for snapshot, expected in (
        (
            {
                "feedback_latencies_ms": [2_001.0],
                "provider_latencies_ms": [1.0],
            },
            "FEEDBACK_P95_SLO_BREACH",
        ),
        (
            {
                "feedback_latencies_ms": [1.0],
                "provider_latencies_ms": [15_001.0],
            },
            "PROVIDER_P95_SLO_BREACH",
        ),
    ):
        state_store, _events = _state_store()
        runtime = _build_runtime(
            generation_client=FakeGenerationClient(), state_store=state_store
        )
        for _index in range(3):
            runtime._latency_rollback_reason(
                {"provider_called": True, "elapsed_ms": 1.0},
                snapshot={
                    "feedback_latencies_ms": [1.0],
                    "provider_latencies_ms": [1.0],
                },
            )
        assert (
            runtime._latency_rollback_reason(
                {"provider_called": True, "elapsed_ms": 1.0}, snapshot=snapshot
            )
            == expected
        )


def test_cutover_state_validation_and_idempotent_event_identity() -> None:
    authorization_hash = _authorization(_activation())["authorization_hash"]
    active = build_cutover_state(
        authorization_hash=authorization_hash,
        cutover_state=ACTIVE,
        reason_code="approved",
    )
    assert validate_cutover_state(active) == active
    assert active["user_visible"] is True

    state_store, events = _state_store()
    state_store.record_state(active)
    state_store.record_state(active)
    assert len(events.list_events(event_type=CUTOVER_EVENT_TYPE)) == 1
    assert state_store.current_state(authorization_hash) == active

    for field in ("state_hash", "cutover_receipt_hash", "cutover_state"):
        drift = deepcopy(active)
        drift[field] = "bad"
        with pytest.raises(AnswerSupportPolicyCutoverError):
            validate_cutover_state(drift)


def test_state_source_ignores_unrelated_and_malformed_events() -> None:
    authorization_hash = _authorization(_activation())["authorization_hash"]

    class Store:
        def list_events(self, **_kwargs: Any) -> list[dict[str, Any]]:
            return [
                {"details": "invalid"},
                {"details": {"cutover_receipt_hash": "sha256:" + "0" * 64}},
                {
                    "details": build_cutover_state(
                        authorization_hash=authorization_hash,
                        cutover_state=ACTIVE,
                        reason_code="approved",
                    )
                },
            ]

    emitter = OperationalEventEmitter(
        service_id="nex-cx", store=InMemoryOperationalEventStore()
    )
    source = OperationalPolicyCutoverStateStore(emitter=emitter, store=Store())  # type: ignore[arg-type]
    assert source.current_state(authorization_hash)["cutover_state"] == ACTIVE


def test_authorization_and_validation_helpers_fail_closed(tmp_path) -> None:
    activation = _activation()
    missing = tmp_path / "missing.json"
    with pytest.raises(
        AnswerSupportPolicyCutoverError,
        match="authorization is unavailable",
    ):
        load_cutover_authorization(missing, activation_bundle=activation)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(AnswerSupportPolicyCutoverError):
        load_cutover_authorization(invalid, activation_bundle=activation)

    authorization = _authorization(activation)
    bad_fields = deepcopy(authorization)
    bad_fields["extra"] = True
    bad_fields.pop("authorization_hash")
    bad_fields["authorization_hash"] = semantic_sha256_hash_ref(bad_fields)
    with pytest.raises(AnswerSupportPolicyCutoverError):
        validate_cutover_authorization(bad_fields, activation_bundle=activation)

    bad_receipt = deepcopy(authorization)
    bad_receipt["decision_receipt"]["status"] = "FAIL"
    receipt = dict(bad_receipt["decision_receipt"])
    receipt.pop("receipt_hash")
    bad_receipt["decision_receipt"]["receipt_hash"] = semantic_sha256_hash_ref(receipt)
    outer = dict(bad_receipt)
    outer.pop("authorization_hash")
    bad_receipt["authorization_hash"] = semantic_sha256_hash_ref(outer)
    with pytest.raises(AnswerSupportPolicyCutoverError):
        validate_cutover_authorization(bad_receipt, activation_bundle=activation)

    assert _bounded_score(None) == 0.0
    assert _bounded_score(2.0) == 1.0
    for call in (
        lambda: _numbers("bad"),
        lambda: _number(True),
        lambda: _mapping([], "mapping"),
        lambda: _required_text(""),
    ):
        with pytest.raises(AnswerSupportPolicyCutoverError):
            call()


def _build_runtime(
    *,
    generation_client: FakeGenerationClient,
    state_store: OperationalPolicyCutoverStateStore,
) -> ControlledAnswerSupportPolicyCutover:
    runtime = build_installed_answer_support_policy_cutover(
        environ={CUTOVER_MODE_ENV: CUTOVER_MODE_CONTROLLED},
        generation_client=generation_client,
        progress_sink=OperationalAnswerSupportProgressSink(state_store.emitter),
        outcome_sink=RecordingOutcomeSink(),
        state_store=state_store,
    )
    assert runtime is not None
    return runtime


def _activation() -> dict[str, Any]:
    return load_controlled_activation_bundle(DEFAULT_ACTIVATION_BUNDLE_PATH)


def _authorization(activation: dict[str, Any]) -> dict[str, Any]:
    return load_cutover_authorization(
        DEFAULT_AUTHORIZATION_PATH, activation_bundle=activation
    )


def _state_store() -> tuple[
    OperationalPolicyCutoverStateStore, InMemoryOperationalEventStore
]:
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    return OperationalPolicyCutoverStateStore(emitter, events), events


def _application(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_text": "What does the evidence support?",
        "evidence_items": package["evidence_items"],
        "primary_package": package,
        "access_context": CxAccessContext(
            tenant_id="tenant-one",
            subject_id="owner-one",
            caller_service_id="nex-ae-api",
            scopes=("cx:retrieval:read",),
            request_id="cutover-request-one",
            trace_id="a" * 32,
        ),
    }


def _package() -> dict[str, Any]:
    return {
        "retrieval_package_id": "incumbent-package",
        "package_hash": "a" * 64,
        "status": "READY",
        "purpose": "grounded_answer",
        "permission_snapshot": {"policy_version": "cx.private_owner_active.v1"},
        "evidence_items": [
            {
                "evidence_id": "evidence-one",
                "text": "The approved evidence directly supports the answer.",
                "permission_result": {"visible": True},
            }
        ],
        "retrieval_profile": {
            "confidence_policy": {
                "policy_id": "cx_retrieval_confidence_multisignal_v1",
                "low_confidence_threshold": 0.2,
                "calibration_profile_id": "incumbent",
                "calibration_profile_hash": "b" * 64,
            },
            "quality_policy": {"low_confidence_threshold": 0.2},
            "candidate_summary": {"fused_candidate_count": 1},
        },
        "score_summary": {
            "best_score": 0.8,
            "confidence_bucket": "READY",
            "decision_reason": None,
            "low_confidence_threshold": 0.2,
            "confidence_features": {
                "feature_schema_version": "cx_retrieval_confidence_features.v1",
                "candidate_count": 1,
                "reranker_score": 0.8,
                "reranker_margin": 0.8,
                "rrf_normalized_score": 0.8,
                "channel_support": 1.0,
                "composite_score": 0.8,
            },
            "calibration_profile_id": "incumbent",
            "calibration_profile_hash": "b" * 64,
        },
        "no_answer_reason": None,
    }
