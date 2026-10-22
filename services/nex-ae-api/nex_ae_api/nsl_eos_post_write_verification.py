from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

import httpx
from nex_runtime.semantic_hashes import validate_hash_ref

from .nsl_eos_write_execution import (
    DEFAULT_EOS_BASE_URL,
    EOS_CREATE_VOUCHER_OPERATION,
)
from .nsl_v02_public_api import NslV02PublicApiAdapter
from .service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

EOS_GET_VOUCHER_OPERATION = "FINANCE.GET_VOUCHER_DRAFT"
EOS_VOUCHER_VERIFICATION_SCHEMA = "eos_voucher_verification.v1"
EOS_VOUCHER_VERIFICATION_PATH = "/internal/v1/finance/voucher-drafts"

_PROJECTION_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "voucher_ref",
        "business_operation_id",
        "operation",
        "idempotency_key",
        "business_transaction_ref",
        "payload_hash",
        "commit_state",
        "voucher_state",
        "voucher_version",
        "project_ref",
        "line_count",
        "attachment_count",
        "balance",
        "stable_business_state_hash",
        "last_observed_at",
    }
)
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_AUTHORITATIVE_FAILURES = {
    404: "EOS_VOUCHER_VERIFICATION_NOT_FOUND",
    409: "EOS_VOUCHER_VERIFICATION_BINDING_INVALID",
}


@dataclass(frozen=True)
class EosPostWriteVerificationError(RuntimeError):
    error_code: str
    detail: str
    status_code: int | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class EosVoucherVerificationResponse:
    status_code: int
    payload: Mapping[str, Any]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class HttpEosPostWriteVerificationAdapter:
    public_api: NslV02PublicApiAdapter
    base_url: str = DEFAULT_EOS_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 15.0
    transport: httpx.AsyncBaseTransport | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    clock: Callable[[], datetime] = field(
        default=_utc_now,
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
            raise ValueError("EOS verification timeout must be a positive number")
        if not callable(self.clock):
            raise TypeError("EOS verification clock must be callable")

    async def read(self, request: object) -> object:
        response = await self.query_raw(request)
        return map_eos_voucher_verification_response(
            response,
            request,
            public_api=self.public_api,
            observed_at=self.clock(),
        )

    async def query_raw(self, request: object) -> EosVoucherVerificationResponse:
        binding = _request_binding(request, self.public_api)
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-eos",
            )
        except AeOutboundServiceTokenError as exc:
            raise EosPostWriteVerificationError(
                "ae.nsl_eos_verification.service_token_unavailable",
                "EOS post-WRITE verification authentication is unavailable.",
            ) from exc
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{self.base_url.rstrip('/')}{EOS_VOUCHER_VERIFICATION_PATH}/"
                    f"{binding['voucher_id']}/verification",
                    params={"business_operation_id": binding["business_operation_id"]},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Cache-Control": "no-store, max-age=0",
                        "Pragma": "no-cache",
                        "X-NeX-Tenant-Id": binding["tenant_id"],
                        "X-Request-ID": binding["invocation_id"],
                        "X-Service-ID": "nex-ae-api",
                    },
                )
        except httpx.TimeoutException as exc:
            raise TimeoutError("EOS post-WRITE verification timed out.") from exc
        except httpx.NetworkError as exc:
            raise ConnectionError(
                "EOS post-WRITE verification connection was lost."
            ) from exc
        except httpx.HTTPError as exc:
            raise EosPostWriteVerificationError(
                "ae.nsl_eos_verification.transport_failed",
                "EOS post-WRITE verification transport failed.",
            ) from exc
        return EosVoucherVerificationResponse(
            response.status_code,
            MappingProxyType(_response_payload(response)),
        )


def build_default_eos_post_write_verification_adapter(
    *,
    public_api: NslV02PublicApiAdapter,
    environ: Mapping[str, str] | None = None,
) -> HttpEosPostWriteVerificationAdapter:
    env = os.environ if environ is None else environ
    timeout_text = env.get("NEX_AE_EOS_VERIFICATION_TIMEOUT_SECONDS", "15")
    try:
        timeout = float(timeout_text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "NEX_AE_EOS_VERIFICATION_TIMEOUT_SECONDS must be numeric"
        ) from exc
    return HttpEosPostWriteVerificationAdapter(
        public_api=public_api,
        base_url=env.get("NEX_EOS_BASE_URL", DEFAULT_EOS_BASE_URL),
        service_token=env.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
        timeout_seconds=timeout,
    )


