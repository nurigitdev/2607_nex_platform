from __future__ import annotations

import json
from typing import Any

import pytest
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter

import nex_ag.liveness_ack_expiry_automation as automation
import nex_ag.liveness_ack_expiry_automation_cli as cli
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateError,
    OperatorReviewLivenessAckStateStore,
)


ENABLED_ENV = {automation.ACK_EXPIRY_AUTOMATION_ENABLED_ENV: "1"}
OBSERVED_AT = "2026-09-18T03:00:00Z"


def event_emitter() -> tuple[OperationalEventEmitter, InMemoryOperationalEventStore]:
    store = InMemoryOperationalEventStore()
    return OperationalEventEmitter(service_id="nex-ag", store=store), store


def test_event_details_are_aggregate_and_redacted() -> None:
    details = automation.build_liveness_ack_expiry_automation_event_details(
        result={
            "tick_id": "tick-0826",
            "tick_status": "COMPLETED_WITH_CONFLICTS",
            "plan": {"plan_status": "READY", "batch_limit": "10"},
            "planned_candidate_count": "2",
            "candidate_count": 2,
            "applied_count": 1,
            "conflict_count": 1,
            "skipped_count": None,
            "mutation_performed": True,
        }
    )

    assert details["tick_id"] == "tick-0826"
    assert details["batch_limit"] == 10
    assert details["planned_candidate_count"] == 2
    assert details["conflict_count"] == 1
    assert details["raw_comments_included"] is False
    assert details["raw_idempotency_keys_included"] is False


def test_event_details_defaults_and_failure_code() -> None:
    details = automation.build_liveness_ack_expiry_automation_event_details(
        error_code="ag.ack_expiry_automation_tick_failed"
    )

    assert details["tick_id"] is None
    assert details["candidate_count"] == 0
    assert details["failure_code"] == "ag.ack_expiry_automation_tick_failed"


def test_event_emitter_not_configured_is_safe_failure() -> None:
    result = automation.emit_liveness_ack_expiry_automation_event(
        None,
        event_name="started",
        request_id="req-0826",
    )

    assert result.ok is False
    assert result.error_code.endswith("emitter_not_configured")


@pytest.mark.parametrize(
    ("event_name", "event_type", "severity"),
    [
        ("started", automation.ACK_EXPIRY_AUTOMATION_EVENT_STARTED, "INFO"),
        ("completed", automation.ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED, "INFO"),
        ("blocked", automation.ACK_EXPIRY_AUTOMATION_EVENT_BLOCKED, "WARNING"),
        ("failed", automation.ACK_EXPIRY_AUTOMATION_EVENT_FAILED, "ERROR"),
    ],
)
def test_lifecycle_event_envelopes(
    event_name: str,
    event_type: str,
    severity: str,
) -> None:
    emitter, store = event_emitter()

    result = automation.emit_liveness_ack_expiry_automation_event(
        emitter,
        event_name=event_name,
        request_id="req-0826",
        trace_id="trace-0826",
        result={"tick_id": "tick-0826", "plan": {}},
        occurred_at=OBSERVED_AT,
    )

    assert result.ok is True
    assert result.event is not None
    assert result.event["event_type"] == event_type
    assert result.event["severity"] == severity
    assert result.event["subject_ref"]["id"] == "tick-0826"
    assert len(store.list_events(event_type=event_type)) == 1


def test_lifecycle_event_rejects_unknown_name() -> None:
    emitter, _store = event_emitter()

    with pytest.raises(ValueError, match="Unsupported acknowledgement expiry event"):
        automation.emit_liveness_ack_expiry_automation_event(
            emitter,
            event_name="unknown",
            request_id="req-0826",
        )


def test_cli_confirmed_tick_emits_started_and_completed() -> None:
    emitter, store = event_emitter()

    result = cli.execute_liveness_ack_expiry_automation_cli(
        OperatorReviewLivenessAckStateStore(),
        action="run_once",
        environ=ENABLED_ENV,
        request_id="req-completed-0826",
        confirm_tick=True,
        observed_at=OBSERVED_AT,
        lifecycle_emitter=emitter,
    )

    assert [event["ok"] for event in result["lifecycle_events"]] == [True, True]
    assert [event["event_type"] for event in result["lifecycle_events"]] == [
        automation.ACK_EXPIRY_AUTOMATION_EVENT_STARTED,
        automation.ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED,
    ]
    assert {event["event_type"] for event in store.list_events(limit=10)} == {
        automation.ACK_EXPIRY_AUTOMATION_EVENT_STARTED,
        automation.ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED,
    }


def test_cli_unconfirmed_tick_emits_started_and_blocked() -> None:
    emitter, store = event_emitter()

    result = cli.execute_liveness_ack_expiry_automation_cli(
        OperatorReviewLivenessAckStateStore(),
        action="run_once",
        environ=ENABLED_ENV,
        request_id="req-blocked-0826",
        observed_at=OBSERVED_AT,
        lifecycle_emitter=emitter,
    )

    assert result["result_status"] == "BLOCKED"
    assert len(
        store.list_events(event_type=automation.ACK_EXPIRY_AUTOMATION_EVENT_BLOCKED)
    ) == 1


def test_cli_failure_emits_safe_failure_and_reraises() -> None:
    class BrokenStore:
        def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
            raise OperatorReviewLivenessAckStateError(
                "database contains private detail",
                error_code="ag.operator_review_liveness_ack_state_store_unavailable",
                status_code=503,
            )

    emitter, store = event_emitter()

    with pytest.raises(OperatorReviewLivenessAckStateError):
        cli.execute_liveness_ack_expiry_automation_cli(
            BrokenStore(),
            action="run_once",
            environ=ENABLED_ENV,
            request_id="req-failed-0826",
            confirm_tick=True,
            observed_at=OBSERVED_AT,
            lifecycle_emitter=emitter,
        )

    failure = store.list_events(
        event_type=automation.ACK_EXPIRY_AUTOMATION_EVENT_FAILED
    )[0]
    serialized = json.dumps(failure)
    assert failure["details"]["failure_code"].endswith("store_unavailable")
    assert "database contains private detail" not in serialized


def test_cli_failure_uses_generic_code_for_untyped_error() -> None:
    class BrokenStore:
        def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("private runtime detail")

    emitter, store = event_emitter()

    with pytest.raises(RuntimeError):
        cli.execute_liveness_ack_expiry_automation_cli(
            BrokenStore(),
            action="run_once",
            environ=ENABLED_ENV,
            confirm_tick=True,
            observed_at=OBSERVED_AT,
            lifecycle_emitter=emitter,
        )

    failure = store.list_events(
        event_type=automation.ACK_EXPIRY_AUTOMATION_EVENT_FAILED
    )[0]
    assert failure["details"]["failure_code"] == (
        "ag.ack_expiry_automation_tick_failed"
    )


def test_runtime_lifecycle_emitter_uses_shared_engine() -> None:
    engine = object()
    session_factory = object()

    emitter = cli.build_liveness_ack_expiry_automation_lifecycle_emitter(
        engine,
        session_factory_builder=lambda actual: session_factory
        if actual is engine
        else None,
    )

    assert emitter.service_id == "nex-ag"
    assert emitter.store._session_factory is session_factory
