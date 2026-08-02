from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

TRACEPARENT_PATTERN = re.compile(r"^00-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")


def problem_response(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    title: str,
    detail: str,
    retryable: bool = False,
    type_uri: str = "https://nex-platform.local/problems/request-failed",
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content={
            "type": type_uri,
            "title": title,
            "status": status_code,
            "detail": detail,
            "instance": request.url.path,
            "error_code": error_code,
            "retryable": retryable,
            "request_id": request_id_from_headers(request),
            "trace_id": trace_id_from_headers(request),
            "details": details or {},
        },
    )


def request_id_from_headers(request: Request) -> str:
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        return request_id.lower()
    return str(uuid4())


def trace_id_from_headers(request: Request) -> str:
    traceparent = request.headers.get("traceparent")
    if traceparent:
        match = TRACEPARENT_PATTERN.fullmatch(traceparent)
        if match:
            return match.group(1)
    return uuid4().hex
