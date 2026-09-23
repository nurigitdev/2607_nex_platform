from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
import threading
from typing import Any, Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_cx.access_context import CxAccessContext
from nex_cx.generation_private_output import persist_generation_output
from nex_cx.generation_repository import (
    GenerationRuntimeRepository,
    GenerationRuntimeRepositoryError,
)
from nex_cx.owner_lineage import build_owner_lineage
from nex_cx.private_content import CxPrivateContentError, CxPrivateTextStore


CX_GENERATION_ADMISSION_SCHEMA_VERSION = "cx_generation_admission.v1"
CX_GENERATION_ADMISSION_TABLE = "cx_gen_admissions"
DEFAULT_GENERATION_LEASE_SECONDS = 120
_TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED"})


@dataclass(frozen=True)
class GroundedGenerationRuntimeError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class GroundedGenerationAdmission:
    decision: str
    admission: dict[str, Any]
    mo_payload: dict[str, Any]
    existing_record: dict[str, Any] | None = None

    @property
    def is_replay(self) -> bool:
        return self.decision == "REPLAY"


@runtime_checkable
class GenerationAdmissionRepository(Protocol):
    def reserve(
        self,
        admission: Mapping[str, Any],
        *,
        observed_at: datetime,
    ) -> dict[str, Any]:
        ...

    def mark_terminal(
        self,
        admission_id: str,
        *,
        access_context: CxAccessContext,
        cx_generation_id: str,
        status: str,
        observed_at: datetime,
    ) -> dict[str, Any]:
        ...

    def get(
        self,
        admission_id: str,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any] | None:
        ...


