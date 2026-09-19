from __future__ import annotations

import json
from typing import Any

import pytest

import nex_ag.recovery_notification_delivery as delivery
from nex_ag.operator_review_cases import (
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
from nex_ag.recovery_notification_policy import build_recovery_notification_plan


EXECUTED_AT = "2026-09-19T04:00:00Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _plan() -> dict[str, Any]:
    return build_recovery_notification_plan(
        {
            "projection_schema_version": "recovery-plan.v1",
            "summary": {"liveness_status": "STALE"},
            "daemon_identity": {
                "service_id": "nex-ag",
                "worker_id": "ag-dispatch-execution-daemon",
            },
            "recommended_actions": [{"severity": "ERROR"}],
        },
        environ={"NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED": "1"},
        evaluated_at=EXECUTED_AT,
    )


def _case() -> dict[str, Any]:
    return {
        "case_id": "case-0847",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
    }


def _escalation() -> dict[str, Any]:
    return {
        "escalation_schema_version": "ag_operator_review_escalation.v1",
        "escalation_id": "escalation-0847",
        "candidate_id": "candidate-0847",
        "case_id": "case-0847",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "trace_id": TRACE_ID,
        "request_id": "request-0847",
        "operator_ref": {"operator_type": "service", "operator_id": "nex-ag"},
        "assignment_ref": {},
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "sla_state": "WARNING",
        "reason_codes": ["daemon_stale"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
        "recommended_actions": ["inspect_dispatch_daemon"],
        "action_comment_hash": None,
        "action_comment_preview": None,
        "snoozed_until": None,
        "metadata": {},
        "created_at": EXECUTED_AT,
        "updated_at": EXECUTED_AT,
        "closed_at": None,
    }


def _service_with_delivery() -> tuple[
    OperatorReviewCaseService,
    OperatorReviewEscalationDispatchStore,
    str,
]:
    plan = _plan()
    admission = delivery.build_recovery_notification_delivery_admission(
        plan,
        _case(),
        _escalation(),
        admitted_at=EXECUTED_AT,
    )
    handoff = delivery.build_recovery_notification_dispatch_handoff(
        plan,
        admission,
        _escalation(),
        request_id="request-0847",
        trace_id=TRACE_ID,
        idempotency_key="idem-0847",
        created_at=EXECUTED_AT,
    )
    store = OperatorReviewEscalationDispatchStore()
    persisted = delivery.persist_recovery_notification_dispatch_handoff(
        handoff,
        store,
    )
    dispatch_id = persisted["dispatch_record"]["dispatch_id"]
    service = OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=OperatorReviewEscalationStore(),
        dispatch_store=store,
    )
    return service, store, dispatch_id


def test_mock_execution_requires_confirmation_without_mutation() -> None:
    service, store, dispatch_id = _service_with_delivery()

    result = delivery.run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0847-blocked",
        trace_id=TRACE_ID,
        executed_at=EXECUTED_AT,
    )

    assert result["execution_status"] == "BLOCKED"
    assert result["worker_run"]["blocked_reason"] == "confirm_run_required"
    assert store.get(dispatch_id)["dispatch_status"] == "PENDING"
    assert result["guardrails"]["batch_limit"] == 1
    assert result["guardrails"]["external_network_allowed"] is False


def test_mock_execution_targets_only_delivery_and_persists_result() -> None:
    service, store, dispatch_id = _service_with_delivery()
    unrelated = dict(store.get(dispatch_id) or {})
    unrelated["dispatch_id"] = "dispatch-unrelated-0847"
    store.save(unrelated)

    result = delivery.run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0847-execute",
        trace_id=TRACE_ID,
        confirm_run=True,
        executed_at=EXECUTED_AT,
    )

    assert result["delivery_execution_schema_version"] == (
        delivery.RECOVERY_NOTIFICATION_DELIVERY_EXECUTION_SCHEMA_VERSION
    )
    assert result["execution_status"] == "COMPLETED"
    assert result["worker_run"]["candidate_count"] == 1
    assert result["worker_run"]["succeeded_count"] == 1
    assert store.get(dispatch_id)["dispatch_status"] == "SUCCEEDED"
    assert store.get("dispatch-unrelated-0847")["dispatch_status"] == "PENDING"
    metadata = store.get(dispatch_id)["metadata"]["last_execution_result"]
    assert metadata["execution_status"] == "SUCCEEDED"
    assert metadata["provider_mode"] == "mock_first_only"
    assert "idem-0847" not in json.dumps(result)


def test_mock_execution_is_noop_after_delivery_completed() -> None:
    service, _store, dispatch_id = _service_with_delivery()
    first = delivery.run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0847-first",
        confirm_run=True,
        executed_at=EXECUTED_AT,
    )
    second = delivery.run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0847-second",
        confirm_run=True,
        executed_at="2026-09-19T04:01:00Z",
    )

    assert first["execution_status"] == "COMPLETED"
    assert second["execution_status"] == "NOOP"
    assert second["worker_run"]["candidate_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda record: record.update(metadata=None),
            "ag.recovery_notification_delivery_execution_metadata_invalid",
        ),
        (
            lambda record: record["metadata"].pop(
                "recovery_notification_delivery"
            ),
            "ag.recovery_notification_delivery_execution_marker_required",
        ),
        (
            lambda record: record.update(channel_type="NOTIFICATION"),
            "ag.recovery_notification_delivery_execution_mock_only",
        ),
    ],
)
def test_mock_execution_rejects_non_delivery_or_live_dispatch(
    mutation,
    error_code: str,
) -> None:
    service, store, dispatch_id = _service_with_delivery()
    record = dict(store.get(dispatch_id) or {})
    record["metadata"] = dict(record.get("metadata") or {})
    mutation(record)
    store.save(record)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.run_recovery_notification_delivery_mock_once(
            service,
            dispatch_id=dispatch_id,
            request_id="request-0847-invalid",
            confirm_run=True,
            executed_at=EXECUTED_AT,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        (
            "dispatch_id",
            " ",
            "ag.recovery_notification_delivery_dispatch_id_required",
        ),
        (
            "request_id",
            " ",
            "ag.recovery_notification_delivery_request_id_required",
        ),
        (
            "worker_id",
            " ",
            "ag.recovery_notification_delivery_worker_id_required",
        ),
    ],
)
def test_mock_execution_requires_identifiers(
    field: str,
    value: str,
    error_code: str,
) -> None:
    service, _store, dispatch_id = _service_with_delivery()
    kwargs = {
        "dispatch_id": dispatch_id,
        "request_id": "request-0847",
        "worker_id": "worker-0847",
    }
    kwargs[field] = value

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.run_recovery_notification_delivery_mock_once(
            service,
            **kwargs,
        )

    assert exc_info.value.error_code == error_code
