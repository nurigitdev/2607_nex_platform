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
from nex_runtime.semantic_hashes import validate_hash_ref

from .nsl_eos_journal_execution import (
    DEFAULT_EOS_BASE_URL,
    EOS_JOURNAL_POST_OPERATION,
)
from .nsl_v02_public_api import NslV02PublicApiAdapter
from .service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

EOS_JOURNAL_RECONCILE_OPERATION = "FINANCE.JOURNAL.RECONCILE"
EOS_JOURNAL_RECONCILIATION_SCHEMA = "eos_journal_reconciliation.v1"
EOS_JOURNAL_STATUS_PATH = "/internal/v2/finance/business-operations"

_PROJECTION_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "tenant_id",
        "business_operation_id",
        "posting_operation",
        "idempotency_key",
        "payload_hash",
        "commit_state",
        "reconciliation_status",
        "verification_status",
        "retry_disposition",
        "new_idempotency_key_allowed",
        "last_observed_at",
        "journal",
        "outbox",
    }
)
_JOURNAL_FIELDS = frozenset(
    {
        "company_id",
        "journal_id",
        "journal_no",
        "journal_hash",
        "candidate_id",
        "candidate_revision",
        "accounting_acceptance_id",
        "accounting_acceptance_hash",
        "accounting_period_id",
        "project_codes",
        "line_count",
        "total_debit_functional",
        "total_credit_functional",
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
        "attempt_count",
        "projector_state",
    }
)
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


@dataclass(frozen=True)
class EosJournalReconciliationError(RuntimeError):
    error_code: str
    detail: str
    status_code: int | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class EosJournalReconciliationResponse:
    status_code: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class HttpEosJournalReconciliationAdapter:
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
            raise ValueError("EOS Journal reconciliation timeout must be positive")

    async def reconcile(self, request: object, unknown: object) -> object:
        identity = _bound_unknown_identity(request, unknown, self.public_api)
        result_type, classification = _result_contract(
            self.result_type, self.result_classification
        )
        try:
            response = await self.query_raw(request)
        except (TimeoutError, ConnectionError, EosJournalReconciliationError):
            return _unknown(
                identity,
                public_api=self.public_api,
                reason_code="RECONCILIATION_REQUIRED",
            )
        return map_eos_journal_reconciliation_response(
            response,
            request,
            identity=identity,
            public_api=self.public_api,
            result_type=result_type,
            result_classification=classification,
        )

    async def query_raw(self, request: object) -> EosJournalReconciliationResponse:
        identity = _request_identity(request, self.public_api)
        return await self.query_identity_raw(identity)

    async def query_identity_raw(
        self, identity: object
    ) -> EosJournalReconciliationResponse:
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token, audience="nex-eos"
            )
        except AeOutboundServiceTokenError as exc:
            raise EosJournalReconciliationError(
                "ae.nsl_eos_journal_reconciliation.service_token_unavailable",
                "EOS Journal reconciliation authentication is unavailable.",
            ) from exc
        operation_id = _uuid("business_operation_id", identity.business_operation_id)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{self.base_url.rstrip('/')}{EOS_JOURNAL_STATUS_PATH}/"
                    f"{operation_id}/journal-status",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Cache-Control": "no-store, max-age=0",
                        "Pragma": "no-cache",
                        "X-NeX-Tenant-Id": str(identity.tenant_id),
                        "X-Request-ID": str(identity.invocation_id),
                        "X-Service-ID": "nex-ae-api",
                    },
                )
        except httpx.TimeoutException as exc:
            raise TimeoutError("EOS Journal reconciliation timed out.") from exc
        except httpx.NetworkError as exc:
            raise ConnectionError("EOS Journal reconciliation connection was lost.") from exc
        except httpx.HTTPError as exc:
            raise EosJournalReconciliationError(
                "ae.nsl_eos_journal_reconciliation.transport_failed",
                "EOS Journal reconciliation transport failed.",
            ) from exc
        return EosJournalReconciliationResponse(
            response.status_code,
            MappingProxyType(_response_payload(response)),
        )


