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

from nex_ae_api.route_auth import authorize_ae_operations_request
from nex_runtime import (
    CrossServiceTraceError,
    build_cross_service_trace_source_projection,
    build_cross_service_trace_stage,
    problem_response,
)

AE_TRACE_OPERATIONS_PATH = "/internal/v1/operations/traces/{trace_id}"
AE_TRACE_RECORD_KINDS = ("upload", "response", "artifact", "render", "access")


@dataclass(frozen=True)
class AeTraceProjectionError(Exception):
    error_code: str
    detail: str
    status_code: int = 503
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


class AeTraceProjectionSource(Protocol):
    def list_trace_records(self, trace_id: str) -> list[dict[str, Any]]: ...


@dataclass
class InMemoryAeTraceProjectionSource:
    records: list[dict[str, Any]] = field(default_factory=list)

    def list_trace_records(self, trace_id: str) -> list[dict[str, Any]]:
        return [
            deepcopy(record)
            for record in self.records
            if record.get("trace_id") == trace_id
        ]


class SqlAlchemyAeTraceProjectionSource:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_trace_records(self, trace_id: str) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                records: list[dict[str, Any]] = []
                records.extend(
                    _records(
                        session,
                        "upload",
                        """
                        SELECT upload_handoff_id, status, cx_upload_id,
                               ingestion_job_id, trace_id, request_id,
                               tenant_id, owner_user_id, created_at, updated_at
                        FROM ae_upload_handoffs
                        WHERE trace_id = :trace_id
                        """,
                        trace_id,
                    )
                )
                records.extend(
                    _records(
                        session,
                        "response",
                        """
                        SELECT chat_interaction_id, status,
                               cx_retrieval_package_id, cx_generation_id,
                               cx_generation_status, trace_id, request_id,
                               tenant_id, user_id AS owner_user_id,
                               created_at, updated_at
                        FROM ae_chat_interactions
                        WHERE trace_id = :trace_id
                        """,
                        trace_id,
                    )
                )
                records.extend(
                    _records(
                        session,
                        "artifact",
                        """
                        SELECT artifact_id, artifact_status AS status,
                               trace_id, request_id, tenant_id, owner_user_id,
                               created_at, updated_at
                        FROM ae_artifacts
                        WHERE trace_id = :trace_id
                        """,
                        trace_id,
                    )
                )
                records.extend(
                    _records(
                        session,
                        "render",
                        """
                        SELECT j.render_job_id, j.artifact_id,
                               j.job_status AS status, j.progress_percent,
                               j.retryable, j.failure_code,
                               a.trace_id, a.request_id, a.tenant_id,
                               a.owner_user_id, j.created_at, j.updated_at
                        FROM ae_artifact_render_jobs AS j
                        JOIN ae_artifacts AS a ON a.artifact_id = j.artifact_id
                        WHERE a.trace_id = :trace_id
                        """,
                        trace_id,
                    )
                )
                records.extend(
                    _records(
                        session,
                        "access",
                        """
                        SELECT event_id, event_type, trace_id, request_id,
                               subject_id, details, created_at,
                               created_at AS updated_at
                        FROM service_operational_events
                        WHERE service_id = 'nex-ae-api'
                          AND trace_id = :trace_id
                          AND event_type LIKE 'ae.artifact_access.%'
                        """,
                        trace_id,
                    )
                )
                return records
        except SQLAlchemyError as exc:
            raise AeTraceProjectionError(
                "ae.trace_source_unavailable",
                "AE durable trace records are unavailable.",
            ) from exc


def build_ae_trace_projection(
    trace_id: str,
    records: Sequence[Mapping[str, Any]],
    *,
    checked_at: datetime,
) -> dict[str, Any]:
    if checked_at.tzinfo is None:
        raise AeTraceProjectionError(
            "ae.trace_clock_invalid",
            "AE trace projection clock must be timezone-aware.",
            status_code=500,
            retryable=False,
        )
    stages = [_build_stage(trace_id, record) for record in records]
    return build_cross_service_trace_source_projection(
        service_id="nex-ae-api",
        trace_id=trace_id,
        stages=stages,
        source_status="READY",
        checked_at=_timestamp(checked_at),
    )


