from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ag.platform_alerting import AlertRecord

NOTIFICATION_STATES = (
    "PENDING",
    "CLAIMED",
    "DELIVERED",
    "RETRY_WAIT",
    "BLOCKED",
    "DEAD_LETTER",
)
NOTIFICATION_OUTCOMES = ("DELIVERED", "RETRY_WAIT", "BLOCKED", "DEAD_LETTER")
NOTIFICATION_CHANNELS = ("LOCAL", "INTERNAL_WEBHOOK", "EXTERNAL_WEBHOOK")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class PlatformAlertRepositoryError(RuntimeError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class NotificationOutboxRecord:
    notify_id: str
    alert_id: str
    idempotency_key_hash: str
    channel: str
    route_alias: str
    payload_hash: str
    delivery_state: str
    attempt_count: int
    next_attempt_at: str | None
    lease_owner: str | None
    lease_expires_at: str | None
    last_error_code: str | None
    created_at: str
    updated_at: str
    delivered_at: str | None

    def __post_init__(self) -> None:
        for field in ("notify_id", "alert_id", "route_alias"):
            _identifier(getattr(self, field), field)
        _digest(self.idempotency_key_hash, "idempotency_key_hash")
        _digest(self.payload_hash, "payload_hash")
        if self.channel not in NOTIFICATION_CHANNELS:
            raise PlatformAlertRepositoryError(
                "alert.notification_channel_invalid", "notification channel is invalid"
            )
        if self.delivery_state not in NOTIFICATION_STATES:
            raise PlatformAlertRepositoryError(
                "alert.notification_state_invalid", "notification state is invalid"
            )
        if self.attempt_count < 0:
            raise PlatformAlertRepositoryError(
                "alert.notification_attempt_count_invalid", "attempt count must not be negative"
            )
        for field in ("next_attempt_at", "lease_expires_at", "delivered_at"):
            value = getattr(self, field)
            if value is not None:
                _timestamp(value, field)
        if self.lease_owner is not None:
            _identifier(self.lease_owner, "lease_owner")
        if self.last_error_code is not None:
            _identifier(self.last_error_code, "last_error_code")
        created = _timestamp(self.created_at, "created_at")
        updated = _timestamp(self.updated_at, "updated_at")
        if updated < created:
            raise PlatformAlertRepositoryError(
                "alert.notification_timestamp_order_invalid",
                "notification update must not precede creation",
            )


@dataclass(frozen=True)
class NotificationAttempt:
    attempt_id: str
    notify_id: str
    attempt_number: int
    outcome: str
    response_code: int | None
    receipt_digest: str | None
    error_code: str | None
    attempted_at: str

    def __post_init__(self) -> None:
        _identifier(self.attempt_id, "attempt_id")
        _identifier(self.notify_id, "notify_id")
        if self.attempt_number < 1:
            raise PlatformAlertRepositoryError(
                "alert.attempt_number_invalid", "attempt number must be positive"
            )
        if self.outcome not in NOTIFICATION_OUTCOMES:
            raise PlatformAlertRepositoryError(
                "alert.attempt_outcome_invalid", "attempt outcome is invalid"
            )
        if self.response_code is not None and not 100 <= self.response_code <= 599:
            raise PlatformAlertRepositoryError(
                "alert.response_code_invalid", "response code is invalid"
            )
        if self.receipt_digest is not None:
            _digest(self.receipt_digest, "receipt_digest")
        if self.error_code is not None:
            _identifier(self.error_code, "error_code")
        _timestamp(self.attempted_at, "attempted_at")


class SqlAlchemyPlatformAlertRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def insert_alert_with_notifications(
        self,
        alert: AlertRecord,
        intents: Sequence[Mapping[str, str]],
        *,
        created_at: str,
    ) -> tuple[AlertRecord, list[NotificationOutboxRecord]]:
        created = _wire_timestamp(_timestamp(created_at, "created_at"))
        notifications = [_notification_from_intent(alert, intent, created) for intent in intents]
        if len({item.idempotency_key_hash for item in notifications}) != len(notifications):
            raise PlatformAlertRepositoryError(
                "alert.notification_duplicate", "notification intents must be unique"
            )
        session = self._session_factory()
        try:
            try:
                session.execute(text(_INSERT_ALERT_SQL), _alert_params(alert))
                for record in notifications:
                    session.execute(text(_INSERT_NOTIFICATION_SQL), _notification_params(record))
                session.commit()
                return alert, notifications
            except Exception:
                session.rollback()
                raise
        except IntegrityError as exc:
            raise PlatformAlertRepositoryError(
                "alert.persistence_conflict", "alert or notification already exists"
            ) from exc
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc
        finally:
            session.close()

    def get_alert(self, alert_id: str) -> AlertRecord | None:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(_SELECT_ALERT_SQL + " WHERE alert_id = :alert_id"),
                    {"alert_id": alert_id},
                ).mappings().first()
            return None if row is None else _alert_from_mapping(row)
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc

    def update_alert(
        self, alert: AlertRecord, *, expected_state_revision: int
    ) -> AlertRecord:
        if alert.state_revision != expected_state_revision + 1:
            raise PlatformAlertRepositoryError(
                "alert.revision_invalid", "alert revision must advance exactly once"
            )
        params = _alert_params(alert)
        params["expected_state_revision"] = expected_state_revision
        session = self._session_factory()
        try:
            try:
                result = session.execute(text(_UPDATE_ALERT_SQL), params)
                if int(result.rowcount or 0) != 1:
                    raise PlatformAlertRepositoryError(
                        "alert.revision_conflict", "alert changed or no longer exists"
                    )
                session.commit()
                return alert
            except Exception:
                session.rollback()
                raise
        except PlatformAlertRepositoryError:
            raise
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc
        finally:
            session.close()

    def list_notifications(
        self, *, alert_id: str | None = None, state: str | None = None, limit: int = 100
    ) -> list[NotificationOutboxRecord]:
        if state is not None and state not in NOTIFICATION_STATES:
            raise PlatformAlertRepositoryError(
                "alert.notification_filter_invalid", "notification state filter is invalid"
            )
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise PlatformAlertRepositoryError(
                "alert.notification_filter_invalid", "notification limit is invalid"
            )
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if alert_id is not None:
            clauses.append("alert_id = :alert_id")
            params["alert_id"] = alert_id
        if state is not None:
            clauses.append("delivery_state = :delivery_state")
            params["delivery_state"] = state
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(_SELECT_NOTIFICATION_SQL + where + " ORDER BY created_at, notify_id LIMIT :limit"),
                    params,
                ).mappings().all()
            return [_notification_from_mapping(row) for row in rows]
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc

    def claim_notifications(
        self,
        *,
        worker_id: str,
        claimed_at: str,
        lease_seconds: int,
        limit: int = 10,
    ) -> list[NotificationOutboxRecord]:
        _identifier(worker_id, "worker_id")
        claimed = _timestamp(claimed_at, "claimed_at")
        if lease_seconds < 1 or not 1 <= limit <= 100:
            raise PlatformAlertRepositoryError(
                "alert.claim_policy_invalid", "claim lease and limit must be positive and bounded"
            )
        expires = claimed + timedelta(seconds=lease_seconds)
        session = self._session_factory()
        try:
            try:
                suffix = " FOR UPDATE SKIP LOCKED" if session.bind is not None and session.bind.dialect.name == "postgresql" else ""
                rows = session.execute(
                    text(_CLAIMABLE_NOTIFICATION_SQL + suffix),
                    {"claimed_at": claimed, "limit": limit},
                ).mappings().all()
                claimed_records = []
                for row in rows:
                    result = session.execute(
                        text(_CLAIM_NOTIFICATION_SQL),
                        {
                            "notify_id": row["notify_id"],
                            "worker_id": worker_id,
                            "lease_expires_at": expires,
                            "updated_at": claimed,
                            "claimed_at": claimed,
                        },
                    )
                    if int(result.rowcount or 0) == 1:
                        claimed_records.append(
                            _notification_from_mapping(
                                {
                                    **dict(row),
                                    "delivery_state": "CLAIMED",
                                    "lease_owner": worker_id,
                                    "lease_expires_at": expires,
                                    "updated_at": claimed,
                                }
                            )
                        )
                session.commit()
                return claimed_records
            except Exception:
                session.rollback()
                raise
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc
        finally:
            session.close()

    def record_attempt(
        self,
        *,
        notify_id: str,
        worker_id: str,
        outcome: str,
        attempted_at: str,
        response_code: int | None = None,
        receipt_digest: str | None = None,
        error_code: str | None = None,
        next_attempt_at: str | None = None,
    ) -> tuple[NotificationOutboxRecord, NotificationAttempt]:
        _identifier(notify_id, "notify_id")
        _identifier(worker_id, "worker_id")
        attempted = _timestamp(attempted_at, "attempted_at")
        if outcome == "RETRY_WAIT" and next_attempt_at is None:
            raise PlatformAlertRepositoryError(
                "alert.retry_time_required", "retry outcome requires next_attempt_at"
            )
        if outcome != "RETRY_WAIT" and next_attempt_at is not None:
            raise PlatformAlertRepositoryError(
                "alert.retry_time_forbidden", "terminal outcome cannot include next_attempt_at"
            )
        retry_at = _timestamp(next_attempt_at, "next_attempt_at") if next_attempt_at else None
        if retry_at is not None and retry_at <= attempted:
            raise PlatformAlertRepositoryError(
                "alert.retry_time_invalid", "next attempt must be after the current attempt"
            )
        session = self._session_factory()
        try:
            try:
                row = session.execute(
                    text(_SELECT_NOTIFICATION_SQL + " WHERE notify_id = :notify_id"),
                    {"notify_id": notify_id},
                ).mappings().first()
                if row is None:
                    raise PlatformAlertRepositoryError(
                        "alert.notification_not_found", "notification was not found"
                    )
                current = _notification_from_mapping(row)
                if current.delivery_state != "CLAIMED" or current.lease_owner != worker_id:
                    raise PlatformAlertRepositoryError(
                        "alert.notification_claim_conflict", "notification is not claimed by this worker"
                    )
                attempt_number = current.attempt_count + 1
                attempt = NotificationAttempt(
                    attempt_id=f"attempt:{notify_id.split(':', 1)[-1]}:{attempt_number}",
                    notify_id=notify_id,
                    attempt_number=attempt_number,
                    outcome=outcome,
                    response_code=response_code,
                    receipt_digest=receipt_digest,
                    error_code=error_code,
                    attempted_at=_wire_timestamp(attempted),
                )
                delivered_at = attempted if outcome == "DELIVERED" else None
                session.execute(
                    text(_COMPLETE_NOTIFICATION_SQL),
                    {
                        "notify_id": notify_id,
                        "worker_id": worker_id,
                        "delivery_state": outcome,
                        "attempt_count": attempt_number,
                        "next_attempt_at": retry_at,
                        "last_error_code": error_code,
                        "updated_at": attempted,
                        "delivered_at": delivered_at,
                    },
                )
                session.execute(text(_INSERT_ATTEMPT_SQL), _attempt_params(attempt))
                session.commit()
                updated = NotificationOutboxRecord(
                    **{
                        **current.__dict__,
                        "delivery_state": outcome,
                        "attempt_count": attempt_number,
                        "next_attempt_at": _wire_timestamp(retry_at) if retry_at else None,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "last_error_code": error_code,
                        "updated_at": _wire_timestamp(attempted),
                        "delivered_at": _wire_timestamp(delivered_at) if delivered_at else None,
                    }
                )
                return updated, attempt
            except Exception:
                session.rollback()
                raise
        except PlatformAlertRepositoryError:
            raise
        except IntegrityError as exc:
            raise PlatformAlertRepositoryError(
                "alert.attempt_conflict", "notification attempt already exists"
            ) from exc
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc
        finally:
            session.close()

    def list_attempts(self, notify_id: str) -> list[NotificationAttempt]:
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(_SELECT_ATTEMPT_SQL + " WHERE notify_id = :notify_id ORDER BY attempt_number"),
                    {"notify_id": notify_id},
                ).mappings().all()
            return [_attempt_from_mapping(row) for row in rows]
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise _unavailable() from exc


