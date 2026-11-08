from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import nex_cx.retrieval_answer_support_controlled_activation as subject
import pytest
from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_controlled_activation import (
    ACTIVATION_BUNDLE_PATH_ENV,
    ACTIVATION_EVENT_TYPE,
    ACTIVATION_MODE_ENV,
    ACTIVE,
    DEFAULT_ACTIVATION_BUNDLE_PATH,
    ROLLED_BACK,
    ControlledAnswerSupportRuntime,
    ControlledRuntimeActivationError,
    OperationalAnswerSupportProgressSink,
    OperationalRuntimeActivationStateStore,
    build_activation_state,
    build_installed_controlled_answer_support_runtime,
    load_controlled_activation_bundle,
    validate_activation_state,
    validate_controlled_activation_bundle,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

QUERY = "정산 기준을 알려줘"
EVIDENCE_TEXT = "승인 완료 후 정산한다"


class RecordingSink:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.events: list[dict[str, Any]] = []

    def record(self, event) -> None:
        if self.error is not None:
            raise self.error
        self.events.append(dict(event))


class MemoryStateStore:
    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []

    def current_state(self, bundle_hash: str):
        return next(
            (
                deepcopy(row)
                for row in reversed(self.states)
                if row["activation_bundle_hash"] == bundle_hash
            ),
            None,
        )

    def record_state(self, state) -> None:
        self.states.append(deepcopy(dict(state)))


class FakeGenerationClient:
    def __init__(
        self,
        *,
        deployment_id: str = "dgx-qwen3-5-9b-9116",
        error: Exception | None = None,
    ) -> None:
        self.deployment_id = deployment_id
        self.error = error
        self.calls = 0

    def create_generation(self, payload, *, request_id: str, trace_id: str):
        self.calls += 1
        if self.error is not None:
            raise self.error
        request = json.loads(payload["messages"][1]["content"])
        return {
            "alias": "general-llm-default",
            "model_revision": "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "deployment_id": self.deployment_id,
            "provider_type": "vllm",
            "output": {
                "type": "text",
                "text": json.dumps(
                    {
                        "items": [
                            {
                                "candidate_id": row["candidate_id"],
                                "classification": "SUPPORTING_EVIDENCE",
                                "answer_support_score": 0.9,
                                "contradiction_score": 0.05,
                            }
                            for row in request["candidates"]
                        ]
                    }
                ),
            },
            "finish_reason": "STOP",
            "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        }


class StubGateway:
    def __init__(self, snapshots: list[dict[str, Any]]) -> None:
        self.snapshots = snapshots

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(
            self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
        )


class StubDelegate:
    def __init__(
        self,
        outcome: dict[str, Any] | None,
        snapshots: list[dict[str, Any]],
        *,
        error: Exception | None = None,
    ) -> None:
        self.outcome = outcome
        self.error = error
        self.generation_client = StubGateway(snapshots)

    def observe(self, **kwargs):
        if self.error is not None:
            raise self.error
        return deepcopy(self.outcome)


def test_activation_bundle_is_integrity_bound_and_rejects_drift(tmp_path: Path) -> None:
    bundle = _bundle()
    assert (
        validate_controlled_activation_bundle(bundle)["bundle_hash"]
        == bundle["bundle_hash"]
    )

    drift = deepcopy(bundle)
    drift["safety"]["production_cutover_permitted"] = True
    with pytest.raises(ControlledRuntimeActivationError) as raised:
        validate_controlled_activation_bundle(drift)
    assert raised.value.error_code.endswith("INTEGRITY")

    malformed = tmp_path / "bad.json"
    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(ControlledRuntimeActivationError):
        load_controlled_activation_bundle(malformed)
    with pytest.raises(ControlledRuntimeActivationError) as raised:
        load_controlled_activation_bundle(tmp_path / "missing.json")
    assert raised.value.error_code.endswith("UNAVAILABLE")


def test_installed_builder_is_explicit_restart_safe_and_rollback_sticky() -> None:
    store = MemoryStateStore()
    client = FakeGenerationClient()
    progress = RecordingSink()
    outcomes = RecordingSink()
    env = {
        ACTIVATION_MODE_ENV: "controlled",
        ACTIVATION_BUNDLE_PATH_ENV: str(DEFAULT_ACTIVATION_BUNDLE_PATH),
    }

    assert (
        build_installed_controlled_answer_support_runtime(
            environ={},
            generation_client=client,
            progress_sink=progress,
            outcome_sink=outcomes,
            state_store=store,
        )
        is None
    )
    runtime = build_installed_controlled_answer_support_runtime(
        environ=env,
        generation_client=client,
        progress_sink=progress,
        outcome_sink=outcomes,
        state_store=store,
    )
    assert runtime is not None
    assert store.states[-1]["activation_state"] == ACTIVE
    assert runtime.observe(**_observation())["status"] == "OBSERVED"
    assert runtime.snapshot()["activation_state"] == ACTIVE

    restarted = build_installed_controlled_answer_support_runtime(
        environ=env,
        generation_client=client,
        progress_sink=progress,
        outcome_sink=outcomes,
        state_store=store,
    )
    assert restarted is not None
    assert len(store.states) == 1

    failing = build_installed_controlled_answer_support_runtime(
        environ=env,
        generation_client=FakeGenerationClient(error=RuntimeError("private")),
        progress_sink=progress,
        outcome_sink=outcomes,
        state_store=store,
    )
    assert failing is not None
    assert failing.observe(**_observation())["status"] == "FAILED"
    assert failing.snapshot()["activation_state"] == ROLLED_BACK
    assert store.states[-1]["reason_code"] == "PROVIDER_ERROR"

    assert (
        build_installed_controlled_answer_support_runtime(
            environ=env,
            generation_client=client,
            progress_sink=progress,
            outcome_sink=outcomes,
            state_store=store,
        )
        is None
    )
    before = client.calls
    skipped = failing.observe(**_observation())
    assert skipped["skip_reason"] == "RUNTIME_ROLLED_BACK"
    assert client.calls == before


def test_provider_binding_and_progress_failures_trigger_immediate_rollback() -> None:
    drift = _runtime(client=FakeGenerationClient(deployment_id="drift"))
    outcome = drift.observe(**_observation())
    assert outcome["error_code"] == "cx.answer_support_shadow.provider_binding_drift"
    assert drift.snapshot()["rollback_reason"] == "SOURCE_BINDING_DRIFT"

    progress = _runtime(
        client=FakeGenerationClient(),
        progress_sink=RecordingSink(RuntimeError("sink unavailable")),
    )
    outcome = progress.observe(**_observation())
    assert outcome["status"] == "FAILED"
    assert progress.snapshot()["rollback_reason"] == "PROGRESS_SINK_FAILURE"


def test_ineligible_request_and_healthy_minimum_window_do_not_rollback() -> None:
    runtime = _runtime(client=FakeGenerationClient())
    ineligible = _observation()
    ineligible["primary_package"]["purpose"] = "search"
    assert runtime.observe(**ineligible)["status"] == "SKIPPED"
    assert runtime.snapshot()["activation_state"] == ACTIVE

    for _ in range(4):
        assert runtime.observe(**_observation())["status"] == "OBSERVED"
    assert runtime.snapshot()["rollback_reason"] is None


@pytest.mark.parametrize(
    ("feedback", "provider", "e2e", "reason"),
    [
        ([2_001.0] * 4, [1.0] * 4, 1.0, "FEEDBACK_P95_SLO_BREACH"),
        ([1.0] * 4, [15_001.0] * 4, 1.0, "PROVIDER_P95_SLO_BREACH"),
        ([1.0] * 4, [1.0] * 4, 20_001.0, "INTERACTIVE_E2E_P95_SLO_BREACH"),
    ],
)
def test_latency_slo_breaches_rollback_after_minimum_sample_count(
    feedback: list[float], provider: list[float], e2e: float, reason: str
) -> None:
    snapshot = _gateway_snapshot(feedback=feedback, provider=provider)
    outcome = {"status": "OBSERVED", "provider_called": True, "elapsed_ms": e2e}
    runtime = ControlledAnswerSupportRuntime(
        StubDelegate(outcome, [snapshot, snapshot]),  # type: ignore[arg-type]
        bundle=_bundle(),
        state_store=MemoryStateStore(),
    )
    for _ in range(4):
        runtime.observe(**_observation())
    assert runtime.snapshot()["rollback_reason"] == reason


def test_unexpected_delegate_error_rolls_back_and_propagates() -> None:
    snapshot = _gateway_snapshot(feedback=[], provider=[])
    runtime = ControlledAnswerSupportRuntime(
        StubDelegate(None, [snapshot], error=RuntimeError("overload")),  # type: ignore[arg-type]
        bundle=_bundle(),
        state_store=MemoryStateStore(),
    )
    with pytest.raises(RuntimeError):
        runtime.observe(**_observation())
    assert runtime.snapshot()["rollback_reason"] == "NON_RETRYABLE_OVERLOAD"
    runtime._rollback("SECOND_REASON")
    assert runtime.snapshot()["rollback_reason"] == "NON_RETRYABLE_OVERLOAD"


def test_operational_state_and_progress_sinks_store_only_sanitized_events() -> None:
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    states = OperationalRuntimeActivationStateStore(emitter=emitter, store=events)
    state = build_activation_state(
        bundle_hash=_bundle()["bundle_hash"],
        activation_state=ACTIVE,
        reason_code="OPERATOR_APPROVED_CONTROLLED_ACTIVATION",
    )
    states.record_state(state)
    assert states.current_state(state["activation_bundle_hash"]) == state
    assert len(events.list_events(event_type=ACTIVATION_EVENT_TYPE)) == 1
    assert states.current_state("sha256:" + "f" * 64) is None

    sticky_rollback = build_activation_state(
        bundle_hash=state["activation_bundle_hash"],
        activation_state=ROLLED_BACK,
        reason_code="PROVIDER_ERROR",
    )
    states.record_state(sticky_rollback)
    assert states.current_state(state["activation_bundle_hash"]) == sticky_rollback

    rolled_back = build_activation_state(
        bundle_hash="sha256:" + "e" * 64,
        activation_state=ROLLED_BACK,
        reason_code="PROVIDER_ERROR",
    )
    states.record_state(rolled_back)
    assert (
        events.list_events(event_type=ACTIVATION_EVENT_TYPE)[0]["severity"] == "WARNING"
    )

    progress = OperationalAnswerSupportProgressSink(emitter)
    progress.record(
        {
            "event_schema_version": "cx_answer_support_sync_progress_event.v1",
            "event_type": "REQUEST_ADMITTED",
            "request_id": "request-one",
            "trace_id": "a" * 32,
            "elapsed_ms": 1.5,
            "retryable": False,
            "event_hash": "sha256:" + "1" * 64,
        }
    )
    stored = events.list_events(event_type="cx.retrieval.answer_support_progress")[0]
    assert EVIDENCE_TEXT not in json.dumps(stored)
    assert stored["details"]["elapsed_ms"] == 1.5


def test_activation_state_and_mode_fail_closed_on_invalid_input(tmp_path: Path) -> None:
    state = build_activation_state(
        bundle_hash=_bundle()["bundle_hash"],
        activation_state=ROLLED_BACK,
        reason_code="PROVIDER_ERROR",
    )
    assert validate_activation_state(state)["activation_state"] == ROLLED_BACK
    tampered = deepcopy(state)
    tampered["reason_code"] = "changed"
    with pytest.raises(ControlledRuntimeActivationError):
        validate_activation_state(tampered)

    with pytest.raises(ControlledRuntimeActivationError):
        build_installed_controlled_answer_support_runtime(
            environ={ACTIVATION_MODE_ENV: "unknown"},
            generation_client=FakeGenerationClient(),
            progress_sink=RecordingSink(),
            outcome_sink=RecordingSink(),
            state_store=MemoryStateStore(),
        )
    with pytest.raises(ControlledRuntimeActivationError):
        build_installed_controlled_answer_support_runtime(
            environ={
                ACTIVATION_MODE_ENV: "controlled",
                ACTIVATION_BUNDLE_PATH_ENV: str(tmp_path / "missing.json"),
            },
            generation_client=FakeGenerationClient(),
            progress_sink=RecordingSink(),
            outcome_sink=RecordingSink(),
            state_store=MemoryStateStore(),
        )


def test_bundle_contract_rejects_shape_identity_source_approval_and_slo_drift() -> None:
    missing = _bundle()
    missing.pop("safety")
    with pytest.raises(ControlledRuntimeActivationError):
        validate_controlled_activation_bundle(missing)

    identity = _bundle()
    identity["status"] = "DRAFT"
    _rehash_bundle(identity)
    with pytest.raises(ControlledRuntimeActivationError):
        validate_controlled_activation_bundle(identity)

    source = _bundle()
    source["source_binding"]["provider_binding_hash"] = "sha256:" + "a" * 64
    _rehash_bundle(source)
    with pytest.raises(ControlledRuntimeActivationError):
        validate_controlled_activation_bundle(source)

    approval_integrity = _bundle()
    approval_integrity["approval_receipt"]["status"] = "FAIL"
    _rehash_bundle(approval_integrity)
    with pytest.raises(ControlledRuntimeActivationError):
        validate_controlled_activation_bundle(approval_integrity)

    approval_semantics = _bundle()
    approval_semantics["approval_receipt"]["status"] = "FAIL"
    _rehash_approval(approval_semantics)
    with pytest.raises(ControlledRuntimeActivationError):
        validate_controlled_activation_bundle(approval_semantics)

    slo_shape = _bundle()
    slo_shape["slo_profile"].pop("minimum_sample_count")
    _rehash_bundle(slo_shape)
    with pytest.raises(ControlledRuntimeActivationError):
        validate_controlled_activation_bundle(slo_shape)

    slo_value = _bundle()
    slo_value["slo_profile"]["minimum_sample_count"] = 3
    _rehash_bundle(slo_value)
    with pytest.raises(ControlledRuntimeActivationError):
        validate_controlled_activation_bundle(slo_value)


def test_low_level_contract_guards_reject_malformed_values() -> None:
    with pytest.raises(ControlledRuntimeActivationError):
        subject._numbers("bad")
    with pytest.raises(ControlledRuntimeActivationError):
        subject._number(True, "value")
    with pytest.raises(ControlledRuntimeActivationError):
        subject._required_text("", "value")
    with pytest.raises(ControlledRuntimeActivationError):
        subject._mapping([], "value")
    with pytest.raises(ControlledRuntimeActivationError):
        subject._exact({"a": 1}, {"b"}, "value")
    with pytest.raises(ControlledRuntimeActivationError):
        subject._hash_ref(None, "value")
    with pytest.raises(ControlledRuntimeActivationError):
        subject._hash_ref("bad", "value")


def _runtime(
    *,
    client: FakeGenerationClient,
    progress_sink: RecordingSink | None = None,
) -> ControlledAnswerSupportRuntime:
    runtime = build_installed_controlled_answer_support_runtime(
        environ={
            ACTIVATION_MODE_ENV: "controlled",
            ACTIVATION_BUNDLE_PATH_ENV: str(DEFAULT_ACTIVATION_BUNDLE_PATH),
        },
        generation_client=client,
        progress_sink=progress_sink or RecordingSink(),
        outcome_sink=RecordingSink(),
        state_store=MemoryStateStore(),
    )
    assert runtime is not None
    return runtime


def _bundle() -> dict[str, Any]:
    return json.loads(DEFAULT_ACTIVATION_BUNDLE_PATH.read_text(encoding="utf-8"))


def _observation() -> dict[str, Any]:
    return {
        "query_text": QUERY,
        "evidence_items": [
            {
                "evidence_id": "evidence-one",
                "text": EVIDENCE_TEXT,
                "permission_result": {"visible": True},
            }
        ],
        "primary_package": {
            "retrieval_package_id": "package-one",
            "status": "READY",
            "purpose": "grounded_answer",
        },
        "access_context": CxAccessContext(
            tenant_id="tenant-one",
            subject_id="subject-one",
            caller_service_id="nex-ae-api",
            scopes=("cx:retrieval:read",),
            request_id="request-one",
            trace_id="a" * 32,
        ),
    }


def _gateway_snapshot(
    *, feedback: list[float], provider: list[float]
) -> dict[str, Any]:
    return {
        "maximum_in_flight": 4,
        "in_flight": 0,
        "peak_in_flight": 1,
        "admitted_count": len(provider),
        "rejected_count": 0,
        "completed_count": len(provider),
        "failed_count": 0,
        "progress_failure_count": 0,
        "feedback_latencies_ms": feedback,
        "provider_latencies_ms": provider,
        "pending_request_count": 0,
    }


def _rehash_bundle(bundle: dict[str, Any]) -> None:
    bundle.pop("bundle_hash", None)
    bundle["bundle_hash"] = semantic_sha256_hash_ref(bundle)


def _rehash_approval(bundle: dict[str, Any]) -> None:
    receipt = bundle["approval_receipt"]
    receipt.pop("receipt_hash", None)
    receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
    source = bundle["source_binding"]
    source["approval_receipt_hash"] = receipt["receipt_hash"]
    source["approval_receipt_document_hash"] = semantic_sha256_hash_ref(receipt)
    _rehash_bundle(bundle)
