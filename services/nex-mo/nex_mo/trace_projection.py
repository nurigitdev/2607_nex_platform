from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import re
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_mo.provider_auth import authorize_mo_operations_request
from nex_runtime import (
    CrossServiceTraceError,
    OperationalEventError,
    OperationalEventStore,
    build_cross_service_trace_source_projection,
    build_cross_service_trace_stage,
    problem_response,
)

MO_TRACE_OPERATIONS_PATH = "/internal/v1/operations/traces/{trace_id}"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


@dataclass(frozen=True)
class MoTraceProjectionError(Exception):
    error_code: str
    detail: str
    status_code: int = 503
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


@dataclass
class MoTraceProjectionSource:
    operational_store: OperationalEventStore

    def list_trace_records(self, trace_id: str) -> list[dict[str, Any]]:
        try:
            return [
                event
                for event in self.operational_store.list_events(
                    service_id="nex-mo",
                    trace_id=trace_id,
                    limit=500,
                )
                if str(event.get("event_type") or "").startswith("mo.provider.")
            ]
        except OperationalEventError as exc:
            raise MoTraceProjectionError(
                "mo.trace_source_unavailable",
                "MO durable provider trace records are unavailable.",
            ) from exc


def build_mo_trace_projection(
    trace_id: str,
    records: Sequence[Mapping[str, Any]],
    *,
    checked_at: datetime,
) -> dict[str, Any]:
    if checked_at.tzinfo is None:
        raise MoTraceProjectionError(
            "mo.trace_clock_invalid",
            "MO trace projection clock must be timezone-aware.",
            status_code=500,
            retryable=False,
        )
    return build_cross_service_trace_source_projection(
        service_id="nex-mo",
        trace_id=trace_id,
        stages=[_build_stage(trace_id, record) for record in records],
        source_status="READY",
        checked_at=_timestamp(checked_at),
    )


def register_mo_trace_projection_routes(
    app: FastAPI,
    *,
    source: MoTraceProjectionSource,
    clock: Callable[[], datetime] | None = None,
) -> None:
    selected_clock = clock or (lambda: datetime.now(UTC))

    @app.get(MO_TRACE_OPERATIONS_PATH, response_model=None)
    def get_mo_trace_projection(
        trace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_mo_operations_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            return build_mo_trace_projection(
                trace_id,
                source.list_trace_records(trace_id),
                checked_at=selected_clock(),
            )
        except CrossServiceTraceError as exc:
            return _problem(
                request,
                MoTraceProjectionError(
                    exc.error_code,
                    exc.detail,
                    status_code=422,
                    retryable=False,
                ),
            )
        except MoTraceProjectionError as exc:
            return _problem(request, exc)


def _build_stage(trace_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    if str(record.get("trace_id") or "") != trace_id:
        raise MoTraceProjectionError(
            "mo.trace_record_mismatch",
            "MO trace record does not match the requested trace.",
            status_code=500,
            retryable=False,
        )
    event_type = _required_text(record, "event_type")
    if not event_type.startswith("mo.provider."):
        raise MoTraceProjectionError(
            "mo.trace_record_kind_invalid",
            "MO trace record kind is invalid.",
            status_code=500,
            retryable=False,
        )
    details = _mapping(record.get("details"))
    capability = _required_detail(details, "provider_capability")
    result_code = _required_detail(details, "result_code")
    attributes: dict[str, object] = {
        "event_type": event_type,
        "provider_capability": capability,
        "result_code": result_code,
    }
    for field_name in (
        "model_alias",
        "model_revision",
        "deployment_id",
        "provider_route_id",
        "provider_mode",
        "failure_code",
    ):
        value = details.get(field_name)
        if isinstance(value, str) and value:
            attributes[field_name] = _safe_text(value)
    retryable = details.get("retryable")
    if isinstance(retryable, bool):
        attributes["retryable"] = retryable

    refs: dict[str, object] = {}
    provider_request_id = details.get("provider_request_id")
    if isinstance(provider_request_id, str) and provider_request_id:
        refs["provider_request_id"] = _opaque_identifier(
            "mo-provider-request",
            provider_request_id,
        )
    return build_cross_service_trace_stage(
        stage_id=_opaque_identifier("mo-event", record.get("event_id")),
        trace_id=trace_id,
        request_id=_opaque_identifier("mo-request", record.get("request_id")),
        service_id="nex-mo",
        stage_family=("GENERATION" if capability == "generation" else "RETRIEVAL"),
        stage_status=(
            "FAILED"
            if event_type.endswith(".failed") or result_code.upper() == "FAILED"
            else "SUCCEEDED"
        ),
        operation_timestamp=_required_timestamp(record, "created_at"),
        correlation_refs=refs,
        safe_attributes=attributes,
    )


def _required_detail(details: Mapping[str, Any], field_name: str) -> str:
    value = details.get(field_name)
    if not isinstance(value, str) or not value:
        raise MoTraceProjectionError(
            "mo.trace_record_invalid",
            f"MO trace detail field is invalid: {field_name}",
            status_code=500,
            retryable=False,
        )
    return _safe_text(value)


def _required_text(record: Mapping[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str) or not value:
        raise MoTraceProjectionError(
            "mo.trace_record_invalid",
            f"MO trace record field is invalid: {field_name}",
            status_code=500,
            retryable=False,
        )
    return value


def _required_timestamp(record: Mapping[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, str) and value:
        return value
    raise MoTraceProjectionError(
        "mo.trace_record_timestamp_invalid",
        "MO trace record timestamp is invalid.",
        status_code=500,
        retryable=False,
    )


def _opaque_identifier(prefix: str, value: object) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER_PATTERN.fullmatch(normalized):
        return normalized
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _safe_text(value: str) -> str:
    return (
        value
        if len(value) <= 128
        else f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _problem(request: Request, exc: MoTraceProjectionError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="MO trace projection failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/mo-trace-projection",
        retryable=exc.retryable,
    )
