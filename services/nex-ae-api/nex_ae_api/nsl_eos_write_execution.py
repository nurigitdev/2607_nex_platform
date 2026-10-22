from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import httpx
from nex_runtime import SERVICE_SPECS
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref

from .nsl_v02_public_api import NslV02PublicApiAdapter
from .service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

EOS_CREATE_VOUCHER_OPERATION = "FINANCE.CREATE_VOUCHER_DRAFT"
EOS_CREATE_VOUCHER_SCHEMA = "eos_create_voucher_draft_command.v1"
EOS_CREATE_VOUCHER_RESULT_SCHEMA = "eos_create_voucher_draft_result.v1"
EOS_CREATE_VOUCHER_PATH = "/internal/v1/finance/voucher-drafts"
DEFAULT_EOS_BASE_URL = f"http://127.0.0.1:{SERVICE_SPECS['nex-eos'].default_port}"

_BUSINESS_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "requester_ref",
        "project_ref",
        "voucher_type",
        "transaction_date",
        "currency",
        "description",
        "lines",
        "nsl_approval_request_id",
        "nsl_approval_evidence_ref",
        "business_approval_proof_ref",
        "attachments",
    }
)
_TRACE_FIELDS = ("trace_id", "correlation_id", "causation_id")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True)
class EosWriteExecutionError(RuntimeError):
    error_code: str
    detail: str
    retryable: bool = False
    outcome_uncertain: bool = False
    status_code: int | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class EosWriteExecutionResponse:
    status_code: int
    payload: Mapping[str, Any]

    @property
    def accepted(self) -> bool:
        return self.status_code in {200, 201}


@dataclass(frozen=True)
class HttpEosWriteExecutionPort:
    public_api: NslV02PublicApiAdapter
    base_url: str = DEFAULT_EOS_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 15.0
    transport: httpx.AsyncBaseTransport | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _validated_base_url(self.base_url)
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("EOS WRITE timeout must be a positive number")

    async def execute(self, request: object) -> EosWriteExecutionResponse:
        command = build_eos_create_voucher_command(
            request,
            public_api=self.public_api,
        )
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-eos",
            )
        except AeOutboundServiceTokenError as exc:
            raise EosWriteExecutionError(
                "ae.nsl_eos.service_token_unavailable",
                "EOS service authentication is unavailable.",
            ) from exc

        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}{EOS_CREATE_VOUCHER_PATH}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "X-NeX-Tenant-Id": str(request.tenant_id),
                        "X-Request-ID": str(request.invocation_id),
                        "X-Service-ID": "nex-ae-api",
                    },
                    json=command,
                )
        except httpx.TimeoutException as exc:
            raise TimeoutError("EOS command response timed out.") from exc
        except httpx.NetworkError as exc:
            raise ConnectionError("EOS command connection was lost.") from exc
        except httpx.HTTPError as exc:
            raise EosWriteExecutionError(
                "ae.nsl_eos.transport_failed",
                "EOS command transport failed before a trustworthy response.",
                retryable=True,
                outcome_uncertain=True,
            ) from exc

        payload = _response_payload(response)
        if response.status_code in {200, 201}:
            _validate_success_response(payload, command, response.status_code)
        elif response.status_code < 400:
            raise EosWriteExecutionError(
                "ae.nsl_eos.response_status_invalid",
                "EOS returned an unsupported command response status.",
                outcome_uncertain=True,
                status_code=response.status_code,
            )
        return EosWriteExecutionResponse(
            status_code=response.status_code,
            payload=MappingProxyType(payload),
        )


def build_default_eos_write_execution_port(
    *,
    public_api: NslV02PublicApiAdapter,
    environ: Mapping[str, str] | None = None,
) -> HttpEosWriteExecutionPort:
    env = os.environ if environ is None else environ
    timeout_text = env.get("NEX_AE_EOS_WRITE_TIMEOUT_SECONDS", "15")
    try:
        timeout = float(timeout_text)
    except (TypeError, ValueError) as exc:
        raise ValueError("NEX_AE_EOS_WRITE_TIMEOUT_SECONDS must be numeric") from exc
    return HttpEosWriteExecutionPort(
        public_api=public_api,
        base_url=env.get("NEX_EOS_BASE_URL", DEFAULT_EOS_BASE_URL),
        service_token=env.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
        timeout_seconds=timeout,
    )


