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
from nex_runtime import SERVICE_SPECS
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref, validate_hash_ref

from .nsl_v02_public_api import NslV02PublicApiAdapter
from .service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

EOS_JOURNAL_POST_OPERATION = "FINANCE.VOUCHER.APPROVE_AND_POST"
EOS_JOURNAL_POST_COMMAND_SCHEMA = "eos_journal_post_command.v1"
EOS_JOURNAL_POST_RESULT_SCHEMA = "eos_journal_post_result.v1"
EOS_JOURNAL_POST_PATH = "/internal/v2/finance/voucher-candidates"
DEFAULT_EOS_BASE_URL = f"http://127.0.0.1:{SERVICE_SPECS['nex-eos'].default_port}"

_BUSINESS_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "company_id",
        "candidate_id",
        "expected_candidate_version",
        "expected_candidate_revision",
        "expected_candidate_hash",
        "accounting_approval_evidence_id",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "idempotency_disposition",
        "created",
        "tenant_id",
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "commit_state",
        "result",
        "outbox",
    }
)
_BUSINESS_RESULT_FIELDS = frozenset(
    {
        "business_result_ref",
        "company_id",
        "journal_id",
        "journal_no",
        "candidate_id",
        "candidate_revision",
        "candidate_version",
        "candidate_state",
        "accounting_acceptance_id",
        "accounting_period_id",
        "project_codes",
        "consumption_id",
        "journal_hash",
        "posted_at",
    }
)
_OUTBOX_FIELDS = frozenset(
    {
        "outbox_id",
        "event_id",
        "event_type",
        "event_payload_hash",
        "delivery_state",
    }
)
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


@dataclass(frozen=True)
class EosJournalExecutionError(RuntimeError):
    error_code: str
    detail: str
    outcome_uncertain: bool = False
    status_code: int | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class EosJournalExecutionResponse:
    status_code: int
    payload: Mapping[str, Any]

    @property
    def accepted(self) -> bool:
        return self.status_code in {200, 201}


@dataclass(frozen=True)
class HttpEosJournalExecutionPort:
    public_api: NslV02PublicApiAdapter
    base_url: str = DEFAULT_EOS_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 15.0
    transport: httpx.AsyncBaseTransport | None = field(
        default=None, repr=False, compare=False
    )
    result_type: object | None = field(default=None, repr=False, compare=False)
    result_classification: object | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _validated_base_url(self.base_url)
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("EOS Journal WRITE timeout must be a positive number")

    async def execute(self, request: object) -> object:
        result_type, classification = _result_contract(
            self.result_type, self.result_classification
        )
        try:
            response = await self.execute_raw(request)
        except (TimeoutError, ConnectionError) as exc:
            reason = (
                "PROVIDER_TIMEOUT"
                if isinstance(exc, TimeoutError)
                else "PROVIDER_CONNECTION_LOST"
            )
            return _unknown(request, public_api=self.public_api, reason_code=reason)
        except EosJournalExecutionError as exc:
            if exc.outcome_uncertain:
                return _unknown(
                    request,
                    public_api=self.public_api,
                    reason_code="EOS_JOURNAL_RESPONSE_UNTRUSTWORTHY",
                    status_code=exc.status_code,
                )
            return _not_committed(
                request,
                public_api=self.public_api,
                reason_code="EOS_JOURNAL_COMMAND_NOT_DISPATCHED",
                status_code=exc.status_code,
            )
        return map_eos_journal_execution_response(
            response,
            request,
            public_api=self.public_api,
            result_type=result_type,
            result_classification=classification,
        )

    async def execute_raw(self, request: object) -> EosJournalExecutionResponse:
        candidate_id, command = build_eos_journal_post_command(
            request, public_api=self.public_api
        )
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token, audience="nex-eos"
            )
        except AeOutboundServiceTokenError as exc:
            raise EosJournalExecutionError(
                "ae.nsl_eos_journal.service_token_unavailable",
                "EOS Journal service authentication is unavailable.",
            ) from exc
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}{EOS_JOURNAL_POST_PATH}/"
                    f"{candidate_id}/posting",
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
            raise TimeoutError("EOS Journal command response timed out.") from exc
        except httpx.NetworkError as exc:
            raise ConnectionError("EOS Journal command connection was lost.") from exc
        except httpx.HTTPError as exc:
            raise EosJournalExecutionError(
                "ae.nsl_eos_journal.transport_failed",
                "EOS Journal transport failed before a trustworthy response.",
                outcome_uncertain=True,
            ) from exc
        payload = _response_payload(response)
        if response.status_code in {200, 201}:
            _validate_success_response(payload, command, candidate_id, response.status_code)
        elif response.status_code < 400:
            raise EosJournalExecutionError(
                "ae.nsl_eos_journal.response_status_invalid",
                "EOS returned an unsupported Journal response status.",
                outcome_uncertain=True,
                status_code=response.status_code,
            )
        return EosJournalExecutionResponse(
            response.status_code, MappingProxyType(payload)
        )


