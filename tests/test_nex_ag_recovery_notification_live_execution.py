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
from nex_ag.operator_review_dispatch_execution import (
    MockDispatchProviderHttpTransport,
    build_dispatch_execution_provider_config,
)
from nex_ag.recovery_notification_operations import (
    _delivery_execution_projection,
    build_recovery_notification_delivery_operations_projection,
)
from nex_ag.recovery_notification_policy import build_recovery_notification_plan


EXECUTED_AT = "2026-09-19T07:00:00Z"


def live_config() -> dict[str, Any]:
    return build_dispatch_execution_provider_config(
        {
            "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "live_http",
            "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE": "1",
            "NEX_AG_NOTIFICATION_WEBHOOK_URL": "http://127.0.0.1:18555/notify",
            "NEX_AG_NOTIFICATION_SERVICE_TOKEN": "token-0855",
        }
    )


def service_with_live_delivery(
    *,
    channel_type: str = "NOTIFICATION",
    provider_profile: str = "notification-webhook-default",
) -> tuple[
    OperatorReviewCaseService,
    OperatorReviewEscalationDispatchStore,
    str,
]:
    plan = build_recovery_notification_plan(
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
    case = {
        "case_id": "case-0855",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
    }
    escalation = {
        "escalation_id": "escalation-0855",
        "case_id": "case-0855",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "reason_codes": ["daemon_stale"],
        "recommended_actions": ["inspect_dispatch_daemon"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
    }
    admitted = delivery.build_recovery_notification_delivery_admission(
        plan,
        case,
        escalation,
        channel_type=channel_type,
        provider_profile=provider_profile,
        admitted_at=EXECUTED_AT,
    )
    live = delivery.build_recovery_notification_live_admission(
        admitted,
        live_config(),
        confirm_live_delivery=True,
        admitted_at=EXECUTED_AT,
    )
    handoff = delivery.build_recovery_notification_dispatch_handoff(
        plan,
        admitted,
        escalation,
        request_id="request-0855",
        idempotency_key="idem-0855",
        created_at=EXECUTED_AT,
        live_admission=live,
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


def test_live_execution_requires_confirmation_without_transport_or_mutation() -> None:
    service, store, dispatch_id = service_with_live_delivery()

    result = delivery.run_recovery_notification_delivery_live_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0855-blocked",
        provider_config=live_config(),
        executed_at=EXECUTED_AT,
    )

    assert result["execution_status"] == "BLOCKED"
    assert result["worker_run"]["blocked_reason"] == "confirm_run_required"
    assert result["delivery"]["provider_invocation_performed"] is False
    assert store.get(dispatch_id)["dispatch_status"] == "PENDING"


def test_live_execution_targets_dispatch_persists_result_and_projects_it() -> None:
    service, store, dispatch_id = service_with_live_delivery()
    unrelated = dict(store.get(dispatch_id) or {})
    unrelated["dispatch_id"] = "dispatch-unrelated-0855"
    store.save(unrelated)

    result = delivery.run_recovery_notification_delivery_live_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0855-live",
        provider_config=live_config(),
        live_http_transport=MockDispatchProviderHttpTransport((202,)),
        confirm_run=True,
        executed_at=EXECUTED_AT,
    )

    assert result["live_execution_schema_version"] == (
        delivery.RECOVERY_NOTIFICATION_LIVE_EXECUTION_SCHEMA_VERSION
    )
    assert result["execution_status"] == "COMPLETED"
    assert result["worker_run"]["candidate_count"] == 1
    assert result["worker_run"]["succeeded_count"] == 1
    assert result["delivery"]["provider_invocation_performed"] is True
    assert store.get(dispatch_id)["dispatch_status"] == "SUCCEEDED"
    assert store.get("dispatch-unrelated-0855")["dispatch_status"] == "PENDING"
    metadata = store.get(dispatch_id)["metadata"]["last_execution_result"]
    assert metadata["provider_mode"] == "live_http"
    assert metadata["http_status_code"] == 202
    projection = build_recovery_notification_delivery_operations_projection(
        list(store.records.values())
    )
    item = next(
        item for item in projection["recent"] if item["dispatch_id"] == dispatch_id
    )
    assert item["execution"]["provider_mode"] == "live_http"
    assert item["execution"]["http_status_code"] == 202
    assert item["execution"]["provider_result_hash"]
    assert item["execution"]["response_body_hash"]
    serialized = json.dumps(result)
    assert "token-0855" not in serialized
    assert "127.0.0.1" not in serialized


def test_live_execution_is_noop_after_success() -> None:
    service, _store, dispatch_id = service_with_live_delivery()
    first = delivery.run_recovery_notification_delivery_live_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0855-first",
        provider_config=live_config(),
        live_http_transport=MockDispatchProviderHttpTransport(),
        confirm_run=True,
        executed_at=EXECUTED_AT,
    )
    second = delivery.run_recovery_notification_delivery_live_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0855-second",
        provider_config=live_config(),
        live_http_transport=MockDispatchProviderHttpTransport(),
        confirm_run=True,
        executed_at="2026-09-19T07:01:00Z",
    )

    assert first["execution_status"] == "COMPLETED"
    assert second["execution_status"] == "NOOP"
    assert second["delivery"]["provider_invocation_performed"] is False