def map_eos_voucher_verification_response(
    response: EosVoucherVerificationResponse,
    request: object,
    *,
    public_api: NslV02PublicApiAdapter,
    observed_at: datetime,
) -> object:
    if not isinstance(response, EosVoucherVerificationResponse):
        raise TypeError("response must be an EosVoucherVerificationResponse")
    binding = _request_binding(request, public_api)
    if response.status_code == 200:
        projection = _validated_projection(response.payload, binding)
        return public_api.verification_observation(
            request_hash=binding["request_hash"],
            business_reference=binding["business_reference"],
            matched=True,
            evidence_ref=(
                "eos.voucher_verification:"
                f"{binding['business_operation_id']}:"
                f"{projection['stable_business_state_hash']}"
            ),
            observed_at=projection["last_observed_at"],
        )
    expected_reason = _AUTHORITATIVE_FAILURES.get(response.status_code)
    observed_reason = _problem_reason_code(response)
    if expected_reason is not None and observed_reason == expected_reason:
        return public_api.verification_observation(
            request_hash=binding["request_hash"],
            business_reference=binding["business_reference"],
            matched=False,
            reason_code=expected_reason,
            evidence_ref=(
                "eos.voucher_verification_failure:"
                f"{binding['business_operation_id']}:{expected_reason}"
            ),
            observed_at=_utc_datetime_value(observed_at, "observed_at"),
        )
    raise EosPostWriteVerificationError(
        "ae.nsl_eos_verification.unavailable",
        "EOS did not provide an authoritative verification observation.",
        status_code=response.status_code,
    )


def _request_binding(
    request: object,
    public_api: NslV02PublicApiAdapter,
) -> dict[str, str]:
    if not isinstance(request, public_api.verification_request):
        raise EosPostWriteVerificationError(
            "ae.nsl_eos_verification.request_invalid",
            "EOS verification requires an admitted NSL VerificationRequest.",
        )
    identity = request.identity
    if not isinstance(identity, public_api.write_outcome_identity):
        raise EosPostWriteVerificationError(
            "ae.nsl_eos_verification.request_invalid",
            "EOS verification requires an admitted WRITE outcome identity.",
        )
    if identity.tool_id != EOS_CREATE_VOUCHER_OPERATION:
        raise _request_invalid("WRITE tool identity is not supported by EOS.")
    if request.verification_tool_id != EOS_GET_VOUCHER_OPERATION:
        raise _request_invalid("Verification tool identity is not supported by EOS.")
    if request.consistency_hint != "READ_AFTER_WRITE_STRONG":
        raise _request_invalid("EOS verification requires strong read-after-write.")
    tenant_id = _scoped_id("tenant_id", identity.tenant_id)
    invocation_id = _scoped_id("invocation_id", identity.invocation_id)
    business_operation_id = _uuid(
        "business_operation_id",
        identity.business_operation_id,
    )
    if request.provider_transaction_id != business_operation_id:
        raise _request_invalid(
            "Provider transaction and BusinessOperation identities differ."
        )
    voucher_id = _voucher_id(request.business_reference)
    try:
        payload_hash = validate_hash_ref(identity.payload_hash)
    except ValueError as exc:
        raise _request_invalid("WRITE payload hash is invalid.") from exc
    idempotency_key = _scoped_id("idempotency_key", identity.idempotency_key)
    try:
        request_hash = validate_hash_ref(request.request_hash)
    except ValueError as exc:
        raise _request_invalid("Verification request hash is invalid.") from exc
    return {
        "tenant_id": tenant_id,
        "invocation_id": invocation_id,
        "business_operation_id": business_operation_id,
        "business_reference": request.business_reference,
        "voucher_id": voucher_id,
        "payload_hash": payload_hash,
        "idempotency_key": idempotency_key,
        "request_hash": request_hash,
    }


