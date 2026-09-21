from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_cx.ingestion_orchestration import validate_ingestion_run


CX_INGEST_RUN_TABLE = "cx_ingest_runs"


@dataclass(frozen=True)
class IngestionRunRepositoryError(Exception):
    error_code: str
    detail: str
    status_code: int = 409

    def __str__(self) -> str:
        return self.detail


class IngestionRunRepository(Protocol):
    def create(self, run: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def save(
        self,
        run: Mapping[str, Any],
        *,
        expected_checkpoint_version: int,
    ) -> dict[str, Any]:
        ...

    def get(
        self,
        run_id: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        ...

    def find_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        ...

    def list_for_document(
        self,
        document_id: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> list[dict[str, Any]]:
        ...


@dataclass
class InMemoryIngestionRunRepository:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    run_ids_by_owner_key: dict[tuple[str, str, str], str] = field(
        default_factory=dict
    )

    def create(self, run: Mapping[str, Any]) -> dict[str, Any]:
        normalized = validate_ingestion_run(run)
        key = _owner_key(normalized)
        existing_id = self.run_ids_by_owner_key.get(key)
        if existing_id is not None:
            return deepcopy(self.records[existing_id])
        self.records[normalized["run_id"]] = deepcopy(normalized)
        self.run_ids_by_owner_key[key] = normalized["run_id"]
        return deepcopy(normalized)

    def save(
        self,
        run: Mapping[str, Any],
        *,
        expected_checkpoint_version: int,
    ) -> dict[str, Any]:
        normalized = validate_ingestion_run(run)
        existing = self.records.get(normalized["run_id"])
        if existing is None or not _same_owner(existing, normalized):
            raise _not_found()
        if existing["checkpoint_version"] != expected_checkpoint_version:
            raise _checkpoint_conflict()
        if normalized["checkpoint_version"] != expected_checkpoint_version + 1:
            raise _checkpoint_increment_invalid()
        if _immutable_identity(existing) != _immutable_identity(normalized):
            raise _identity_conflict()
        self.records[normalized["run_id"]] = deepcopy(normalized)
        return deepcopy(normalized)

    def get(
        self,
        run_id: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        record = self.records.get(run_id)
        if record is None or not _visible_to_owner(
            record,
            tenant_id=tenant_id,
            owner_subject_id=owner_subject_id,
        ):
            return None
        return deepcopy(record)

    def find_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        run_id = self.run_ids_by_owner_key.get(
            (tenant_id, owner_subject_id, idempotency_key)
        )
        return (
            deepcopy(self.records[run_id])
            if run_id is not None and run_id in self.records
            else None
        )

    def list_for_document(
        self,
        document_id: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> list[dict[str, Any]]:
        return sorted(
            (
                deepcopy(record)
                for record in self.records.values()
                if record["document_id"] == document_id
                and _visible_to_owner(
                    record,
                    tenant_id=tenant_id,
                    owner_subject_id=owner_subject_id,
                )
            ),
            key=lambda record: (record["updated_at"], record["run_id"]),
            reverse=True,
        )


class SqlAlchemyIngestionRunRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        source_kind: str = "postgres-write",
        database_env: str | None = None,
        redacted_database_url: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.source_kind = source_kind
        self.database_env = database_env
        self.redacted_database_url = redacted_database_url

    def create(self, run: Mapping[str, Any]) -> dict[str, Any]:
        normalized = validate_ingestion_run(run)
        try:
            return self._run_in_transaction(
                lambda session: self._create_in_session(session, normalized)
            )
        except IngestionRunRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def save(
        self,
        run: Mapping[str, Any],
        *,
        expected_checkpoint_version: int,
    ) -> dict[str, Any]:
        normalized = validate_ingestion_run(run)
        if normalized["checkpoint_version"] != expected_checkpoint_version + 1:
            raise _checkpoint_increment_invalid()
        try:
            return self._run_in_transaction(
                lambda session: self._save_in_session(
                    session,
                    normalized,
                    expected_checkpoint_version=expected_checkpoint_version,
                )
            )
        except IngestionRunRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(
        self,
        run_id: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        return self._select_one(
            "run_id = :run_id AND tenant_ref_id = :tenant_id "
            "AND owner_subject_ref_id = :owner_subject_id",
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "owner_subject_id": owner_subject_id,
            },
        )

    def find_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        return self._select_one(
            "idempotency_key = :idempotency_key AND tenant_ref_id = :tenant_id "
            "AND owner_subject_ref_id = :owner_subject_id",
            {
                "idempotency_key": idempotency_key,
                "tenant_id": tenant_id,
                "owner_subject_id": owner_subject_id,
            },
        )

    def list_for_document(
        self,
        document_id: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        _select_sql(
                            "document_id = :document_id "
                            "AND tenant_ref_id = :tenant_id "
                            "AND owner_subject_ref_id = :owner_subject_id"
                        )
                        + " ORDER BY updated_at DESC, run_id DESC"
                    ),
                    {
                        "document_id": document_id,
                        "tenant_id": tenant_id,
                        "owner_subject_id": owner_subject_id,
                    },
                ).mappings().all()
                return [_record_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def _create_in_session(
        self,
        session: Session,
        run: dict[str, Any],
    ) -> dict[str, Any]:
        session.execute(text(_insert_sql(session)), _persistence_params(run))
        row = _select_owner_key_in_session(session, run)
        if row is None:
            raise _unavailable()
        return _record_from_row(row)

    def _save_in_session(
        self,
        session: Session,
        run: dict[str, Any],
        *,
        expected_checkpoint_version: int,
    ) -> dict[str, Any]:
        params = {
            **_persistence_params(run),
            "expected_checkpoint_version": expected_checkpoint_version,
        }
        result = session.execute(text(_update_sql(session)), params)
        if result.rowcount != 1:
            existing = session.execute(
                text(
                    _select_sql(
                        "run_id = :run_id AND tenant_ref_id = :tenant_ref_id "
                        "AND owner_subject_ref_id = :owner_subject_ref_id"
                    )
                ),
                params,
            ).mappings().first()
            if existing is None:
                raise _not_found()
            existing_record = _record_from_row(existing)
            if _immutable_identity(existing_record) != _immutable_identity(run):
                raise _identity_conflict()
            raise _checkpoint_conflict()
        saved = session.execute(
            text(_select_sql("run_id = :run_id")),
            {"run_id": run["run_id"]},
        ).mappings().first()
        if saved is None:
            raise _unavailable()
        return _record_from_row(saved)

    def _select_one(
        self,
        where_clause: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(_select_sql(where_clause)),
                    dict(params),
                ).mappings().first()
                return _record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

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


def _insert_sql(session: Session) -> str:
    step_states = _json_expression(session, "step_states")
    last_error = _json_expression(session, "last_error")
    return f"""
        INSERT INTO {CX_INGEST_RUN_TABLE} (
            run_id, run_schema_version, document_id, job_id, idempotency_key,
            status, current_step, step_states, attempt_count, max_attempts,
            checkpoint_version, tenant_ref_type, tenant_ref_id,
            owner_subject_ref_type, owner_subject_ref_id, trace_id, request_id,
            lease_owner, lease_expires_at, retry_at, last_error,
            created_at, updated_at, completed_at
        ) VALUES (
            :run_id, :run_schema_version, :document_id, :job_id, :idempotency_key,
            :status, :current_step, {step_states}, :attempt_count, :max_attempts,
            :checkpoint_version, :tenant_ref_type, :tenant_ref_id,
            :owner_subject_ref_type, :owner_subject_ref_id, :trace_id, :request_id,
            :lease_owner, :lease_expires_at, :retry_at, {last_error},
            :created_at, :updated_at, :completed_at
        )
        ON CONFLICT (tenant_ref_id, owner_subject_ref_id, idempotency_key)
        DO NOTHING
    """


def _update_sql(session: Session) -> str:
    step_states = _json_expression(session, "step_states")
    last_error = _json_expression(session, "last_error")
    return f"""
        UPDATE {CX_INGEST_RUN_TABLE}
        SET status = :status,
            current_step = :current_step,
            step_states = {step_states},
            attempt_count = :attempt_count,
            max_attempts = :max_attempts,
            checkpoint_version = :checkpoint_version,
            trace_id = :trace_id,
            request_id = :request_id,
            lease_owner = :lease_owner,
            lease_expires_at = :lease_expires_at,
            retry_at = :retry_at,
            last_error = {last_error},
            updated_at = :updated_at,
            completed_at = :completed_at
        WHERE run_id = :run_id
          AND document_id = :document_id
          AND job_id = :job_id
          AND idempotency_key = :idempotency_key
          AND tenant_ref_type = :tenant_ref_type
          AND tenant_ref_id = :tenant_ref_id
          AND owner_subject_ref_type = :owner_subject_ref_type
          AND owner_subject_ref_id = :owner_subject_ref_id
          AND checkpoint_version = :expected_checkpoint_version
    """


def _select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            run_id, run_schema_version, document_id, job_id, idempotency_key,
            status, current_step, step_states, attempt_count, max_attempts,
            checkpoint_version, tenant_ref_type, tenant_ref_id,
            owner_subject_ref_type, owner_subject_ref_id, trace_id, request_id,
            lease_owner, lease_expires_at, retry_at, last_error,
            created_at, updated_at, completed_at
        FROM {CX_INGEST_RUN_TABLE}
        WHERE {where_clause}
    """


def _select_owner_key_in_session(
    session: Session,
    run: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    return session.execute(
        text(
            _select_sql(
                "tenant_ref_id = :tenant_ref_id "
                "AND owner_subject_ref_id = :owner_subject_ref_id "
                "AND idempotency_key = :idempotency_key"
            )
        ),
        _persistence_params(run),
    ).mappings().first()


def _persistence_params(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run["run_id"],
        "run_schema_version": run["run_schema_version"],
        "document_id": run["document_id"],
        "job_id": run["job_id"],
        "idempotency_key": run["idempotency_key"],
        "status": run["status"],
        "current_step": run["current_step"],
        "step_states": json.dumps(run["step_states"], separators=(",", ":")),
        "attempt_count": run["attempt_count"],
        "max_attempts": run["max_attempts"],
        "checkpoint_version": run["checkpoint_version"],
        "tenant_ref_type": run["tenant_ref"]["type"],
        "tenant_ref_id": run["tenant_ref"]["id"],
        "owner_subject_ref_type": run["owner_subject_ref"]["type"],
        "owner_subject_ref_id": run["owner_subject_ref"]["id"],
        "trace_id": run["trace_id"],
        "request_id": run["request_id"],
        "lease_owner": run["lease_owner"],
        "lease_expires_at": run["lease_expires_at"],
        "retry_at": run["retry_at"],
        "last_error": (
            json.dumps(run["last_error"], separators=(",", ":"))
            if run["last_error"] is not None
            else None
        ),
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
        "completed_at": run["completed_at"],
    }


def _record_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    record = {
        "run_schema_version": str(row["run_schema_version"]),
        "run_id": str(row["run_id"]),
        "document_id": str(row["document_id"]),
        "job_id": str(row["job_id"]),
        "idempotency_key": str(row["idempotency_key"]),
        "status": str(row["status"]),
        "current_step": row["current_step"],
        "step_states": _json_value(row["step_states"], {}),
        "attempt_count": int(row["attempt_count"]),
        "max_attempts": int(row["max_attempts"]),
        "checkpoint_version": int(row["checkpoint_version"]),
        "tenant_ref": {
            "type": str(row["tenant_ref_type"]),
            "id": str(row["tenant_ref_id"]),
        },
        "owner_subject_ref": {
            "type": str(row["owner_subject_ref_type"]),
            "id": str(row["owner_subject_ref_id"]),
        },
        "trace_id": str(row["trace_id"]),
        "request_id": str(row["request_id"]),
        "lease_owner": row["lease_owner"],
        "lease_expires_at": _timestamp(row["lease_expires_at"]),
        "retry_at": _timestamp(row["retry_at"]),
        "last_error": _json_value(row["last_error"], None),
        "created_at": _timestamp(row["created_at"]),
        "updated_at": _timestamp(row["updated_at"]),
        "completed_at": _timestamp(row["completed_at"]),
    }
    return validate_ingestion_run(record)


def _json_expression(session: Session, parameter: str) -> str:
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        return f"CAST(:{parameter} AS JSONB)"
    return f":{parameter}"


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return deepcopy(fallback)
    if isinstance(value, str):
        return json.loads(value)
    return deepcopy(value)


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        observed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _owner_key(run: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(run["tenant_ref"]["id"]),
        str(run["owner_subject_ref"]["id"]),
        str(run["idempotency_key"]),
    )


def _immutable_identity(run: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        run["run_id"],
        run["document_id"],
        run["job_id"],
        run["idempotency_key"],
        run["tenant_ref"],
        run["owner_subject_ref"],
        run["created_at"],
    )


def _same_owner(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        left["tenant_ref"] == right["tenant_ref"]
        and left["owner_subject_ref"] == right["owner_subject_ref"]
    )


def _visible_to_owner(
    run: Mapping[str, Any],
    *,
    tenant_id: str,
    owner_subject_id: str,
) -> bool:
    return (
        run["tenant_ref"]["id"] == tenant_id
        and run["owner_subject_ref"]["id"] == owner_subject_id
    )


def _not_found() -> IngestionRunRepositoryError:
    return IngestionRunRepositoryError(
        error_code="cx.ingestion_run.not_found",
        detail="Ingestion run was not found in the owner scope.",
        status_code=404,
    )


def _checkpoint_conflict() -> IngestionRunRepositoryError:
    return IngestionRunRepositoryError(
        error_code="cx.ingestion_run.checkpoint_conflict",
        detail="Ingestion run checkpoint changed before persistence.",
        status_code=409,
    )


def _checkpoint_increment_invalid() -> IngestionRunRepositoryError:
    return IngestionRunRepositoryError(
        error_code="cx.ingestion_run.checkpoint_increment_invalid",
        detail="Persisted checkpoint version must advance by exactly one.",
        status_code=422,
    )


def _identity_conflict() -> IngestionRunRepositoryError:
    return IngestionRunRepositoryError(
        error_code="cx.ingestion_run.identity_conflict",
        detail="Immutable ingestion run identity cannot be changed.",
        status_code=409,
    )


def _unavailable() -> IngestionRunRepositoryError:
    return IngestionRunRepositoryError(
        error_code="cx.ingestion_run.repository_unavailable",
        detail="CX ingestion run repository is unavailable.",
        status_code=503,
    )
