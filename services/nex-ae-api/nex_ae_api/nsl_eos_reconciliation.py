from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

import httpx

from .nsl_eos_write_execution import (
    DEFAULT_EOS_BASE_URL,
    EOS_CREATE_VOUCHER_OPERATION,
)
from .nsl_v02_public_api import NslV02PublicApiAdapter
from .service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

EOS_BUSINESS_OPERATION_QUERY_SCHEMA = "eos_business_operation_query.v1"
EOS_BUSINESS_OPERATION_PATH = "/internal/v1/business-operations"

_PROJECTION_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "business_operation_id",
        "operation",
        "payload_hash",
        "commit_state",
        "business_transaction_ref",
        "voucher_ref",
        "reconciliation_status",
        "last_observed_at",
    }
)
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True)
class EosReconciliationError(RuntimeError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class EosBusinessOperationResponse:
    status_code: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class HttpEosReconciliationAdapter:
    public_api: NslV02PublicApiAdapter
    base_url: str = DEFAULT_EOS_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 15.0
    transport: httpx.AsyncBaseTransport | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    result_type: object | None = field(default=None, repr=False, compare=False)
    result_classification: object | None = field(
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
            raise ValueError("EOS reconciliation timeout must be a positive number")

    async def reconcile(self, request: object, unknown: object) -> object:
        identity = _bound_unknown_identity(request, unknown, self.public_api)
        result_type, result_classification = _result_contract(
            self.result_type,
            self.result_classification,
        )
        try:
            response = await self.query_raw(request)
        except TimeoutError:
            return _unknown(
                identity,
                public_api=self.public_api,
                reason_code="RECONCILIATION_REQUIRED",
                cause_code="EOS_RECONCILIATION_TIMEOUT",
            )
        except ConnectionError:
            return _unknown(
                identity,
                public_api=self.public_api,
                reason_code="RECONCILIATION_REQUIRED",
                cause_code="EOS_RECONCILIATION_CONNECTION_LOST",
            )
        except EosReconciliationError:
            return _unknown(
                identity,
                public_api=self.public_api,
                reason_code="RECONCILIATION_REQUIRED",
                cause_code="EOS_RECONCILIATION_UNAVAILABLE",
            )
        return map_eos_business_operation_response(
            response,
            request,
            identity=identity,
            public_api=self.public_api,
            result_type=result_type,
            result_classification=result_classification,
        )

    async def query_raw(self, request: object) -> EosBusinessOperationResponse:
        _request_identity(request, self.public_api)
        tenant_id = _scoped_id("tenant_id", getattr(request, "tenant_id", None))
        operation_id = _uuid(
            "business_operation_id",
            getattr(request, "business_operation_id", None),
        )
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-eos",
            )
        except AeOutboundServiceTokenError as exc:
            raise EosReconciliationError(
                "ae.nsl_eos_reconciliation.service_token_unavailable",
                "EOS reconciliation authentication is unavailable.",
            ) from exc
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{self.base_url.rstrip('/')}{EOS_BUSINESS_OPERATION_PATH}/"
                    f"{operation_id}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Cache-Control": "no-store, max-age=0",
                        "Pragma": "no-cache",
                        "X-NeX-Tenant-Id": tenant_id,
                        "X-Request-ID": str(request.invocation_id),
                        "X-Service-ID": "nex-ae-api",
                    },
                )
        except httpx.TimeoutException as exc:
            raise TimeoutError("EOS reconciliation query timed out.") from exc
        except httpx.NetworkError as exc:
            raise ConnectionError("EOS reconciliation connection was lost.") from exc
        except httpx.HTTPError as exc:
            raise EosReconciliationError(
                "ae.nsl_eos_reconciliation.transport_failed",
                "EOS reconciliation transport failed.",
            ) from exc
        return EosBusinessOperationResponse(
            response.status_code,
            MappingProxyType(_response_payload(response)),
        )


def build_default_eos_reconciliation_adapter(
    *,
    public_api: NslV02PublicApiAdapter,
    result_type: object,
    result_classification: object,
    environ: Mapping[str, str] | None = None,
) -> HttpEosReconciliationAdapter:
    env = os.environ if environ is None else environ
    timeout_text = env.get("NEX_AE_EOS_RECONCILIATION_TIMEOUT_SECONDS", "15")
    try:
        timeout = float(timeout_text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "NEX_AE_EOS_RECONCILIATION_TIMEOUT_SECONDS must be numeric"
        ) from exc
    return HttpEosReconciliationAdapter(
        public_api=public_api,
        base_url=env.get("NEX_EOS_BASE_URL", DEFAULT_EOS_BASE_URL),
        service_token=env.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
        timeout_seconds=timeout,
        result_type=result_type,
        result_classification=result_classification,
    )


