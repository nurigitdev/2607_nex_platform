from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from nex_ag.platform_alert_repository import SqlAlchemyPlatformAlertRepository
from nex_ag.platform_alerting import AlertRecord
from nex_ag.platform_notification_delivery import (
    LocalNotificationTransport,
    NotificationDeliveryPolicy,
    NotificationTransportResponse,
    PlatformNotificationDeliveryError,
    ScriptedMockNotificationTransport,
    execute_notification_batch,
)
from run_s148_alert_persistence_restart import SQLITE_SCHEMA


@pytest.fixture
def repository() -> SqlAlchemyPlatformAlertRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    return SqlAlchemyPlatformAlertRepository(factory)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _alert(suffix: str = "a") -> AlertRecord:
    return AlertRecord(
        alert_id=f"alert:{suffix}",
        dedup_key=_digest(suffix),
        rule_id=f"rule:{suffix}",
        policy_id=f"slo:{suffix}",
        service_id="nex-cx",
        state="FIRING",
        severity="CRITICAL",
        reason_code="SLO_CRITICAL_BURN",
        occurrence_count=1,
        first_observed_at="2026-10-08T01:00:00Z",
        last_observed_at="2026-10-08T01:00:00Z",
        accountable_owner="content",
        runbook_ref="runbook:nex-cx:index",
    )


def _intent(channel: str, character: str) -> dict[str, str]:
    return {
        "channel": channel,
        "route_alias": f"route-{character}",
        "idempotency_key_hash": _digest(character),
        "payload_hash": _digest("f"),
    }


def test_local_delivery_is_persisted_as_real_delivery(repository) -> None:
    repository.insert_alert_with_notifications(
        _alert(), [_intent("LOCAL", "a")], created_at="2026-10-08T01:00:00Z"
    )
    result = execute_notification_batch(
        repository,
        worker_id="worker:local",
        attempted_at="2026-10-08T01:00:01Z",
        policy=NotificationDeliveryPolicy("local_only"),
        transports={"LOCAL": LocalNotificationTransport()},
    )
    item = result["results"][0]
    assert result["schema_version"] == "ag_notification_delivery_execution.v1"
    assert result["claimed_count"] == result["result_count"] == 1
    assert item["delivery_state"] == "DELIVERED"
    assert item["acceptance_status"] == "LOCAL_DELIVERED"
    assert item["external_activation"] == "LOCAL_ONLY"
    assert item["response_code"] == 204
    assert item["receipt_digest"].startswith("sha256:")
    assert result["private_payload_included"] is False


@pytest.mark.parametrize(
    ("mode", "channel"),
    [
        ("private_network", "INTERNAL_WEBHOOK"),
        ("internet_connected", "EXTERNAL_WEBHOOK"),
    ],
)
def test_external_mock_acceptance_never_becomes_live_delivery(
    repository, mode: str, channel: str
) -> None:
    repository.insert_alert_with_notifications(
        _alert(), [_intent(channel, "a")], created_at="2026-10-08T01:00:00Z"
    )
    result = execute_notification_batch(
        repository,
        worker_id="worker:mock",
        attempted_at="2026-10-08T01:00:01Z",
        policy=NotificationDeliveryPolicy(mode),
        transports={channel: ScriptedMockNotificationTransport((202,))},
    )
    item = result["results"][0]
    assert item["acceptance_status"] == "MOCK_ACCEPTED"
    assert item["external_activation"] == "EXTERNAL_NOT_ACTIVATED"
    assert item["delivery_state"] == "BLOCKED"
    assert item["error_code"] == "EXTERNAL_NOT_ACTIVATED"
    assert repository.list_attempts(item["notify_id"])[0].outcome == "BLOCKED"