def build_default_eos_journal_execution_port(
    *,
    public_api: NslV02PublicApiAdapter,
    result_type: object,
    result_classification: object,
    environ: Mapping[str, str] | None = None,
) -> HttpEosJournalExecutionPort:
    env = os.environ if environ is None else environ
    try:
        timeout = float(env.get("NEX_AE_EOS_JOURNAL_WRITE_TIMEOUT_SECONDS", "15"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "NEX_AE_EOS_JOURNAL_WRITE_TIMEOUT_SECONDS must be numeric"
        ) from exc
    return HttpEosJournalExecutionPort(
        public_api=public_api,
        base_url=env.get("NEX_EOS_BASE_URL", DEFAULT_EOS_BASE_URL),
        service_token=env.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
        timeout_seconds=timeout,
        result_type=result_type,
        result_classification=result_classification,
    )


def build_eos_journal_post_command(
    request: object, *, public_api: NslV02PublicApiAdapter
) -> tuple[str, dict[str, Any]]:
    if not isinstance(request, public_api.write_call_request):
        raise _invalid("request must be the admitted NSL WriteCallRequest type")
    if request.tool_id != EOS_JOURNAL_POST_OPERATION:
        raise _invalid("NSL WRITE tool is not the EOS Journal Posting operation")
    if not isinstance(request.arguments, Mapping) or set(request.arguments) != (
        _BUSINESS_PAYLOAD_FIELDS
    ):
        raise _invalid("NSL WRITE arguments do not match the Journal business payload")
    business_payload = {
        name: _json_value(getattr(envelope, "value", None), path=f"$.{name}")
        for name, envelope in request.arguments.items()
    }
    if business_payload["schema_version"] != EOS_JOURNAL_POST_COMMAND_SCHEMA:
        raise _invalid("EOS Journal command schema version is not supported")
    if business_payload["tenant_id"] != request.tenant_id:
        raise _invalid("EOS Journal tenant differs from the NSL WRITE request")
    candidate_id = _uuid("candidate_id", business_payload["candidate_id"])
    _uuid("company_id", business_payload["company_id"])
    _positive_int("expected_candidate_version", business_payload["expected_candidate_version"])
    _positive_int("expected_candidate_revision", business_payload["expected_candidate_revision"])
    _hash_ref("expected_candidate_hash", business_payload["expected_candidate_hash"])
    _uuid(
        "accounting_approval_evidence_id",
        business_payload["accounting_approval_evidence_id"],
    )
    try:
        computed_hash = nsl_write_payload_hash_ref(business_payload)
    except (TypeError, ValueError) as exc:
        raise _invalid("EOS Journal business payload is not canonical JSON") from exc
    if computed_hash != request.payload_hash:
        raise _invalid("EOS Journal payload hash differs from the NSL payload hash")
    command = dict(business_payload)
    command.pop("candidate_id")
    command.update(
        business_operation_id=_uuid(
            "business_operation_id", request.business_operation_id
        ),
        idempotency_key=_scoped_id("idempotency_key", request.idempotency_key),
        payload_hash=_hash_ref("payload_hash", request.payload_hash),
        correlation_id=_correlation_id(request.trace_refs),
    )
    return candidate_id, command


def map_eos_journal_execution_response(
    response: EosJournalExecutionResponse,
    request: object,
    *,
    public_api: NslV02PublicApiAdapter,
    result_type: object,
    result_classification: object,
) -> object:
    if not isinstance(response, EosJournalExecutionResponse):
        raise TypeError("response must be an EosJournalExecutionResponse")
    identity = public_api.write_outcome_identity.from_request(request)
    if response.accepted:
        candidate_id, command = build_eos_journal_post_command(
            request, public_api=public_api
        )
        business = _validate_success_response(
            response.payload, command, candidate_id, response.status_code
        )
        evidence_refs = (
            f"eos.business_operation:{command['business_operation_id']}",
            f"eos.posted_journal:{business['journal_id']}:{business['journal_hash']}",
            f"eos.outbox_event:{response.payload['outbox']['event_id']}",
        )
        value = _result_value_envelope(
            request,
            value=_journal_result_value(business),
            result_type=result_type,
            result_classification=result_classification,
            evidence_refs=evidence_refs,
        )
        result = public_api.write_result_envelope(
            identity=identity,
            value=value,
            business_reference=business["business_result_ref"],
            provider_transaction_id=command["business_operation_id"],
            committed_at=_utc_datetime(business["posted_at"]),
            evidence_refs=evidence_refs,
        )
        return public_api.write_committed(result=result)
    reason = _problem_reason_code(response)
    if 400 <= response.status_code < 500:
        return _not_committed(
            request,
            public_api=public_api,
            identity=identity,
            reason_code=reason or "EOS_JOURNAL_COMMAND_REJECTED",
            status_code=response.status_code,
        )
    return _unknown(
        request,
        public_api=public_api,
        identity=identity,
        reason_code=reason or "EOS_JOURNAL_COMMIT_ACKNOWLEDGEMENT_UNAVAILABLE",
        status_code=response.status_code,
    )


def _validate_success_response(
    payload: Mapping[str, Any],
    command: Mapping[str, Any],
    candidate_id: str,
    status_code: int,
) -> dict[str, Any]:
    if set(payload) != _RESULT_FIELDS:
        raise _untrustworthy("EOS Journal result fields differ from the contract", status_code)
    expected = {
        "schema_version": EOS_JOURNAL_POST_RESULT_SCHEMA,
        "operation": EOS_JOURNAL_POST_OPERATION,
        "tenant_id": command["tenant_id"],
        "business_operation_id": command["business_operation_id"],
        "idempotency_key": command["idempotency_key"],
        "payload_hash": command["payload_hash"],
        "commit_state": "COMMITTED",
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise _untrustworthy("EOS Journal result lineage differs from the request", status_code)
    disposition = payload.get("idempotency_disposition")
    created = payload.get("created")
    if (status_code, disposition, created) not in {
        (201, "CREATED", True),
        (200, "REPLAYED", False),
    }:
        raise _untrustworthy("EOS Journal replay disposition is inconsistent", status_code)
    business = payload.get("result")
    outbox = payload.get("outbox")
    if not isinstance(business, Mapping) or set(business) != _BUSINESS_RESULT_FIELDS:
        raise _untrustworthy("EOS Journal business result is invalid", status_code)
    if not isinstance(outbox, Mapping) or set(outbox) != _OUTBOX_FIELDS:
        raise _untrustworthy("EOS Journal outbox result is invalid", status_code)
    journal_id = _uuid_response("journal_id", business.get("journal_id"), status_code)
    if business.get("business_result_ref") != f"eos.posted_journal:{journal_id}":
        raise _untrustworthy("EOS Journal business reference is invalid", status_code)
    if business.get("candidate_id") != candidate_id:
        raise _untrustworthy("EOS Journal candidate lineage is invalid", status_code)
    if business.get("company_id") != command["company_id"]:
        raise _untrustworthy("EOS Journal company lineage is invalid", status_code)
    if business.get("candidate_revision") != command["expected_candidate_revision"]:
        raise _untrustworthy("EOS Journal revision lineage is invalid", status_code)
    if business.get("candidate_version") != command["expected_candidate_version"] + 1:
        raise _untrustworthy("EOS Journal candidate version is invalid", status_code)
    if business.get("candidate_state") != "POSTED":
        raise _untrustworthy("EOS Journal candidate state is invalid", status_code)
    _hash_ref_response("journal_hash", business.get("journal_hash"), status_code)
    _utc_datetime_response(business.get("posted_at"), status_code)
    project_codes = business.get("project_codes")
    if (
        not isinstance(project_codes, list)
        or not project_codes
        or project_codes != sorted(set(project_codes))
        or any(not isinstance(code, str) or not _PROJECT_CODE.fullmatch(code) for code in project_codes)
    ):
        raise _untrustworthy("EOS Journal project-code lineage is invalid", status_code)
    for field_name in (
        "accounting_acceptance_id",
        "accounting_period_id",
        "consumption_id",
    ):
        _uuid_response(field_name, business.get(field_name), status_code)
    if (
        outbox.get("event_type") != "FINANCE.JOURNAL_POSTED.v1"
        or outbox.get("delivery_state") != "PENDING"
    ):
        raise _untrustworthy("EOS Journal outbox state is invalid", status_code)
    for field_name in ("outbox_id", "event_id"):
        _uuid_response(field_name, outbox.get(field_name), status_code)
    _hash_ref_response("event_payload_hash", outbox.get("event_payload_hash"), status_code)
    return dict(business)


def _journal_result_value(business: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "journal_id": business["journal_id"],
        "journal_no": business["journal_no"],
        "journal_hash": business["journal_hash"],
        "candidate_id": business["candidate_id"],
        "project_codes": list(business["project_codes"]),
    }


def _not_committed(
    request: object,
    *,
    public_api: NslV02PublicApiAdapter,
    reason_code: str,
    status_code: int | None,
    identity: object | None = None,
) -> object:
    return public_api.write_not_committed(
        identity=identity or public_api.write_outcome_identity.from_request(request),
        reason_code=reason_code,
        message="EOS confirmed that Journal Posting was not committed.",
        evidence_refs=_error_refs(reason_code, status_code),
    )


def _unknown(
    request: object,
    *,
    public_api: NslV02PublicApiAdapter,
    reason_code: str,
    status_code: int | None = None,
    identity: object | None = None,
) -> object:
    return public_api.write_commit_unknown(
        identity=identity or public_api.write_outcome_identity.from_request(request),
        reason_code=reason_code,
        message="EOS Journal commit state is uncertain; reconcile before retry.",
        evidence_refs=_error_refs(reason_code, status_code),
    )


def _result_contract(
    result_type: object | None, result_classification: object | None
) -> tuple[object, object]:
    if result_type is None:
        raise ValueError("EOS Journal result type must be supplied by the NSL binding")
    if getattr(result_classification, "value", None) not in {
        "PUBLIC",
        "INTERNAL",
        "CONFIDENTIAL",
        "RESTRICTED",
    }:
        raise ValueError(
            "EOS Journal result classification must be supplied by the NSL binding"
        )
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
        raise EosJournalExecutionError(
            "ae.nsl_eos_journal.result_envelope_unavailable",
            "NSL Journal request lacks an admitted ValueEnvelope type.",
            outcome_uncertain=True,
        )
    complete = getattr(type(next(iter(arguments.values()))), "complete", None)
    if not callable(complete):
        raise EosJournalExecutionError(
            "ae.nsl_eos_journal.result_envelope_unavailable",
            "NSL Journal request lacks an admitted ValueEnvelope factory.",
            outcome_uncertain=True,
        )
    return complete(dict(value), result_type, result_classification, evidence_refs)


def _correlation_id(trace_refs: object) -> str:
    if not isinstance(trace_refs, tuple):
        raise _invalid("NSL Journal trace_refs must be a tuple")
    values = [
        item.removeprefix("correlation_id:")
        for item in trace_refs
        if isinstance(item, str) and item.startswith("correlation_id:")
    ]
    if len(values) != 1:
        raise _invalid("NSL Journal trace_refs require one correlation_id")
    return _scoped_id("correlation_id", values[0])


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EosJournalExecutionError(
            "ae.nsl_eos_journal.response_invalid",
            "EOS Journal response is not valid JSON.",
            outcome_uncertain=response.status_code < 400,
            status_code=response.status_code,
        ) from exc
    if not isinstance(payload, Mapping):
        raise EosJournalExecutionError(
            "ae.nsl_eos_journal.response_invalid",
            "EOS Journal response must be an object.",
            outcome_uncertain=response.status_code < 400,
            status_code=response.status_code,
        )
    return dict(payload)


def _problem_reason_code(response: EosJournalExecutionResponse) -> str | None:
    code = response.payload.get("error_code")
    status = response.payload.get("status")
    if isinstance(code, str) and _REASON_CODE.fullmatch(code) and status == response.status_code:
        return code
    return None


def _error_refs(reason_code: str, status_code: int | None) -> tuple[str, ...]:
    refs = [f"eos.reason:{reason_code}"]
    if status_code is not None:
        refs.append(f"eos.http_status:{status_code}")
    return tuple(refs)


def _json_value(value: Any, *, path: str) -> Any:
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{path} is not canonical JSON") from exc


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _uuid_response(field_name: str, value: object, status_code: int) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _untrustworthy(f"EOS Journal {field_name} is invalid", status_code) from exc


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field_name} must be a positive integer")
    return value


def _hash_ref(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field_name} must be a SHA-256 hash reference") from exc


def _hash_ref_response(field_name: str, value: object, status_code: int) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _untrustworthy(f"EOS Journal {field_name} is invalid", status_code) from exc


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid(f"{field_name} has invalid stable-reference syntax")
    return value


def _utc_datetime(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("posted_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise _invalid("posted_at must use timezone-aware UTC")
    return parsed


def _utc_datetime_response(value: object, status_code: int) -> datetime:
    try:
        return _utc_datetime(value)
    except EosJournalExecutionError as exc:
        raise _untrustworthy("EOS Journal posted_at is invalid", status_code) from exc


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


def _invalid(detail: str) -> EosJournalExecutionError:
    return EosJournalExecutionError("ae.nsl_eos_journal.request_invalid", detail)


def _untrustworthy(detail: str, status_code: int) -> EosJournalExecutionError:
    return EosJournalExecutionError(
        "ae.nsl_eos_journal.response_invalid",
        detail,
        outcome_uncertain=True,
        status_code=status_code,
    )
