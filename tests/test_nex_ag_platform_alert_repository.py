from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from nex_ag.platform_alert_repository import (
    NotificationAttempt,
    NotificationOutboxRecord,
    PlatformAlertRepositoryError,
    SqlAlchemyPlatformAlertRepository,
    _datetime,
)
from nex_ag.platform_alerting import AlertRecord, AlertRule, apply_slo_evaluation
from run_s148_alert_persistence_restart import SQLITE_SCHEMA

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


@pytest.fixture
def repository() -> SqlAlchemyPlatformAlertRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    factory: sessionmaker[Session] = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return SqlAlchemyPlatformAlertRepository(factory)


def _alert() -> AlertRecord:
    rule = AlertRule(
        "rule:nex-cx:index", "slo:nex-cx:index", "nex-cx", 1, 300
    )
    alert = apply_slo_evaluation(
        rule,
        {
            "policy_id": rule.policy_id,
            "service_id": rule.service_id,
            "status": "BREACHED",
            "reason_code": "SLO_CRITICAL_BURN",
            "accountable_owner": "content",
            "runbook_ref": "runbook:nex-cx:index",
        },
        evaluated_at="2026-10-08T01:00:00Z",
    )
    assert alert is not None
    return alert


def _intents() -> list[dict[str, str]]:
    return [
        {
            "channel": "LOCAL",
            "route_alias": "ag-local",
            "idempotency_key_hash": DIGEST_A,
            "payload_hash": DIGEST_B,
        }
    ]


def test_repository_insert_get_list_claim_deliver_and_history(repository) -> None:
    alert = _alert()
    _, notifications = repository.insert_alert_with_notifications(
        alert, _intents(), created_at="2026-10-08T01:00:00Z"
    )
    assert repository.get_alert(alert.alert_id) == alert
    assert repository.get_alert("alert:missing") is None
    assert repository.list_notifications() == notifications
    assert repository.list_notifications(alert_id=alert.alert_id, state="PENDING") == notifications
    claimed = repository.claim_notifications(
        worker_id="worker:one", claimed_at="2026-10-08T01:00:01Z", lease_seconds=30, limit=1
    )
    assert len(claimed) == 1 and claimed[0].delivery_state == "CLAIMED"
    delivered, attempt = repository.record_attempt(
        notify_id=claimed[0].notify_id,
        worker_id="worker:one",
        outcome="DELIVERED",
        attempted_at="2026-10-08T01:00:02Z",
        response_code=202,
        receipt_digest=DIGEST_A,
    )
    assert delivered.delivery_state == "DELIVERED"
    assert repository.list_attempts(delivered.notify_id) == [attempt]
    assert repository.claim_notifications(
        worker_id="worker:two", claimed_at="2026-10-08T01:01:00Z", lease_seconds=30
    ) == []


def test_repository_retries_blocks_and_dead_letters(repository) -> None:
    for suffix, outcome in (("a", "BLOCKED"), ("b", "DEAD_LETTER"), ("c", "RETRY_WAIT")):
        alert = replace(
            _alert(),
            alert_id=f"alert:{suffix}",
            dedup_key=f"sha256:{suffix * 64}",
        )
        intent = {
            **_intents()[0],
            "idempotency_key_hash": f"sha256:{suffix * 64}",
        }
        repository.insert_alert_with_notifications(alert, [intent], created_at="2026-10-08T01:00:00Z")
        claimed = repository.claim_notifications(
            worker_id=f"worker:{suffix}", claimed_at="2026-10-08T01:00:01Z", lease_seconds=30, limit=1
        )[0]
        result, _ = repository.record_attempt(
            notify_id=claimed.notify_id,
            worker_id=f"worker:{suffix}",
            outcome=outcome,
            attempted_at="2026-10-08T01:00:02Z",
            response_code=503,
            error_code="DELIVERY_FAILED",
            next_attempt_at="2026-10-08T01:01:00Z" if outcome == "RETRY_WAIT" else None,
        )
        assert result.delivery_state == outcome


def test_repository_update_optimistic_revision(repository) -> None:
    alert = _alert()
    repository.insert_alert_with_notifications(alert, [], created_at="2026-10-08T01:00:00Z")
    updated = replace(alert, state="RESOLVED", state_revision=2, last_observed_at="2026-10-08T01:01:00Z")
    assert repository.update_alert(updated, expected_state_revision=1) == updated
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        repository.update_alert(replace(updated, state_revision=4), expected_state_revision=2)
    assert exc_info.value.error_code == "alert.revision_invalid"
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        repository.update_alert(updated, expected_state_revision=1)
    assert exc_info.value.error_code == "alert.revision_conflict"


