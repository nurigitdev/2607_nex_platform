from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

import nex_ag.recovery_notification_delivery as delivery
from nex_ag.operator_review_dispatch_execution import (
    build_dispatch_execution_provider_config,
)


ADMITTED_AT = "2026-09-19T05:00:00Z"


def base_admission(
    *,
    channel_type: str = "NOTIFICATION",
    provider_profile: str = "notification-webhook-default",
) -> dict[str, Any]:
    return {
        "delivery_admission_schema_version": (
            delivery.RECOVERY_NOTIFICATION_DELIVERY_ADMISSION_SCHEMA_VERSION
        ),
        "admission_status": "ADMITTED",
        "notification_plan_id": "plan-0852",
        "case_id": "case-0852",
        "escalation_id": "escalation-0852",
        "target": {
            "target_service": "nex-ag",
            "target_kind": "dispatch_daemon",
            "target_id": "ag-dispatch-execution-daemon",
        },
        "delivery": {
            "channel_type": channel_type,
            "provider_profile": provider_profile,
            "dispatch_intent": "NOTIFY_OPERATOR",
        },
    }


def live_config() -> dict[str, Any]:
    return build_dispatch_execution_provider_config(
        {
            "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "live_http",
            "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE": "1",
            "NEX_AG_NOTIFICATION_WEBHOOK_URL": "http://127.0.0.1:18552/notify",
            "NEX_AG_NOTIFICATION_SERVICE_TOKEN": "test-token-0852",
        }
    )


@pytest.mark.parametrize(
    ("channel_type", "provider_profile"),
    [
        ("NOTIFICATION", "notification-webhook-default"),
        ("WEBHOOK", "notification-webhook-default"),
        ("EMAIL", "email-notification-default"),
    ],
)
def test_live_admission_accepts_ready_notification_channels(
    channel_type: str,
    provider_profile: str,
) -> None:
    result = delivery.build_recovery_notification_live_admission(
        base_admission(
            channel_type=channel_type,
            provider_profile=provider_profile,
        ),
        live_config(),
        confirm_live_delivery=True,
        admitted_at=ADMITTED_AT,
    )

    assert result["live_admission_schema_version"] == (
        delivery.RECOVERY_NOTIFICATION_LIVE_ADMISSION_SCHEMA_VERSION
    )
    assert result["admission_status"] == "ADMITTED"
    assert result["delivery"] == {
        "channel_type": channel_type,
        "provider_profile": provider_profile,
        "provider_mode": "live_http",
        "dispatch_intent": "NOTIFY_OPERATOR",
    }
    assert result["readiness"] == {
        "live_network_calls_enabled": True,
        "endpoint_configured": True,
        "token_configured": True,
        "explicit_confirmation": True,
    }
    assert result["admitted_at"] == ADMITTED_AT
    serialized = str(result)
    assert "127.0.0.1" not in serialized
    assert "test-token-0852" not in serialized


def test_live_admission_allows_tokenless_loopback_readiness() -> None:
    config = live_config()
    config["endpoints"]["notification"]["token_configured"] = False

    result = delivery.build_recovery_notification_live_admission(
        base_admission(),
        config,
        confirm_live_delivery=True,
        admitted_at=ADMITTED_AT,
    )

    assert result["readiness"]["token_configured"] is False
    assert result["guardrails"]["provider_secret_included"] is False


@pytest.mark.parametrize(
    ("admission", "config", "error_code"),
    [
        (None, {}, "ag.recovery_notification_live_admission_invalid"),
        ({}, None, "ag.recovery_notification_live_provider_config_invalid"),
    ],
)
def test_live_admission_requires_object_inputs(
    admission: object,
    config: object,
    error_code: str,
) -> None:
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_live_admission(
            admission,  # type: ignore[arg-type]
            config,  # type: ignore[arg-type]
            confirm_live_delivery=True,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(
            delivery_admission_schema_version="unsupported"
        ),
        lambda value: value.update(admission_status="REJECTED"),
    ],
)
def test_live_admission_requires_admitted_s85_contract(mutation) -> None:
    admission = base_admission()
    mutation(admission)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_live_admission(
            admission,
            live_config(),
            confirm_live_delivery=True,
        )

    assert exc_info.value.error_code == (
        "ag.recovery_notification_live_base_admission_required"
    )
    assert exc_info.value.status_code == 409


