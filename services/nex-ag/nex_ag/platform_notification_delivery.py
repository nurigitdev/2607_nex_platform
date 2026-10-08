from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any, Protocol

from nex_ag.platform_alert_repository import (
    NotificationOutboxRecord,
    SqlAlchemyPlatformAlertRepository,
)

DELIVERY_EXECUTION_SCHEMA_VERSION = "ag_notification_delivery_execution.v1"
DELIVERY_ACCEPTANCE_STATES = (
    "LOCAL_DELIVERED",
    "MOCK_ACCEPTED",
    "RETRY_SCHEDULED",
    "DELIVERY_BLOCKED",
    "DELIVERY_EXHAUSTED",
)
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429})


class PlatformNotificationDeliveryError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class NotificationDeliveryPolicy:
    notification_mode: str
    max_attempts: int = 4
    retry_base_seconds: int = 30
    retry_max_seconds: int = 900
    lease_seconds: int = 60
    batch_size: int = 20

    def __post_init__(self) -> None:
        if self.notification_mode not in {
            "local_only",
            "private_network",
            "internet_connected",
        }:
            raise PlatformNotificationDeliveryError(
                "notification.mode_invalid", "notification mode is invalid"
            )
        if not 1 <= self.max_attempts <= 20:
            raise PlatformNotificationDeliveryError(
                "notification.attempt_policy_invalid", "max attempts must be between 1 and 20"
            )
        if not 1 <= self.retry_base_seconds <= self.retry_max_seconds <= 86_400:
            raise PlatformNotificationDeliveryError(
                "notification.retry_policy_invalid", "retry delays are invalid"
            )
        if not 1 <= self.lease_seconds <= 3_600 or not 1 <= self.batch_size <= 100:
            raise PlatformNotificationDeliveryError(
                "notification.claim_policy_invalid", "lease and batch size must be bounded"
            )


@dataclass(frozen=True)
class NotificationTransportResponse:
    status_code: int
    receipt_digest: str
    transport_kind: str
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not 100 <= self.status_code <= 599:
            raise PlatformNotificationDeliveryError(
                "notification.response_code_invalid", "transport response code is invalid"
            )
        if self.transport_kind not in {"LOCAL", "MOCK"}:
            raise PlatformNotificationDeliveryError(
                "notification.transport_kind_invalid", "transport kind is invalid"
            )
        if not self.receipt_digest.startswith("sha256:") or len(self.receipt_digest) != 71:
            raise PlatformNotificationDeliveryError(
                "notification.receipt_invalid", "transport receipt must be a SHA-256 digest"
            )


class NotificationTransport(Protocol):
    transport_kind: str

    def deliver(
        self, notification: NotificationOutboxRecord, *, attempted_at: str
    ) -> NotificationTransportResponse: ...


class LocalNotificationTransport:
    transport_kind = "LOCAL"

    def deliver(
        self, notification: NotificationOutboxRecord, *, attempted_at: str
    ) -> NotificationTransportResponse:
        return NotificationTransportResponse(
            status_code=204,
            receipt_digest=_receipt_digest(notification, attempted_at, "LOCAL", 204),
            transport_kind=self.transport_kind,
        )


class ScriptedMockNotificationTransport:
    transport_kind = "MOCK"

    def __init__(self, outcomes: Sequence[int | str] = (202,)) -> None:
        if not outcomes or any(
            not isinstance(value, (int, str)) or isinstance(value, bool)
            for value in outcomes
        ):
            raise PlatformNotificationDeliveryError(
                "notification.mock_script_invalid", "mock outcomes must not be empty"
            )
        self._outcomes = tuple(outcomes)
        self._index = 0

    def deliver(
        self, notification: NotificationOutboxRecord, *, attempted_at: str
    ) -> NotificationTransportResponse:
        outcome = self._outcomes[min(self._index, len(self._outcomes) - 1)]
        self._index += 1
        if isinstance(outcome, str):
            if outcome not in {"timeout", "connection_error"}:
                raise PlatformNotificationDeliveryError(
                    "notification.mock_script_invalid", "mock outcome is unsupported"
                )
            code = 599 if outcome == "timeout" else 598
            error = "MOCK_TIMEOUT" if outcome == "timeout" else "MOCK_CONNECTION_ERROR"
        else:
            code = outcome
            error = None if 200 <= code <= 299 else "MOCK_HTTP_RESPONSE"
        return NotificationTransportResponse(
            status_code=code,
            receipt_digest=_receipt_digest(notification, attempted_at, "MOCK", code),
            transport_kind=self.transport_kind,
            error_code=error,
        )


def execute_notification_batch(
    repository: SqlAlchemyPlatformAlertRepository,
    *,
    worker_id: str,
    attempted_at: str,
    policy: NotificationDeliveryPolicy,
    transports: Mapping[str, NotificationTransport],
) -> dict[str, Any]:
    attempted = _timestamp(attempted_at)
    claimed = repository.claim_notifications(
        worker_id=worker_id,
        claimed_at=_wire_timestamp(attempted),
        lease_seconds=policy.lease_seconds,
        limit=policy.batch_size,
    )
    results = [
        _execute_one(
            repository,
            item,
            worker_id=worker_id,
            attempted=attempted,
            policy=policy,
            transport=transports.get(item.channel),
        )
        for item in claimed
    ]
    return {
        "schema_version": DELIVERY_EXECUTION_SCHEMA_VERSION,
        "notification_mode": policy.notification_mode,
        "claimed_count": len(claimed),
        "result_count": len(results),
        "results": results,
        "private_payload_included": False,
    }