def map_eos_business_operation_response(
    response: EosBusinessOperationResponse,
    request: object,
    *,
    identity: object,
    public_api: NslV02PublicApiAdapter,
    result_type: object,
    result_classification: object,
) -> object:
    if not isinstance(response, EosBusinessOperationResponse):
        raise TypeError("response must be an EosBusinessOperationResponse")
    if response.status_code != 200:
        cause_code = _problem_reason_code(response) or "EOS_RECONCILIATION_UNAVAILABLE"
        return _unknown(
            identity,
            public_api=public_api,
            reason_code="RECONCILIATION_REQUIRED",
            cause_code=cause_code,
            status_code=response.status_code,
        )
    try:
        projection = _validated_projection(response.payload, request)
    except EosReconciliationError:
        return _unknown(
            identity,
            public_api=public_api,
            reason_code="RECONCILIATION_REQUIRED",
            cause_code="EOS_RECONCILIATION_RESPONSE_UNTRUSTWORTHY",
            status_code=response.status_code,
        )
    evidence_refs = (
        f"eos.business_operation:{projection['business_operation_id']}",
        f"eos.reconciliation:{projection['business_operation_id']}",
    )
    if projection["commit_state"] == "COMMITTED":
        voucher_ref = projection["voucher_ref"]
        value = _result_value_envelope(
            request,
            value={"voucher_no": voucher_ref["id"]},
            result_type=result_type,
            result_classification=result_classification,
            evidence_refs=evidence_refs,
        )
        result = public_api.write_result_envelope(
            identity=identity,
            value=value,
            business_reference=f"{voucher_ref['type']}:{voucher_ref['id']}",
            provider_transaction_id=projection["business_operation_id"],
            committed_at=projection["last_observed_at"],
            evidence_refs=evidence_refs,
        )
        return public_api.write_committed(result=result)
    if projection["commit_state"] == "NOT_COMMITTED":
        return public_api.write_not_committed(
            identity=identity,
            reason_code="EOS_NOT_COMMITTED_CONFIRMED",
            message="EOS reconciliation confirmed that the command was not committed.",
            provider_transaction_id=projection["business_operation_id"],
            evidence_refs=evidence_refs,
        )
    return _unknown(
        identity,
        public_api=public_api,
        reason_code="RECONCILIATION_REQUIRED",
        provider_transaction_id=projection["business_operation_id"],
        evidence_refs=evidence_refs,
    )


def _bound_unknown_identity(
    request: object,
    unknown: object,
    public_api: NslV02PublicApiAdapter,
) -> object:
    identity = _request_identity(request, public_api)
    if not isinstance(unknown, public_api.write_commit_unknown):
        raise EosReconciliationError(
            "ae.nsl_eos_reconciliation.outcome_invalid",
            "Reconciliation requires an NSL WriteCommitUnknown outcome.",
        )
    if unknown.identity != identity:
        raise EosReconciliationError(
            "ae.nsl_eos_reconciliation.identity_mismatch",
            "Unknown outcome and WRITE request identities differ.",
        )
    return identity


def _request_identity(
    request: object,
    public_api: NslV02PublicApiAdapter,
) -> object:
    if not isinstance(request, public_api.write_call_request):
        raise EosReconciliationError(
            "ae.nsl_eos_reconciliation.request_invalid",
            "Reconciliation requires an admitted NSL WriteCallRequest.",
        )
    return public_api.write_outcome_identity.from_request(request)


