from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import re
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_oa.auth_events import OaAuthEventError, OaAuthEventRepository
from nex_oa.service_auth import authorize_oa_operations_request
from nex_runtime import (
    CrossServiceTraceError,
    OperationalEventError,
    OperationalEventStore,
    build_cross_service_trace_source_projection,
    build_cross_service_trace_stage,
    problem_response,
)

OA_TRACE_OPERATIONS_PATH = "/internal/v1/operations/traces/{trace_id}"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


@dataclass(frozen=True)
class OaTraceProjectionError(Exception):
    error_code: str
    detail: str
    status_code: int = 503
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


class OaTraceProjectionSource(Protocol):
    def list_trace_records(self, trace_id: str) -> list[dict[str, Any]]: ...


@dataclass
class RepositoryOaTraceProjectionSource:
    auth_repository: OaAuthEventRepository
    operational_store: OperationalEventStore

    def list_trace_records(self, trace_id: str) -> list[dict[str, Any]]:
        try:
            auth_events = [
                {"record_kind": "auth", **event}
                for event in self.auth_repository.list_events_by_trace(trace_id)
            ]
            trust_events = [
                {"record_kind": "trust", **event}
                for event in self.operational_store.list_events(
                    service_id="nex-oa",
                    trace_id=trace_id,
                    limit=500,
                )
            ]
            return auth_events + trust_events
        except (OaAuthEventError, OperationalEventError) as exc:
            raise OaTraceProjectionError(
                "oa.trace_source_unavailable",
                "OA durable trust trace records are unavailable.",
            ) from exc


def build_oa_trace_projection(
    trace_id: str,
    records: Sequence[Mapping[str, Any]],
    *,
    checked_at: datetime,
) -> dict[str, Any]:
    if checked_at.tzinfo is None:
        raise OaTraceProjectionError(
            "oa.trace_clock_invalid",
            "OA trace projection clock must be timezone-aware.",
            status_code=500,
            retryable=False,
        )
    return build_cross_service_trace_source_projection(
        service_id="nex-oa",
        trace_id=trace_id,
        stages=[_build_stage(trace_id, record) for record in records],
        source_status="READY",
        checked_at=_timestamp(checked_at),
    )


def register_oa_trace_projection_routes(
    app: FastAPI,
    *,
    source: OaTraceProjectionSource,
    clock: Callable[[], datetime] | None = None,
) -> None:
    selected_clock = clock or (lambda: datetime.now(UTC))

    @app.get(OA_TRACE_OPERATIONS_PATH, response_model=None)
    def get_oa_trace_projection(
        trace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_oa_operations_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            return build_oa_trace_projection(
                trace_id,
                source.list_trace_records(trace_id),
                checked_at=selected_clock(),
            )
        except CrossServiceTraceError as exc:
            return _problem(
                request,
                OaTraceProjectionError(
                    exc.error_code,
                    exc.detail,
                    status_code=422,
                    retryable=False,
                ),
            )
        except OaTraceProjectionError as exc:
            return _problem(request, exc)


def _build_stage(trace_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    kind = record.get("record_kind")
    if kind not in {"auth", "trust"}:
        raise OaTraceProjectionError(
            "oa.trace_record_kind_invalid",
            "OA trace record kind is invalid.",
            status_code=500,
            retryable=False,
        )
    if str(record.get("trace_id") or "") != trace_id:
        raise OaTraceProjectionError(
            "oa.trace_record_mismatch",
            "OA trace record does not match the requested trace.",
            status_code=500,
            retryable=False,
        )
    event_id = _required_text(record, "event_id")
    event_type = _required_text(record, "event_type")
    request_id = _opaque_identifier("oa-request", record.get("request_id"))
    attributes: dict[str, object] = {"event_type": event_type}
    owner_digest: str | None = None

    if kind == "auth":
        outcome = _required_text(record, "outcome").upper()
        attributes["result_code"] = outcome
        details = _mapping(record.get("details"))
        failure_code = details.get("error_code")
        if outcome != "SUCCEEDED" and isinstance(failure_code, str) and failure_code:
            attributes["failure_code"] = failure_code
        owner_digest = _owner_digest(record)
        timestamp = _required_timestamp(record, "occurred_at")
        status = _auth_status(outcome)
    else:
        severity = _required_text(record, "severity").upper()
        attributes["result_code"] = severity
        details = _mapping(record.get("details"))
        failure_code = details.get("error_code")
        if isinstance(failure_code, str) and failure_code:
            attributes["failure_code"] = failure_code
        timestamp = _required_timestamp(record, "created_at")
        status = "FAILED" if severity in {"ERROR", "CRITICAL"} else "SUCCEEDED"

    return build_cross_service_trace_stage(
        stage_id=_opaque_identifier("oa-event", event_id),
        trace_id=trace_id,
        request_id=request_id,
        service_id="nex-oa",
        stage_family="AUTH",
        stage_status=status,
        operation_timestamp=timestamp,
        correlation_refs={},
        safe_attributes=attributes,
        owner_digest=owner_digest,
    )


def _owner_digest(record: Mapping[str, Any]) -> str | None:
    tenant_id = _ref_id(record.get("tenant_ref"))
    subject_id = _ref_id(record.get("subject_ref"))
    if tenant_id is None or subject_id is None:
        return None
    return hashlib.sha256(f"{tenant_id}:{subject_id}".encode("utf-8")).hexdigest()


def _auth_status(outcome: str) -> str:
    if outcome == "SUCCEEDED":
        return "SUCCEEDED"
    if outcome == "FAILED":
        return "FAILED"
    if outcome == "BLOCKED":
        return "BLOCKED"
    raise OaTraceProjectionError(
        "oa.trace_record_invalid",
        "OA authentication outcome is invalid.",
        status_code=500,
        retryable=False,
    )


def _opaque_identifier(prefix: str, value: object) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER_PATTERN.fullmatch(normalized):
        return normalized
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _required_text(record: Mapping[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise OaTraceProjectionError(
            "oa.trace_record_invalid",
            f"OA trace record field is invalid: {field_name}",
            status_code=500,
            retryable=False,
        )
    return value.strip()


def _required_timestamp(record: Mapping[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, str) and value:
        return value
    raise OaTraceProjectionError(
        "oa.trace_record_timestamp_invalid",
        "OA trace record timestamp is invalid.",
        status_code=500,
        retryable=False,
    )


def _ref_id(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    identifier = value.get("id")
    return identifier if isinstance(identifier, str) and identifier else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _problem(request: Request, exc: OaTraceProjectionError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="OA trace projection failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/oa-trace-projection",
        retryable=exc.retryable,
    )
