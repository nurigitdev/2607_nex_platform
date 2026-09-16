from __future__ import annotations

from typing import Any

import nex_ag.operations as operations
from nex_ag.operator_review_dispatch_execution import (
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
)
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateStore,
    build_operator_review_liveness_ack_state_record,
)
from nex_runtime import IDLE, InMemoryWorkerHeartbeatStore, build_worker_heartbeat


def ack_state(
    *,
    state_status: str = "SUPPRESSED",
    suppressed_until: str | None = "2020-01-01T00:00:00Z",
) -> dict[str, Any]:
    return build_operator_review_liveness_ack_state_record(
        ack_state_id="ack-expiry-overlay",
        acknowledgement_key="nex-ag:ag-dispatch-execution-daemon:stale",
        service_id="nex-ag",
        worker_id="ag-dispatch-execution-daemon",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status=state_status,
        operator_ref={"operator_type": "user", "operator_id": "employee-1"},
        reason_codes=["planned-maintenance"],
        requested_ttl_seconds=1800,
        suppressed_until=suppressed_until,
        created_at="2019-01-01T00:00:00Z",
        updated_at="2019-01-01T00:00:00Z",
    )


def stale_heartbeat_store() -> InMemoryWorkerHeartbeatStore:
    store = InMemoryWorkerHeartbeatStore()
    store.upsert_heartbeat(
        build_worker_heartbeat(
            service_id=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
            worker_id="ag-dispatch-execution-daemon",
            worker_type=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
            status=IDLE,
            active_job_id=None,
            started_at="2019-01-01T00:00:00Z",
            last_seen_at="2020-01-01T00:00:00Z",
        )
    )
    return store


def test_expiry_reconciliation_overlay_status_matrix() -> None:
    pending = operations._operator_review_liveness_ack_expiry_reconciliation_overlay(
        {"state_status": "SUPPRESSED"},
        effective_status={"effective_state_status": "EXPIRED"},
    )
    reconciled = (
        operations._operator_review_liveness_ack_expiry_reconciliation_overlay(
            {"state_status": "EXPIRED"},
            effective_status={"effective_state_status": "EXPIRED"},
        )
    )
    not_due = operations._operator_review_liveness_ack_expiry_reconciliation_overlay(
        {"state_status": "SUPPRESSED"},
        effective_status={"effective_state_status": "SUPPRESSED"},
    )
    missing = operations._operator_review_liveness_ack_expiry_reconciliation_overlay(
        None,
        effective_status=None,
    )

    assert pending["reconciliation_status"] == "PENDING"
    assert pending["reconciliation_pending"] is True
    assert pending["state_mutated"] is False
    assert reconciled["reconciliation_status"] == "RECONCILED"
    assert not_due["reconciliation_status"] == "NOT_DUE"
    assert missing["reconciliation_status"] == "NOT_APPLICABLE"
    assert pending["redaction"]["raw_payloads_included"] is False


def test_expiry_reconciliation_is_visible_in_dashboard_and_issue_signal(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEX_AG_DISPATCH_DAEMON_ENABLED", "1")
    ack_store = OperatorReviewLivenessAckStateStore()
    ack_store.save(ack_state())
    heartbeat_store = stale_heartbeat_store()

    dashboard = operations.build_operations_dashboard_snapshot_projection(
        worker_heartbeat_stores={"nex-ag": heartbeat_store},
        operator_review_liveness_ack_state_store=ack_store,
        recent_limit=2,
    )
    issues = operations.build_operations_issue_candidate_projection(
        worker_heartbeat_stores={"nex-ag": heartbeat_store},
        operator_review_liveness_ack_state_store=ack_store,
        stale_after_seconds=60,
        recent_limit=2,
    )

    overlay = dashboard["operator_review_escalation_dispatches"]["daemon_recovery"][
        "acknowledgement_state_overlay"
    ]
    assert overlay["expiry_reconciliation"]["reconciliation_status"] == "PENDING"
    assert overlay["expiry_reconciliation"]["reconciliation_pending"] is True

    candidate = next(
        item
        for item in issues["issue_candidates"]
        if item["rule_id"]
        == "operator_review_dispatch_daemon_liveness_attention_required.v1"
    )
    signal = candidate["signal"]["acknowledgement_state_overlay"][
        "expiry_reconciliation"
    ]
    assert signal["reconciliation_status"] == "PENDING"
    assert signal["reconciliation_pending"] is True
    assert signal["reconcile_path"].endswith("/reconcile-expired")
    assert signal["state_mutated"] is False


def test_expiry_reconciliation_overlay_reports_reconciled_state() -> None:
    ack_store = OperatorReviewLivenessAckStateStore()
    ack_store.save(ack_state(state_status="EXPIRED"))
    liveness = operations.build_operator_review_escalation_dispatch_daemon_liveness_projection(
        worker_heartbeat_stores={"nex-ag": stale_heartbeat_store()},
        checked_at="2026-09-17T02:00:00Z",
    )

    plan = operations.build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan(
        liveness,
        ack_state_store=ack_store,
        checked_at="2026-09-17T02:00:00Z",
    )

    reconciliation = plan["acknowledgement_state_overlay"][
        "expiry_reconciliation"
    ]
    assert reconciliation["reconciliation_status"] == "RECONCILED"
    assert reconciliation["reconciliation_pending"] is False


def test_expiry_signal_defaults_are_safe() -> None:
    signal = operations._operator_review_liveness_ack_expiry_signal(None)

    assert signal == {
        "reconciliation_status": None,
        "reconciliation_pending": False,
        "stored_state_status": None,
        "effective_state_status": None,
        "reconcile_path": None,
        "state_mutated": False,
    }
