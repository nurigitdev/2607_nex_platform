from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    OperationalEventError,
)

import nex_ag.liveness_ack_expiry_automation as automation
import nex_ag.liveness_ack_expiry_automation_operations as operations
import nex_ag.operations as ag_operations


ENABLED_ENV = {automation.ACK_EXPIRY_AUTOMATION_ENABLED_ENV: "1"}


def event_store_with(event_name: str) -> InMemoryOperationalEventStore:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=store)
    automation.emit_liveness_ack_expiry_automation_event(
        emitter,
        event_name=event_name,
        request_id=f"req-{event_name}-0827",
        trace_id="trace-0827",
        result={
            "tick_id": f"tick-{event_name}-0827",
            "tick_status": event_name.upper(),
            "plan": {"plan_status": "READY", "batch_limit": 10},
            "candidate_count": 2,
            "applied_count": 1,
            "conflict_count": 1,
            "mutation_performed": True,
        },
        error_code="ag.safe.failure" if event_name == "failed" else None,
        occurred_at=f"2026-09-18T04:00:0{len(store.events)}Z",
    )
    return store


def test_projection_disabled_without_event_source_is_expected_state() -> None:
    projection = operations.build_liveness_ack_expiry_automation_operations_projection(
        None,
        environ={},
    )

    assert projection["projection_status"] == "READY"
    assert projection["automation_status"] == "DISABLED"
    assert projection["source_statuses"]["nex-ag"]["status"] == "NOT_CONFIGURED"
    assert projection["summary"]["requires_operator_action"] is False


def test_projection_enabled_waits_for_first_run() -> None:
    projection = operations.build_liveness_ack_expiry_automation_operations_projection(
        InMemoryOperationalEventStore(),
        environ=ENABLED_ENV,
        request_trace_id="trace-0827",
    )

    assert projection["automation_status"] == "WAITING_FIRST_RUN"
    assert projection["request_trace_id"] == "trace-0827"
    assert projection["scheduler"]["owner"] == "external_scheduler"


def test_projection_completed_event_is_healthy_and_redacted() -> None:
    projection = operations.build_liveness_ack_expiry_automation_operations_projection(
        event_store_with("completed"),
        environ=ENABLED_ENV,
    )
    serialized = json.dumps(projection)

    assert projection["automation_status"] == "HEALTHY"
    assert projection["summary"]["event_count"] == 1
    assert projection["summary"]["by_lifecycle"]["completed"] == 1
    assert projection["recent_events"][0]["candidate_count"] == 2
    assert "private raw comment" not in serialized
    assert "postgresql://" not in serialized


def test_projection_blocked_and_failed_events_require_attention() -> None:
    blocked = operations.build_liveness_ack_expiry_automation_operations_projection(
        event_store_with("blocked"),
        environ=ENABLED_ENV,
    )
    failed = operations.build_liveness_ack_expiry_automation_operations_projection(
        event_store_with("failed"),
        environ=ENABLED_ENV,
    )

    assert blocked["automation_status"] == "ATTENTION"
    assert blocked["summary"]["requires_operator_action"] is True
    assert failed["automation_status"] == "DEGRADED"
    assert failed["projection_status"] == "DEGRADED"


def test_projection_started_event_is_running() -> None:
    projection = operations.build_liveness_ack_expiry_automation_operations_projection(
        event_store_with("started"),
        environ=ENABLED_ENV,
    )

    assert projection["automation_status"] == "RUNNING"


def test_projection_handles_event_source_failure_without_detail_leak() -> None:
    class BrokenStore:
        def list_events(self, **_kwargs: Any) -> list[dict[str, Any]]:
            raise OperationalEventError(
                error_code="operational_event.store_unavailable",
                detail="postgresql://private-secret",
                status_code=503,
            )

    projection = operations.build_liveness_ack_expiry_automation_operations_projection(
        BrokenStore(),
        environ=ENABLED_ENV,
    )

    assert projection["automation_status"] == "SOURCE_UNAVAILABLE"
    assert projection["projection_status"] == "DEGRADED"
    assert "private-secret" not in json.dumps(projection)


def test_projection_defensively_normalizes_bad_event_counts() -> None:
    event = event_store_with("completed").list_events(limit=1)[0]
    event["details"]["candidate_count"] = "bad"
    event["details"]["applied_count"] = -3

    class StaticStore:
        def list_events(self, *, event_type: str, **_kwargs: Any) -> list[dict[str, Any]]:
            return [event] if event["event_type"] == event_type else []

    projection = operations.build_liveness_ack_expiry_automation_operations_projection(
        StaticStore(),
        environ=ENABLED_ENV,
    )

    assert projection["recent_events"][0]["candidate_count"] == 0
    assert projection["recent_events"][0]["applied_count"] == 0
    assert operations._event_counts([{"event_type": "unknown"}]) == {
        "started": 0,
        "completed": 0,
        "blocked": 0,
        "failed": 0,
    }


def test_dashboard_includes_automation_projection(monkeypatch: Any) -> None:
    monkeypatch.setenv(automation.ACK_EXPIRY_AUTOMATION_ENABLED_ENV, "1")
    store = event_store_with("completed")

    dashboard = ag_operations.build_operations_dashboard_snapshot_projection(
        event_store=store,
        recent_limit=5,
    )
    projection = dashboard["operator_review_escalation_dispatches"][
        "ack_expiry_automation"
    ]

    assert projection["automation_status"] == "HEALTHY"
    assert projection["source_statuses"]["nex-ag"]["event_count"] == 1


def test_dashboard_contract_and_canonical_fixture_include_projection() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (
            root
            / "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    fixture = json.loads(
        (
            root
            / "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json"
        ).read_text(encoding="utf-8")
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(fixture)
    assert fixture["operator_review_escalation_dispatches"][
        "ack_expiry_automation"
    ]["automation_status"] == "DISABLED"