def test_mock_retry_backoff_then_honest_acceptance(repository) -> None:
    repository.insert_alert_with_notifications(
        _alert(), [_intent("EXTERNAL_WEBHOOK", "a")], created_at="2026-10-08T01:00:00Z"
    )
    transport = ScriptedMockNotificationTransport((503, 202))
    policy = NotificationDeliveryPolicy(
        "internet_connected", retry_base_seconds=30, retry_max_seconds=60
    )
    first = execute_notification_batch(
        repository,
        worker_id="worker:retry",
        attempted_at="2026-10-08T01:00:01Z",
        policy=policy,
        transports={"EXTERNAL_WEBHOOK": transport},
    )["results"][0]
    assert first["delivery_state"] == "RETRY_WAIT"
    assert first["acceptance_status"] == "RETRY_SCHEDULED"
    assert first["next_attempt_at"] == "2026-10-08T01:00:31Z"
    assert execute_notification_batch(
        repository,
        worker_id="worker:early",
        attempted_at="2026-10-08T01:00:30Z",
        policy=policy,
        transports={"EXTERNAL_WEBHOOK": transport},
    )["result_count"] == 0
    second = execute_notification_batch(
        repository,
        worker_id="worker:retry",
        attempted_at="2026-10-08T01:00:31Z",
        policy=policy,
        transports={"EXTERNAL_WEBHOOK": transport},
    )["results"][0]
    assert second["acceptance_status"] == "MOCK_ACCEPTED"
    assert [item.outcome for item in repository.list_attempts(second["notify_id"])] == [
        "RETRY_WAIT",
        "BLOCKED",
    ]


@pytest.mark.parametrize("outcome", ["timeout", "connection_error", 429, 599])
def test_retryable_mock_outcomes_exhaust_to_dead_letter(repository, outcome) -> None:
    repository.insert_alert_with_notifications(
        _alert(), [_intent("EXTERNAL_WEBHOOK", "a")], created_at="2026-10-08T01:00:00Z"
    )
    result = execute_notification_batch(
        repository,
        worker_id="worker:exhausted",
        attempted_at="2026-10-08T01:00:01Z",
        policy=NotificationDeliveryPolicy("internet_connected", max_attempts=1),
        transports={"EXTERNAL_WEBHOOK": ScriptedMockNotificationTransport((outcome,))},
    )["results"][0]
    assert result["delivery_state"] == "DEAD_LETTER"
    assert result["acceptance_status"] == "DELIVERY_EXHAUSTED"


def test_rejected_or_unavailable_delivery_is_blocked(repository) -> None:
    repository.insert_alert_with_notifications(
        _alert("a"), [_intent("EXTERNAL_WEBHOOK", "a")], created_at="2026-10-08T01:00:00Z"
    )
    rejected = execute_notification_batch(
        repository,
        worker_id="worker:rejected",
        attempted_at="2026-10-08T01:00:01Z",
        policy=NotificationDeliveryPolicy("internet_connected"),
        transports={"EXTERNAL_WEBHOOK": ScriptedMockNotificationTransport((400,))},
    )["results"][0]
    assert rejected["delivery_state"] == "BLOCKED"
    assert rejected["acceptance_status"] == "DELIVERY_BLOCKED"
    assert rejected["error_code"] == "MOCK_HTTP_RESPONSE"

    repository.insert_alert_with_notifications(
        _alert("b"), [_intent("INTERNAL_WEBHOOK", "b")], created_at="2026-10-08T01:00:02Z"
    )
    unavailable = execute_notification_batch(
        repository,
        worker_id="worker:missing",
        attempted_at="2026-10-08T01:00:03Z",
        policy=NotificationDeliveryPolicy("private_network"),
        transports={},
    )["results"][0]
    assert unavailable["error_code"] == "NOTIFICATION_TRANSPORT_UNAVAILABLE"
    assert unavailable["response_code"] is None
    assert unavailable["receipt_digest"] is None


class _RaisingTransport:
    transport_kind = "MOCK"

    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    def deliver(self, notification, *, attempted_at: str):
        raise self._exception