def test_repository_conflicts_filters_and_claim_policy(repository) -> None:
    alert = _alert()
    repository.insert_alert_with_notifications(alert, _intents(), created_at="2026-10-08T01:00:00Z")
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        repository.insert_alert_with_notifications(alert, _intents(), created_at="2026-10-08T01:00:00Z")
    assert exc_info.value.error_code == "alert.persistence_conflict"
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        repository.insert_alert_with_notifications(
            replace(alert, alert_id="alert:other", dedup_key="sha256:" + "c" * 64),
            _intents() * 2,
            created_at="2026-10-08T01:00:00Z",
        )
    assert exc_info.value.error_code == "alert.notification_duplicate"
    for kwargs in ({"state": "BAD"}, {"limit": 0}, {"limit": True}):
        with pytest.raises(PlatformAlertRepositoryError) as exc_info:
            repository.list_notifications(**kwargs)
        assert exc_info.value.error_code == "alert.notification_filter_invalid"
    for lease, limit in ((0, 1), (1, 0), (1, 101)):
        with pytest.raises(PlatformAlertRepositoryError) as exc_info:
            repository.claim_notifications(
                worker_id="worker", claimed_at="2026-10-08T01:00:00Z", lease_seconds=lease, limit=limit
            )
        assert exc_info.value.error_code == "alert.claim_policy_invalid"


def test_record_attempt_requires_claim_and_valid_retry_time(repository) -> None:
    alert = _alert()
    _, notifications = repository.insert_alert_with_notifications(
        alert, _intents(), created_at="2026-10-08T01:00:00Z"
    )
    notify_id = notifications[0].notify_id
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        repository.record_attempt(
            notify_id="notify:missing", worker_id="worker", outcome="DELIVERED", attempted_at="2026-10-08T01:00:00Z"
        )
    assert exc_info.value.error_code == "alert.notification_not_found"
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        repository.record_attempt(
            notify_id=notify_id, worker_id="worker", outcome="DELIVERED", attempted_at="2026-10-08T01:00:00Z"
        )
    assert exc_info.value.error_code == "alert.notification_claim_conflict"
    repository.claim_notifications(
        worker_id="worker", claimed_at="2026-10-08T01:00:00Z", lease_seconds=30
    )
    invalid_cases = [
        ("RETRY_WAIT", None, "alert.retry_time_required"),
        ("DELIVERED", "2026-10-08T01:01:00Z", "alert.retry_time_forbidden"),
        ("RETRY_WAIT", "2026-10-08T00:59:00Z", "alert.retry_time_invalid"),
    ]
    for outcome, next_at, code in invalid_cases:
        with pytest.raises(PlatformAlertRepositoryError) as exc_info:
            repository.record_attempt(
                notify_id=notify_id,
                worker_id="worker",
                outcome=outcome,
                attempted_at="2026-10-08T01:00:01Z",
                next_attempt_at=next_at,
            )
        assert exc_info.value.error_code == code


def test_attempt_conflict_rolls_back_notification_update(repository) -> None:
    alert = _alert()
    _, notifications = repository.insert_alert_with_notifications(
        alert, _intents(), created_at="2026-10-08T01:00:00Z"
    )
    claimed = repository.claim_notifications(
        worker_id="worker", claimed_at="2026-10-08T01:00:00Z", lease_seconds=30
    )[0]
    expected_attempt_id = f"attempt:{claimed.notify_id.split(':', 1)[-1]}:1"
    with repository._session_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO ag_notify_attempts "
                "(attempt_id, notify_id, attempt_number, outcome, attempted_at) "
                "VALUES (:attempt_id, :notify_id, 99, 'BLOCKED', :attempted_at)"
            ),
            {
                "attempt_id": expected_attempt_id,
                "notify_id": claimed.notify_id,
                "attempted_at": "2026-10-08T00:59:00Z",
            },
        )
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        repository.record_attempt(
            notify_id=claimed.notify_id,
            worker_id="worker",
            outcome="DELIVERED",
            attempted_at="2026-10-08T01:00:01Z",
        )
    assert exc_info.value.error_code == "alert.attempt_conflict"
    assert repository.list_notifications()[0].delivery_state == "CLAIMED"