@pytest.mark.parametrize("channel_type", ["MOCK", "INCIDENT"])
def test_live_admission_rejects_non_notification_channels(
    channel_type: str,
) -> None:
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_live_admission(
            base_admission(channel_type=channel_type),
            live_config(),
            confirm_live_delivery=True,
        )

    assert exc_info.value.error_code == (
        "ag.recovery_notification_live_channel_unsupported"
    )


def test_live_admission_requires_explicit_confirmation() -> None:
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_live_admission(
            base_admission(),
            live_config(),
        )

    assert exc_info.value.error_code == (
        "ag.recovery_notification_live_confirmation_required"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(configured_provider_mode="mock_http"),
        lambda value: value.update(effective_provider_mode="mock_http"),
        lambda value: value.update(live_network_calls_enabled=False),
    ],
)
def test_live_admission_requires_fully_enabled_live_http(mutation) -> None:
    config = live_config()
    mutation(config)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_live_admission(
            base_admission(),
            config,
            confirm_live_delivery=True,
        )

    assert exc_info.value.error_code == (
        "ag.recovery_notification_live_provider_not_enabled"
    )


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda value: value.update(endpoints=None),
            "ag.recovery_notification_live_endpoint_config_invalid",
        ),
        (
            lambda value: value["endpoints"].update(notification=None),
            "ag.recovery_notification_live_endpoint_config_invalid",
        ),
        (
            lambda value: value["endpoints"]["notification"].update(
                configured=False
            ),
            "ag.recovery_notification_live_endpoint_required",
        ),
        (
            lambda value: value.update(profiles=None),
            "ag.recovery_notification_live_provider_profile_unknown",
        ),
        (
            lambda value: value["profiles"].update(live_readiness=None),
            "ag.recovery_notification_live_provider_profile_unknown",
        ),
        (
            lambda value: value["profiles"]["live_readiness"].pop(
                "notification-webhook-default"
            ),
            "ag.recovery_notification_live_provider_profile_unknown",
        ),
    ],
)
def test_live_admission_requires_safe_endpoint_and_profile_shape(
    mutation,
    error_code: str,
) -> None:
    config = live_config()
    mutation(config)

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_live_admission(
            base_admission(),
            config,
            confirm_live_delivery=True,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize("channel_types", [None, ["EMAIL"]])
def test_live_admission_rejects_profile_channel_mismatch(channel_types) -> None:
    config = deepcopy(live_config())
    profile = config["profiles"]["live_readiness"][
        "notification-webhook-default"
    ]
    profile["channel_types"] = channel_types

    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery.build_recovery_notification_live_admission(
            base_admission(),
            config,
            confirm_live_delivery=True,
        )

    assert exc_info.value.error_code == (
        "ag.recovery_notification_live_profile_channel_mismatch"
    )


def test_live_admission_rejects_invalid_selection_and_target() -> None:
    invalid_selection = base_admission()
    invalid_selection["delivery"] = None
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as selection:
        delivery.build_recovery_notification_live_admission(
            invalid_selection,
            live_config(),
            confirm_live_delivery=True,
        )
    assert selection.value.error_code == (
        "ag.recovery_notification_live_selection_invalid"
    )

    invalid_target = base_admission()
    invalid_target["target"] = None
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as target:
        delivery.build_recovery_notification_live_admission(
            invalid_target,
            live_config(),
            confirm_live_delivery=True,
        )
    assert target.value.error_code == "ag.recovery_notification_live_target_invalid"


def test_nested_mapping_helper_rejects_non_mapping_leaf() -> None:
    with pytest.raises(delivery.RecoveryNotificationDeliveryError) as exc_info:
        delivery._nested_mapping(
            {"outer": {"inner": None}},
            "outer",
            "inner",
            error_code="test.invalid",
        )

    assert exc_info.value.error_code == "test.invalid"