def build_eos_create_voucher_command(
    request: object,
    *,
    public_api: NslV02PublicApiAdapter,
) -> dict[str, Any]:
    if not isinstance(request, public_api.write_call_request):
        raise _invalid("request must be the admitted NSL WriteCallRequest type")
    if request.tool_id != EOS_CREATE_VOUCHER_OPERATION:
        raise _invalid("NSL WRITE tool is not supported by the EOS adapter")
    if not isinstance(request.arguments, Mapping):
        raise _invalid("NSL WRITE arguments must be an object")
    if set(request.arguments) != _BUSINESS_FIELDS:
        raise _invalid("NSL WRITE arguments do not match the canonical EOS payload")

    business_payload = {
        name: _json_value(getattr(envelope, "value", _MISSING), path=f"$.{name}")
        for name, envelope in request.arguments.items()
    }
    if business_payload["schema_version"] != EOS_CREATE_VOUCHER_SCHEMA:
        raise _invalid("EOS command schema version is not supported")
    if business_payload["tenant_id"] != request.tenant_id:
        raise _invalid("EOS command tenant does not match the NSL WRITE request")
    if business_payload["nsl_approval_request_id"] != request.approval_request_id:
        raise _invalid("EOS command approval request lineage is invalid")
    try:
        computed_hash = nsl_write_payload_hash_ref(business_payload)
    except (TypeError, ValueError) as exc:
        raise _invalid("EOS business payload is not canonical JSON") from exc
    if computed_hash != request.payload_hash:
        raise _invalid("EOS business payload hash differs from the NSL payload hash")

    return {
        **business_payload,
        "business_operation_id": str(request.business_operation_id),
        "idempotency_key": str(request.idempotency_key),
        "payload_hash": str(request.payload_hash),
        "trace": _trace_from_refs(request.trace_refs),
    }


def _trace_from_refs(value: object) -> dict[str, str]:
    if not isinstance(value, tuple):
        raise _invalid("NSL WRITE trace_refs must be a tuple")
    result: dict[str, str] = {}
    for item in value:
        if not isinstance(item, str):
            raise _invalid("NSL WRITE trace_refs contain a non-string value")
        name, separator, trace_value = item.partition(":")
        if name not in _TRACE_FIELDS:
            continue
        if not separator or name in result or _SCOPED_ID.fullmatch(trace_value) is None:
            raise _invalid("NSL WRITE trace_refs contain an invalid EOS trace identity")
        result[name] = trace_value
    if tuple(sorted(result)) != tuple(sorted(_TRACE_FIELDS)):
        raise _invalid("NSL WRITE trace_refs lack canonical EOS trace identities")
    return {name: result[name] for name in _TRACE_FIELDS}


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EosWriteExecutionError(
            "ae.nsl_eos.response_invalid",
            "EOS command response is not valid JSON.",
            retryable=response.status_code >= 500,
            outcome_uncertain=response.status_code < 400,
            status_code=response.status_code,
        ) from exc
    if not isinstance(payload, Mapping):
        raise EosWriteExecutionError(
            "ae.nsl_eos.response_invalid",
            "EOS command response must be an object.",
            retryable=response.status_code >= 500,
            outcome_uncertain=response.status_code < 400,
            status_code=response.status_code,
        )
    try:
        return _json_value(payload, path="$")
    except EosWriteExecutionError as exc:
        raise EosWriteExecutionError(
            "ae.nsl_eos.response_invalid",
            "EOS command response contains a non-JSON value.",
            retryable=response.status_code >= 500,
            outcome_uncertain=response.status_code < 400,
            status_code=response.status_code,
        ) from exc


def _validate_success_response(
    payload: Mapping[str, Any],
    command: Mapping[str, Any],
    status_code: int,
) -> None:
    expected = {
        "schema_version": EOS_CREATE_VOUCHER_RESULT_SCHEMA,
        "tenant_id": command["tenant_id"],
        "business_operation_id": command["business_operation_id"],
        "idempotency_key": command["idempotency_key"],
        "payload_hash": command["payload_hash"],
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise EosWriteExecutionError(
            "ae.nsl_eos.response_lineage_invalid",
            "EOS command response lineage does not match the NSL WRITE request.",
            outcome_uncertain=True,
            status_code=status_code,
        )
    disposition = payload.get("idempotency_disposition")
    if (status_code, disposition) not in {(201, "CREATED"), (200, "REPLAYED")}:
        raise EosWriteExecutionError(
            "ae.nsl_eos.response_disposition_invalid",
            "EOS command response status and idempotency disposition differ.",
            outcome_uncertain=True,
            status_code=status_code,
        )


def _validated_base_url(value: object) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("EOS base URL must be a bounded HTTP URL")
    try:
        parsed = httpx.URL(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("EOS base URL must be a bounded HTTP URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise ValueError("EOS base URL must be a bounded HTTP URL")
    if parsed.username or parsed.password:
        raise ValueError("EOS base URL must not contain credentials")
    return value


def _json_value(value: Any, *, path: str) -> Any:
    if value is _MISSING:
        raise _invalid(f"NSL WRITE argument envelope is invalid at {path}")
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _invalid(f"EOS JSON object key is invalid at {path}")
            result[key] = _json_value(item, path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise _invalid(f"EOS JSON value is unsupported at {path}")


def _invalid(detail: str) -> EosWriteExecutionError:
    return EosWriteExecutionError("ae.nsl_eos.request_invalid", detail)


_MISSING = object()
