from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_cx.retrieval_answer_support_controlled_activation import (
    OperationalAnswerSupportProgressSink,
)
from nex_cx.retrieval_answer_support_policy_cutover import (
    ACTIVE,
    CUTOVER_MODE_CONTROLLED,
    CUTOVER_MODE_ENV,
    ROLLBACK_PENDING_REVIEW,
    ROLLED_BACK,
    AnswerSupportPolicyCutoverError,
    OperationalPolicyCutoverStateStore,
    build_cutover_decision_event,
    build_installed_answer_support_policy_cutover,
    validate_cutover_decision_event,
)
from nex_cx.retrieval_answer_support_policy_cutover_operations import (
    DECISION_EVENT_TYPE,
    DEFAULT_POLICY_PATH,
    OPERATIONS_PATH,
    WINDOW_EVENT_TYPE,
    OperationalPolicyCutoverDecisionSink,
    OperationalPolicyCutoverSource,
    PolicyCutoverOperationsError,
    _decision_projection,
    _ensure_window_open,
    _hash_ref,
    _p95,
    _progress_projection,
    _required_text,
    _runtime_projection,
    _safe_integer,
    _safe_number,
    _state_projection,
    _window_projection,
    build_installed_policy_cutover_operations_source,
    load_policy_cutover_operations_policy,
    register_policy_cutover_operations_routes,
    validate_policy_cutover_operations_policy,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    issue_mock_service_token,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_policy_cutover import (
    FakeGenerationClient,
    RecordingOutcomeSink,
    _application,
    _package,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


class FailingStore:
    def list_events(self, **_kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("private database failure")


class FailingDecisionSink:
    def record(self, _decision: object) -> None:
        raise RuntimeError("telemetry unavailable")


def test_policy_is_integrity_bound_and_source_admitted(tmp_path: Path) -> None:
    policy = _policy()
    assert validate_policy_cutover_operations_policy(policy) == policy
    assert policy["minimum_operator_review_samples"] == 12
    assert policy["safety"]["runtime_stopped_at_observation_cap"] is False

    for mutate in (
        lambda value: value.update(maximum_observation_provider_samples=13),
        lambda value: value["source_acceptance"].update(decision="REJECTED"),
        lambda value: value["safety"].update(production_cutover_permitted=True),
    ):
        drift = deepcopy(policy)
        mutate(drift)
        _rehash(drift)
        with pytest.raises(PolicyCutoverOperationsError):
            validate_policy_cutover_operations_policy(drift)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(PolicyCutoverOperationsError):
        load_policy_cutover_operations_policy(malformed)
    with pytest.raises(PolicyCutoverOperationsError):
        load_policy_cutover_operations_policy(tmp_path / "missing.json")


def test_cutover_decision_contract_and_operational_sink_are_idempotent() -> None:
    package = _package()
    result = deepcopy(package)
    result.update(
        retrieval_package_id="cutover-package",
        package_hash="b" * 64,
        status="LOW_CONFIDENCE",
    )
    decision = build_cutover_decision_event(
        authorization_hash=_policy()["authorization_hash"],
        selected_policy_hash=_policy()["selected_policy_hash"],
        request_id="request-one",
        trace_id="a" * 32,
        primary_package=package,
        result=result,
        outcome={"provider_called": True, "elapsed_ms": 12.5},
        decision_state="APPLIED",
        reason_code=None,
    )
    assert validate_cutover_decision_event(decision) == decision
    assert decision["user_visible"] is True
    assert "evidence" not in json.dumps(decision)

    events = InMemoryOperationalEventStore()
    sink = OperationalPolicyCutoverDecisionSink(_emitter(events))
    sink.record(decision)
    sink.record(decision)
    stored = events.list_events(event_type=DECISION_EVENT_TYPE)
    assert len(stored) == 1
    assert stored[0]["details"] == decision

    drift = deepcopy(decision)
    drift["decision_state"] = "FALLBACK"
    with pytest.raises(AnswerSupportPolicyCutoverError):
        validate_cutover_decision_event(drift)


def test_runtime_decisions_are_projected_in_restart_safe_bounded_window() -> None:
    events, runtime, source = _runtime_and_source()

    initial = source.snapshot(generated_at=NOW)
    assert initial["operations_status"] == "OBSERVING"
    assert initial["decisions"]["provider_sample_count"] == 0

    for index in range(1, 13):
        result = runtime.apply(**_unique_application(index))
        assert result["status"] == "READY"

    snapshot = source.snapshot(generated_at=NOW)
    assert snapshot["operations_status"] == "REVIEW_REQUIRED"
    assert snapshot["health_status"] == "READY"
    assert snapshot["decisions"]["provider_sample_count"] == 12
    assert snapshot["decisions"]["applied_count"] == 12
    assert snapshot["decisions"]["ready_count"] == 12
    assert snapshot["decisions"]["observation_cap_reached"] is True
    assert snapshot["decisions"]["observation_overrun_count"] == 0
    assert snapshot["progress"]["completed_count"] == 12
    assert all(snapshot["slo"]["checks"].values())
    assert snapshot["runtime"]["peak_in_flight"] <= 4
    assert "approved evidence directly" not in json.dumps(snapshot)

    restarted = OperationalPolicyCutoverSource(
        store=events,
        policy=_policy(),
        runtime_snapshot=runtime.snapshot,
    )
    assert (
        restarted.snapshot(generated_at=NOW)["snapshot_hash"]
        == snapshot["snapshot_hash"]
    )


def test_window_cap_is_observational_and_does_not_stop_authoritative_runtime() -> None:
    _events, runtime, source = _runtime_and_source()
    for index in range(1, 14):
        assert runtime.apply(**_unique_application(index))["status"] == "READY"

    snapshot = source.snapshot(generated_at=NOW)
    assert snapshot["decisions"]["provider_sample_count"] == 13
    assert snapshot["decisions"]["observation_overrun_count"] == 1
    assert snapshot["operations_status"] == "REVIEW_REQUIRED"
    assert snapshot["safety"]["runtime_stopped_at_observation_cap"] is False


@pytest.mark.parametrize(
    ("pending_review", "expected"),
    [(False, ROLLED_BACK), (True, ROLLBACK_PENDING_REVIEW)],
)
def test_terminal_cutover_state_is_visible_and_restart_safe(
    pending_review: bool, expected: str
) -> None:
    _events, runtime, source = _runtime_and_source()
    runtime._rollback("PROVIDER_ERROR", pending_review=pending_review)

    snapshot = source.snapshot(generated_at=NOW)
    assert snapshot["operations_status"] == expected
    assert snapshot["health_status"] == "DEGRADED"
    assert snapshot["state"]["reason_code"] == "PROVIDER_ERROR"
    fallback = runtime.apply(**_unique_application(1))
    assert fallback == _unique_application(1)["primary_package"]
    assert source.snapshot(generated_at=NOW)["decisions"]["fallback_count"] == 1


def test_skip_and_telemetry_failure_preserve_safe_runtime_result() -> None:
    events = InMemoryOperationalEventStore()
    state_store = OperationalPolicyCutoverStateStore(_emitter(events), events)
    runtime = build_installed_answer_support_policy_cutover(
        environ={CUTOVER_MODE_ENV: CUTOVER_MODE_CONTROLLED},
        generation_client=FakeGenerationClient(),
        progress_sink=OperationalAnswerSupportProgressSink(state_store.emitter),
        outcome_sink=RecordingOutcomeSink(),
        state_store=state_store,
        decision_sink=FailingDecisionSink(),
    )
    assert runtime is not None
    request = _unique_application(1)
    request["primary_package"]["purpose"] = "search"
    assert runtime.apply(**request) == request["primary_package"]
    assert runtime.snapshot()["cutover_state"] == ACTIVE


def test_window_open_is_idempotent_and_binding_drift_fails_closed() -> None:
    events, runtime, _source = _runtime_and_source()
    rebuilt = build_installed_policy_cutover_operations_source(
        environ={},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=runtime.snapshot,
    )
    assert rebuilt.snapshot(generated_at=NOW)["window"]["window_state"] == "OPEN"
    assert len(events.list_events(event_type=WINDOW_EVENT_TYPE)) == 1

    bad_runtime = lambda: {
        **runtime.snapshot(),
        "selected_policy_hash": "sha256:" + "0" * 64,
    }
    with pytest.raises(PolicyCutoverOperationsError) as raised:
        build_installed_policy_cutover_operations_source(
            environ={},
            store=events,
            emitter=_emitter(events),
            runtime_snapshot=bad_runtime,
        )
    assert "BINDING_DRIFT" in raised.value.error_code

    window_id = str(
        uuid5(
            NAMESPACE_URL,
            f"cx-answer-support-policy-cutover-window:{_policy()['window_id']}",
        )
    )
    existing = events.get_event(window_id)
    assert existing is not None
    existing["details"]["window_state"] = "CLOSED"
    drifted = InMemoryOperationalEventStore(events={window_id: existing})
    with pytest.raises(PolicyCutoverOperationsError):
        build_installed_policy_cutover_operations_source(
            environ={},
            store=drifted,
            emitter=_emitter(drifted),
            runtime_snapshot=runtime.snapshot,
        )


def test_disabled_source_and_source_failure_are_explicit() -> None:
    events = InMemoryOperationalEventStore()
    source = build_installed_policy_cutover_operations_source(
        environ={},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=lambda: None,
    )
    snapshot = source.snapshot(generated_at=NOW)
    assert snapshot["operations_status"] == "DISABLED"
    assert snapshot["health_status"] == "UNAVAILABLE"

    failing = OperationalPolicyCutoverSource(
        store=FailingStore(),  # type: ignore[arg-type]
        policy=_policy(),
        runtime_snapshot=lambda: None,
    )
    with pytest.raises(PolicyCutoverOperationsError) as raised:
        failing.snapshot()
    assert raised.value.status_code == 503
    assert raised.value.retryable is True


def test_operations_route_is_ag_scope_protected_and_redacted() -> None:
    _events, runtime, source = _runtime_and_source()
    runtime.apply(**_unique_application(1))
    app = FastAPI()
    register_policy_cutover_operations_routes(app, source=source)
    client = TestClient(app)

    assert client.get(OPERATIONS_PATH).status_code == 401
    assert (
        client.get(
            OPERATIONS_PATH, headers={"Authorization": _authorization("nex-ae-api")}
        ).status_code
        == 403
    )
    assert (
        client.get(
            OPERATIONS_PATH,
            headers={"Authorization": _authorization(include_scope=False)},
        ).status_code
        == 401
    )
    response = client.get(OPERATIONS_PATH, headers={"Authorization": _authorization()})
    assert response.status_code == 200
    assert response.json()["decisions"]["applied_count"] == 1
    assert "approved evidence directly" not in response.text

    unavailable_app = FastAPI()
    register_policy_cutover_operations_routes(
        unavailable_app,
        source=OperationalPolicyCutoverSource(
            store=FailingStore(),  # type: ignore[arg-type]
            policy=_policy(),
            runtime_snapshot=lambda: None,
        ),
    )
    unavailable = TestClient(unavailable_app).get(
        OPERATIONS_PATH, headers={"Authorization": _authorization()}
    )
    assert unavailable.status_code == 503
    assert "private database failure" not in unavailable.text


def test_projection_helpers_ignore_malformed_unbound_and_pre_window_events() -> None:
    policy = _policy()
    decisions = _decision_projection(
        [
            {"created_at": "2026-11-06T09:59:00Z", "details": {}},
            {"created_at": "2026-11-06T10:01:00Z", "details": "bad"},
            {
                "created_at": "2026-11-06T10:02:00Z",
                "details": {
                    "cutover_receipt_hash": "sha256:" + "0" * 64,
                    "selected_policy_hash": policy["selected_policy_hash"],
                    "provider_called": True,
                },
            },
        ],
        opened_at="2026-11-06T10:00:00Z",
        maximum_samples=12,
        authorization_hash=policy["authorization_hash"],
        selected_policy_hash=policy["selected_policy_hash"],
    )
    assert decisions["total_count"] == 0

    progress = _progress_projection(
        [
            {"created_at": "2026-11-06T10:01:00Z", "details": "bad"},
            {
                "created_at": "2026-11-06T10:02:00Z",
                "details": {
                    "progress_event_type": "REQUEST_FAILED",
                    "elapsed_ms": 12.5,
                },
            },
        ],
        opened_at="2026-11-06T10:00:00Z",
    )
    assert progress["failed_count"] == 1
    assert progress["provider_p95_latency_ms"] == 12.5
    assert _p95([]) == 0.0
    assert _safe_number(True) is None
    assert _safe_integer(True) == 0
    assert _runtime_projection(None)["installed"] is False


def test_projection_contract_edge_branches_are_fail_closed() -> None:
    policy = _policy()
    window = _window_projection(
        [
            {"created_at": "2026-11-06T10:00:00Z", "details": "bad"},
            {
                "created_at": "2026-11-06T10:01:00Z",
                "details": {"window_id": "other"},
            },
        ],
        policy,
    )
    assert window["window_state"] == "NOT_OPENED"

    state = _state_projection(
        [
            {"created_at": "2026-11-06T10:00:00Z", "details": "bad"},
            {
                "created_at": "2026-11-06T10:01:00Z",
                "details": {"cutover_receipt_hash": "sha256:" + "0" * 64},
            },
        ],
        policy,
    )
    assert state["cutover_state"] == "NOT_ACTIVATED"

    decision = _decision_projection(
        [
            {
                "created_at": "2026-11-06T10:01:00Z",
                "details": {
                    "cutover_receipt_hash": policy["authorization_hash"],
                    "selected_policy_hash": policy["selected_policy_hash"],
                    "decision_state": "UNKNOWN",
                    "provider_called": True,
                    "elapsed_ms": "bad",
                },
            }
        ],
        opened_at="2026-11-06T10:00:00Z",
        maximum_samples=12,
        authorization_hash=policy["authorization_hash"],
        selected_policy_hash=policy["selected_policy_hash"],
    )
    assert decision["total_count"] == 0
    assert decision["provider_sample_count"] == 1
    assert decision["e2e_p95_latency_ms"] == 0.0

    progress = _progress_projection(
        [
            {
                "created_at": "2026-11-06T10:01:00Z",
                "details": {"progress_event_type": "UNKNOWN"},
            },
            {
                "created_at": "2026-11-06T10:02:00Z",
                "details": {
                    "progress_event_type": "REQUEST_COMPLETED",
                    "elapsed_ms": "bad",
                },
            },
        ],
        opened_at="2026-11-06T10:00:00Z",
    )
    assert progress["completed_count"] == 1
    assert progress["provider_p95_latency_ms"] == 0.0

    for call in (
        lambda: _required_text(""),
        lambda: _hash_ref(None),
        lambda: _hash_ref("bad"),
    ):
        with pytest.raises(PolicyCutoverOperationsError):
            call()


def test_window_recovery_and_terminal_open_attempt_fail_closed() -> None:
    events, runtime, _source = _runtime_and_source()
    runtime._rollback("PROVIDER_ERROR", pending_review=False)
    with pytest.raises(PolicyCutoverOperationsError):
        _ensure_window_open(
            emitter=_emitter(events),
            store=events,
            policy=_policy(),
            runtime=runtime.snapshot(),
        )

    class MissingRecoveryStore(InMemoryOperationalEventStore):
        def get_event(self, event_id: str):
            del event_id
            return self.events.get("never-persisted")

    missing = MissingRecoveryStore()
    active_runtime = {
        **runtime.snapshot(),
        "cutover_state": ACTIVE,
        "rollback_reason": None,
    }
    with pytest.raises(PolicyCutoverOperationsError) as raised:
        _ensure_window_open(
            emitter=_emitter(missing),
            store=missing,
            policy=_policy(),
            runtime=active_runtime,
        )
    assert raised.value.status_code == 503


def test_naive_clock_and_semantic_policy_fields_fail_closed() -> None:
    source = OperationalPolicyCutoverSource(
        store=InMemoryOperationalEventStore(),
        policy=_policy(),
        runtime_snapshot=lambda: None,
    )
    with pytest.raises(PolicyCutoverOperationsError):
        source.snapshot(generated_at=datetime(2026, 11, 6))  # noqa: DTZ001

    drift = _policy()
    drift.pop("window_id")
    _rehash(drift)
    with pytest.raises(PolicyCutoverOperationsError):
        validate_policy_cutover_operations_policy(drift)


def _runtime_and_source():
    events = InMemoryOperationalEventStore()
    emitter = _emitter(events)
    state_store = OperationalPolicyCutoverStateStore(emitter, events)
    runtime = build_installed_answer_support_policy_cutover(
        environ={CUTOVER_MODE_ENV: CUTOVER_MODE_CONTROLLED},
        generation_client=FakeGenerationClient(),
        progress_sink=OperationalAnswerSupportProgressSink(emitter),
        outcome_sink=RecordingOutcomeSink(),
        state_store=state_store,
        decision_sink=OperationalPolicyCutoverDecisionSink(emitter),
    )
    assert runtime is not None
    source = build_installed_policy_cutover_operations_source(
        environ={},
        store=events,
        emitter=emitter,
        runtime_snapshot=runtime.snapshot,
    )
    return events, runtime, source


def _unique_application(index: int) -> dict[str, Any]:
    package = _package()
    package["retrieval_package_id"] = f"cutover-operations-package-{index}"
    package["package_hash"] = f"{index:064x}"
    application = _application(package)
    application["access_context"] = replace(
        application["access_context"], request_id=f"cutover-operations-{index}"
    )
    return application


def _policy() -> dict[str, Any]:
    return json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))


def _rehash(policy: dict[str, Any]) -> None:
    policy.pop("policy_hash", None)
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)


def _emitter(events: InMemoryOperationalEventStore) -> OperationalEventEmitter:
    return OperationalEventEmitter(service_id="nex-cx", store=events)


def _authorization(service_id: str = "nex-ag", *, include_scope: bool = True) -> str:
    scopes = ["service:call"]
    if include_scope:
        scopes.append("operations:read")
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-cx",
        scopes=scopes,
    )
    return f"Bearer {token.access_token}"