def _validated_projection(
    payload: Mapping[str, Any],
    binding: Mapping[str, str],
) -> dict[str, Any]:
    if set(payload) != _PROJECTION_FIELDS:
        raise _response_invalid(
            "EOS verification fields differ from the canonical contract."
        )
    expected = {
        "schema_version": EOS_VOUCHER_VERIFICATION_SCHEMA,
        "tenant_id": binding["tenant_id"],
        "business_operation_id": binding["business_operation_id"],
        "operation": EOS_CREATE_VOUCHER_OPERATION,
        "idempotency_key": binding["idempotency_key"],
        "payload_hash": binding["payload_hash"],
        "commit_state": "COMMITTED",
        "voucher_state": "DRAFT",
        "balance": "0.00",
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise _response_invalid(
            "EOS verification state differs from the committed WRITE identity."
        )
    voucher_ref = _entity_ref(
        payload.get("voucher_ref"),
        expected_type="eos.voucher_draft",
    )
    if voucher_ref["id"] != binding["voucher_id"]:
        raise _response_invalid("EOS verification Voucher identity differs.")
    transaction_ref = _entity_ref(
        payload.get("business_transaction_ref"),
        expected_type="eos.business_operation",
    )
    if transaction_ref["id"] != binding["business_operation_id"]:
        raise _response_invalid("EOS verification transaction identity differs.")
    project_ref = _entity_ref(
        payload.get("project_ref"),
        expected_type="eos.project",
    )
    voucher_version = _bounded_count(
        "voucher_version",
        payload.get("voucher_version"),
        minimum=1,
    )
    line_count = _bounded_count("line_count", payload.get("line_count"), minimum=2)
    attachment_count = _bounded_count(
        "attachment_count",
        payload.get("attachment_count"),
        minimum=0,
    )
    try:
        stable_hash = validate_hash_ref(payload.get("stable_business_state_hash"))
    except ValueError as exc:
        raise _response_invalid(
            "EOS verification business-state hash is invalid."
        ) from exc
    return {
        **expected,
        "voucher_ref": voucher_ref,
        "business_transaction_ref": transaction_ref,
        "project_ref": project_ref,
        "voucher_version": voucher_version,
        "line_count": line_count,
        "attachment_count": attachment_count,
        "stable_business_state_hash": stable_hash,
        "last_observed_at": _utc_datetime(payload.get("last_observed_at")),
    }


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _response_invalid("EOS verification response is not JSON.") from exc
    if not isinstance(payload, Mapping):
        raise _response_invalid("EOS verification response must be an object.")
    return dict(payload)


def _problem_reason_code(response: EosVoucherVerificationResponse) -> str | None:
    code = response.payload.get("error_code")
    status = response.payload.get("status")
    if (
        isinstance(code, str)
        and _REASON_CODE.fullmatch(code) is not None
        and status == response.status_code
    ):
        return code
    return None


def _voucher_id(business_reference: object) -> str:
    prefix = "eos.voucher_draft:"
    if not isinstance(business_reference, str) or not business_reference.startswith(
        prefix
    ):
        raise _request_invalid("Verification business reference is not a VoucherRef.")
    return _uuid("voucher_id", business_reference[len(prefix) :])


def _entity_ref(value: object, *, expected_type: str) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"type", "id"}
        or value.get("type") != expected_type
        or not isinstance(value.get("id"), str)
    ):
        raise _response_invalid("EOS verification entity reference is invalid.")
    try:
        entity_id = str(uuid.UUID(value["id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _response_invalid(
            "EOS verification entity reference is invalid."
        ) from exc
    return {"type": expected_type, "id": entity_id}


def _bounded_count(field_name: str, value: object, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _response_invalid(f"EOS verification {field_name} is invalid.")
    return value


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise _response_invalid("EOS verification observation time is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _response_invalid(
            "EOS verification observation time is invalid."
        ) from exc
    return _utc_datetime_value(parsed, "EOS verification observation time")


def _utc_datetime_value(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise EosPostWriteVerificationError(
            "ae.nsl_eos_verification.time_invalid",
            f"{field_name} must use timezone-aware UTC.",
        )
    return value


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _request_invalid(f"{field_name} has an invalid format.")
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _request_invalid(f"{field_name} must be a UUID.") from exc


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


def _request_invalid(detail: str) -> EosPostWriteVerificationError:
    return EosPostWriteVerificationError(
        "ae.nsl_eos_verification.request_invalid",
        detail,
    )


def _response_invalid(detail: str) -> EosPostWriteVerificationError:
    return EosPostWriteVerificationError(
        "ae.nsl_eos_verification.response_invalid",
        detail,
    )
