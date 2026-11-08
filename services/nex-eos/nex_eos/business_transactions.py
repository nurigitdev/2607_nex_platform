from __future__ import annotations

import json
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_runtime import SqlAlchemyUnitOfWork, build_unit_of_work
from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

EOS_EVENT_TYPES = frozenset(
    {
        "BUSINESS_TRANSACTION_COMMITTED",
        "VOUCHER_DRAFT_CREATED",
    }
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OPERATION = re.compile(r"^[A-Z][A-Z0-9_.]{0,127}$")

EOS_METADATA = MetaData()
EOS_BUSINESS_OPERATION_TABLE = Table(
    "eos_business_operation",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("business_operation_id", Uuid(as_uuid=False), primary_key=True),
    Column("idempotency_key", String(256), nullable=False),
    Column("operation", String(128), nullable=False),
    Column("payload_hash", String(71), nullable=False),
    Column("commit_state", String(32), nullable=False),
    Column("result_json", JSON(none_as_null=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("committed_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "tenant_id",
        "idempotency_key",
        name="ux_eos_bo_idempotency",
    ),
)
EOS_IDEMPOTENCY_TABLE = Table(
    "eos_idempotency",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("idempotency_key", String(256), primary_key=True),
    Column("business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("operation", String(128), nullable=False),
    Column("payload_hash", String(71), nullable=False),
    Column("idempotency_state", String(16), nullable=False),
    Column("result_json", JSON(none_as_null=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "tenant_id",
        "business_operation_id",
        name="ux_eos_idem_operation",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_idem_operation",
    ),
)
EOS_OUTBOX_TABLE = Table(
    "eos_outbox",
    EOS_METADATA,
    Column("outbox_id", Uuid(as_uuid=False), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("event_id", Uuid(as_uuid=False), nullable=False),
    Column("business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("event_type", String(128), nullable=False),
    Column("event_payload", JSON, nullable=False),
    Column("event_payload_hash", String(71), nullable=False),
    Column("delivery_state", String(16), nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("tenant_id", "event_id", name="ux_eos_outbox_event"),
    UniqueConstraint(
        "tenant_id",
        "business_operation_id",
        "event_type",
        name="ux_eos_outbox_operation_event",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_outbox_operation",
    ),
)

BusinessMutation = Callable[[Session | None], Mapping[str, Any]]
IdentifierFactory = Callable[[], str]
Clock = Callable[[], datetime]


class EosBusinessOperationError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class EosBusinessOperationRequest:
    tenant_id: str
    business_operation_id: str
    idempotency_key: str
    operation: str
    payload_hash: str
    event_type: str = "BUSINESS_TRANSACTION_COMMITTED"


@dataclass(frozen=True)
class EosBusinessTransactionResult:
    created: bool
    tenant_id: str
    business_operation_id: str
    idempotency_key: str
    operation: str
    payload_hash: str
    commit_state: str
    result: dict[str, Any]
    outbox_id: str
    event_id: str
    event_type: str
    event_payload_hash: str

    def to_public_projection(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "tenant_id": self.tenant_id,
            "business_operation_id": self.business_operation_id,
            "idempotency_key": self.idempotency_key,
            "operation": self.operation,
            "payload_hash": self.payload_hash,
            "commit_state": self.commit_state,
            "result": _json_object(self.result, field_name="result"),
            "outbox": {
                "outbox_id": self.outbox_id,
                "event_id": self.event_id,
                "event_type": self.event_type,
                "event_payload_hash": self.event_payload_hash,
                "delivery_state": "PENDING",
            },
        }


class EosBusinessTransactionCoordinator(Protocol):
    def execute(
        self,
        request: EosBusinessOperationRequest,
        mutation: BusinessMutation,
    ) -> EosBusinessTransactionResult: ...


class InMemoryEosBusinessTransactionCoordinator:
    def __init__(
        self,
        *,
        id_factory: IdentifierFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._operations: dict[tuple[str, str], dict[str, Any]] = {}
        self._idempotency: dict[tuple[str, str], dict[str, Any]] = {}
        self._outbox: dict[tuple[str, str], dict[str, Any]] = {}

    def execute(
        self,
        request: EosBusinessOperationRequest,
        mutation: BusinessMutation,
    ) -> EosBusinessTransactionResult:
        normalized = _normalize_request(request)
        with self._lock:
            operation = self._operations.get(
                (normalized.tenant_id, normalized.business_operation_id)
            )
            idempotency = self._idempotency.get(
                (normalized.tenant_id, normalized.idempotency_key)
            )
            outbox = _memory_outbox_for_operation(self._outbox, normalized)
            existing = _resolve_existing(
                normalized,
                operation=operation,
                idempotency=idempotency,
                outbox=outbox,
            )
            if existing is not None:
                return existing

            result = _run_mutation(mutation, None)
            now = _aware_datetime(self._clock())
            outbox_id = _uuid("outbox_id", self._id_factory())
            event_id = _uuid("event_id", self._id_factory())
            event_payload = _event_payload(normalized, result)
            event_payload_hash = semantic_sha256_hash_ref(event_payload)
            operation = _operation_record(normalized, result, now)
            idempotency = _idempotency_record(normalized, result, now)
            outbox = _outbox_record(
                normalized,
                outbox_id=outbox_id,
                event_id=event_id,
                event_payload=event_payload,
                event_payload_hash=event_payload_hash,
                now=now,
            )
            self._operations[
                (normalized.tenant_id, normalized.business_operation_id)
            ] = operation
            self._idempotency[(normalized.tenant_id, normalized.idempotency_key)] = (
                idempotency
            )
            self._outbox[(normalized.tenant_id, outbox_id)] = outbox
            return _transaction_result(
                normalized,
                result=result,
                outbox=outbox,
                created=True,
            )

    def record_counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "business_operations": len(self._operations),
                "idempotency": len(self._idempotency),
                "outbox": len(self._outbox),
            }


class SqlAlchemyEosBusinessTransactionCoordinator:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        id_factory: IdentifierFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        request: EosBusinessOperationRequest,
        mutation: BusinessMutation,
    ) -> EosBusinessTransactionResult:
        normalized = _normalize_request(request)
        try:
            with self._transaction() as transaction:
                existing = _load_existing(transaction.db, normalized)
                if existing is not None:
                    result = existing
                else:
                    result = self._execute_new(transaction.db, normalized, mutation)
            return result
        except IntegrityError as exc:
            replay = self._load_after_integrity_conflict(normalized)
            if replay is not None:
                return replay
            raise _persistence_error() from exc
        except EosBusinessOperationError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def _execute_new(
        self,
        session: Session,
        request: EosBusinessOperationRequest,
        mutation: BusinessMutation,
    ) -> EosBusinessTransactionResult:
        started_at = _aware_datetime(self._clock())
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=request.tenant_id,
                business_operation_id=request.business_operation_id,
                idempotency_key=request.idempotency_key,
                operation=request.operation,
                payload_hash=request.payload_hash,
                commit_state="PENDING",
                result_json=None,
                created_at=started_at,
                committed_at=None,
            )
        )
        session.execute(
            EOS_IDEMPOTENCY_TABLE.insert().values(
                tenant_id=request.tenant_id,
                idempotency_key=request.idempotency_key,
                business_operation_id=request.business_operation_id,
                operation=request.operation,
                payload_hash=request.payload_hash,
                idempotency_state="IN_PROGRESS",
                result_json=None,
                created_at=started_at,
                completed_at=None,
            )
        )

        result = _run_mutation(mutation, session)
        committed_at = _aware_datetime(self._clock())
        outbox_id = _uuid("outbox_id", self._id_factory())
        event_id = _uuid("event_id", self._id_factory())
        event_payload = _event_payload(request, result)
        event_payload_hash = semantic_sha256_hash_ref(event_payload)
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.update()
            .where(
                EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == request.tenant_id,
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == request.business_operation_id,
            )
            .values(
                commit_state="COMMITTED",
                result_json=result,
                committed_at=committed_at,
            )
        )
        session.execute(
            EOS_IDEMPOTENCY_TABLE.update()
            .where(
                EOS_IDEMPOTENCY_TABLE.c.tenant_id == request.tenant_id,
                EOS_IDEMPOTENCY_TABLE.c.idempotency_key == request.idempotency_key,
            )
            .values(
                idempotency_state="COMPLETED",
                result_json=result,
                completed_at=committed_at,
            )
        )
        outbox = _outbox_record(
            request,
            outbox_id=outbox_id,
            event_id=event_id,
            event_payload=event_payload,
            event_payload_hash=event_payload_hash,
            now=committed_at,
        )
        session.execute(EOS_OUTBOX_TABLE.insert().values(**outbox))
        return _transaction_result(
            request,
            result=result,
            outbox=outbox,
            created=True,
        )

    def _load_after_integrity_conflict(
        self,
        request: EosBusinessOperationRequest,
    ) -> EosBusinessTransactionResult | None:
        try:
            with self._transaction() as transaction:
                return _load_existing(transaction.db, request)
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def _transaction(self) -> SqlAlchemyUnitOfWork:
        return build_unit_of_work(self._session_factory)


def _load_existing(
    session: Session,
    request: EosBusinessOperationRequest,
) -> EosBusinessTransactionResult | None:
    operation = (
        session.execute(
            select(EOS_BUSINESS_OPERATION_TABLE).where(
                EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == request.tenant_id,
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == request.business_operation_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    idempotency = (
        session.execute(
            select(EOS_IDEMPOTENCY_TABLE).where(
                EOS_IDEMPOTENCY_TABLE.c.tenant_id == request.tenant_id,
                EOS_IDEMPOTENCY_TABLE.c.idempotency_key == request.idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    outbox = None
    if operation is not None:
        outbox = (
            session.execute(
                select(EOS_OUTBOX_TABLE).where(
                    EOS_OUTBOX_TABLE.c.tenant_id == request.tenant_id,
                    EOS_OUTBOX_TABLE.c.business_operation_id
                    == request.business_operation_id,
                )
            )
            .mappings()
            .one_or_none()
        )
    return _resolve_existing(
        request,
        operation=operation,
        idempotency=idempotency,
        outbox=outbox,
    )


def _resolve_existing(
    request: EosBusinessOperationRequest,
    *,
    operation: Mapping[str, Any] | None,
    idempotency: Mapping[str, Any] | None,
    outbox: Mapping[str, Any] | None,
) -> EosBusinessTransactionResult | None:
    if operation is None and idempotency is None:
        return None
    if operation is None or idempotency is None:
        raise _idempotency_conflict()
    expected = {
        "tenant_id": request.tenant_id,
        "business_operation_id": request.business_operation_id,
        "idempotency_key": request.idempotency_key,
        "operation": request.operation,
        "payload_hash": request.payload_hash,
    }
    for field_name, expected_value in expected.items():
        if str(operation[field_name]) != expected_value:
            raise _idempotency_conflict()
        if str(idempotency[field_name]) != expected_value:
            raise _idempotency_conflict()
    if (
        operation["commit_state"] != "COMMITTED"
        or idempotency["idempotency_state"] != "COMPLETED"
        or outbox is None
    ):
        raise _state_error()
    if outbox["event_type"] != request.event_type:
        raise _idempotency_conflict()
    result = _json_object(operation["result_json"], field_name="result_json")
    if result != _json_object(idempotency["result_json"], field_name="result_json"):
        raise _state_error()
    return _transaction_result(
        request,
        result=result,
        outbox=outbox,
        created=False,
    )


def _normalize_request(
    request: EosBusinessOperationRequest,
) -> EosBusinessOperationRequest:
    if not isinstance(request, EosBusinessOperationRequest):
        raise _request_error("request must be an EosBusinessOperationRequest")
    tenant_id = _pattern_text("tenant_id", request.tenant_id, _SCOPED_ID)
    business_operation_id = _uuid(
        "business_operation_id", request.business_operation_id
    )
    idempotency_key = _idempotency_key(request.idempotency_key)
    operation = _pattern_text("operation", request.operation, _OPERATION)
    try:
        payload_hash = validate_hash_ref(request.payload_hash)
    except ValueError as exc:
        raise _request_error("payload_hash must be a sha256 hash reference") from exc
    event_type = _pattern_text("event_type", request.event_type, _OPERATION)
    if event_type not in EOS_EVENT_TYPES:
        raise _request_error("event_type is not enabled for P8-S09")
    return EosBusinessOperationRequest(
        tenant_id=tenant_id,
        business_operation_id=business_operation_id,
        idempotency_key=idempotency_key,
        operation=operation,
        payload_hash=payload_hash,
        event_type=event_type,
    )


def _run_mutation(
    mutation: BusinessMutation,
    session: Session | None,
) -> dict[str, Any]:
    if not callable(mutation):
        raise _request_error("mutation must be callable")
    try:
        return _json_object(mutation(session), field_name="business result")
    except EosBusinessOperationError:
        raise
    except Exception as exc:
        raise EosBusinessOperationError(
            "EOS_BUSINESS_MUTATION_FAILED",
            "The EOS business mutation failed and was rolled back.",
            status_code=500,
        ) from exc


def _operation_record(
    request: EosBusinessOperationRequest,
    result: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    return {
        "tenant_id": request.tenant_id,
        "business_operation_id": request.business_operation_id,
        "idempotency_key": request.idempotency_key,
        "operation": request.operation,
        "payload_hash": request.payload_hash,
        "commit_state": "COMMITTED",
        "result_json": dict(result),
        "created_at": now,
        "committed_at": now,
    }


def _idempotency_record(
    request: EosBusinessOperationRequest,
    result: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    return {
        "tenant_id": request.tenant_id,
        "idempotency_key": request.idempotency_key,
        "business_operation_id": request.business_operation_id,
        "operation": request.operation,
        "payload_hash": request.payload_hash,
        "idempotency_state": "COMPLETED",
        "result_json": dict(result),
        "created_at": now,
        "completed_at": now,
    }


def _outbox_record(
    request: EosBusinessOperationRequest,
    *,
    outbox_id: str,
    event_id: str,
    event_payload: Mapping[str, Any],
    event_payload_hash: str,
    now: datetime,
) -> dict[str, Any]:
    return {
        "outbox_id": outbox_id,
        "tenant_id": request.tenant_id,
        "event_id": event_id,
        "business_operation_id": request.business_operation_id,
        "event_type": request.event_type,
        "event_payload": dict(event_payload),
        "event_payload_hash": event_payload_hash,
        "delivery_state": "PENDING",
        "attempt_count": 0,
        "created_at": now,
        "updated_at": now,
        "published_at": None,
    }


def _event_payload(
    request: EosBusinessOperationRequest,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "tenant_id": request.tenant_id,
        "business_operation_id": request.business_operation_id,
        "operation": request.operation,
    }
    result_ref = result.get("business_result_ref")
    if result_ref is not None:
        payload["business_result_ref"] = _bounded_text(
            "business_result_ref", result_ref, maximum=512
        )
    return payload


def _transaction_result(
    request: EosBusinessOperationRequest,
    *,
    result: Mapping[str, Any],
    outbox: Mapping[str, Any],
    created: bool,
) -> EosBusinessTransactionResult:
    return EosBusinessTransactionResult(
        created=created,
        tenant_id=request.tenant_id,
        business_operation_id=request.business_operation_id,
        idempotency_key=request.idempotency_key,
        operation=request.operation,
        payload_hash=request.payload_hash,
        commit_state="COMMITTED",
        result=_json_object(result, field_name="result"),
        outbox_id=str(outbox["outbox_id"]),
        event_id=str(outbox["event_id"]),
        event_type=str(outbox["event_type"]),
        event_payload_hash=str(outbox["event_payload_hash"]),
    )


def _memory_outbox_for_operation(
    outbox_records: Mapping[tuple[str, str], Mapping[str, Any]],
    request: EosBusinessOperationRequest,
) -> Mapping[str, Any] | None:
    matches = [
        record
        for record in outbox_records.values()
        if record["tenant_id"] == request.tenant_id
        and record["business_operation_id"] == request.business_operation_id
    ]
    return matches[0] if matches else None


def _json_object(value: object, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _request_error(f"{field_name} must be a JSON object")
    try:
        normalized = json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _request_error(f"{field_name} must contain valid JSON values") from exc
    return normalized


def _pattern_text(field_name: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _request_error(f"{field_name} has an invalid format")
    return value


def _idempotency_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or value.strip() != value
        or not value.isprintable()
    ):
        raise _request_error("idempotency_key has an invalid format")
    return value


def _bounded_text(field_name: str, value: object, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value.strip() != value
        or not value.isprintable()
    ):
        raise _request_error(f"{field_name} has an invalid format")
    return value


def _uuid(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise _request_error(f"{field_name} must be a UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise _request_error(f"{field_name} must be a UUID") from exc


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _request_error("clock must return a timezone-aware datetime")
    return value


def _request_error(detail: str) -> EosBusinessOperationError:
    return EosBusinessOperationError(
        "EOS_TRANSACTION_REQUEST_INVALID",
        detail,
        status_code=400,
    )


def _idempotency_conflict() -> EosBusinessOperationError:
    return EosBusinessOperationError(
        "EOS_IDEMPOTENCY_CONFLICT",
        "The idempotency identity is already bound to different semantics.",
        status_code=409,
    )


def _state_error() -> EosBusinessOperationError:
    return EosBusinessOperationError(
        "EOS_TRANSACTION_STATE_INVALID",
        "The persisted EOS transaction state is incomplete or inconsistent.",
        status_code=500,
    )


def _persistence_error() -> EosBusinessOperationError:
    return EosBusinessOperationError(
        "EOS_TRANSACTION_UNAVAILABLE",
        "The EOS transaction store is unavailable.",
        status_code=503,
        retryable=True,
    )
