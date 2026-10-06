from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import os
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_ag.service_auth import (
    AgOutboundServiceTokenError,
    resolve_ag_outbound_service_token,
)
from nex_runtime import (
    CrossServiceTraceError,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    OperationalEventStore,
    build_cross_service_trace_timeline,
    build_cross_service_trace_stage,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_cross_service_trace_source_projection,
)
from nex_ag.service_auth import authorize_ag_service_request

AG_TRACE_SOURCE_SERVICE_IDS = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo")
AG_TRACE_REQUIRED_SCOPES = ("service:call", "operations:read")
AG_TRACE_SOURCE_PATH = "/internal/v1/operations/traces/{trace_id}"
DEFAULT_TRACE_SOURCE_TIMEOUT_SECONDS = 5.0
AG_TRACE_READ_EVENT_TYPE = "ag.cross_service_trace.read.succeeded"
AG_TRACE_OPERATIONS_PATH = "/admin/v1/operations/traces/{trace_id}"
DEFAULT_TRACE_SOURCE_BASE_URLS = {
    "nex-oa": "http://127.0.0.1:8101",
    "nex-ae-api": "http://127.0.0.1:8103",
    "nex-cx": "http://127.0.0.1:8104",
    "nex-mo": "http://127.0.0.1:8105",
}
TRACE_SOURCE_BASE_URL_ENV = {
    "nex-oa": "NEX_OA_BASE_URL",
    "nex-ae-api": "NEX_AE_API_BASE_URL",
    "nex-cx": "NEX_CX_BASE_URL",
    "nex-mo": "NEX_MO_BASE_URL",
}
TRACE_SOURCE_TOKEN_ENV = {
    "nex-oa": "NEX_AG_TO_OA_SERVICE_TOKEN",
    "nex-ae-api": "NEX_AG_TO_AE_SERVICE_TOKEN",
    "nex-cx": "NEX_AG_TO_CX_SERVICE_TOKEN",
    "nex-mo": "NEX_AG_TO_MO_SERVICE_TOKEN",
}

HttpRequester = Callable[..., httpx.Response]