def _notification_from_intent(
    alert: AlertRecord, intent: Mapping[str, str], created_at: str
) -> NotificationOutboxRecord:
    channel = str(intent.get("channel") or "")
    route_alias = str(intent.get("route_alias") or "")
    idempotency = str(intent.get("idempotency_key_hash") or "")
    payload_hash = str(intent.get("payload_hash") or "")
    suffix = idempotency.removeprefix("sha256:")[:24]
    return NotificationOutboxRecord(
        notify_id=f"notify:{suffix}",
        alert_id=alert.alert_id,
        idempotency_key_hash=idempotency,
        channel=channel,
        route_alias=route_alias,
        payload_hash=payload_hash,
        delivery_state="PENDING",
        attempt_count=0,
        next_attempt_at=None,
        lease_owner=None,
        lease_expires_at=None,
        last_error_code=None,
        created_at=created_at,
        updated_at=created_at,
        delivered_at=None,
    )


def _alert_params(alert: AlertRecord) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "dedup_key": alert.dedup_key,
        "rule_id": alert.rule_id,
        "policy_id": alert.policy_id,
        "service_id": alert.service_id,
        "alert_state": alert.state,
        "severity": alert.severity,
        "reason_code": alert.reason_code,
        "occurrence_count": alert.occurrence_count,
        "state_revision": alert.state_revision,
        "first_observed_at": _timestamp(alert.first_observed_at, "first_observed_at"),
        "last_observed_at": _timestamp(alert.last_observed_at, "last_observed_at"),
        "accountable_owner": alert.accountable_owner,
        "runbook_ref": alert.runbook_ref,
        "suppression_until": _optional_timestamp(alert.suppression_until, "suppression_until"),
        "acknowledged_by_hash": alert.acknowledged_by_hash,
    }


