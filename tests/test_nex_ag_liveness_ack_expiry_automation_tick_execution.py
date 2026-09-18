from __future__ import annotations

from typing import Any

import nex_ag.liveness_ack_expiry_automation as automation
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateStore,
    build_operator_review_liveness_ack_state_record,
)


def expired_state(state_id: str = "ack-tick-0824") -> dict[str, Any]:
    return build_operator_review_liveness_ack_state_record(
        ack_state_id=state_id,
        acknowledgement_key=f"nex-ag:{state_id}:stale",
        service_id="nex-ag",
        worker_id="ag-dispatch-execution-daemon",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={"operator_type": "service", "operator_id": "test-0824"},
        reason_codes=["tick_execution_test"],
        requested_ttl_seconds=300,
        suppressed_until="2026-09-17T01:30:00Z",
        created_at="2026-09-17T01:00:00Z",
        updated_at="2026-09-17T01:00:00Z",
    )


def enabled_policy() -> dict[str, Any]:
    return automation.build_liveness_ack_expiry_automation_policy(
        {automation.ACK_EXPIRY_AUTOMATION_ENABLED_ENV: "1"}
    )


def test_tick_once_disabled_does_not_query_or_mutate() -> None:
    class FailingStore:
        def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
            raise AssertionError("disabled tick must not query")

    result = automation.run_liveness_ack_expiry_automation_tick_once(
        FailingStore(),
        request_id="req-disabled",
        executed_at="2026-09-17T02:00:00Z",
        environ={},
        confirm_tick=True,
    )

    assert result["tick_status"] == "BLOCKED"
    assert result["blocked_reason"] == "automation_disabled"
    assert result["worker_run"] is None
    assert result["mutation_performed"] is False


def test_tick_once_requires_confirmation_without_mutating() -> None:
    store = OperatorReviewLivenessAckStateStore()
    store.save(expired_state())

    result = automation.run_liveness_ack_expiry_automation_tick_once(
        store,
        request_id="req-unconfirmed",
        policy=enabled_policy(),
        executed_at="2026-09-17T02:00:00Z",
    )

    assert result["tick_status"] == "BLOCKED"
    assert result["blocked_reason"] == "confirm_tick_required"
    assert result["planned_candidate_count"] == 1
    assert result["candidate_count"] == 0
    assert store.get("ack-tick-0824")["state_status"] == "SUPPRESSED"


def test_tick_once_confirmed_applies_reconciliation() -> None:
    store = OperatorReviewLivenessAckStateStore()
    store.save(expired_state())

    result = automation.run_liveness_ack_expiry_automation_tick_once(
        store,
        request_id="req-confirmed",
        trace_id="trace-0824",
        policy=enabled_policy(),
        executed_at="2026-09-17T02:00:00Z",
        confirm_tick=True,
    )

    assert result["tick_status"] == "COMPLETED"
    assert result["blocked_reason"] is None
    assert result["trace_id"] == "trace-0824"
    assert result["planned_candidate_count"] == 1
    assert result["candidate_count"] == 1
    assert result["applied_count"] == 1
    assert result["conflict_count"] == 0
    assert result["mutation_performed"] is True
    assert store.get("ack-tick-0824")["state_status"] == "EXPIRED"
    assert result["guardrails"]["execution_requeries_candidates"] is True


def test_tick_once_confirmed_idle_is_successful_noop() -> None:
    result = automation.run_liveness_ack_expiry_automation_tick_once(
        OperatorReviewLivenessAckStateStore(),
        request_id="req-idle",
        policy=enabled_policy(),
        executed_at="2026-09-17T02:00:00Z",
        confirm_tick=True,
    )

    assert result["tick_status"] == "COMPLETED"
    assert result["plan"]["plan_status"] == "IDLE"
    assert result["candidate_count"] == 0
    assert result["mutation_performed"] is False


def test_tick_once_reports_compare_and_set_conflict() -> None:
    class ConflictStore:
        def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
            return [expired_state("ack-conflict-0824")]

        def apply_expiry_reconciliation(
            self,
            *_args: Any,
            **_kwargs: Any,
        ) -> bool:
            return False

    result = automation.run_liveness_ack_expiry_automation_tick_once(
        ConflictStore(),
        request_id="req-conflict",
        policy=enabled_policy(),
        executed_at="2026-09-17T02:00:00Z",
        confirm_tick=True,
    )

    assert result["tick_status"] == "COMPLETED_WITH_CONFLICTS"
    assert result["candidate_count"] == 1
    assert result["applied_count"] == 0
    assert result["conflict_count"] == 1
    assert result["mutation_performed"] is False


def test_tick_once_id_is_deterministic() -> None:
    kwargs = {
        "request_id": "req-stable",
        "policy": enabled_policy(),
        "executed_at": "2026-09-17T02:00:00Z",
        "confirm_tick": True,
    }
    first = automation.run_liveness_ack_expiry_automation_tick_once(
        OperatorReviewLivenessAckStateStore(), **kwargs
    )
    second = automation.run_liveness_ack_expiry_automation_tick_once(
        OperatorReviewLivenessAckStateStore(), **kwargs
    )

    assert first["tick_id"] == second["tick_id"]