def _execute_one(
    repository: SqlAlchemyPlatformAlertRepository,
    notification: NotificationOutboxRecord,
    *,
    worker_id: str,
    attempted: datetime,
    policy: NotificationDeliveryPolicy,
    transport: NotificationTransport | None,
) -> dict[str, Any]:
    response: NotificationTransportResponse | None = None
    if transport is None or not _transport_allowed(notification, policy, transport):
        outcome = "BLOCKED"
        acceptance = "DELIVERY_BLOCKED"
        error_code = "NOTIFICATION_TRANSPORT_UNAVAILABLE"
        next_attempt_at = None
    else:
        try:
            response = transport.deliver(
                notification, attempted_at=_wire_timestamp(attempted)
            )
        except Exception as exc:
            response = NotificationTransportResponse(
                status_code=599,
                receipt_digest=_receipt_digest(
                    notification, _wire_timestamp(attempted), "ERROR", 599
                ),
                transport_kind=transport.transport_kind,
                error_code=_safe_transport_error(exc),
            )
        outcome, acceptance, error_code, next_attempt_at = _classify(
            notification, response, attempted=attempted, policy=policy
        )
    updated, attempt = repository.record_attempt(
        notify_id=notification.notify_id,
        worker_id=worker_id,
        outcome=outcome,
        attempted_at=_wire_timestamp(attempted),
        response_code=response.status_code if response else None,
        receipt_digest=response.receipt_digest if response else None,
        error_code=error_code,
        next_attempt_at=next_attempt_at,
    )
    return {
        "notify_id": updated.notify_id,
        "channel": updated.channel,
        "route_alias": updated.route_alias,
        "attempt_number": attempt.attempt_number,
        "delivery_state": updated.delivery_state,
        "acceptance_status": acceptance,
        "external_activation": (
            "LOCAL_ONLY" if updated.channel == "LOCAL" else "EXTERNAL_NOT_ACTIVATED"
        ),
        "response_code": attempt.response_code,
        "receipt_digest": attempt.receipt_digest,
        "error_code": attempt.error_code,
        "next_attempt_at": updated.next_attempt_at,
        "private_payload_included": False,
    }


def _transport_allowed(
    notification: NotificationOutboxRecord,
    policy: NotificationDeliveryPolicy,
    transport: NotificationTransport,
) -> bool:
    if notification.channel == "LOCAL":
        return transport.transport_kind == "LOCAL"
    expected_channel = (
        "INTERNAL_WEBHOOK"
        if policy.notification_mode == "private_network"
        else "EXTERNAL_WEBHOOK"
        if policy.notification_mode == "internet_connected"
        else None
    )
    return notification.channel == expected_channel and transport.transport_kind == "MOCK"


def _classify(
    notification: NotificationOutboxRecord,
    response: NotificationTransportResponse,
    *,
    attempted: datetime,
    policy: NotificationDeliveryPolicy,
) -> tuple[str, str, str | None, str | None]:
    retryable = response.status_code in RETRYABLE_STATUS_CODES or response.status_code >= 500
    next_attempt = notification.attempt_count + 1
    if retryable:
        if next_attempt >= policy.max_attempts:
            return "DEAD_LETTER", "DELIVERY_EXHAUSTED", response.error_code or "DELIVERY_RETRY_EXHAUSTED", None
        delay = min(
            policy.retry_base_seconds * (2 ** notification.attempt_count),
            policy.retry_max_seconds,
        )
        return (
            "RETRY_WAIT",
            "RETRY_SCHEDULED",
            response.error_code or "DELIVERY_RETRYABLE_RESPONSE",
            _wire_timestamp(attempted + timedelta(seconds=delay)),
        )
    if not 200 <= response.status_code <= 299:
        return "BLOCKED", "DELIVERY_BLOCKED", response.error_code or "DELIVERY_REJECTED", None
    if notification.channel == "LOCAL":
        return "DELIVERED", "LOCAL_DELIVERED", None, None
    return "BLOCKED", "MOCK_ACCEPTED", "EXTERNAL_NOT_ACTIVATED", None


def _safe_transport_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "TRANSPORT_TIMEOUT"
    if isinstance(exc, ConnectionError):
        return "TRANSPORT_CONNECTION_ERROR"
    return "TRANSPORT_FAILURE"


def _receipt_digest(
    notification: NotificationOutboxRecord,
    attempted_at: str,
    transport_kind: str,
    status_code: int,
) -> str:
    payload = {
        "notify_id": notification.notify_id,
        "payload_hash": notification.payload_hash,
        "attempt_number": notification.attempt_count + 1,
        "attempted_at": attempted_at,
        "transport_kind": transport_kind,
        "status_code": status_code,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise PlatformNotificationDeliveryError(
            "notification.timestamp_invalid", "attempted_at is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise PlatformNotificationDeliveryError(
            "notification.timestamp_timezone_required", "attempted_at must be timezone-aware"
        )
    return parsed.astimezone(UTC)


def _wire_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
