from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_cx.authorization import authorize_cx_operations_request
from nex_runtime import (
    CrossServiceTraceError,
    build_cross_service_trace_source_projection,
    build_cross_service_trace_stage,
    problem_response,
)


CX_TRACE_OPERATIONS_PATH = "/internal/v1/operations/traces/{trace_id}"
CX_TRACE_RECORD_KINDS = ("ingestion", "retrieval", "generation")


@dataclass(frozen=True)
class CxTraceProjectionError(Exception):
    error_code: str
    detail: str
    status_code: int = 503
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


class CxTraceProjectionSource(Protocol):
    def list_trace_records(self, trace_id: str) -> list[dict[str, Any]]:
        ...


@dataclass
class InMemoryCxTraceProjectionSource:
    records: list[dict[str, Any]] = field(default_factory=list)

    def list_trace_records(self, trace_id: str) -> list[dict[str, Any]]:
        return [
            deepcopy(record)
            for record in self.records
            if record.get("trace_id") == trace_id
        ]


class SqlAlchemyCxTraceProjectionSource:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_trace_records(self, trace_id: str) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                records: list[dict[str, Any]] = []
                records.extend(
                    _records(
                        session,
                        "ingestion",
                        """
                        SELECT run_id, status, current_step, attempt_count,
                               trace_id, request_id, tenant_ref_id,
                               owner_subject_ref_id, created_at, updated_at
                        FROM cx_ingest_runs
                        WHERE trace_id = :trace_id
                        """,
                        trace_id,
                    )
                )
                records.extend(
                    _records(
                        session,
                        "retrieval",
                        """
                        SELECT retrieval_package_id, status, rerank_state,
                               trace_id, request_id, tenant_ref_id,
                               owner_subject_ref_id, created_at, updated_at
                        FROM cx_retrieval_packages
                        WHERE trace_id = :trace_id
                        """,
                        trace_id,
                    )
                )
                records.extend(
                    _records(
                        session,
                        "generation",
                        """
                        SELECT cx_generation_id, status, retrieval_package_id,
                               trace_id, request_id, tenant_ref_id,
                               owner_subject_ref_id, alias, provider_capability,
                               created_at, updated_at
                        FROM cx_generation_executions
                        WHERE trace_id = :trace_id
                        """,
                        trace_id,
                    )
                )
                return records
        except SQLAlchemyError as exc:
            raise CxTraceProjectionError(
                "cx.trace_source_unavailable",
                "CX durable trace records are unavailable.",
            ) from exc


def build_cx_trace_projection(
    trace_id: str,
    records: Sequence[Mapping[str, Any]],
    *,
    checked_at: datetime,
) -> dict[str, Any]:
    if checked_at.tzinfo is None:
        raise CxTraceProjectionError(
            "cx.trace_clock_invalid",
            "CX trace projection clock must be timezone-aware.",
            status_code=500,
            retryable=False,
        )
    stages = [_build_stage(trace_id, record) for record in records]
    return build_cross_service_trace_source_projection(
        service_id="nex-cx",
        trace_id=trace_id,
        stages=stages,
        source_status="READY",
        checked_at=_timestamp(checked_at),
    )


