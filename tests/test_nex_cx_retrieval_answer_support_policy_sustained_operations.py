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
from nex_cx.retrieval_answer_support_policy_sustained_operations import (
    DEFAULT_POLICY_PATH,
    OPERATIONS_PATH,
    WINDOW_EVENT_TYPE,
    OperationalPolicySustainedSource,
    PolicySustainedOperationsError,
    _cadence_projection,
    _ensure_window_open,
    _hash_ref,
    _operations_status,
    _required_text,
    _slo_checks,
    _window_projection,
    build_installed_policy_sustained_operations_source,
    load_policy_sustained_operations_policy,
    register_policy_sustained_operations_routes,
    validate_policy_sustained_operations_policy,
)
from nex_runtime import InMemoryOperationalEventStore
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_policy_cutover_operations import (
    FailingStore,
    _authorization,
    _emitter,
    _runtime_and_source,
    _unique_application,
)

NOW = datetime(2026, 11, 6, 14, 0, tzinfo=UTC)


def test_policy_is_integrity_bound_to_operator_continuation(tmp_path: Path) -> None:
    policy = _policy()
    assert validate_policy_sustained_operations_policy(policy) == policy
    assert policy["review_sample_interval"] == 12
    assert policy["source_review"]["decision_receipt_hash"].startswith("sha256:")

    for mutate in (
        lambda value: value.update(review_sample_interval=13),
        lambda value: value["source_review"].update(decision="REJECTED"),
        lambda value: value["safety"].update(production_cutover_permitted=True),
        lambda value: value["escalation_policy"].update(
            provider_failure="IGNORE"
        ),
    ):
        drift = deepcopy(policy)
        mutate(drift)
        _rehash(drift)
        with pytest.raises(PolicySustainedOperationsError):
            validate_policy_sustained_operations_policy(drift)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(PolicySustainedOperationsError):
        load_policy_sustained_operations_policy(malformed)
    with pytest.raises(PolicySustainedOperationsError):
        load_policy_sustained_operations_policy(tmp_path / "missing.json")


def test_sustained_window_reaches_review_cadence_without_stopping_runtime() -> None:
    events, runtime, _old_source = _runtime_and_source()
    source = _source(events, runtime)

    initial = source.snapshot(generated_at=NOW)
    assert initial["operations_status"] == "MONITORING"
    assert initial["cadence"]["remaining_review_samples"] == 12

    for index in range(1, 13):
        assert runtime.apply(**_unique_application(index))["status"] == "READY"

    snapshot = source.snapshot(generated_at=NOW)
    assert snapshot["operations_status"] == "OPERATOR_REVIEW_DUE"
    assert snapshot["health_status"] == "ATTENTION"
    assert snapshot["cadence"]["provider_samples_since_review"] == 12
    assert snapshot["cadence"]["operator_review_due"] is True
    assert snapshot["cadence"]["runtime_stopped"] is False
    assert snapshot["decisions"]["ready_count"] == 12
    assert snapshot["escalations"] == ["OPERATOR_REVIEW_REQUIRED"]
    assert all(snapshot["slo"]["checks"].values())
    assert "approved evidence directly" not in json.dumps(snapshot)

    assert runtime.apply(**_unique_application(13))["status"] == "READY"
    overrun = source.snapshot(generated_at=NOW)
    assert overrun["cadence"]["observation_overrun_count"] == 1
    assert overrun["operations_status"] == "OPERATOR_REVIEW_DUE"


def test_restart_recovers_same_sustained_window_and_projection() -> None:
    events, runtime, _old_source = _runtime_and_source()
    source = _source(events, runtime)
    runtime.apply(**_unique_application(1))
    expected = source.snapshot(generated_at=NOW)

    restarted = OperationalPolicySustainedSource(
        store=events,
        policy=_policy(),
        runtime_snapshot=runtime.snapshot,
    )
    assert restarted.snapshot(generated_at=NOW)["snapshot_hash"] == expected[
        "snapshot_hash"
    ]
    assert len(events.list_events(event_type=WINDOW_EVENT_TYPE)) == 1


@pytest.mark.parametrize(
    ("cutover_state", "expected"),
    [(ROLLED_BACK, "ROLLED_BACK"), (ROLLBACK_PENDING_REVIEW, "ROLLBACK_PENDING_REVIEW")],
)
def test_terminal_cutover_state_dominates_sustained_projection(
    cutover_state: str, expected: str
) -> None:
    events, runtime, _old_source = _runtime_and_source()
    source = _source(events, runtime)
    runtime._rollback("PROVIDER_ERROR", pending_review=cutover_state == ROLLBACK_PENDING_REVIEW)

    snapshot = source.snapshot(generated_at=NOW)
    assert snapshot["operations_status"] == expected
    assert snapshot["health_status"] == "DEGRADED"
    assert snapshot["escalations"] == ["ROLLBACK_STATE_DOMINANT"]