class CrossServiceTraceSourceClient(Protocol):
    service_id: str

    def get_trace_projection(
        self,
        trace_id: str,
        *,
        request_id: str,
        request_trace_id: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AgTraceSourceError(Exception):
    service_id: str
    error_code: str
    source_status: str
    status_code: int = 503
    retryable: bool = True

    def __str__(self) -> str:
        return self.error_code


@dataclass(frozen=True)
class CrossServiceTraceAggregation:
    projection: dict[str, Any]
    diagnostics: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class HttpCrossServiceTraceSourceClient:
    service_id: str
    base_url: str
    service_token: str | None = field(default=None, repr=False)
    timeout_seconds: float = DEFAULT_TRACE_SOURCE_TIMEOUT_SECONDS
    requester: HttpRequester = field(default=httpx.get, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.service_id not in AG_TRACE_SOURCE_SERVICE_IDS:
            raise ValueError("unsupported trace source service")
        if not self.base_url or self.base_url != self.base_url.strip():
            raise ValueError("trace source base URL is invalid")
        if self.timeout_seconds <= 0:
            raise ValueError("trace source timeout must be positive")

    def get_trace_projection(
        self,
        trace_id: str,
        *,
        request_id: str,
        request_trace_id: str,
    ) -> dict[str, Any]:
        try:
            token = resolve_ag_outbound_service_token(
                self.service_token,
                audience=self.service_id,
                required_scopes=AG_TRACE_REQUIRED_SCOPES,
            )
            response = self.requester(
                f"{self.base_url.rstrip('/')}{AG_TRACE_SOURCE_PATH.format(trace_id=trace_id)}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{request_trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": "nex-ag",
                },
                timeout=self.timeout_seconds,
            )
        except AgOutboundServiceTokenError as exc:
            raise AgTraceSourceError(
                self.service_id,
                exc.error_code,
                "UNAVAILABLE",
                retryable=False,
            ) from exc
        except httpx.TimeoutException as exc:
            raise AgTraceSourceError(
                self.service_id,
                "ag.trace_source_timeout",
                "UNAVAILABLE",
            ) from exc
        except httpx.HTTPError as exc:
            raise AgTraceSourceError(
                self.service_id,
                "ag.trace_source_transport_failed",
                "UNAVAILABLE",
            ) from exc

        if response.status_code >= 400:
            problem = _safe_response_json(response)
            raise AgTraceSourceError(
                self.service_id,
                _safe_error_code(problem.get("error_code")),
                "DEGRADED" if response.status_code < 500 else "UNAVAILABLE",
                status_code=response.status_code,
                retryable=bool(problem.get("retryable", response.status_code >= 500)),
            )
        try:
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise ValueError("trace source response must be an object")
            return validate_cross_service_trace_source_projection(
                payload,
                expected_service_id=self.service_id,
                expected_trace_id=trace_id,
            )
        except (ValueError, CrossServiceTraceError) as exc:
            raise AgTraceSourceError(
                self.service_id,
                "ag.trace_source_contract_invalid",
                "DEGRADED",
                status_code=502,
                retryable=False,
            ) from exc


@dataclass(frozen=True)
class CrossServiceTraceAggregator:
    clients: Mapping[str, CrossServiceTraceSourceClient]
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC), repr=False, compare=False
    )

    def __post_init__(self) -> None:
        invalid = sorted(set(self.clients) - set(AG_TRACE_SOURCE_SERVICE_IDS))
        if invalid:
            raise ValueError("unsupported trace source client")

    def aggregate(
        self,
        trace_id: str,
        *,
        request_id: str,
        request_trace_id: str,
        service_ids: Sequence[str] | None = None,
    ) -> CrossServiceTraceAggregation:
        selected = tuple(
            AG_TRACE_SOURCE_SERVICE_IDS if service_ids is None else service_ids
        )
        if not selected or len(selected) != len(set(selected)):
            raise ValueError("trace source selection is invalid")
        unknown = sorted(set(selected) - set(AG_TRACE_SOURCE_SERVICE_IDS))
        if unknown:
            raise ValueError("trace source selection contains an unsupported service")

        statuses: dict[str, str] = {}
        stages: list[Mapping[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for service_id in selected:
            client = self.clients.get(service_id)
            if client is None:
                statuses[service_id] = "UNAVAILABLE"
                diagnostics.append(
                    _diagnostic(
                        service_id,
                        "ag.trace_source_not_configured",
                        retryable=False,
                    )
                )
                continue
            try:
                source = client.get_trace_projection(
                    trace_id,
                    request_id=request_id,
                    request_trace_id=request_trace_id,
                )
                validated = validate_cross_service_trace_source_projection(
                    source,
                    expected_service_id=service_id,
                    expected_trace_id=trace_id,
                )
            except AgTraceSourceError as exc:
                statuses[service_id] = exc.source_status
                diagnostics.append(
                    _diagnostic(
                        service_id,
                        exc.error_code,
                        retryable=exc.retryable,
                        status_code=exc.status_code,
                    )
                )
                continue
            except (CrossServiceTraceError, ValueError):
                statuses[service_id] = "DEGRADED"
                diagnostics.append(
                    _diagnostic(
                        service_id,
                        "ag.trace_source_contract_invalid",
                        retryable=False,
                        status_code=502,
                    )
                )
                continue
            statuses[service_id] = validated["source_status"]
            stages.extend(validated["stages"])

        checked_at = self.clock()
        if checked_at.tzinfo is None:
            raise ValueError("trace aggregation clock must be timezone-aware")
        projection = build_cross_service_trace_timeline(
            trace_id=trace_id,
            stages=stages,
            source_statuses=statuses,
            checked_at=checked_at.isoformat().replace("+00:00", "Z"),
        )
        return CrossServiceTraceAggregation(
            projection=projection,
            diagnostics=tuple(diagnostics),
        )


def build_default_cross_service_trace_aggregator(
    environ: Mapping[str, str] | None = None,
) -> CrossServiceTraceAggregator:
    env = os.environ if environ is None else environ
    clients = {
        service_id: HttpCrossServiceTraceSourceClient(
            service_id=service_id,
            base_url=env.get(
                TRACE_SOURCE_BASE_URL_ENV[service_id],
                DEFAULT_TRACE_SOURCE_BASE_URLS[service_id],
            ),
            service_token=env.get(TRACE_SOURCE_TOKEN_ENV[service_id]) or None,
        )
        for service_id in AG_TRACE_SOURCE_SERVICE_IDS
    }
    return CrossServiceTraceAggregator(clients)


def register_cross_service_trace_routes(
    app: FastAPI,
    *,
    aggregator: CrossServiceTraceAggregator | None = None,
    event_store: OperationalEventStore | None = None,
) -> None:
    selected_aggregator = aggregator or build_default_cross_service_trace_aggregator()
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=event_store or InMemoryOperationalEventStore(),
    )

    @app.get(AG_TRACE_OPERATIONS_PATH, response_model=None)
    def get_cross_service_trace(
        trace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_ag_service_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        request_id = request_id_from_headers(request)
        request_trace_id = trace_id_from_headers(request)
        try:
            aggregation = selected_aggregator.aggregate(
                trace_id,
                request_id=request_id,
                request_trace_id=request_trace_id,
            )
        except CrossServiceTraceError as exc:
            return problem_response(
                request,
                status_code=422,
                error_code=exc.error_code,
                title="Cross-service trace query rejected",
                detail=exc.detail,
                retryable=False,
                type_uri="https://nex-platform.local/problems/cross-service-trace-invalid",
            )
        except ValueError:
            return problem_response(
                request,
                status_code=503,
                error_code="ag.cross_service_trace_aggregation_failed",
                title="Cross-service trace unavailable",
                detail="Cross-service trace aggregation is temporarily unavailable.",
                retryable=True,
                type_uri="https://nex-platform.local/problems/cross-service-trace-unavailable",
            )

        audit = emit_cross_service_trace_read_audit_event(
            audit_emitter,
            trace_id=trace_id,
            request_id=request_id,
            aggregation=aggregation,
        )
        if not audit.ok or audit.event is None:
            return problem_response(
                request,
                status_code=503,
                error_code="ag.cross_service_trace_audit_unavailable",
                title="Cross-service trace audit unavailable",
                detail="Durable trace-read audit evidence is unavailable.",
                retryable=True,
                type_uri="https://nex-platform.local/problems/cross-service-trace-audit-unavailable",
            )
        return attach_ag_trace_read_audit_stage(aggregation.projection, audit.event)


def emit_cross_service_trace_read_audit_event(
    emitter: OperationalEventEmitter,
    *,
    trace_id: str,
    request_id: str,
    aggregation: CrossServiceTraceAggregation,
):
    statuses = {
        item["service_id"]: item["source_status"]
        for item in aggregation.projection["source_statuses"]
    }
    return emitter.safe_emit(
        event_type=AG_TRACE_READ_EVENT_TYPE,
        severity=(
            "INFO"
            if aggregation.projection["projection_status"] == "READY"
            else "WARNING"
        ),
        message="AG cross-service trace projection was read.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref={"type": "cross_service_trace", "id": trace_id},
        details={
            "projection_status": aggregation.projection["projection_status"],
            "source_count": len(statuses),
            "ready_source_count": sum(value == "READY" for value in statuses.values()),
            "degraded_source_count": sum(
                value == "DEGRADED" for value in statuses.values()
            ),
            "unavailable_source_count": sum(
                value == "UNAVAILABLE" for value in statuses.values()
            ),
            "stage_count": aggregation.projection["summary"]["stage_count"],
            "diagnostic_count": len(aggregation.diagnostics),
            "diagnostic_error_codes": sorted(
                str(item["error_code"]) for item in aggregation.diagnostics
            ),
            "private_payload_included": False,
        },
    )


def attach_ag_trace_read_audit_stage(
    projection: Mapping[str, Any],
    audit_event: Mapping[str, Any],
) -> dict[str, Any]:
    stage = build_cross_service_trace_stage(
        stage_id=f"ag-event-{audit_event['event_id']}",
        trace_id=projection["trace_id"],
        request_id=audit_event["request_id"],
        service_id="nex-ag",
        stage_family="OPERATIONS",
        stage_status="SUCCEEDED",
        operation_timestamp=audit_event["created_at"],
        safe_attributes={
            "event_type": audit_event["event_type"],
            "result_code": "AUDITED",
        },
    )
    statuses = {
        item["service_id"]: item["source_status"]
        for item in projection["source_statuses"]
    }
    statuses["nex-ag"] = "READY"
    return build_cross_service_trace_timeline(
        trace_id=projection["trace_id"],
        stages=[*projection["timeline"], stage],
        source_statuses=statuses,
        checked_at=audit_event["created_at"],
    )


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _safe_error_code(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(
        ("ag.", "ae.", "cx.", "mo.", "oa.")
    ):
        return "ag.trace_source_request_failed"
    return value[:128]


def _diagnostic(
    service_id: str,
    error_code: str,
    *,
    retryable: bool,
    status_code: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "service_id": service_id,
        "error_code": error_code,
        "retryable": retryable,
    }
    if status_code is not None:
        result["status_code"] = status_code
    return result
