from __future__ import annotations

import os
from typing import Any

from fastapi import Request

from nex_mo.provider_catalog import DEFAULT_PROVIDER_MODE
from nex_mo.provider_registry import ProviderRouteError
from nex_runtime import (
    OperationalEventEmitter,
    request_id_from_headers,
    trace_id_from_headers,
)


def emit_provider_trace_event(
    emitter: OperationalEventEmitter,
    *,
    request: Request,
    capability: str,
    alias: str,
    response: dict[str, Any] | None = None,
    route_error: ProviderRouteError | None = None,
) -> None:
    succeeded = route_error is None
    details: dict[str, Any] = {
        "provider_capability": capability,
        "model_alias": alias,
        "provider_mode": os.getenv("NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE),
        "result_code": "SUCCEEDED" if succeeded else "FAILED",
        "retryable": bool(route_error.retryable) if route_error is not None else False,
    }
    if isinstance(response, dict):
        for field_name in ("model_revision", "deployment_id"):
            value = response.get(field_name)
            if isinstance(value, str) and value:
                details[field_name] = value
        metadata = response.get("runtime_metadata")
        if isinstance(metadata, dict):
            for source_field, target_field in (
                ("route_id", "provider_route_id"),
                ("provider_request_id", "provider_request_id"),
            ):
                value = metadata.get(source_field)
                if isinstance(value, str) and value:
                    details[target_field] = value
    if route_error is not None:
        details["failure_code"] = route_error.error_code
    request_id = request_id_from_headers(request)
    provider_request_id = details.get("provider_request_id")
    emitter.safe_emit(
        event_type=(
            "mo.provider.request.succeeded"
            if succeeded
            else "mo.provider.request.failed"
        ),
        severity="INFO" if succeeded else "ERROR",
        message=(
            "MO provider request completed."
            if succeeded
            else "MO provider request failed."
        ),
        trace_id=trace_id_from_headers(request),
        request_id=request_id,
        subject_ref={
            "type": "mo.provider_request",
            "id": (
                provider_request_id
                if isinstance(provider_request_id, str)
                else request_id
            ),
        },
        details=details,
    )