def test_escalation_order_is_fail_closed() -> None:
    baseline = {
        "window": {"window_state": "OPEN"},
        "state": {"cutover_state": ACTIVE},
        "decisions": {"fallback_count": 0},
        "progress": {"failed_count": 0},
        "runtime": {"installed": True},
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


def test_slo_and_cadence_projection_are_deterministic() -> None:
    cadence = _cadence_projection(
        {"provider_sample_count": 15}, review_sample_interval=12
    )
    assert cadence == {
        "review_sample_interval": 12,
        "provider_samples_since_review": 15,
        "remaining_review_samples": 0,
        "operator_review_due": True,
        "observation_overrun_count": 3,
        "runtime_stopped": False,
    }
    checks = _slo_checks(
        decisions={"e2e_p95_latency_ms": 20001, "fallback_count": 1},
        progress={
            "feedback_p95_latency_ms": 2001,
            "provider_p95_latency_ms": 15001,
            "failed_count": 1,
        },
        slo=_policy()["operational_slo"],
    )
    assert not any(checks.values())


def test_window_open_is_idempotent_and_binding_drift_fails_closed() -> None:
    events, runtime, _old_source = _runtime_and_source()
    source = _source(events, runtime)
    assert source.snapshot(generated_at=NOW)["window"]["window_state"] == "OPEN"
    _source(events, runtime)
    assert len(events.list_events(event_type=WINDOW_EVENT_TYPE)) == 1

    bad_runtime = lambda: {
        **runtime.snapshot(),
        "selected_policy_hash": "sha256:" + "0" * 64,
    }
    with pytest.raises(PolicySustainedOperationsError):
        build_installed_policy_sustained_operations_source(
            environ={},
            store=events,
            emitter=_emitter(events),
            runtime_snapshot=bad_runtime,
        )

    event_id = str(
        uuid5(
            NAMESPACE_URL,
            "cx-answer-support-policy-sustained-window:"
            f"{_policy()['sustained_window_id']}",
        )
    )
    existing = events.get_event(event_id)
    assert existing is not None
    existing["details"]["window_state"] = "CLOSED"
    drifted = InMemoryOperationalEventStore(events={event_id: existing})
    with pytest.raises(PolicySustainedOperationsError):
        _ensure_window_open(
            emitter=_emitter(drifted),
            store=drifted,
            policy=_policy(),
            runtime=runtime.snapshot(),
        )


def test_window_recovery_terminal_attempt_and_missing_persistence_fail_closed() -> None:
    events, runtime, _old_source = _runtime_and_source()
    runtime._rollback("PROVIDER_ERROR", pending_review=False)
    terminal_source = build_installed_policy_sustained_operations_source(
        environ={},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=runtime.snapshot,
    )
    assert terminal_source.snapshot(generated_at=NOW)["operations_status"] == ROLLED_BACK
    with pytest.raises(PolicySustainedOperationsError):
        _ensure_window_open(
            emitter=_emitter(events),
            store=events,
            policy=_policy(),
            runtime=runtime.snapshot(),
        )

    class MissingRecoveryStore(InMemoryOperationalEventStore):
        def get_event(self, event_id: str):
            return self.events.get(f"missing-{event_id}")

    missing = MissingRecoveryStore()
    active_runtime = {**runtime.snapshot(), "cutover_state": ACTIVE}
    with pytest.raises(PolicySustainedOperationsError) as raised:
        _ensure_window_open(
            emitter=_emitter(missing),
            store=missing,
            policy=_policy(),
            runtime=active_runtime,
        )
    assert raised.value.status_code == 503


def test_disabled_source_failure_and_naive_clock_are_explicit() -> None:
    events = InMemoryOperationalEventStore()
    source = build_installed_policy_sustained_operations_source(
        environ={},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=lambda: None,
    )
    assert source.snapshot(generated_at=NOW)["operations_status"] == "DISABLED"
    with pytest.raises(PolicySustainedOperationsError):
        source.snapshot(generated_at=datetime(2026, 11, 6))  # noqa: DTZ001

    failing = OperationalPolicySustainedSource(
        store=FailingStore(),  # type: ignore[arg-type]
        policy=_policy(),
        runtime_snapshot=lambda: None,
    )
    with pytest.raises(PolicySustainedOperationsError) as raised:
        failing.snapshot()
    assert raised.value.status_code == 503
    assert raised.value.retryable is True


def test_operations_route_is_ag_scope_protected_and_redacted() -> None:
    events, runtime, _old_source = _runtime_and_source()
    source = _source(events, runtime)
    runtime.apply(**_unique_application(1))
    app = FastAPI()
    register_policy_sustained_operations_routes(app, source=source)
    client = TestClient(app)

    assert client.get(OPERATIONS_PATH).status_code == 401
    assert (
        client.get(
            OPERATIONS_PATH, headers={"Authorization": _authorization("nex-ae-api")}
        ).status_code
        == 403
    )
    response = client.get(OPERATIONS_PATH, headers={"Authorization": _authorization()})
    assert response.status_code == 200
    assert response.json()["cadence"]["provider_samples_since_review"] == 1
    assert "approved evidence directly" not in response.text

    unavailable_app = FastAPI()
    register_policy_sustained_operations_routes(
        unavailable_app,
        source=OperationalPolicySustainedSource(
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
            {"created_at": "2026-11-06T10:00:00Z", "details": "bad"},
            {"created_at": "2026-11-06T10:01:00Z", "details": {"window_id": "other"}},
        ],
        policy,
    )
    assert window["window_state"] == "NOT_OPENED"

    drift = _policy()
    drift.pop("sustained_window_id")
    _rehash(drift)
    with pytest.raises(PolicySustainedOperationsError):
        validate_policy_sustained_operations_policy(drift)

    for call in (
        lambda: _required_text(""),
        lambda: _hash_ref(None),
        lambda: _hash_ref("bad"),
    ):
        with pytest.raises(PolicySustainedOperationsError):
            call()


def _source(events, runtime) -> OperationalPolicySustainedSource:
    return build_installed_policy_sustained_operations_source(
        environ={},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=runtime.snapshot,
    )


def _policy() -> dict[str, Any]:
    return json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))


def _rehash(policy: dict[str, Any]) -> None:
    policy.pop("policy_hash", None)
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
