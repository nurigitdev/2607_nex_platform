from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any
from urllib.parse import parse_qs

from .diagnostic_evidence import DiagnosticEvidenceRecorder

HTTP_EVIDENCE_CAPTURE_LIMIT_BYTES = 4 * 1024 * 1024

AsgiReceive = Callable[[], Awaitable[MutableMapping[str, Any]]]
AsgiSend = Callable[[MutableMapping[str, Any]], Awaitable[None]]
AsgiApplication = Callable[
    [MutableMapping[str, Any], AsgiReceive, AsgiSend], Awaitable[None]
]


class DiagnosticHttpEvidenceMiddleware:
    """Capture one HTTP exchange into the restricted live-journey evidence set."""

    def __init__(
        self,
        app: AsgiApplication,
        *,
        recorder: DiagnosticEvidenceRecorder,
        capture_limit_bytes: int = HTTP_EVIDENCE_CAPTURE_LIMIT_BYTES,
    ) -> None:
        if capture_limit_bytes < 1:
            raise ValueError("capture_limit_bytes must be positive")
        self._app = app
        self._recorder = recorder
        self._capture_limit_bytes = capture_limit_bytes

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: AsgiReceive,
        send: AsgiSend,
    ) -> None:
        if scope.get("type") != "http" or not self._recorder.policy.enabled:
            await self._app(scope, receive, send)
            return

        request_capture = _BodyCapture(self._capture_limit_bytes)
        response_capture = _BodyCapture(self._capture_limit_bytes)
        response_status: int | None = None
        response_headers: list[tuple[bytes, bytes]] = []
        started = time.monotonic()
        application_error: BaseException | None = None

        async def observed_receive() -> MutableMapping[str, Any]:
            message = await receive()
            if message.get("type") == "http.request":
                request_capture.append(bytes(message.get("body") or b""))
            return message

        async def observed_send(message: MutableMapping[str, Any]) -> None:
            nonlocal response_status, response_headers
            if message.get("type") == "http.response.start":
                response_status = int(message.get("status") or 0)
                response_headers = list(message.get("headers") or ())
            elif message.get("type") == "http.response.body":
                response_capture.append(bytes(message.get("body") or b""))
            await send(message)

        try:
            await self._app(scope, observed_receive, observed_send)
        except BaseException as exc:
            application_error = exc
            raise
        finally:
            self._emit_exchange(
                scope=scope,
                request_capture=request_capture,
                response_capture=response_capture,
                response_status=response_status,
                response_headers=response_headers,
                duration_ms=round((time.monotonic() - started) * 1000, 3),
                application_error=application_error,
            )

    def _emit_exchange(
        self,
        *,
        scope: Mapping[str, Any],
        request_capture: _BodyCapture,
        response_capture: _BodyCapture,
        response_status: int | None,
        response_headers: list[tuple[bytes, bytes]],
        duration_ms: float,
        application_error: BaseException | None,
    ) -> None:
        request_headers = _headers(scope.get("headers") or ())
        response_header_values = _headers(response_headers)
        request_body = _body_projection(
            request_capture,
            request_headers.get("content-type", ""),
        )
        response_body = _body_projection(
            response_capture,
            response_header_values.get("content-type", ""),
        )
        query = _query_projection(bytes(scope.get("query_string") or b""))
        body_mapping = request_body if isinstance(request_body, Mapping) else {}
        trace_id = _first_text(
            request_headers.get("x-trace-id"),
            request_headers.get("traceparent"),
            body_mapping.get("trace_id"),
        )
        request_id = _first_text(
            request_headers.get("x-request-id"), body_mapping.get("request_id")
        )
        self._recorder.emit(
            "http.exchange",
            {
                "method": str(scope.get("method") or ""),
                "path": str(scope.get("path") or ""),
                "query_parameters": query,
                "request_headers": request_headers,
                "request_body": request_body,
                "request_body_size_bytes": request_capture.size_bytes,
                "request_body_sha256": request_capture.sha256,
                "request_body_truncated": request_capture.truncated,
                "response_status": response_status,
                "response_headers": response_header_values,
                "response_body": response_body,
                "response_body_size_bytes": response_capture.size_bytes,
                "response_body_sha256": response_capture.sha256,
                "response_body_truncated": response_capture.truncated,
                "duration_ms": duration_ms,
                "application_error_type": (
                    type(application_error).__name__
                    if application_error is not None
                    else None
                ),
            },
            trace_id=trace_id,
            request_id=request_id,
            interaction_id=_first_text(body_mapping.get("interaction_id")),
            agent_execution_id=_first_text(body_mapping.get("execution_id")),
            runtime_job_id=_first_text(body_mapping.get("runtime_job_id")),
        )


class _BodyCapture:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._buffer = bytearray()
        self._digest = hashlib.sha256()
        self.size_bytes = 0

    def append(self, value: bytes) -> None:
        self._digest.update(value)
        self.size_bytes += len(value)
        remaining = self._limit - len(self._buffer)
        if remaining > 0:
            self._buffer.extend(value[:remaining])

    @property
    def body(self) -> bytes:
        return bytes(self._buffer)

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    @property
    def truncated(self) -> bool:
        return self.size_bytes > len(self._buffer)


def _body_projection(capture: _BodyCapture, content_type: str) -> Any:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if capture.truncated or media_type.startswith("multipart/"):
        return _opaque_body_projection(capture, media_type)
    body = capture.body
    if not body:
        return None
    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _opaque_body_projection(capture, media_type, malformed=True)
    if media_type == "application/x-www-form-urlencoded":
        try:
            return _query_projection(body)
        except UnicodeDecodeError:
            return _opaque_body_projection(capture, media_type, malformed=True)
    if media_type.startswith("text/"):
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return _opaque_body_projection(capture, media_type, malformed=True)
    return _opaque_body_projection(capture, media_type)


def _opaque_body_projection(
    capture: _BodyCapture,
    media_type: str,
    *,
    malformed: bool = False,
) -> dict[str, Any]:
    return {
        "content_type": media_type or "application/octet-stream",
        "size_bytes": capture.size_bytes,
        "sha256": capture.sha256,
        "truncated": capture.truncated,
        "malformed_structured_body": malformed,
        "raw_binary_included": False,
    }


def _headers(values: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, raw_value in values:
        name = bytes(raw_name).decode("latin-1").lower()
        value = bytes(raw_value).decode("latin-1")
        result[name] = f"{result[name]}, {value}" if name in result else value
    return result


def _query_projection(value: bytes) -> dict[str, Any]:
    parsed = parse_qs(value.decode("utf-8"), keep_blank_values=True)
    return {
        key: values[0] if len(values) == 1 else values for key, values in parsed.items()
    }


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()[:512]
    return None
