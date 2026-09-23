from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_cx.access_context import CxAccessContext
from nex_cx.generation_persistence import (
    CxGenerationPersistenceError,
    build_generation_persistence_record,
)
from nex_cx.generation_private_output import (
    validate_generation_output_metadata,
)
from nex_cx.owner_lineage import CxOwnerLineageError, build_owner_lineage
from nex_cx.private_content import CxPrivateContentError


CX_GENERATION_RUNTIME_TABLE = "cx_generation_executions"


@dataclass(frozen=True)
class GenerationRuntimeRepositoryError(Exception):
    error_code: str
    detail: str
    status_code: int = 409

    def __str__(self) -> str:
        return self.detail


@runtime_checkable
class GenerationRuntimeRepository(Protocol):
    def save(
        self,
        execution_record: Mapping[str, Any],
        *,
        access_context: CxAccessContext,
        private_output_metadata: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        ...

    def get(
        self,
        cx_generation_id: str,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any] | None:
        ...


class SqlAlchemyGenerationRuntimeRepository:
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

    def save(
        self,
        execution_record: Mapping[str, Any],
        *,
        access_context: CxAccessContext,
        private_output_metadata: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        stored = build_generation_runtime_persistence_record(
            execution_record,
            access_context=access_context,
            private_output_metadata=private_output_metadata,
        )
        try:
            return self._run_in_transaction(
                lambda session: self._save_in_session(session, stored)
            )
        except GenerationRuntimeRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(
        self,
        cx_generation_id: str,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        _select_sql(
                            "cx_generation_id = :cx_generation_id "
                            "AND tenant_ref_id = :tenant_ref_id "
                            "AND owner_subject_ref_id = :owner_subject_ref_id"
                        )
                    ),
                    {
                        "cx_generation_id": cx_generation_id,
                        "tenant_ref_id": access_context.tenant_id,
                        "owner_subject_ref_id": access_context.subject_id,
                    },
                ).mappings().first()
                return _runtime_record_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def _save_in_session(
        self,
        session: Session,
        stored: Mapping[str, Any],
    ) -> dict[str, Any]:
        session.execute(text(_insert_sql(session)), _persistence_params(stored))
        row = session.execute(
            text(
                _select_sql(
                    "cx_generation_id = :cx_generation_id "
                    "AND tenant_ref_id = :tenant_ref_id "
                    "AND owner_subject_ref_id = :owner_subject_ref_id"
                )
            ),
            _persistence_params(stored),
        ).mappings().first()
        if row is None:
            raise _identity_conflict()
        reloaded = _storage_record_from_row(row)
        if _canonical_record(reloaded) != _canonical_record(stored):
            raise _identity_conflict()
        return _runtime_record_from_storage(reloaded)

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


def build_generation_runtime_persistence_record(
    execution_record: Mapping[str, Any],
    *,
    access_context: CxAccessContext,
    private_output_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    try:
        stored = build_generation_persistence_record(
            execution_record,
            owner_lineage=build_owner_lineage(access_context),
        )
    except (
        CxGenerationPersistenceError,
        CxOwnerLineageError,
        CxPrivateContentError,
    ) as exc:
        raise _invalid(str(exc)) from exc

    if stored["status"] == "COMPLETED":
        if private_output_metadata is None:
            raise _private_output_required()
        try:
            private_output = validate_generation_output_metadata(
                private_output_metadata
            )
        except CxPrivateContentError as exc:
            raise _invalid(exc.detail) from exc
        if stored["response_metadata"].get("output_hash") != private_output[
            "output_sha256"
        ]:
            raise GenerationRuntimeRepositoryError(
                error_code="cx.generation_runtime.output_hash_mismatch",
                detail="Generation output reference does not match execution metadata.",
            )
    elif private_output_metadata is not None:
        raise GenerationRuntimeRepositoryError(
            error_code="cx.generation_runtime.failed_output_forbidden",
            detail="Failed generation records cannot reference a generated output.",
            status_code=422,
        )
    else:
        private_output = None

    return {
        **stored,
        "private_output_schema_version": (
            private_output["private_output_schema_version"]
            if private_output is not None
            else None
        ),
        "output_storage_backend": (
            private_output["output_storage_backend"]
            if private_output is not None
            else None
        ),
        "output_storage_uri": (
            private_output["output_storage_uri"]
            if private_output is not None
            else None
        ),
        "output_sha256": (
            private_output["output_sha256"]
            if private_output is not None
            else None
        ),
        "output_size_bytes": (
            private_output["output_size_bytes"]
            if private_output is not None
            else None
        ),
    }


def _insert_sql(session: Session) -> str:
    json_fields = {
        field: _json_expression(session, field)
        for field in (
            "request_metadata",
            "response_metadata",
            "mo_runtime_metadata",
            "usage",
            "failure",
            "recovery_lineage",
        )
    }
    return f"""
        INSERT INTO {CX_GENERATION_RUNTIME_TABLE} (
            cx_generation_id, record_schema_version,
            tenant_ref_type, tenant_ref_id,
            owner_subject_ref_type, owner_subject_ref_id,
            status, retrieval_package_id, trace_id, request_id, alias,
            provider_capability, mo_generation_id, request_metadata,
            response_metadata, mo_runtime_metadata, usage, failure,
            recovery_lineage, private_output_schema_version,
            output_storage_backend, output_storage_uri, output_sha256,
            output_size_bytes, created_at, updated_at
        ) VALUES (
            :cx_generation_id, :record_schema_version,
            :tenant_ref_type, :tenant_ref_id,
            :owner_subject_ref_type, :owner_subject_ref_id,
            :status, :retrieval_package_id, :trace_id, :request_id, :alias,
            :provider_capability, :mo_generation_id,
            {json_fields['request_metadata']},
            {json_fields['response_metadata']},
            {json_fields['mo_runtime_metadata']},
            {json_fields['usage']}, {json_fields['failure']},
            {json_fields['recovery_lineage']}, :private_output_schema_version,
            :output_storage_backend, :output_storage_uri, :output_sha256,
            :output_size_bytes, :created_at, :updated_at
        )
        ON CONFLICT (cx_generation_id) DO NOTHING
    """


def _select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            cx_generation_id, record_schema_version,
            tenant_ref_type, tenant_ref_id,
            owner_subject_ref_type, owner_subject_ref_id,
            status, retrieval_package_id, trace_id, request_id, alias,
            provider_capability, mo_generation_id, request_metadata,
            response_metadata, mo_runtime_metadata, usage, failure,
            recovery_lineage, private_output_schema_version,
            output_storage_backend, output_storage_uri, output_sha256,
            output_size_bytes, created_at, updated_at
        FROM {CX_GENERATION_RUNTIME_TABLE}
        WHERE {where_clause}
    """


def _persistence_params(record: Mapping[str, Any]) -> dict[str, Any]:
    params = dict(record)
    for field in (
        "request_metadata",
        "response_metadata",
        "mo_runtime_metadata",
        "usage",
        "failure",
        "recovery_lineage",
    ):
        value = params[field]
        params[field] = (
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            if value is not None
            else None
        )
    return params


def _storage_record_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cx_generation_id": str(row["cx_generation_id"]),
        "record_schema_version": str(row["record_schema_version"]),
        "tenant_ref_type": str(row["tenant_ref_type"]),
        "tenant_ref_id": str(row["tenant_ref_id"]),
        "owner_subject_ref_type": str(row["owner_subject_ref_type"]),
        "owner_subject_ref_id": str(row["owner_subject_ref_id"]),
        "status": str(row["status"]),
        "retrieval_package_id": (
            str(row["retrieval_package_id"])
            if row["retrieval_package_id"] is not None
            else None
        ),
        "trace_id": str(row["trace_id"]),
        "request_id": str(row["request_id"]),
        "alias": str(row["alias"]),
        "provider_capability": str(row["provider_capability"]),
        "mo_generation_id": (
            str(row["mo_generation_id"])
            if row["mo_generation_id"] is not None
            else None
        ),
        "request_metadata": _json_value(row["request_metadata"], {}),
        "response_metadata": _json_value(row["response_metadata"], {}),
        "mo_runtime_metadata": _json_value(row["mo_runtime_metadata"], {}),
        "usage": _json_value(row["usage"], {}),
        "failure": _json_value(row["failure"], None),
        "recovery_lineage": _json_value(row["recovery_lineage"], None),
        "private_output_schema_version": row["private_output_schema_version"],
        "output_storage_backend": row["output_storage_backend"],
        "output_storage_uri": row["output_storage_uri"],
        "output_sha256": row["output_sha256"],
        "output_size_bytes": (
            int(row["output_size_bytes"])
            if row["output_size_bytes"] is not None
            else None
        ),
        "created_at": _datetime_value(row["created_at"]),
        "updated_at": _datetime_value(row["updated_at"]),
    }


def _runtime_record_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return _runtime_record_from_storage(_storage_record_from_row(row))


def _runtime_record_from_storage(record: Mapping[str, Any]) -> dict[str, Any]:
    private_output = None
    if record["output_storage_uri"] is not None:
        private_output = {
            "private_output_schema_version": record[
                "private_output_schema_version"
            ],
            "output_storage_backend": record["output_storage_backend"],
            "output_storage_uri": record["output_storage_uri"],
            "output_sha256": record["output_sha256"],
            "output_size_bytes": record["output_size_bytes"],
        }
    return {
        key: deepcopy(value)
        for key, value in record.items()
        if key
        not in {
            "private_output_schema_version",
            "output_storage_backend",
            "output_storage_uri",
            "output_sha256",
            "output_size_bytes",
        }
    } | {"private_output_metadata": private_output}


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


def _datetime_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        observed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return observed.astimezone(UTC)
    observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


def _canonical_record(record: Mapping[str, Any]) -> str:
    def normalize(value: Any) -> Any:
        if isinstance(value, datetime):
            observed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            return observed.astimezone(UTC).isoformat()
        if isinstance(value, Mapping):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        return value

    return json.dumps(normalize(record), sort_keys=True, separators=(",", ":"))


def _invalid(detail: str) -> GenerationRuntimeRepositoryError:
    return GenerationRuntimeRepositoryError(
        error_code="cx.generation_runtime.record_invalid",
        detail=detail,
        status_code=422,
    )


def _private_output_required() -> GenerationRuntimeRepositoryError:
    return GenerationRuntimeRepositoryError(
        error_code="cx.generation_runtime.private_output_required",
        detail="Completed generation records require private output metadata.",
        status_code=422,
    )


def _identity_conflict() -> GenerationRuntimeRepositoryError:
    return GenerationRuntimeRepositoryError(
        error_code="cx.generation_runtime.identity_conflict",
        detail="Generation identity is already bound to another runtime record.",
    )


def _unavailable() -> GenerationRuntimeRepositoryError:
    return GenerationRuntimeRepositoryError(
        error_code="cx.generation_runtime.repository_unavailable",
        detail="CX generation runtime repository is unavailable.",
        status_code=503,
    )