def _notification_params(record: NotificationOutboxRecord) -> dict[str, Any]:
    return {
        **record.__dict__,
        "next_attempt_at": _optional_timestamp(record.next_attempt_at, "next_attempt_at"),
        "lease_expires_at": _optional_timestamp(record.lease_expires_at, "lease_expires_at"),
        "created_at": _timestamp(record.created_at, "created_at"),
        "updated_at": _timestamp(record.updated_at, "updated_at"),
        "delivered_at": _optional_timestamp(record.delivered_at, "delivered_at"),
    }


def _attempt_params(attempt: NotificationAttempt) -> dict[str, Any]:
    return {**attempt.__dict__, "attempted_at": _timestamp(attempt.attempted_at, "attempted_at")}


def _alert_from_mapping(row: Mapping[str, Any]) -> AlertRecord:
    return AlertRecord(
        alert_id=str(row["alert_id"]),
        dedup_key=str(row["dedup_key"]),
        rule_id=str(row["rule_id"]),
        policy_id=str(row["policy_id"]),
        service_id=str(row["service_id"]),
        state=str(row["alert_state"]),
        severity=str(row["severity"]),
        reason_code=str(row["reason_code"]),
        occurrence_count=int(row["occurrence_count"]),
        first_observed_at=_wire_timestamp(_datetime(row["first_observed_at"])),
        last_observed_at=_wire_timestamp(_datetime(row["last_observed_at"])),
        accountable_owner=str(row["accountable_owner"]),
        runbook_ref=str(row["runbook_ref"]),
        suppression_until=_optional_wire_timestamp(row.get("suppression_until")),
        acknowledged_by_hash=_optional_text(row.get("acknowledged_by_hash")),
        state_revision=int(row["state_revision"]),
    )