def build_default_eos_journal_reconciliation_adapter(
    *,
    public_api: NslV02PublicApiAdapter,
    result_type: object,
    result_classification: object,
    environ: Mapping[str, str] | None = None,
) -> HttpEosJournalReconciliationAdapter:
    env = os.environ if environ is None else environ
    try:
        timeout = float(
            env.get("NEX_AE_EOS_JOURNAL_RECONCILIATION_TIMEOUT_SECONDS", "15")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "NEX_AE_EOS_JOURNAL_RECONCILIATION_TIMEOUT_SECONDS must be numeric"
        ) from exc
    return HttpEosJournalReconciliationAdapter(
        public_api=public_api,
        base_url=env.get("NEX_EOS_BASE_URL", DEFAULT_EOS_BASE_URL),
        service_token=env.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
        timeout_seconds=timeout,
        result_type=result_type,
        result_classification=result_classification,
    )


def map_eos_journal_reconciliation_response(
    response: EosJournalReconciliationResponse,
    request: object,
    *,
    identity: object,
    public_api: NslV02PublicApiAdapter,
    result_type: object,
    result_classification: object,
) -> object:
    if not isinstance(response, EosJournalReconciliationResponse):
        raise TypeError("response must be an EosJournalReconciliationResponse")
    if response.status_code not in {200, 202}:
        return _unknown(
            identity,
            public_api=public_api,
            reason_code="RECONCILIATION_REQUIRED",
            cause_code=_problem_reason_code(response)
            or "EOS_JOURNAL_RECONCILIATION_UNAVAILABLE",
            status_code=response.status_code,
        )
    try:
        projection = validate_eos_journal_reconciliation(
            response.payload,
            identity=identity,
            expected_http_status=response.status_code,
        )
    except (EosJournalReconciliationError, ValueError):
        return _unknown(
            identity,
            public_api=public_api,
            reason_code="RECONCILIATION_REQUIRED",
            cause_code="EOS_JOURNAL_RECONCILIATION_UNTRUSTWORTHY",
            status_code=response.status_code,
        )
    evidence_refs = _projection_evidence_refs(projection)
    state = projection["commit_state"]
    if state == "COMMITTED" and projection["verification_status"] == "VERIFIED":
        journal = projection["journal"]
        value = _result_value_envelope(
            request,
            value=_journal_result_value(journal),
            result_type=result_type,
            result_classification=result_classification,
            evidence_refs=evidence_refs,
        )
        result = public_api.write_result_envelope(
            identity=identity,
            value=value,
            business_reference=f"eos.posted_journal:{journal['journal_id']}",
            provider_transaction_id=projection["business_operation_id"],
            committed_at=projection["last_observed_at"],
            evidence_refs=evidence_refs,
        )
        return public_api.write_committed(result=result)
    if state == "NOT_COMMITTED":
        return public_api.write_not_committed(
            identity=identity,
            reason_code="EOS_JOURNAL_NOT_COMMITTED_CONFIRMED",
            message="EOS confirmed that Journal Posting was not committed.",
            provider_transaction_id=projection["business_operation_id"],
            evidence_refs=evidence_refs,
        )
    reason = (
        "EOS_JOURNAL_COMMITTED_VERIFICATION_FAILED"
        if state == "COMMITTED"
        else "RECONCILIATION_REQUIRED"
    )
    return _unknown(
        identity,
        public_api=public_api,
        reason_code=reason,
        provider_transaction_id=projection["business_operation_id"],
        evidence_refs=evidence_refs,
    )