def test_live_execution_persists_retryable_result() -> None:
    service, store, dispatch_id = service_with_live_delivery()

    result = delivery.run_recovery_notification_delivery_live_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0855-retry",
        provider_config=live_config(),
        live_http_transport=MockDispatchProviderHttpTransport((503, 503, 503)),
        confirm_run=True,
        executed_at=EXECUTED_AT,
    )

    assert result["execution_status"] == "COMPLETED"
    assert result["worker_run"]["retry_wait_count"] == 1
    assert store.get(dispatch_id)["dispatch_status"] == "RETRY_WAIT"
    metadata = store.get(dispatch_id)["metadata"]["last_execution_result"]
    assert metadata["execution_status"] == "RETRY_WAIT"
    assert metadata["retryable"] is True


@pytest.mark.parametrize(
    ("field", "error_code"),
    [
        (
            "dispatch_id",
            "ag.recovery_notification_live_execution_dispatch_id_required",
        ),
        (
            "request_id",
            "ag.recovery_notification_live_execution_request_id_required",
        ),
        (
            "worker_id",
            "ag.recovery_notification_live_execution_worker_id_required",
        ),
    ],
)
def test_live_execution_requires_identifiers(field: str, error_code: str) -> None:
    service, _store, dispatch_id = service_with_live_delivery()
    kwargs = {
        "dispatch_id": dispatch_id,
        "request_id": "request-0855",
        "worker_id": "worker-0855",
    }
    kwargs[field] = " "

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.run_recovery_notification_delivery_live_once(
            service,
            provider_config=live_config(),
            **kwargs,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda record: record.update(metadata=None),
            "ag.recovery_notification_live_execution_metadata_invalid",
        ),
        (
            lambda record: record["metadata"].pop(
                "recovery_notification_delivery"
            ),
            "ag.recovery_notification_live_execution_marker_required",
        ),
        (
            lambda record: record.update(channel_type="MOCK"),
            "ag.recovery_notification_live_execution_channel_unsupported",
        ),
        (
            lambda record: record.update(provider_profile=None),
            "ag.recovery_notification_live_execution_profile_required",
        ),
    ],
)
def test_live_execution_rejects_invalid_dispatch(mutation, error_code: str) -> None:
    service, store, dispatch_id = service_with_live_delivery()
    record = dict(store.get(dispatch_id) or {})
    record["metadata"] = dict(record.get("metadata") or {})
    mutation(record)
    store.save(record)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.run_recovery_notification_delivery_live_once(
            service,
            dispatch_id=dispatch_id,
            request_id="request-0855-invalid",
            provider_config=live_config(),
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda config: config.update(effective_provider_mode="mock_http"),
            "ag.recovery_notification_live_execution_not_enabled",
        ),
        (
            lambda config: config["endpoints"]["notification"].update(
                configured=False
            ),
            "ag.recovery_notification_live_execution_endpoint_required",
        ),
        (
            lambda config: config["profiles"]["live_readiness"].pop(
                "notification-webhook-default"
            ),
            "ag.recovery_notification_live_execution_profile_unknown",
        ),
        (
            lambda config: config["profiles"]["live_readiness"][
                "notification-webhook-default"
            ].update(channel_types=["EMAIL"]),
            "ag.recovery_notification_live_execution_profile_mismatch",
        ),
    ],
)
def test_live_execution_rechecks_runtime_configuration(
    mutation,
    error_code: str,
) -> None:
    service, _store, dispatch_id = service_with_live_delivery()
    config = live_config()
    mutation(config)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.run_recovery_notification_delivery_live_once(
            service,
            dispatch_id=dispatch_id,
            request_id="request-0855-config",
            provider_config=config,
        )

    assert exc_info.value.error_code == error_code


def test_live_execution_requires_injected_transport_when_confirmed() -> None:
    service, _store, dispatch_id = service_with_live_delivery()

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.run_recovery_notification_delivery_live_once(
            service,
            dispatch_id=dispatch_id,
            request_id="request-0855-no-transport",
            provider_config=live_config(),
            confirm_run=True,
        )

    assert exc_info.value.error_code == (
        "ag.recovery_notification_live_execution_transport_required"
    )
    assert exc_info.value.status_code == 503


def test_live_execution_requires_config_object_and_projection_handles_gaps() -> None:
    service, _store, dispatch_id = service_with_live_delivery()
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.run_recovery_notification_delivery_live_once(
            service,
            dispatch_id=dispatch_id,
            request_id="request-0855-config-shape",
            provider_config=None,  # type: ignore[arg-type]
        )
    assert exc_info.value.error_code == (
        "ag.recovery_notification_live_execution_config_invalid"
    )

    assert _delivery_execution_projection({"metadata": None}) is None
    assert build_recovery_notification_delivery_operations_projection(
        [{"metadata": None}]
    )["recent"] == []
    assert build_recovery_notification_delivery_operations_projection(
        [
            {
                "dispatch_id": "projection-0855",
                "metadata": {"recovery_notification_delivery": {}},
            }
        ]
    )["recent"][0]["execution"] is None