@dataclass
class InMemoryGenerationAdmissionRepository:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reserve(
        self,
        admission: Mapping[str, Any],
        *,
        observed_at: datetime,
    ) -> dict[str, Any]:
        candidate = _validate_admission(admission)
        owner_key = _owner_idempotency_key(candidate)
        with self._lock:
            existing = next(
                (
                    record
                    for record in self.records.values()
                    if _owner_idempotency_key(record) == owner_key
                ),
                None,
            )
            if existing is None:
                self.records[candidate["admission_id"]] = deepcopy(candidate)
                return {**deepcopy(candidate), "reservation_status": "NEW"}
            return _resolve_existing_reservation(
                existing,
                candidate=candidate,
                observed_at=_utc_datetime(observed_at),
                replace=lambda record: self.records.__setitem__(
                    record["admission_id"], deepcopy(record)
                ),
            )

    def mark_terminal(
        self,
        admission_id: str,
        *,
        access_context: CxAccessContext,
        cx_generation_id: str,
        status: str,
        observed_at: datetime,
    ) -> dict[str, Any]:
        terminal = _terminal_status(status)
        with self._lock:
            current = self.records.get(admission_id)
            if current is None or not _visible_to_owner(current, access_context):
                raise _admission_not_found()
            if current["cx_generation_id"] != cx_generation_id:
                raise _admission_conflict()
            if current["status"] in _TERMINAL_STATUSES:
                if current["status"] != terminal:
                    raise _admission_conflict()
                return deepcopy(current)
            completed = {
                **current,
                "status": terminal,
                "updated_at": _utc_datetime(observed_at),
                "completed_at": _utc_datetime(observed_at),
            }
            self.records[admission_id] = completed
            return deepcopy(completed)

    def get(
        self,
        admission_id: str,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self.records.get(admission_id)
            if record is None or not _visible_to_owner(record, access_context):
                return None
            return deepcopy(record)


class SqlAlchemyGenerationAdmissionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def reserve(
        self,
        admission: Mapping[str, Any],
        *,
        observed_at: datetime,
    ) -> dict[str, Any]:
        candidate = _validate_admission(admission)
        now = _utc_datetime(observed_at)
        try:
            return self._run_in_transaction(
                lambda session: self._reserve_in_session(session, candidate, now)
            )
        except GroundedGenerationRuntimeError:
            raise
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc

    def mark_terminal(
        self,
        admission_id: str,
        *,
        access_context: CxAccessContext,
        cx_generation_id: str,
        status: str,
        observed_at: datetime,
    ) -> dict[str, Any]:
        terminal = _terminal_status(status)
        params = {
            "admission_id": admission_id,
            "tenant_ref_id": access_context.tenant_id,
            "owner_subject_ref_id": access_context.subject_id,
            "cx_generation_id": cx_generation_id,
            "status": terminal,
            "observed_at": _utc_datetime(observed_at),
        }
        try:
            return self._run_in_transaction(
                lambda session: self._mark_terminal_in_session(session, params)
            )
        except GroundedGenerationRuntimeError:
            raise
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc

    def get(
        self,
        admission_id: str,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        _select_sql(
                            "admission_id = :admission_id "
                            "AND tenant_ref_id = :tenant_ref_id "
                            "AND owner_subject_ref_id = :owner_subject_ref_id"
                        )
                    ),
                    {
                        "admission_id": admission_id,
                        "tenant_ref_id": access_context.tenant_id,
                        "owner_subject_ref_id": access_context.subject_id,
                    },
                ).mappings().first()
                return _admission_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc

    def _reserve_in_session(
        self,
        session: Session,
        candidate: dict[str, Any],
        observed_at: datetime,
    ) -> dict[str, Any]:
        inserted = session.execute(text(_insert_sql()), candidate)
        row = session.execute(
            text(
                _select_sql(
                    "tenant_ref_id = :tenant_ref_id "
                    "AND owner_subject_ref_id = :owner_subject_ref_id "
                    "AND idempotency_key_hash = :idempotency_key_hash"
                )
            ),
            candidate,
        ).mappings().first()
        if row is None:
            raise _repository_unavailable()
        existing = _admission_from_row(row)
        if inserted.rowcount == 1:
            return {**existing, "reservation_status": "NEW"}
        _assert_same_request(existing, candidate)
        if (
            existing["status"] == "IN_PROGRESS"
            and existing["lease_expires_at"] <= observed_at
        ):
            reclaimed = session.execute(
                text(
                    f"""
                    UPDATE {CX_GENERATION_ADMISSION_TABLE}
                    SET trace_id = :trace_id,
                        request_id = :request_id,
                        lease_expires_at = :lease_expires_at,
                        updated_at = :updated_at
                    WHERE admission_id = :admission_id
                      AND status = 'IN_PROGRESS'
                      AND lease_expires_at <= :observed_at
                    """
                ),
                {**candidate, "observed_at": observed_at},
            )
            if reclaimed.rowcount == 1:
                return {**candidate, "reservation_status": "RECLAIMED"}
        return {
            **existing,
            "reservation_status": (
                "REPLAY" if existing["status"] in _TERMINAL_STATUSES
                else "IN_PROGRESS"
            ),
        }

    def _mark_terminal_in_session(
        self,
        session: Session,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = session.execute(
            text(
                f"""
                UPDATE {CX_GENERATION_ADMISSION_TABLE}
                SET status = :status,
                    updated_at = :observed_at,
                    completed_at = :observed_at
                WHERE admission_id = :admission_id
                  AND tenant_ref_id = :tenant_ref_id
                  AND owner_subject_ref_id = :owner_subject_ref_id
                  AND cx_generation_id = :cx_generation_id
                  AND status = 'IN_PROGRESS'
                """
            ),
            dict(params),
        )
        row = session.execute(
            text(
                _select_sql(
                    "admission_id = :admission_id "
                    "AND tenant_ref_id = :tenant_ref_id "
                    "AND owner_subject_ref_id = :owner_subject_ref_id"
                )
            ),
            dict(params),
        ).mappings().first()
        if row is None:
            raise _admission_not_found()
        saved = _admission_from_row(row)
        if saved["cx_generation_id"] != params["cx_generation_id"]:
            raise _admission_conflict()
        if result.rowcount != 1 and saved["status"] != params["status"]:
            raise _admission_conflict()
        return saved

    def _run_in_transaction(self, operation: Callable[[Session], Any]) -> Any:
        session = self._session_factory()
        try:
            try:
                result = operation(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
        finally:
            session.close()


@dataclass
class GroundedGenerationRuntime:
    admission_repository: GenerationAdmissionRepository
    execution_repository: GenerationRuntimeRepository
    private_output_store: CxPrivateTextStore
    lease_seconds: int = DEFAULT_GENERATION_LEASE_SECONDS
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def admit(
        self,
        *,
        source_payload: Mapping[str, Any],
        mo_payload: Mapping[str, Any],
        access_context: CxAccessContext,
        request_id: str,
        trace_id: str,
        idempotency_key: str | None,
    ) -> GroundedGenerationAdmission:
        now = _utc_datetime(self.clock())
        request_hash = generation_execution_request_hash(mo_payload)
        key_hash = generation_idempotency_key_hash(
            idempotency_key
            or _optional_text(source_payload.get("client_request_id"))
            or request_hash
        )
        generation_id = str(
            uuid5(
                NAMESPACE_URL,
                "cx-generation:"
                f"{access_context.tenant_id}:{access_context.subject_id}:{key_hash}",
            )
        )
        resolved_payload = deepcopy(dict(mo_payload))
        resolved_payload["cx_generation_id"] = generation_id
        resolved_payload["client_request_id"] = generation_id
        metadata = deepcopy(dict(resolved_payload.get("metadata", {})))
        metadata["generation_request_hash"] = request_hash
        resolved_payload["metadata"] = metadata
        admission = _build_admission(
            access_context=access_context,
            idempotency_key_hash=key_hash,
            execution_request_hash=request_hash,
            cx_generation_id=generation_id,
            trace_id=trace_id,
            request_id=request_id,
            observed_at=now,
            lease_seconds=self.lease_seconds,
        )
        reserved = self.admission_repository.reserve(admission, observed_at=now)
        status = reserved["reservation_status"]
        if status in {"NEW", "RECLAIMED"}:
            return GroundedGenerationAdmission(status, reserved, resolved_payload)

        try:
            existing = self.execution_repository.get(
                generation_id,
                access_context=access_context,
            )
        except GenerationRuntimeRepositoryError as exc:
            raise _execution_repository_error(exc) from exc
        if existing is not None:
            self.admission_repository.mark_terminal(
                reserved["admission_id"],
                access_context=access_context,
                cx_generation_id=generation_id,
                status=existing["status"],
                observed_at=now,
            )
            return GroundedGenerationAdmission(
                "REPLAY", reserved, resolved_payload, existing
            )
        if status == "REPLAY":
            raise GroundedGenerationRuntimeError(
                error_code="cx.generation_runtime.terminal_record_missing",
                detail="Generation admission is terminal but its execution record is unavailable.",
                status_code=503,
                retryable=True,
            )
        raise GroundedGenerationRuntimeError(
            error_code="cx.generation_runtime.in_progress",
            detail="An identical grounded generation request is already in progress.",
            status_code=409,
            retryable=True,
        )

    def persist_completed(
        self,
        *,
        admission: GroundedGenerationAdmission,
        execution_record: Mapping[str, Any],
        output_text: str,
        access_context: CxAccessContext,
    ) -> dict[str, Any]:
        output_hash = execution_record.get("response_metadata", {}).get("output_hash")
        if not isinstance(output_hash, str):
            raise GroundedGenerationRuntimeError(
                error_code="cx.generation_runtime.output_hash_missing",
                detail="Completed generation output hash is missing.",
                status_code=422,
            )
        try:
            private_output = persist_generation_output(
                private_text_store=self.private_output_store,
                access_context=access_context,
                cx_generation_id=admission.mo_payload["cx_generation_id"],
                output_text=output_text,
                expected_sha256=output_hash,
            )
            stored = self.execution_repository.save(
                execution_record,
                access_context=access_context,
                private_output_metadata=private_output,
            )
        except (CxPrivateContentError, GenerationRuntimeRepositoryError) as exc:
            raise GroundedGenerationRuntimeError(
                error_code=exc.error_code,
                detail=exc.detail,
                status_code=exc.status_code,
                retryable=bool(getattr(exc, "retryable", exc.status_code == 503)),
            ) from exc
        self._mark_terminal(admission, access_context, "COMPLETED")
        return stored

    def persist_failed(
        self,
        *,
        admission: GroundedGenerationAdmission,
        execution_record: Mapping[str, Any],
        access_context: CxAccessContext,
    ) -> dict[str, Any]:
        try:
            stored = self.execution_repository.save(
                execution_record,
                access_context=access_context,
                private_output_metadata=None,
            )
        except GenerationRuntimeRepositoryError as exc:
            raise GroundedGenerationRuntimeError(
                error_code=exc.error_code,
                detail=exc.detail,
                status_code=exc.status_code,
                retryable=exc.status_code == 503,
            ) from exc
        self._mark_terminal(admission, access_context, "FAILED")
        return stored

    def _mark_terminal(
        self,
        admission: GroundedGenerationAdmission,
        access_context: CxAccessContext,
        status: str,
    ) -> None:
        self.admission_repository.mark_terminal(
            admission.admission["admission_id"],
            access_context=access_context,
            cx_generation_id=admission.mo_payload["cx_generation_id"],
            status=status,
            observed_at=_utc_datetime(self.clock()),
        )


def generation_execution_request_hash(mo_payload: Mapping[str, Any]) -> str:
    metadata = dict(mo_payload.get("metadata", {}))
    metadata.pop("generation_request_hash", None)
    semantic_request = {
        "alias": mo_payload.get("alias"),
        "provider_capability": mo_payload.get("provider_capability"),
        "workload_class": mo_payload.get("workload_class"),
        "generation_profile": mo_payload.get("generation_profile"),
        "provider_prompt_package_hash": mo_payload.get(
            "provider_prompt_package_hash"
        ),
        "response_format": mo_payload.get("response_format"),
        "reasoning_mode": mo_payload.get("reasoning_mode", "provider_default"),
        "max_output_tokens": mo_payload.get("max_output_tokens"),
        "temperature": mo_payload.get("temperature"),
        "stream": mo_payload.get("stream"),
        "metadata": metadata,
    }
    return hashlib.sha256(
        json.dumps(
            semantic_request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def generation_idempotency_key_hash(value: object) -> str:
    if not isinstance(value, str):
        raise _idempotency_key_invalid()
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 200
        or any(ord(character) < 32 for character in normalized)
    ):
        raise _idempotency_key_invalid()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _build_admission(
    *,
    access_context: CxAccessContext,
    idempotency_key_hash: str,
    execution_request_hash: str,
    cx_generation_id: str,
    trace_id: str,
    request_id: str,
    observed_at: datetime,
    lease_seconds: int,
) -> dict[str, Any]:
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds < 1:
        raise GroundedGenerationRuntimeError(
            error_code="cx.generation_runtime.lease_invalid",
            detail="Generation runtime lease must be a positive integer.",
            status_code=500,
        )
    lineage = build_owner_lineage(access_context)
    admission_id = str(
        uuid5(
            NAMESPACE_URL,
            "cx-generation-admission:"
            f"{lineage.tenant_ref_id}:{lineage.owner_subject_ref_id}:"
            f"{idempotency_key_hash}",
        )
    )
    return {
        "admission_id": admission_id,
        "admission_schema_version": CX_GENERATION_ADMISSION_SCHEMA_VERSION,
        **lineage.to_columns(),
        "idempotency_key_hash": idempotency_key_hash,
        "execution_request_hash": execution_request_hash,
        "cx_generation_id": cx_generation_id,
        "status": "IN_PROGRESS",
        "trace_id": trace_id,
        "request_id": request_id,
        "lease_expires_at": observed_at + timedelta(seconds=lease_seconds),
        "created_at": observed_at,
        "updated_at": observed_at,
        "completed_at": None,
    }


def _validate_admission(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "admission_id",
        "admission_schema_version",
        "tenant_ref_type",
        "tenant_ref_id",
        "owner_subject_ref_type",
        "owner_subject_ref_id",
        "idempotency_key_hash",
        "execution_request_hash",
        "cx_generation_id",
        "status",
        "trace_id",
        "request_id",
        "lease_expires_at",
        "created_at",
        "updated_at",
        "completed_at",
    }
    if set(value) != required:
        raise _admission_invalid("Generation admission fields are invalid.")
    normalized = deepcopy(dict(value))
    if normalized["admission_schema_version"] != CX_GENERATION_ADMISSION_SCHEMA_VERSION:
        raise _admission_invalid("Generation admission schema is invalid.")
    if normalized["status"] not in {"IN_PROGRESS", "COMPLETED", "FAILED"}:
        raise _admission_invalid("Generation admission status is invalid.")
    for field_name in ("idempotency_key_hash", "execution_request_hash"):
        digest = normalized[field_name]
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise _admission_invalid(f"{field_name} is invalid.")
    for field_name in ("lease_expires_at", "created_at", "updated_at"):
        normalized[field_name] = _utc_datetime(normalized[field_name])
    if normalized["completed_at"] is not None:
        normalized["completed_at"] = _utc_datetime(normalized["completed_at"])
    return normalized


def _resolve_existing_reservation(
    existing: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    observed_at: datetime,
    replace: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    _assert_same_request(existing, candidate)
    if existing["status"] in _TERMINAL_STATUSES:
        return {**deepcopy(dict(existing)), "reservation_status": "REPLAY"}
    if _utc_datetime(existing["lease_expires_at"]) <= observed_at:
        reclaimed = {
            **deepcopy(dict(existing)),
            "trace_id": candidate["trace_id"],
            "request_id": candidate["request_id"],
            "lease_expires_at": candidate["lease_expires_at"],
            "updated_at": candidate["updated_at"],
        }
        replace(reclaimed)
        return {**reclaimed, "reservation_status": "RECLAIMED"}
    return {**deepcopy(dict(existing)), "reservation_status": "IN_PROGRESS"}


def _assert_same_request(
    existing: Mapping[str, Any], candidate: Mapping[str, Any]
) -> None:
    if (
        existing["execution_request_hash"] != candidate["execution_request_hash"]
        or existing["cx_generation_id"] != candidate["cx_generation_id"]
    ):
        raise GroundedGenerationRuntimeError(
            error_code="cx.generation_runtime.idempotency_conflict",
            detail="Idempotency key is already bound to another generation request.",
            status_code=409,
        )


def _insert_sql() -> str:
    return f"""
        INSERT INTO {CX_GENERATION_ADMISSION_TABLE} (
            admission_id, admission_schema_version,
            tenant_ref_type, tenant_ref_id,
            owner_subject_ref_type, owner_subject_ref_id,
            idempotency_key_hash, execution_request_hash, cx_generation_id,
            status, trace_id, request_id, lease_expires_at,
            created_at, updated_at, completed_at
        ) VALUES (
            :admission_id, :admission_schema_version,
            :tenant_ref_type, :tenant_ref_id,
            :owner_subject_ref_type, :owner_subject_ref_id,
            :idempotency_key_hash, :execution_request_hash, :cx_generation_id,
            :status, :trace_id, :request_id, :lease_expires_at,
            :created_at, :updated_at, :completed_at
        )
        ON CONFLICT (tenant_ref_id, owner_subject_ref_id, idempotency_key_hash)
        DO NOTHING
    """


def _select_sql(where_clause: str) -> str:
    return f"""
        SELECT admission_id, admission_schema_version,
               tenant_ref_type, tenant_ref_id,
               owner_subject_ref_type, owner_subject_ref_id,
               idempotency_key_hash, execution_request_hash, cx_generation_id,
               status, trace_id, request_id, lease_expires_at,
               created_at, updated_at, completed_at
        FROM {CX_GENERATION_ADMISSION_TABLE}
        WHERE {where_clause}
    """


def _admission_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_admission(
        {
            "admission_id": str(row["admission_id"]),
            "admission_schema_version": str(row["admission_schema_version"]),
            "tenant_ref_type": str(row["tenant_ref_type"]),
            "tenant_ref_id": str(row["tenant_ref_id"]),
            "owner_subject_ref_type": str(row["owner_subject_ref_type"]),
            "owner_subject_ref_id": str(row["owner_subject_ref_id"]),
            "idempotency_key_hash": str(row["idempotency_key_hash"]),
            "execution_request_hash": str(row["execution_request_hash"]),
            "cx_generation_id": str(row["cx_generation_id"]),
            "status": str(row["status"]),
            "trace_id": str(row["trace_id"]),
            "request_id": str(row["request_id"]),
            "lease_expires_at": row["lease_expires_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }
    )


def _owner_idempotency_key(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(record["tenant_ref_id"]),
        str(record["owner_subject_ref_id"]),
        str(record["idempotency_key_hash"]),
    )


def _visible_to_owner(
    record: Mapping[str, Any], access_context: CxAccessContext
) -> bool:
    return (
        record["tenant_ref_id"] == access_context.tenant_id
        and record["owner_subject_ref_id"] == access_context.subject_id
    )


def _terminal_status(status: str) -> str:
    if status not in _TERMINAL_STATUSES:
        raise _admission_invalid("Generation terminal status is invalid.")
    return status


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    observed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _idempotency_key_invalid() -> GroundedGenerationRuntimeError:
    return GroundedGenerationRuntimeError(
        error_code="cx.generation_runtime.idempotency_key_invalid",
        detail="Idempotency-Key must contain 1 to 200 printable characters.",
        status_code=422,
    )


def _admission_invalid(detail: str) -> GroundedGenerationRuntimeError:
    return GroundedGenerationRuntimeError(
        error_code="cx.generation_runtime.admission_invalid",
        detail=detail,
        status_code=422,
    )


def _admission_not_found() -> GroundedGenerationRuntimeError:
    return GroundedGenerationRuntimeError(
        error_code="cx.generation_runtime.admission_not_found",
        detail="Generation admission was not found in the owner scope.",
        status_code=404,
    )


def _admission_conflict() -> GroundedGenerationRuntimeError:
    return GroundedGenerationRuntimeError(
        error_code="cx.generation_runtime.admission_conflict",
        detail="Generation admission terminal state conflicts with the execution.",
        status_code=409,
    )


def _repository_unavailable() -> GroundedGenerationRuntimeError:
    return GroundedGenerationRuntimeError(
        error_code="cx.generation_runtime.admission_repository_unavailable",
        detail="CX generation admission repository is unavailable.",
        status_code=503,
        retryable=True,
    )


def _execution_repository_error(
    exc: GenerationRuntimeRepositoryError,
) -> GroundedGenerationRuntimeError:
    return GroundedGenerationRuntimeError(
        error_code=exc.error_code,
        detail=exc.detail,
        status_code=exc.status_code,
        retryable=exc.status_code == 503,
    )