@pytest.mark.parametrize(
    ("exception", "error_code"),
    [
        (TimeoutError(), "TRANSPORT_TIMEOUT"),
        (ConnectionError(), "TRANSPORT_CONNECTION_ERROR"),
        (RuntimeError(), "TRANSPORT_FAILURE"),
    ],
)
def test_transport_exceptions_are_redacted_and_retryable(
    repository, exception: Exception, error_code: str
) -> None:
    repository.insert_alert_with_notifications(
        _alert(), [_intent("EXTERNAL_WEBHOOK", "a")], created_at="2026-10-08T01:00:00Z"
    )
    item = execute_notification_batch(
        repository,
        worker_id="worker:error",
        attempted_at="2026-10-08T01:00:01Z",
        policy=NotificationDeliveryPolicy("internet_connected"),
        transports={"EXTERNAL_WEBHOOK": _RaisingTransport(exception)},
    )["results"][0]
    assert item["delivery_state"] == "RETRY_WAIT"
    assert item["error_code"] == error_code


def test_mode_mismatch_and_transport_kind_mismatch_are_fail_closed(repository) -> None:
    repository.insert_alert_with_notifications(
        _alert("a"), [_intent("INTERNAL_WEBHOOK", "a")], created_at="2026-10-08T01:00:00Z"
    )
    mode_mismatch = execute_notification_batch(
        repository,
        worker_id="worker:mode",
        attempted_at="2026-10-08T01:00:01Z",
        policy=NotificationDeliveryPolicy("internet_connected"),
        transports={"INTERNAL_WEBHOOK": ScriptedMockNotificationTransport()},
    )["results"][0]
    assert mode_mismatch["error_code"] == "NOTIFICATION_TRANSPORT_UNAVAILABLE"

    repository.insert_alert_with_notifications(
        _alert("b"), [_intent("LOCAL", "b")], created_at="2026-10-08T01:00:02Z"
    )
    kind_mismatch = execute_notification_batch(
        repository,
        worker_id="worker:kind",
        attempted_at="2026-10-08T01:00:03Z",
        policy=NotificationDeliveryPolicy("local_only"),
        transports={"LOCAL": ScriptedMockNotificationTransport()},
    )["results"][0]
    assert kind_mismatch["error_code"] == "NOTIFICATION_TRANSPORT_UNAVAILABLE"


@pytest.mark.parametrize(
    "builder",
    [
        lambda: NotificationDeliveryPolicy("bad"),
        lambda: NotificationDeliveryPolicy("local_only", max_attempts=0),
        lambda: NotificationDeliveryPolicy("local_only", retry_base_seconds=10, retry_max_seconds=5),
        lambda: NotificationDeliveryPolicy("local_only", lease_seconds=0),
        lambda: NotificationDeliveryPolicy("local_only", batch_size=101),
        lambda: NotificationTransportResponse(99, _digest("a"), "LOCAL"),
        lambda: NotificationTransportResponse(200, _digest("a"), "LIVE"),
        lambda: NotificationTransportResponse(200, "bad", "LOCAL"),
        lambda: ScriptedMockNotificationTransport(()),
        lambda: ScriptedMockNotificationTransport((True,)),
    ],
)
def test_delivery_policy_and_transport_validation(builder) -> None:
    with pytest.raises(PlatformNotificationDeliveryError):
        builder()


def test_invalid_mock_script_and_timestamp_fail_safely(repository) -> None:
    transport = ScriptedMockNotificationTransport(("unsupported",))
    notification = replace(
        repository.insert_alert_with_notifications(
            _alert(), [_intent("EXTERNAL_WEBHOOK", "a")], created_at="2026-10-08T01:00:00Z"
        )[1][0],
        delivery_state="CLAIMED",
    )
    with pytest.raises(PlatformNotificationDeliveryError) as exc_info:
        transport.deliver(notification, attempted_at="2026-10-08T01:00:01Z")
    assert exc_info.value.error_code == "notification.mock_script_invalid"
    for invalid in ("bad", "2026-10-08T01:00:00"):
        with pytest.raises(PlatformNotificationDeliveryError):
            execute_notification_batch(
                repository,
                worker_id="worker:bad-time",
                attempted_at=invalid,
                policy=NotificationDeliveryPolicy("internet_connected"),
                transports={"EXTERNAL_WEBHOOK": transport},
            )