def validate_eos_journal_reconciliation(
    payload: Mapping[str, Any],
    *,
    identity: object,
    expected_http_status: int,
) -> dict[str, Any]:
    if set(payload) != _PROJECTION_FIELDS:
        raise _invalid("EOS Journal reconciliation fields differ from the contract")
    expected = {
        "schema_version": EOS_JOURNAL_RECONCILIATION_SCHEMA,
        "operation": EOS_JOURNAL_RECONCILE_OPERATION,
        "tenant_id": str(identity.tenant_id),
        "business_operation_id": str(identity.business_operation_id),
        "posting_operation": EOS_JOURNAL_POST_OPERATION,
        "idempotency_key": str(identity.idempotency_key),
        "payload_hash": str(identity.payload_hash),
        "new_idempotency_key_allowed": False,
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise _invalid("EOS Journal reconciliation lineage differs from the WRITE")
    _uuid("business_operation_id", payload["business_operation_id"])
    validate_hash_ref(payload["payload_hash"])
    observed_at = _utc_datetime(payload.get("last_observed_at"))
    state = payload.get("commit_state")
    reconciliation = payload.get("reconciliation_status")
    verification = payload.get("verification_status")
    retry = payload.get("retry_disposition")
    journal = payload.get("journal")
    outbox = payload.get("outbox")
    if (
        state == "COMMITTED"
        and reconciliation == "COMMITTED_CONFIRMED"
        and verification == "VERIFIED"
        and retry == "DO_NOT_REPOST"
        and expected_http_status == 200
    ):
        journal = _validate_journal(journal)
        outbox = _validate_outbox(outbox)
    elif _non_journal_state_is_valid(
        state=state,
        reconciliation=reconciliation,
        verification=verification,
        retry=retry,
        expected_http_status=expected_http_status,
        journal=journal,
        outbox=outbox,
    ):
        pass
    else:
        raise _invalid("EOS Journal reconciliation state is inconsistent")
    return {
        **expected,
        "commit_state": state,
        "reconciliation_status": reconciliation,
        "verification_status": verification,
        "retry_disposition": retry,
        "last_observed_at": observed_at,
        "journal": journal,
        "outbox": outbox,
    }


def _non_journal_state_is_valid(
    *,
    state: object,
    reconciliation: object,
    verification: object,
    retry: object,
    expected_http_status: int,
    journal: object,
    outbox: object,
) -> bool:
    if journal is not None or outbox is not None:
        return False
    return (
        state,
        reconciliation,
        verification,
        retry,
        expected_http_status,
    ) in {
        (
            "NOT_COMMITTED",
            "NOT_COMMITTED_CONFIRMED",
            "NOT_APPLICABLE",
            "RETRY_SAME_IDENTITY_ONLY",
            200,
        ),
        (
            "UNKNOWN_COMMIT_STATE",
            "RECONCILIATION_REQUIRED",
            "NOT_RUN",
            "DO_NOT_REPOST",
            202,
        ),
        (
            "COMMITTED",
            "COMMITTED_VERIFICATION_FAILED",
            "FAILED",
            "DO_NOT_REPOST",
            200,
        ),
    }


def _validate_journal(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _JOURNAL_FIELDS:
        raise _invalid("Committed Journal reconciliation lacks exact Journal lineage")
    result = dict(value)
    for field_name in (
        "company_id",
        "journal_id",
        "candidate_id",
        "accounting_acceptance_id",
        "accounting_period_id",
    ):
        _uuid(field_name, result[field_name])
    for field_name in ("journal_hash", "accounting_acceptance_hash"):
        validate_hash_ref(result[field_name])
    if (
        isinstance(result["candidate_revision"], bool)
        or not isinstance(result["candidate_revision"], int)
        or result["candidate_revision"] < 1
        or isinstance(result["line_count"], bool)
        or not isinstance(result["line_count"], int)
        or result["line_count"] < 2
    ):
        raise _invalid("Committed Journal count or revision is invalid")
    project_codes = result["project_codes"]
    if (
        not isinstance(project_codes, list)
        or not project_codes
        or project_codes != sorted(set(project_codes))
        or any(not isinstance(code, str) or not _PROJECT_CODE.fullmatch(code) for code in project_codes)
    ):
        raise _invalid("Committed Journal project-code lineage is invalid")
    if result["total_debit_functional"] != result["total_credit_functional"]:
        raise _invalid("Committed Journal reconciliation is not balanced")
    _utc_datetime(result["posted_at"])
    return result


def _validate_outbox(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _OUTBOX_FIELDS:
        raise _invalid("Committed Journal reconciliation lacks exact outbox lineage")
    result = dict(value)
    for field_name in ("outbox_id", "event_id"):
        _uuid(field_name, result[field_name])
    validate_hash_ref(result["event_payload_hash"])
    if result["event_type"] != "FINANCE.JOURNAL_POSTED.v1":
        raise _invalid("Journal reconciliation outbox event type is invalid")
    if result["delivery_state"] not in {"PENDING", "PUBLISHED"}:
        raise _invalid("Journal reconciliation outbox state is invalid")
    expected_projector = (
        "CURRENT" if result["delivery_state"] == "PUBLISHED" else "STALE"
    )
    if result["projector_state"] != expected_projector:
        raise _invalid("Journal reconciliation projector state is invalid")
    if (
        isinstance(result["attempt_count"], bool)
        or not isinstance(result["attempt_count"], int)
        or result["attempt_count"] < 0
    ):
        raise _invalid("Journal reconciliation outbox attempt count is invalid")
    return result


def _bound_unknown_identity(
    request: object, unknown: object, public_api: NslV02PublicApiAdapter
) -> object:
    identity = _request_identity(request, public_api)
    if not isinstance(unknown, public_api.write_commit_unknown):
        raise _invalid("Journal reconciliation requires WriteCommitUnknown")
    if unknown.identity != identity:
        raise _invalid("Unknown outcome and Journal WRITE identities differ")
    return identity


def _request_identity(request: object, public_api: NslV02PublicApiAdapter) -> object:
    if not isinstance(request, public_api.write_call_request):
        raise _invalid("Journal reconciliation requires WriteCallRequest")
    identity = public_api.write_outcome_identity.from_request(request)
    if identity.tool_id != EOS_JOURNAL_POST_OPERATION:
        raise _invalid("Journal reconciliation WRITE operation is unsupported")
    return identity


def _projection_evidence_refs(projection: Mapping[str, Any]) -> tuple[str, ...]:
    refs = [
        f"eos.business_operation:{projection['business_operation_id']}",
        f"eos.journal_reconciliation:{projection['business_operation_id']}",
    ]
    if projection["journal"] is not None:
        refs.append(
            "eos.posted_journal:"
            f"{projection['journal']['journal_id']}:"
            f"{projection['journal']['journal_hash']}"
        )
    return tuple(refs)


def _journal_result_value(journal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "journal_id": journal["journal_id"],
        "journal_no": journal["journal_no"],
        "journal_hash": journal["journal_hash"],
        "candidate_id": journal["candidate_id"],
        "project_codes": list(journal["project_codes"]),
    }


def _result_value_envelope(
    request: object,
    *,
    value: Mapping[str, Any],
    result_type: object,
    result_classification: object,
    evidence_refs: tuple[str, ...],
) -> object:
    arguments = getattr(request, "arguments", None)
    complete = (
        None
        if not isinstance(arguments, Mapping) or not arguments
        else getattr(type(next(iter(arguments.values()))), "complete", None)
    )
    if not callable(complete):
        raise _invalid("Journal reconciliation lacks an admitted ValueEnvelope factory")
    return complete(dict(value), result_type, result_classification, evidence_refs)


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


def _unknown(
    identity: object,
    *,
    public_api: NslV02PublicApiAdapter,
    reason_code: str,
    cause_code: str | None = None,
    status_code: int | None = None,
    provider_transaction_id: str | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> object:
    refs = list(evidence_refs)
    if cause_code:
        refs.append(f"eos.reason:{cause_code}")
    if status_code is not None:
        refs.append(f"eos.http_status:{status_code}")
    return public_api.write_commit_unknown(
        identity=identity,
        reason_code=reason_code,
        message="EOS Journal commit state remains uncertain; do not repost.",
        provider_transaction_id=provider_transaction_id,
        evidence_refs=tuple(refs),
    )


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _invalid("EOS Journal reconciliation response is not JSON") from exc
    if not isinstance(payload, Mapping):
        raise _invalid("EOS Journal reconciliation response must be an object")
    return dict(payload)


def _problem_reason_code(response: EosJournalReconciliationResponse) -> str | None:
    code = response.payload.get("error_code")
    status = response.payload.get("status")
    if isinstance(code, str) and _REASON_CODE.fullmatch(code) and status == response.status_code:
        return code
    return None


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid("Journal reconciliation timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("Journal reconciliation timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise _invalid("Journal reconciliation timestamp must use UTC")
    return parsed


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


def _invalid(detail: str) -> EosJournalReconciliationError:
    return EosJournalReconciliationError(
        "ae.nsl_eos_journal_reconciliation.invalid", detail
    )