def register_cx_trace_projection_routes(
    app: FastAPI,
    *,
    source: CxTraceProjectionSource,
    clock: Callable[[], datetime] | None = None,
) -> None:
    selected_clock = clock or (lambda: datetime.now(UTC))

    @app.get(CX_TRACE_OPERATIONS_PATH, response_model=None)
    def get_cx_trace_projection(
        trace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_cx_operations_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            records = source.list_trace_records(trace_id)
            return build_cx_trace_projection(
                trace_id,
                records,
                checked_at=selected_clock(),
            )
        except CrossServiceTraceError as exc:
            return _problem(
                request,
                CxTraceProjectionError(
                    exc.error_code,
                    exc.detail,
                    status_code=422,
                    retryable=False,
                ),
            )
        except CxTraceProjectionError as exc:
            return _problem(request, exc)


def _build_stage(
    trace_id: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    kind = record.get("record_kind")
    if kind not in CX_TRACE_RECORD_KINDS:
        raise CxTraceProjectionError(
            "cx.trace_record_kind_invalid",
            "CX trace record kind is invalid.",
            status_code=500,
            retryable=False,
        )
    if str(record.get("trace_id") or "") != trace_id:
        raise CxTraceProjectionError(
            "cx.trace_record_mismatch",
            "CX trace record does not match the requested trace.",
            status_code=500,
            retryable=False,
        )
    owner_digest = _owner_digest(record)
    timestamp = _record_timestamp(record)
    request_id = _required_text(record, "request_id")
    status = _required_text(record, "status")
    if kind == "ingestion":
        run_id = _required_text(record, "run_id")
        attributes: dict[str, object] = {
            "event_type": "cx.ingestion",
            "result_code": status,
            "attempt": _nonnegative_integer(record.get("attempt_count")),
        }
        current_step = record.get("current_step")
        if isinstance(current_step, str) and current_step:
            attributes["confidence_state"] = current_step
        return build_cross_service_trace_stage(
            stage_id=f"cx-ingestion-{run_id}",
            trace_id=trace_id,
            request_id=request_id,
            service_id="nex-cx",
            stage_family="INGESTION",
            stage_status=_stage_status(kind, status),
            operation_timestamp=timestamp,
            correlation_refs={"ingestion_run_id": run_id},
            safe_attributes=attributes,
            owner_digest=owner_digest,
        )
    if kind == "retrieval":
        package_id = _required_text(record, "retrieval_package_id")
        attributes = {
            "event_type": "cx.retrieval",
            "result_code": status,
            "confidence_state": status,
        }
        rerank_state = record.get("rerank_state")
        if isinstance(rerank_state, str) and rerank_state:
            attributes["citation_status"] = rerank_state
        return build_cross_service_trace_stage(
            stage_id=f"cx-retrieval-{package_id}",
            trace_id=trace_id,
            request_id=request_id,
            service_id="nex-cx",
            stage_family="RETRIEVAL",
            stage_status=_stage_status(kind, status),
            operation_timestamp=timestamp,
            correlation_refs={"retrieval_package_id": package_id},
            safe_attributes=attributes,
            owner_digest=owner_digest,
        )

    generation_id = _required_text(record, "cx_generation_id")
    refs = {"cx_generation_id": generation_id}
    retrieval_package_id = record.get("retrieval_package_id")
    if isinstance(retrieval_package_id, str) and retrieval_package_id:
        refs["retrieval_package_id"] = retrieval_package_id
    attributes = {
        "event_type": "cx.generation",
        "result_code": status,
    }
    for source_field, target_field in (
        ("provider_capability", "provider_capability"),
        ("alias", "model_alias"),
    ):
        value = record.get(source_field)
        if isinstance(value, str) and value:
            attributes[target_field] = value
    return build_cross_service_trace_stage(
        stage_id=f"cx-generation-{generation_id}",
        trace_id=trace_id,
        request_id=request_id,
        service_id="nex-cx",
        stage_family="GENERATION",
        stage_status=_stage_status(kind, status),
        operation_timestamp=timestamp,
        correlation_refs=refs,
        safe_attributes=attributes,
        owner_digest=owner_digest,
    )


def _stage_status(kind: object, status: str) -> str:
    upper = status.upper()
    if upper in {"SUCCEEDED", "COMPLETED", "READY"}:
        return "SUCCEEDED"
    if upper == "FAILED":
        return "FAILED"
    if upper in {"LOW_CONFIDENCE", "NO_ANSWER", "BLOCKED"}:
        return "BLOCKED"
    if upper in {"CANCELLED", "SKIPPED"}:
        return "SKIPPED"
    if upper in {"RECOVERING", "RETRYING"}:
        return "RECOVERING"
    if kind in CX_TRACE_RECORD_KINDS:
        return "STARTED"
    raise CxTraceProjectionError(
        "cx.trace_record_kind_invalid",
        "CX trace record kind is invalid.",
        status_code=500,
        retryable=False,
    )


def _records(
    session: Session,
    kind: str,
    statement: str,
    trace_id: str,
) -> list[dict[str, Any]]:
    rows = session.execute(text(statement), {"trace_id": trace_id}).mappings().all()
    return [{"record_kind": kind, **dict(row)} for row in rows]


def _owner_digest(record: Mapping[str, Any]) -> str:
    tenant_id = _required_text(record, "tenant_ref_id")
    owner_id = _required_text(record, "owner_subject_ref_id")
    return hashlib.sha256(f"{tenant_id}:{owner_id}".encode("utf-8")).hexdigest()


def _record_timestamp(record: Mapping[str, Any]) -> str:
    value = record.get("updated_at") or record.get("created_at")
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, str) and value:
        return value
    raise CxTraceProjectionError(
        "cx.trace_record_timestamp_invalid",
        "CX trace record timestamp is invalid.",
        status_code=500,
        retryable=False,
    )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required_text(record: Mapping[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str) or not value:
        raise CxTraceProjectionError(
            "cx.trace_record_invalid",
            f"CX trace record field is invalid: {field_name}",
            status_code=500,
            retryable=False,
        )
    return value


def _nonnegative_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CxTraceProjectionError(
            "cx.trace_record_invalid",
            "CX trace record attempt count is invalid.",
            status_code=500,
            retryable=False,
        )
    return value


def _problem(request: Request, exc: CxTraceProjectionError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="CX trace projection failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/cx-trace-projection",
        retryable=exc.retryable,
    )