def _notification_from_mapping(row: Mapping[str, Any]) -> NotificationOutboxRecord:
    return NotificationOutboxRecord(
        notify_id=str(row["notify_id"]),
        alert_id=str(row["alert_id"]),
        idempotency_key_hash=str(row["idempotency_key_hash"]),
        channel=str(row["channel"]),
        route_alias=str(row["route_alias"]),
        payload_hash=str(row["payload_hash"]),
        delivery_state=str(row["delivery_state"]),
        attempt_count=int(row["attempt_count"]),
        next_attempt_at=_optional_wire_timestamp(row.get("next_attempt_at")),
        lease_owner=_optional_text(row.get("lease_owner")),
        lease_expires_at=_optional_wire_timestamp(row.get("lease_expires_at")),
        last_error_code=_optional_text(row.get("last_error_code")),
        created_at=_wire_timestamp(_datetime(row["created_at"])),
        updated_at=_wire_timestamp(_datetime(row["updated_at"])),
        delivered_at=_optional_wire_timestamp(row.get("delivered_at")),
    )


def _attempt_from_mapping(row: Mapping[str, Any]) -> NotificationAttempt:
    return NotificationAttempt(
        attempt_id=str(row["attempt_id"]),
        notify_id=str(row["notify_id"]),
        attempt_number=int(row["attempt_number"]),
        outcome=str(row["outcome"]),
        response_code=int(row["response_code"]) if row.get("response_code") is not None else None,
        receipt_digest=_optional_text(row.get("receipt_digest")),
        error_code=_optional_text(row.get("error_code")),
        attempted_at=_wire_timestamp(_datetime(row["attempted_at"])),
    )


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_timestamp(value: str | None, field: str) -> datetime | None:
    return None if value is None else _timestamp(value, field)