def test_repository_maps_sql_failures_to_safe_unavailable_error() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory: sessionmaker[Session] = sessionmaker(bind=engine)
    repository = SqlAlchemyPlatformAlertRepository(factory)
    alert = _alert()
    operations = (
        lambda: repository.insert_alert_with_notifications(
            alert, [], created_at="2026-10-08T01:00:00Z"
        ),
        lambda: repository.get_alert(alert.alert_id),
        lambda: repository.update_alert(
            replace(alert, state_revision=2), expected_state_revision=1
        ),
        lambda: repository.list_notifications(),
        lambda: repository.claim_notifications(
            worker_id="worker", claimed_at="2026-10-08T01:00:00Z", lease_seconds=30
        ),
        lambda: repository.record_attempt(
            notify_id="notify:missing",
            worker_id="worker",
            outcome="DELIVERED",
            attempted_at="2026-10-08T01:00:00Z",
        ),
        lambda: repository.list_attempts("notify:missing"),
    )
    for operation in operations:
        with pytest.raises(PlatformAlertRepositoryError) as exc_info:
            operation()
        assert exc_info.value.error_code == "alert.persistence_unavailable"
        assert "SQL" not in exc_info.value.detail
    engine.dispose()


def test_datetime_helper_normalizes_naive_database_values() -> None:
    assert _datetime(datetime(2026, 10, 8, 1, 0)).tzinfo is not None


@pytest.mark.parametrize(
    ("builder", "error_code"),
    [
        (lambda: NotificationOutboxRecord("bad value", "alert:a", DIGEST_A, "LOCAL", "route", DIGEST_B, "PENDING", 0, None, None, None, None, "2026-10-08T01:00:00Z", "2026-10-08T01:00:00Z", None), "alert.identifier_invalid"),
        (lambda: NotificationOutboxRecord("notify:a", "alert:a", "bad", "LOCAL", "route", DIGEST_B, "PENDING", 0, None, None, None, None, "2026-10-08T01:00:00Z", "2026-10-08T01:00:00Z", None), "alert.digest_invalid"),
        (lambda: NotificationOutboxRecord("notify:a", "alert:a", DIGEST_A, "BAD", "route", DIGEST_B, "PENDING", 0, None, None, None, None, "2026-10-08T01:00:00Z", "2026-10-08T01:00:00Z", None), "alert.notification_channel_invalid"),
        (lambda: NotificationOutboxRecord("notify:a", "alert:a", DIGEST_A, "LOCAL", "route", DIGEST_B, "BAD", 0, None, None, None, None, "2026-10-08T01:00:00Z", "2026-10-08T01:00:00Z", None), "alert.notification_state_invalid"),
        (lambda: NotificationOutboxRecord("notify:a", "alert:a", DIGEST_A, "LOCAL", "route", DIGEST_B, "PENDING", -1, None, None, None, None, "2026-10-08T01:00:00Z", "2026-10-08T01:00:00Z", None), "alert.notification_attempt_count_invalid"),
        (lambda: NotificationOutboxRecord("notify:a", "alert:a", DIGEST_A, "LOCAL", "route", DIGEST_B, "PENDING", 0, None, None, None, None, "2026-10-08T01:00:01Z", "2026-10-08T01:00:00Z", None), "alert.notification_timestamp_order_invalid"),
        (lambda: NotificationOutboxRecord("notify:a", "alert:a", DIGEST_A, "LOCAL", "route", DIGEST_B, "PENDING", 0, None, None, None, None, None, "2026-10-08T01:00:00Z", None), "alert.timestamp_invalid"),
        (lambda: NotificationOutboxRecord("notify:a", "alert:a", DIGEST_A, "LOCAL", "route", DIGEST_B, "PENDING", 0, None, None, None, None, "bad", "2026-10-08T01:00:00Z", None), "alert.timestamp_invalid"),
        (lambda: NotificationOutboxRecord("notify:a", "alert:a", DIGEST_A, "LOCAL", "route", DIGEST_B, "PENDING", 0, None, None, None, None, "2026-10-08T01:00:00", "2026-10-08T01:00:00Z", None), "alert.timestamp_timezone_required"),
        (lambda: NotificationAttempt("attempt:a", "notify:a", 0, "DELIVERED", None, None, None, "2026-10-08T01:00:00Z"), "alert.attempt_number_invalid"),
        (lambda: NotificationAttempt("attempt:a", "notify:a", 1, "BAD", None, None, None, "2026-10-08T01:00:00Z"), "alert.attempt_outcome_invalid"),
        (lambda: NotificationAttempt("attempt:a", "notify:a", 1, "DELIVERED", 99, None, None, "2026-10-08T01:00:00Z"), "alert.response_code_invalid"),
    ],
)
def test_persistence_records_reject_invalid_values(builder, error_code: str) -> None:
    with pytest.raises(PlatformAlertRepositoryError) as exc_info:
        builder()
    assert exc_info.value.error_code == error_code
