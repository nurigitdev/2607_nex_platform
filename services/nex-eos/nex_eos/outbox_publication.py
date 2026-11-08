from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import Select, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_OUTBOX_TABLE

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

Clock = Callable[[], datetime]


class EosOutboxPublicationError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, retryable: bool) -> None:
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class EosOutboxEvent:
    outbox_id: str
    tenant_id: str
    event_id: str
    business_operation_id: str
    event_type: str
    event_payload: dict[str, object]
    event_payload_hash: str


@dataclass(frozen=True)
class EosOutboxPublishReceipt:
    event_id: str
    event_payload_hash: str
    receipt_ref: str


@dataclass(frozen=True)
class EosOutboxPublicationResult:
    outbox_id: str
    event_id: str
    event_payload_hash: str
    delivery_state: str
    attempt_count: int
    retry_required: bool
    receipt_ref: str | None
    error_code: str | None


class EosOutboxTransport(Protocol):
    def publish(self, event: EosOutboxEvent) -> EosOutboxPublishReceipt: ...


class SqlAlchemyEosOutboxPublisher:
    """Publish one pending event while keeping business execution out of retry."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def publish_next(
        self,
        transport: EosOutboxTransport,
        *,
        tenant_id: str | None = None,
    ) -> EosOutboxPublicationResult | None:
        publish = getattr(transport, "publish", None)
        if not callable(publish):
            raise _invalid("EOS outbox transport must expose publish().")
        normalized_tenant = _optional_tenant(tenant_id)
        session = self._session_factory()
        try:
            with session.begin():
                row = session.execute(
                    _claim_statement(session, tenant_id=normalized_tenant)
                ).mappings().first()
                if row is None:
                    return None
                event = _event_from_row(row)
                attempt_count = _attempt_count(row["attempt_count"]) + 1
                attempted_at = _aware_datetime(self._clock())
                try:
                    receipt = publish(event)
                    normalized_receipt = _receipt(receipt, event)
                except (OSError, RuntimeError):
                    _record_attempt(
                        session,
                        event,
                        attempt_count=attempt_count,
                        attempted_at=attempted_at,
                        published_at=None,
                    )
                    return _result(
                        event,
                        delivery_state="PENDING",
                        attempt_count=attempt_count,
                        retry_required=True,
                        receipt_ref=None,
                        error_code="EOS_OUTBOX_ACK_UNCONFIRMED",
                    )
                _record_attempt(
                    session,
                    event,
                    attempt_count=attempt_count,
                    attempted_at=attempted_at,
                    published_at=attempted_at,
                )
                return _result(
                    event,
                    delivery_state="PUBLISHED",
                    attempt_count=attempt_count,
                    retry_required=False,
                    receipt_ref=normalized_receipt.receipt_ref,
                    error_code=None,
                )
        except EosOutboxPublicationError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid("EOS outbox persisted event is malformed.") from exc
        except SQLAlchemyError as exc:
            raise EosOutboxPublicationError(
                "EOS_OUTBOX_PERSISTENCE_UNAVAILABLE",
                "EOS outbox publication state is unavailable.",
                retryable=True,
            ) from exc
        finally:
            session.close()


def _claim_statement(
    session: Session,
    *,
    tenant_id: str | None,
) -> Select[tuple[object, ...]]:
    statement = (
        select(EOS_OUTBOX_TABLE)
        .where(EOS_OUTBOX_TABLE.c.delivery_state == "PENDING")
        .order_by(EOS_OUTBOX_TABLE.c.created_at, EOS_OUTBOX_TABLE.c.outbox_id)
        .limit(1)
    )
    if tenant_id is not None:
        statement = statement.where(EOS_OUTBOX_TABLE.c.tenant_id == tenant_id)
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    return statement


def _event_from_row(row: object) -> EosOutboxEvent:
    try:
        values = dict(row)  # type: ignore[arg-type]
        payload = values["event_payload"]
        if not isinstance(payload, dict):
            raise TypeError
        payload_hash = validate_hash_ref(values["event_payload_hash"])
        if semantic_sha256_hash_ref(payload) != payload_hash:
            raise ValueError
        return EosOutboxEvent(
            outbox_id=_uuid("outbox_id", values["outbox_id"]),
            tenant_id=_tenant(values["tenant_id"]),
            event_id=_uuid("event_id", values["event_id"]),
            business_operation_id=_uuid(
                "business_operation_id", values["business_operation_id"]
            ),
            event_type=_event_type(values["event_type"]),
            event_payload=dict(payload),
            event_payload_hash=payload_hash,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid("EOS outbox event is malformed or has drifted.") from exc


def _receipt(
    value: object,
    event: EosOutboxEvent,
) -> EosOutboxPublishReceipt:
    if not isinstance(value, EosOutboxPublishReceipt):
        raise _invalid("EOS outbox transport receipt is invalid.")
    if _uuid("receipt event_id", value.event_id) != event.event_id:
        raise _invalid("EOS outbox transport receipt event binding is invalid.")
    try:
        payload_hash = validate_hash_ref(value.event_payload_hash)
    except ValueError as exc:
        raise _invalid("EOS outbox transport receipt hash is invalid.") from exc
    if payload_hash != event.event_payload_hash:
        raise _invalid("EOS outbox transport receipt hash binding is invalid.")
    if (
        not isinstance(value.receipt_ref, str)
        or not 1 <= len(value.receipt_ref) <= 512
        or value.receipt_ref.strip() != value.receipt_ref
        or not value.receipt_ref.isprintable()
    ):
        raise _invalid("EOS outbox transport receipt reference is invalid.")
    return EosOutboxPublishReceipt(
        event_id=event.event_id,
        event_payload_hash=payload_hash,
        receipt_ref=value.receipt_ref,
    )


def _record_attempt(
    session: Session,
    event: EosOutboxEvent,
    *,
    attempt_count: int,
    attempted_at: datetime,
    published_at: datetime | None,
) -> None:
    delivery_state = "PUBLISHED" if published_at is not None else "PENDING"
    result = session.execute(
        EOS_OUTBOX_TABLE.update()
        .where(
            EOS_OUTBOX_TABLE.c.outbox_id == event.outbox_id,
            EOS_OUTBOX_TABLE.c.tenant_id == event.tenant_id,
            EOS_OUTBOX_TABLE.c.delivery_state == "PENDING",
        )
        .values(
            delivery_state=delivery_state,
            attempt_count=attempt_count,
            updated_at=attempted_at,
            published_at=published_at,
        )
    )
    if int(result.rowcount or 0) != 1:
        raise EosOutboxPublicationError(
            "EOS_OUTBOX_CLAIM_CONFLICT",
            "EOS outbox publication claim changed before completion.",
            retryable=True,
        )


def _result(
    event: EosOutboxEvent,
    *,
    delivery_state: str,
    attempt_count: int,
    retry_required: bool,
    receipt_ref: str | None,
    error_code: str | None,
) -> EosOutboxPublicationResult:
    return EosOutboxPublicationResult(
        outbox_id=event.outbox_id,
        event_id=event.event_id,
        event_payload_hash=event.event_payload_hash,
        delivery_state=delivery_state,
        attempt_count=attempt_count,
        retry_required=retry_required,
        receipt_ref=receipt_ref,
        error_code=error_code,
    )


def _optional_tenant(value: object) -> str | None:
    return None if value is None else _tenant(value)


def _tenant(value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid("tenant_id has an invalid format.")
    return value


def _event_type(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or value.strip() != value
        or not value.isprintable()
    ):
        raise _invalid("event_type has an invalid format.")
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid(f"{field_name} must be a UUID.") from exc


def _attempt_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid("EOS outbox attempt_count is invalid.")
    return value


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("EOS outbox clock must return a timezone-aware datetime.")
    return value


def _invalid(detail: str) -> EosOutboxPublicationError:
    return EosOutboxPublicationError(
        "EOS_OUTBOX_PUBLICATION_INVALID",
        detail,
        retryable=False,
    )