def register_ae_trace_projection_routes(
    app: FastAPI,
    *,
    source: AeTraceProjectionSource,
    clock: Callable[[], datetime] | None = None,
) -> None:
    selected_clock = clock or (lambda: datetime.now(UTC))

    @app.get(AE_TRACE_OPERATIONS_PATH, response_model=None)
    def get_ae_trace_projection(
        trace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_ae_operations_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            return build_ae_trace_projection(
                trace_id,
                source.list_trace_records(trace_id),
                checked_at=selected_clock(),
            )
        except CrossServiceTraceError as exc:
            return _problem(
                request,
                AeTraceProjectionError(
                    exc.error_code,
                    exc.detail,
                    status_code=422,
                    retryable=False,
                ),
            )
        except AeTraceProjectionError as exc:
            return _problem(request, exc)


def _build_stage(trace_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    kind = record.get("record_kind")
    if kind not in AE_TRACE_RECORD_KINDS:
        raise AeTraceProjectionError(
            "ae.trace_record_kind_invalid",
            "AE trace record kind is invalid.",
            status_code=500,
            retryable=False,
        )
    if str(record.get("trace_id") or "") != trace_id:
        raise AeTraceProjectionError(
            "ae.trace_record_mismatch",
            "AE trace record does not match the requested trace.",
            status_code=500,
            retryable=False,
        )
    timestamp = _record_timestamp(record)
    request_id = _required_text(record, "request_id")

    if kind == "access":
        details = _mapping(record.get("details"))
        result_code = _required_text(details, "result_code")
        event_type = _required_text(record, "event_type")
        _required_text(details, "access_type")
        artifact_id = _optional_identifier(details.get("artifact_id"))
        refs = {"artifact_id": artifact_id} if artifact_id is not None else {}
        attributes: dict[str, object] = {
            "event_type": event_type,
            "result_code": result_code,
        }
        if result_code == "BLOCKED":
            attributes["failure_code"] = "ACCESS_BLOCKED"
        return _stage(
            stage_id=f"ae-access-{_required_identifier(record, 'event_id')}",
            trace_id=trace_id,
            request_id=request_id,
            family="ACCESS",
            status=result_code,
            timestamp=timestamp,
            refs=refs,
            attributes=attributes,
            owner_digest=None,
        )

    owner_digest = _owner_digest(record)
    status = _required_text(record, "status")

    if kind == "upload":
        upload_id = _required_identifier(record, "upload_handoff_id")
        refs = {"upload_id": upload_id}
        ingestion_id = _optional_identifier(record.get("ingestion_job_id"))
        if ingestion_id is not None:
            refs["ingestion_run_id"] = ingestion_id
        return _stage(
            stage_id=f"ae-upload-{upload_id}",
            trace_id=trace_id,
            request_id=request_id,
            family="UPLOAD",
            status=status,
            timestamp=timestamp,
            refs=refs,
            attributes={"event_type": "ae.upload", "result_code": status},
            owner_digest=owner_digest,
        )

    if kind == "response":
        response_id = _required_identifier(record, "chat_interaction_id")
        refs = {"response_id": response_id}
        for source_field, target_field in (
            ("cx_retrieval_package_id", "retrieval_package_id"),
            ("cx_generation_id", "cx_generation_id"),
        ):
            value = _optional_identifier(record.get(source_field))
            if value is not None:
                refs[target_field] = value
        attributes: dict[str, object] = {
            "event_type": "ae.response",
            "result_code": status,
        }
        generation_status = _optional_text(record.get("cx_generation_status"))
        if generation_status is not None:
            attributes["citation_status"] = generation_status
        return _stage(
            stage_id=f"ae-response-{response_id}",
            trace_id=trace_id,
            request_id=request_id,
            family="GENERATION",
            status=status,
            timestamp=timestamp,
            refs=refs,
            attributes=attributes,
            owner_digest=owner_digest,
        )

    artifact_id = _required_identifier(record, "artifact_id")
    refs = {"artifact_id": artifact_id}
    attributes = {"event_type": f"ae.{kind}", "artifact_status": status}
    stage_id = f"ae-artifact-{artifact_id}"
    if kind == "render":
        render_job_id = _required_identifier(record, "render_job_id")
        refs["render_job_id"] = render_job_id
        stage_id = f"ae-render-{render_job_id}"
        attributes["progress_percent"] = _progress(record.get("progress_percent"))
        attributes["retryable"] = _boolean(record.get("retryable"))
        failure_code = _optional_text(record.get("failure_code"))
        if failure_code is not None:
            attributes["failure_code"] = failure_code
    return _stage(
        stage_id=stage_id,
        trace_id=trace_id,
        request_id=request_id,
        family="ARTIFACT",
        status=status,
        timestamp=timestamp,
        refs=refs,
        attributes=attributes,
        owner_digest=owner_digest,
    )


def _stage(
    *,
    stage_id: str,
    trace_id: str,
    request_id: str,
    family: str,
    status: str,
    timestamp: str,
    refs: Mapping[str, object],
    attributes: Mapping[str, object],
    owner_digest: str | None,
) -> dict[str, Any]:
    return build_cross_service_trace_stage(
        stage_id=stage_id,
        trace_id=trace_id,
        request_id=request_id,
        service_id="nex-ae-api",
        stage_family=family,
        stage_status=_stage_status(status),
        operation_timestamp=timestamp,
        correlation_refs=refs,
        safe_attributes=attributes,
        owner_digest=owner_digest,
    )


def _stage_status(status: str) -> str:
    upper = status.upper()
    if upper in {"SUCCEEDED", "COMPLETED", "READY", "ALREADY_EXISTS"}:
        return "SUCCEEDED"
    if upper == "FAILED":
        return "FAILED"
    if upper in {"NO_ANSWER", "BLOCKED"}:
        return "BLOCKED"
    if upper in {"CANCELLED", "SKIPPED", "ARCHIVED", "DELETED"}:
        return "SKIPPED"
    if upper in {"RECOVERING", "RETRYING"}:
        return "RECOVERING"
    return "STARTED"


def _records(
    session: Session,
    kind: str,
    statement: str,
    trace_id: str,
) -> list[dict[str, Any]]:
    rows = session.execute(text(statement), {"trace_id": trace_id}).mappings().all()
    return [{"record_kind": kind, **dict(row)} for row in rows]


def _owner_digest(record: Mapping[str, Any]) -> str:
    tenant_id = _required_text(record, "tenant_id")
    owner_id = _required_text(record, "owner_user_id")
    return hashlib.sha256(f"{tenant_id}:{owner_id}".encode("utf-8")).hexdigest()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _record_timestamp(record: Mapping[str, Any]) -> str:
    value = record.get("updated_at") or record.get("created_at")
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, str) and value:
        return value
    raise AeTraceProjectionError(
        "ae.trace_record_timestamp_invalid",
        "AE trace record timestamp is invalid.",
        status_code=500,
        retryable=False,
    )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required_text(record: Mapping[str, Any], field_name: str) -> str:
    value = _optional_text(record.get(field_name))
    if value is None:
        raise AeTraceProjectionError(
            "ae.trace_record_invalid",
            f"AE trace record field is invalid: {field_name}",
            status_code=500,
            retryable=False,
        )
    return value


def _required_identifier(record: Mapping[str, Any], field_name: str) -> str:
    value = _optional_identifier(record.get(field_name))
    if value is None:
        raise AeTraceProjectionError(
            "ae.trace_record_invalid",
            f"AE trace record field is invalid: {field_name}",
            status_code=500,
            retryable=False,
        )
    return value


def _optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _progress(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise AeTraceProjectionError(
            "ae.trace_record_invalid",
            "AE render progress is invalid.",
            status_code=500,
            retryable=False,
        )
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise AeTraceProjectionError(
            "ae.trace_record_invalid",
            "AE render retryable state is invalid.",
            status_code=500,
            retryable=False,
        )
    return value


def _problem(request: Request, exc: AeTraceProjectionError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="AE trace projection failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/ae-trace-projection",
        retryable=exc.retryable,
    )