def _validated_projection(
    payload: Mapping[str, Any],
    request: object,
) -> dict[str, Any]:
    if set(payload) != _PROJECTION_FIELDS:
        raise _invalid("EOS reconciliation fields differ from the canonical contract.")
    expected = {
        "schema_version": EOS_BUSINESS_OPERATION_QUERY_SCHEMA,
        "tenant_id": str(request.tenant_id),
        "business_operation_id": str(request.business_operation_id),
        "operation": EOS_CREATE_VOUCHER_OPERATION,
        "payload_hash": str(request.payload_hash),
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise _invalid("EOS reconciliation lineage differs from the WRITE request.")
    operation_ref = _entity_ref(
        payload.get("business_transaction_ref"),
        expected_type="eos.business_operation",
    )
    if operation_ref["id"] != request.business_operation_id:
        raise _invalid("EOS reconciliation transaction reference is invalid.")
    observed_at = _utc_datetime(payload.get("last_observed_at"))
    state = payload.get("commit_state")
    reconciliation = payload.get("reconciliation_status")
    voucher_ref = payload.get("voucher_ref")
    if state == "COMMITTED" and reconciliation == "COMMITTED_CONFIRMED":
        voucher = _entity_ref(voucher_ref, expected_type="eos.voucher_draft")
    elif state == "NOT_COMMITTED" and reconciliation == "NOT_COMMITTED_CONFIRMED":
        if voucher_ref is not None:
            raise _invalid("A non-committed reconciliation cannot contain a voucher.")
        voucher = None
    elif (
        state == "UNKNOWN_COMMIT_STATE" and reconciliation == "RECONCILIATION_REQUIRED"
    ):
        if voucher_ref is not None:
            raise _invalid("An unknown reconciliation cannot contain a voucher.")
        voucher = None
    else:
        raise _invalid("EOS reconciliation state is inconsistent.")
    return {
        **expected,
        "commit_state": state,
        "business_transaction_ref": operation_ref,
        "voucher_ref": voucher,
        "reconciliation_status": reconciliation,
        "last_observed_at": observed_at,
    }


def _unknown(
    identity: object,
    *,
    public_api: NslV02PublicApiAdapter,
    reason_code: str,
    status_code: int | None = None,
    cause_code: str | None = None,
    provider_transaction_id: str | None = None,
    evidence_refs: tuple[str, ...] | None = None,
) -> object:
    refs = evidence_refs or _error_evidence_refs(
        cause_code or reason_code,
        status_code,
    )
    return public_api.write_commit_unknown(
        identity=identity,
        reason_code=reason_code,
        message=(
            "EOS has not provided an authoritative terminal commit state; "
            "reconciliation remains required."
        ),
        provider_transaction_id=provider_transaction_id,
        evidence_refs=refs,
    )


def _result_contract(
    result_type: object | None,
    result_classification: object | None,
) -> tuple[object, object]:
    if result_type is None:
        raise ValueError("EOS reconciliation result type is required")
    classification = getattr(result_classification, "value", None)
    if classification not in {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"}:
        raise ValueError("EOS reconciliation result classification is required")
    return result_type, result_classification


def _result_value_envelope(
    request: object,
    *,
    value: Mapping[str, Any],
    result_type: object,
    result_classification: object,
    evidence_refs: tuple[str, ...],
) -> object:
    arguments = getattr(request, "arguments", None)
    if not isinstance(arguments, Mapping) or not arguments:
        raise EosReconciliationError(
            "ae.nsl_eos_reconciliation.result_envelope_unavailable",
            "NSL WRITE request lacks an admitted ValueEnvelope type.",
        )
    envelope_type = type(next(iter(arguments.values())))
    complete = getattr(envelope_type, "complete", None)
    if not callable(complete):
        raise EosReconciliationError(
            "ae.nsl_eos_reconciliation.result_envelope_unavailable",
            "NSL WRITE request lacks an admitted ValueEnvelope factory.",
        )
    return complete(dict(value), result_type, result_classification, evidence_refs)


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EosReconciliationError(
            "ae.nsl_eos_reconciliation.response_invalid",
            "EOS reconciliation response is not JSON.",
        ) from exc
    if not isinstance(payload, Mapping):
        raise EosReconciliationError(
            "ae.nsl_eos_reconciliation.response_invalid",
            "EOS reconciliation response must be an object.",
        )
    return dict(payload)


def _problem_reason_code(response: EosBusinessOperationResponse) -> str | None:
    code = response.payload.get("error_code")
    status = response.payload.get("status")
    if (
        isinstance(code, str)
        and _REASON_CODE.fullmatch(code) is not None
        and (status is None or status == response.status_code)
    ):
        return code
    return None


def _error_evidence_refs(
    reason_code: str,
    status_code: int | None,
) -> tuple[str, ...]:
    refs = [f"eos.reason:{reason_code}"]
    if status_code is not None:
        refs.append(f"eos.http_status:{status_code}")
    return tuple(refs)


def _entity_ref(value: object, *, expected_type: str) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"type", "id"}
        or value.get("type") != expected_type
        or not isinstance(value.get("id"), str)
        or _SCOPED_ID.fullmatch(value["id"]) is None
    ):
        raise _invalid("EOS reconciliation entity reference is invalid.")
    return {"type": expected_type, "id": value["id"]}


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid("EOS reconciliation observation time is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("EOS reconciliation observation time is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise _invalid("EOS reconciliation observation time must be UTC.")
    return parsed


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise EosReconciliationError(
            "ae.nsl_eos_reconciliation.request_invalid",
            f"{field_name} has an invalid format.",
        )
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise EosReconciliationError(
            "ae.nsl_eos_reconciliation.request_invalid",
            f"{field_name} must be a UUID.",
        ) from exc


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


def _invalid(detail: str) -> EosReconciliationError:
    return EosReconciliationError(
        "ae.nsl_eos_reconciliation.response_invalid",
        detail,
    )
