from __future__ import annotations

from typing import Any

import pytest

import nex_ag.liveness_ack_expiry_automation as automation
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateError,
    OperatorReviewLivenessAckStateStore,
    build_operator_review_liveness_ack_state_record,
)


def expired_state(state_id: str = "ack-plan-0823") -> dict[str, Any]:
    return build_operator_review_liveness_ack_state_record(
        ack_state_id=state_id,
        acknowledgement_key=f"nex-ag:{state_id}:stale",
        service_id="nex-ag",
        worker_id="ag-dispatch-execution-daemon",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={"operator_type": "service", "operator_id": "test-0823"},
        reason_codes=["tick_plan_test"],
        comment="must not appear in plan",
        idempotency_key="must-not-appear-in-plan",
        requested_ttl_seconds=300,
        suppressed_until="2026-09-17T01:30:00Z",
        created_at="2026-09-17T01:00:00Z",
        updated_at="2026-09-17T01:00:00Z",
    )


def enabled_policy(**overrides: object) -> dict[str, Any]:
    policy = automation.build_liveness_ack_expiry_automation_policy(
        {automation.ACK_EXPIRY_AUTOMATION_ENABLED_ENV: "1"}
    )
    policy.update(overrides)
    return policy


def test_tick_plan_disabled_does_not_query_store() -> None:
    class FailingStore:
        def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
            raise AssertionError("disabled plan must not query")

    plan = automation.build_liveness_ack_expiry_automation_tick_plan(
        FailingStore(),
        request_id="req-disabled",
        planned_at="2026-09-17T02:00:00Z",
        environ={},
    )

    assert plan["plan_status"] == "DISABLED"
    assert plan["candidate_count"] == 0
    assert plan["candidate_summaries"] == []
    assert plan["will_mutate"] is False


def test_tick_plan_ready_with_safe_candidate_summary() -> None:
    store = OperatorReviewLivenessAckStateStore()
    store.save(expired_state())

    plan = automation.build_liveness_ack_expiry_automation_tick_plan(
        store,
        request_id="req-ready",
        trace_id="trace-0823",
        policy=enabled_policy(batch_limit=10),
        planned_at="2026-09-17T02:00:00Z",
    )
    serialized = str(plan)

    assert plan["plan_status"] == "READY"
    assert plan["candidate_count"] == 1
    assert plan["trace_id"] == "trace-0823"
    assert plan["candidate_summaries"] == [
        {
            "ack_state_id": "ack-plan-0823",
            "service_id": "nex-ag",
            "worker_id": "ag-dispatch-execution-daemon",
            "liveness_status": "STALE",
            "state_status": "SUPPRESSED",
            "suppressed_until": "2026-09-17T01:30:00Z",
            "raw_comment_included": False,
            "raw_idempotency_key_included": False,
        }
    ]
    assert "must not appear in plan" not in serialized
    assert "must-not-appear-in-plan" not in serialized
    assert store.get("ack-plan-0823")["state_status"] == "SUPPRESSED"


def test_tick_plan_idle_when_no_candidates() -> None:
    plan = automation.build_liveness_ack_expiry_automation_tick_plan(
        OperatorReviewLivenessAckStateStore(),
        request_id="req-idle",
        policy=enabled_policy(),
        planned_at="2026-09-17T02:00:00Z",
    )

    assert plan["plan_status"] == "IDLE"
    assert plan["candidate_count"] == 0
    assert plan["trace_id"] is None


def test_tick_plan_is_deterministic_for_same_inputs() -> None:
    store = OperatorReviewLivenessAckStateStore()
    first = automation.build_liveness_ack_expiry_automation_tick_plan(
        store,
        request_id="req-stable",
        policy=enabled_policy(),
        planned_at="2026-09-17T02:00:00Z",
    )
    second = automation.build_liveness_ack_expiry_automation_tick_plan(
        store,
        request_id="req-stable",
        policy=enabled_policy(),
        planned_at="2026-09-17T02:00:00Z",
    )

    assert first["tick_plan_id"] == second["tick_plan_id"]


def test_tick_plan_rejects_invalid_timestamp() -> None:
    with pytest.raises(OperatorReviewLivenessAckStateError):
        automation.build_liveness_ack_expiry_automation_tick_plan(
            OperatorReviewLivenessAckStateStore(),
            request_id="req-invalid",
            policy=enabled_policy(),
            planned_at="not-a-time",
        )


def test_tick_plan_uses_current_time_when_omitted() -> None:
    plan = automation.build_liveness_ack_expiry_automation_tick_plan(
        OperatorReviewLivenessAckStateStore(),
        request_id="req-now",
        policy=enabled_policy(),
    )

    assert plan["planned_at"].endswith("Z")
