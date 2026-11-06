from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_cx.retrieval_answer_support_policy_cutover import (
    ACTIVE,
    ROLLBACK_PENDING_REVIEW,
    ROLLED_BACK,
)
from nex_cx.retrieval_answer_support_policy_steady_state import (
    STEADY_STATE_MODE_CONTROLLED,
    STEADY_STATE_MODE_ENV,
    OperationalSteadyStateStateStore,
    build_installed_answer_support_policy_steady_state,
)
from nex_cx.retrieval_answer_support_policy_steady_state_operations import (
    DEFAULT_POLICY_PATH,
    OPERATIONS_PATH,
    WINDOW_EVENT_TYPE,
    OperationalPolicySteadyStateSource,
    PolicySteadyStateOperationsError,
    _ensure_window_open,
    _hash_ref,
    _operations_status,
    _required_text,
    _runtime_projection,
    _steady_state_projection,
    _window_projection,
    build_installed_policy_steady_state_operations_source,
    load_policy_steady_state_operations_policy,
    register_policy_steady_state_operations_routes,
    validate_policy_steady_state_operations_policy,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_policy_cutover_operations import (
    FailingStore,
    _authorization,
    _emitter,
    _runtime_and_source,
    _unique_application,
)

NOW = datetime(2026, 11, 6, 16, 0, tzinfo=UTC)


def test_policy_is_integrity_bound_to_pan_activation(tmp_path: Path) -> None:
    policy = _policy()

    assert validate_policy_steady_state_operations_policy(policy) == policy
    assert policy["source_activation"]["decision"] == (
        "ANSWER_SUPPORT_POLICY_STEADY_STATE_ACTIVATION_AND_ROLLBACK_ACCEPTED"
    )
    assert policy["review_sample_interval"] == 12

    for mutate in (
        lambda value: value.update(review_sample_interval=13),
        lambda value: value["source_activation"].update(status="FAIL"),
        lambda value: value["safety"].update(production_cutover_permitted=True),
        lambda value: value["escalation_policy"].update(provider_failure="IGNORE"),
    ):
        drift = deepcopy(policy)
        mutate(drift)
        _rehash(drift)
        with pytest.raises(PolicySteadyStateOperationsError):
            validate_policy_steady_state_operations_policy(drift)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(PolicySteadyStateOperationsError):
        load_policy_steady_state_operations_policy(malformed)
    with pytest.raises(PolicySteadyStateOperationsError):
        load_policy_steady_state_operations_policy(tmp_path / "missing.json")


def test_window_reaches_review_cadence_without_stopping_runtime() -> None:
    events, steady = _runtime()
    source = _source(events, steady)

    initial = source.snapshot(generated_at=NOW)
    assert initial["operations_status"] == "MONITORING"
    assert initial["cadence"]["remaining_review_samples"] == 12

    for index in range(1, 13):
        assert steady.apply(**_unique_application(index))["status"] == "READY"

    snapshot = source.snapshot(generated_at=NOW)
    assert snapshot["operations_status"] == "OPERATOR_REVIEW_DUE"
    assert snapshot["health_status"] == "ATTENTION"
    assert snapshot["state"]["steady_state_state"] == ACTIVE
    assert snapshot["cadence"]["provider_samples_since_review"] == 12
    assert snapshot["cadence"]["runtime_stopped"] is False
    assert snapshot["decisions"]["ready_count"] == 12
    assert snapshot["escalations"] == ["OPERATOR_REVIEW_REQUIRED"]
    assert all(snapshot["slo"]["checks"].values())
    assert "approved evidence directly" not in json.dumps(snapshot)

    assert steady.apply(**_unique_application(13))["status"] == "READY"
    assert source.snapshot(generated_at=NOW)["cadence"][
        "observation_overrun_count"
    ] == 1


def test_restart_recovers_window_and_projection() -> None:
    events, steady = _runtime()
    source = _source(events, steady)
    steady.apply(**_unique_application(1))
    expected = source.snapshot(generated_at=NOW)

    restarted = OperationalPolicySteadyStateSource(
        store=events,
        policy=_policy(),
        runtime_snapshot=steady.snapshot,
    )

    assert restarted.snapshot(generated_at=NOW)["snapshot_hash"] == expected[
        "snapshot_hash"
    ]
    assert len(events.list_events(event_type=WINDOW_EVENT_TYPE)) == 1


@pytest.mark.parametrize(
    ("cutover_state", "expected"),
    [(ROLLED_BACK, "ROLLED_BACK"), (ROLLBACK_PENDING_REVIEW, "ROLLBACK_PENDING_REVIEW")],
)
def test_terminal_state_dominates_projection(
    cutover_state: str, expected: str
) -> None:
    events, steady = _runtime()
    source = _source(events, steady)
    steady.delegate._rollback(  # type: ignore[attr-defined]
        "PROVIDER_ERROR", pending_review=cutover_state == ROLLBACK_PENDING_REVIEW
    )
    steady.snapshot()

    snapshot = source.snapshot(generated_at=NOW)
    assert snapshot["operations_status"] == expected
    assert snapshot["health_status"] == "DEGRADED"
    assert snapshot["escalations"] == ["ROLLBACK_STATE_DOMINANT"]


def test_escalation_order_is_fail_closed() -> None:
    baseline = {
        "window": {"window_state": "OPEN"},
        "state": {"steady_state_state": ACTIVE},
        "decisions": {"fallback_count": 0},
        "progress": {"failed_count": 0},
        "runtime": {"installed": True, "steady_state_state": ACTIVE},
        "cadence": {"operator_review_due": False},
        "slo_checks": {
            "provider_p95_within_limit": True,
            "e2e_p95_within_limit": True,
        },
    }
    assert _operations_status(**baseline) == ("MONITORING", "READY", [])

    fallback = deepcopy(baseline)
    fallback["decisions"]["fallback_count"] = 1
    assert _operations_status(**fallback)[0] == "ROLLBACK_REQUIRED"

    failure = deepcopy(baseline)
    failure["progress"]["failed_count"] = 1
    assert _operations_status(**failure)[0] == "ROLLBACK_REQUIRED"

    breach = deepcopy(baseline)
    breach["slo_checks"]["provider_p95_within_limit"] = False
    assert _operations_status(**breach) == (
        "ROLLBACK_PENDING_REVIEW",
        "DEGRADED",
        ["provider_p95_within_limit"],
    )

    due = deepcopy(baseline)
    due["cadence"]["operator_review_due"] = True
    assert _operations_status(**due)[0] == "OPERATOR_REVIEW_DUE"

    disabled = deepcopy(baseline)
    disabled["runtime"]["installed"] = False
    assert _operations_status(**disabled)[0] == "DISABLED"


def test_window_is_idempotent_and_binding_drift_fails_closed() -> None:
    events, steady = _runtime()
    source = _source(events, steady)
    assert source.snapshot(generated_at=NOW)["window"]["window_state"] == "OPEN"
    _source(events, steady)
    assert len(events.list_events(event_type=WINDOW_EVENT_TYPE)) == 1

    bad_runtime = lambda: {
        **steady.snapshot(),
        "operations_profile_hash": "sha256:" + "0" * 64,
    }
    with pytest.raises(PolicySteadyStateOperationsError):
        build_installed_policy_steady_state_operations_source(
            environ={},
            store=events,
            emitter=_emitter(events),
            runtime_snapshot=bad_runtime,
        )

    event_id = str(
        uuid5(
            NAMESPACE_URL,
            "cx-answer-support-policy-steady-state-window:"
            f"{_policy()['steady_state_window_id']}",
        )
    )
    existing = events.get_event(event_id)
    assert existing is not None
    existing["details"]["window_state"] = "CLOSED"
    drifted = InMemoryOperationalEventStore(events={event_id: existing})
    with pytest.raises(PolicySteadyStateOperationsError):
        _ensure_window_open(
            emitter=_emitter(drifted),
            store=drifted,
            policy=_policy(),
            runtime=steady.snapshot(),
        )


def test_terminal_start_missing_persistence_and_source_failure() -> None:
    events, steady = _runtime()
    steady.delegate._rollback("PROVIDER_ERROR", pending_review=False)  # type: ignore[attr-defined]
    steady.snapshot()
    source = build_installed_policy_steady_state_operations_source(
        environ={},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=steady.snapshot,
    )
    assert source.snapshot(generated_at=NOW)["operations_status"] == ROLLED_BACK
    with pytest.raises(PolicySteadyStateOperationsError):
        _ensure_window_open(
            emitter=_emitter(events),
            store=events,
            policy=_policy(),
            runtime=steady.snapshot(),
        )

    class MissingRecoveryStore(InMemoryOperationalEventStore):
        def get_event(self, event_id: str):
            return self.events.get(f"missing-{event_id}")

    active_events, active = _runtime()
    del active_events
    missing = MissingRecoveryStore()
    with pytest.raises(PolicySteadyStateOperationsError) as raised:
        _ensure_window_open(
            emitter=_emitter(missing),
            store=missing,
            policy=_policy(),
            runtime=active.snapshot(),
        )
    assert raised.value.status_code == 503

    failing = OperationalPolicySteadyStateSource(
        store=FailingStore(),  # type: ignore[arg-type]
        policy=_policy(),
        runtime_snapshot=lambda: None,
    )
    with pytest.raises(PolicySteadyStateOperationsError) as unavailable:
        failing.snapshot()
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


def test_disabled_naive_clock_and_route_protection() -> None:
    events = InMemoryOperationalEventStore()
    disabled = build_installed_policy_steady_state_operations_source(
        environ={},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=lambda: None,
    )
    assert disabled.snapshot(generated_at=NOW)["operations_status"] == "DISABLED"
    with pytest.raises(PolicySteadyStateOperationsError):
        disabled.snapshot(generated_at=datetime(2026, 11, 6))  # noqa: DTZ001

    events, steady = _runtime()
    source = _source(events, steady)
    steady.apply(**_unique_application(1))
    app = FastAPI()
    register_policy_steady_state_operations_routes(app, source=source)
    client = TestClient(app)

    assert client.get(OPERATIONS_PATH).status_code == 401
    assert client.get(
        OPERATIONS_PATH, headers={"Authorization": _authorization("nex-ae-api")}
    ).status_code == 403
    response = client.get(
        OPERATIONS_PATH, headers={"Authorization": _authorization()}
    )
    assert response.status_code == 200
    assert response.json()["cadence"]["provider_samples_since_review"] == 1
    assert "approved evidence directly" not in response.text

    unavailable_app = FastAPI()
    register_policy_steady_state_operations_routes(
        unavailable_app,
        source=OperationalPolicySteadyStateSource(
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


def test_projection_and_value_guards_cover_malformed_inputs() -> None:
    policy = _policy()
    window = _window_projection(
        [
            {"details": "bad"},
            {
                "created_at": "2026-11-06T15:00:00Z",
                "details": {
                    "window_schema_version": "wrong",
                    "window_id": policy["steady_state_window_id"],
                },
            },
        ],
        policy,
    )
    assert window["window_state"] == "NOT_OPENED"
    state = _steady_state_projection(
        [
            {"details": "bad"},
            {
                "created_at": "2026-11-06T15:01:00Z",
                "details": {
                    "steady_state_receipt_hash": "sha256:" + "0" * 64,
                    "operations_profile_hash": policy["operations_profile_hash"],
                },
            },
        ],
        policy,
    )
    assert state["steady_state_state"] == "NOT_ACTIVATED"
    assert _runtime_projection(None)["installed"] is False
    assert _runtime_projection({"generation_client": {"in_flight": "bad"}})[
        "in_flight"
    ] == 0

    drift = _policy()
    drift.pop("steady_state_window_id")
    _rehash(drift)
    with pytest.raises(PolicySteadyStateOperationsError):
        validate_policy_steady_state_operations_policy(drift)

    for call in (
        lambda: _required_text(""),
        lambda: _hash_ref(None),
        lambda: _hash_ref("bad"),
    ):
        with pytest.raises(PolicySteadyStateOperationsError):
            call()


def _runtime():
    events, cutover, _source_value = _runtime_and_source()
    steady_store = OperationalSteadyStateStateStore(
        OperationalEventEmitter(service_id="nex-cx", store=events), events
    )
    steady = build_installed_answer_support_policy_steady_state(
        environ={STEADY_STATE_MODE_ENV: STEADY_STATE_MODE_CONTROLLED},
        delegate=cutover,
        state_store=steady_store,
    )
    assert steady is not None
    return events, steady


def _source(events, steady) -> OperationalPolicySteadyStateSource:
    return build_installed_policy_steady_state_operations_source(
        environ={},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=steady.snapshot,
    )


def _policy() -> dict[str, Any]:
    return json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))


def _rehash(policy: dict[str, Any]) -> None:
    policy.pop("policy_hash", None)
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