def _optional_wire_timestamp(value: object) -> str | None:
    return None if value is None else _wire_timestamp(_datetime(value))


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = _timestamp(str(value), "database_timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PlatformAlertRepositoryError("alert.identifier_invalid", f"{field} is invalid")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PlatformAlertRepositoryError("alert.digest_invalid", f"{field} is invalid")
    return value


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise PlatformAlertRepositoryError("alert.timestamp_invalid", f"{field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlatformAlertRepositoryError("alert.timestamp_invalid", f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise PlatformAlertRepositoryError("alert.timestamp_timezone_required", f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _wire_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _unavailable() -> PlatformAlertRepositoryError:
    return PlatformAlertRepositoryError(
        "alert.persistence_unavailable", "platform alert persistence is unavailable"
    )


_SELECT_ALERT_SQL = """
SELECT alert_id, dedup_key, rule_id, policy_id, service_id, alert_state,
       severity, reason_code, occurrence_count, state_revision,
       first_observed_at, last_observed_at, accountable_owner, runbook_ref,
       suppression_until, acknowledged_by_hash
FROM ag_alerts
"""
_INSERT_ALERT_SQL = """
INSERT INTO ag_alerts (
    alert_id, dedup_key, rule_id, policy_id, service_id, alert_state,
    severity, reason_code, occurrence_count, state_revision,
    first_observed_at, last_observed_at, accountable_owner, runbook_ref,
    suppression_until, acknowledged_by_hash
) VALUES (
    :alert_id, :dedup_key, :rule_id, :policy_id, :service_id, :alert_state,
    :severity, :reason_code, :occurrence_count, :state_revision,
    :first_observed_at, :last_observed_at, :accountable_owner, :runbook_ref,
    :suppression_until, :acknowledged_by_hash
)
"""
_UPDATE_ALERT_SQL = """
UPDATE ag_alerts SET
    alert_state = :alert_state, severity = :severity, reason_code = :reason_code,
    occurrence_count = :occurrence_count, state_revision = :state_revision,
    last_observed_at = :last_observed_at, suppression_until = :suppression_until,
    acknowledged_by_hash = :acknowledged_by_hash
WHERE alert_id = :alert_id AND state_revision = :expected_state_revision
"""
_SELECT_NOTIFICATION_SQL = """
SELECT notify_id, alert_id, idempotency_key_hash, channel, route_alias,
       payload_hash, delivery_state, attempt_count, next_attempt_at,
       lease_owner, lease_expires_at, last_error_code, created_at, updated_at,
       delivered_at
FROM ag_notify_outbox
"""
_INSERT_NOTIFICATION_SQL = """
INSERT INTO ag_notify_outbox (
    notify_id, alert_id, idempotency_key_hash, channel, route_alias,
    payload_hash, delivery_state, attempt_count, next_attempt_at,
    lease_owner, lease_expires_at, last_error_code, created_at, updated_at,
    delivered_at
) VALUES (
    :notify_id, :alert_id, :idempotency_key_hash, :channel, :route_alias,
    :payload_hash, :delivery_state, :attempt_count, :next_attempt_at,
    :lease_owner, :lease_expires_at, :last_error_code, :created_at, :updated_at,
    :delivered_at
)
"""
_CLAIMABLE_NOTIFICATION_SQL = """
SELECT notify_id, alert_id, idempotency_key_hash, channel, route_alias,
       payload_hash, delivery_state, attempt_count, next_attempt_at,
       lease_owner, lease_expires_at, last_error_code, created_at, updated_at,
       delivered_at
FROM ag_notify_outbox
WHERE (
    delivery_state = 'PENDING'
    OR (delivery_state = 'RETRY_WAIT' AND (next_attempt_at IS NULL OR next_attempt_at <= :claimed_at))
    OR (delivery_state = 'CLAIMED' AND lease_expires_at <= :claimed_at)
)
ORDER BY created_at, notify_id
LIMIT :limit
"""
_CLAIM_NOTIFICATION_SQL = """
UPDATE ag_notify_outbox SET
    delivery_state = 'CLAIMED', lease_owner = :worker_id,
    lease_expires_at = :lease_expires_at, updated_at = :updated_at
WHERE notify_id = :notify_id AND (
    delivery_state = 'PENDING'
    OR (delivery_state = 'RETRY_WAIT' AND (next_attempt_at IS NULL OR next_attempt_at <= :claimed_at))
    OR (delivery_state = 'CLAIMED' AND lease_expires_at <= :claimed_at)
)
"""
_COMPLETE_NOTIFICATION_SQL = """
UPDATE ag_notify_outbox SET
    delivery_state = :delivery_state, attempt_count = :attempt_count,
    next_attempt_at = :next_attempt_at, lease_owner = NULL,
    lease_expires_at = NULL, last_error_code = :last_error_code,
    updated_at = :updated_at, delivered_at = :delivered_at
WHERE notify_id = :notify_id AND delivery_state = 'CLAIMED' AND lease_owner = :worker_id
"""
_SELECT_ATTEMPT_SQL = """
SELECT attempt_id, notify_id, attempt_number, outcome, response_code,
       receipt_digest, error_code, attempted_at
FROM ag_notify_attempts
"""
_INSERT_ATTEMPT_SQL = """
INSERT INTO ag_notify_attempts (
    attempt_id, notify_id, attempt_number, outcome, response_code,
    receipt_digest, error_code, attempted_at
) VALUES (
    :attempt_id, :notify_id, :attempt_number, :outcome, :response_code,
    :receipt_digest, :error_code, :attempted_at
)
"""
