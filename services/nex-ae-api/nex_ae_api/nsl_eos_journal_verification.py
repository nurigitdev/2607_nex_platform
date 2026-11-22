from __future__ import annotations

import os
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from nex_runtime.semantic_hashes import validate_hash_ref

from .nsl_eos_journal_execution import (
    DEFAULT_EOS_BASE_URL,
    EOS_JOURNAL_POST_OPERATION,
)
from .nsl_eos_journal_reconciliation import (
    EOS_JOURNAL_RECONCILE_OPERATION,
    EosJournalReconciliationError,
    EosJournalReconciliationResponse,
    HttpEosJournalReconciliationAdapter,
    validate_eos_journal_reconciliation,
)
from .nsl_v02_public_api import NslV02PublicApiAdapter

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")


@dataclass(frozen=True)
class EosJournalVerificationError(RuntimeError):
    error_code: str
    detail: str
    status_code: int | None = None

    def __str__(self) -> str:
        return self.detail


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class HttpEosJournalVerificationAdapter:
    public_api: NslV02PublicApiAdapter
    base_url: str = DEFAULT_EOS_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 15.0
    transport: httpx.AsyncBaseTransport | None = field(
        default=None, repr=False, compare=False
    )
    clock: Callable[[], datetime] = field(default=_utc_now, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Reuse the reconciliation transport's fail-closed URL and timeout checks.
        HttpEosJournalReconciliationAdapter(
            public_api=self.public_api,
            base_url=self.base_url,
            service_token=self.service_token,
            timeout_seconds=self.timeout_seconds,
            transport=self.transport,
            result_type=object(),
            result_classification=_InternalClassification(),
        )
        if not callable(self.clock):
            raise TypeError("EOS Journal verification clock must be callable")

    async def read(self, request: object) -> object:
        binding = _request_binding(request, self.public_api)
        query = HttpEosJournalReconciliationAdapter(
            public_api=self.public_api,
            base_url=self.base_url,
            service_token=self.service_token,
            timeout_seconds=self.timeout_seconds,
            transport=self.transport,
            result_type=object(),
            result_classification=_InternalClassification(),
        )
        try:
            response = await query.query_identity_raw(_IdentityProxy.from_binding(binding))
        except (
            TimeoutError,
            ConnectionError,
            EosJournalReconciliationError,
        ) as exc:
            raise EosJournalVerificationError(
                "ae.nsl_eos_journal_verification.unavailable",
                "EOS Journal read-after-write verification is unavailable.",
            ) from exc
        return map_eos_journal_verification_response(
            response,
            request,
            public_api=self.public_api,
            observed_at=self.clock(),
        )


@dataclass(frozen=True)
class _InternalClassification:
    value: str = "INTERNAL"


@dataclass(frozen=True)
class _IdentityProxy:
    tenant_id: str
    business_operation_id: str
    invocation_id: str
    tool_id: str = EOS_JOURNAL_POST_OPERATION

    @classmethod
    def from_binding(cls, binding: Mapping[str, str]) -> _IdentityProxy:
        return cls(
            tenant_id=binding["tenant_id"],
            business_operation_id=binding["business_operation_id"],
            invocation_id=binding["invocation_id"],
        )


def build_default_eos_journal_verification_adapter(
    *,
    public_api: NslV02PublicApiAdapter,
    environ: Mapping[str, str] | None = None,
) -> HttpEosJournalVerificationAdapter:
    env = os.environ if environ is None else environ
    try:
        timeout = float(
            env.get("NEX_AE_EOS_JOURNAL_VERIFICATION_TIMEOUT_SECONDS", "15")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "NEX_AE_EOS_JOURNAL_VERIFICATION_TIMEOUT_SECONDS must be numeric"
        ) from exc
    return HttpEosJournalVerificationAdapter(
        public_api=public_api,
        base_url=env.get("NEX_EOS_BASE_URL", DEFAULT_EOS_BASE_URL),
        service_token=env.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or None,
        timeout_seconds=timeout,
    )


def map_eos_journal_verification_response(
    response: EosJournalReconciliationResponse,
    request: object,
    *,
    public_api: NslV02PublicApiAdapter,
    observed_at: datetime,
) -> object:
    if not isinstance(response, EosJournalReconciliationResponse):
        raise TypeError("response must be an EosJournalReconciliationResponse")
    binding = _request_binding(request, public_api)
    if response.status_code not in {200, 202}:
        raise EosJournalVerificationError(
            "ae.nsl_eos_journal_verification.unavailable",
            "EOS did not provide an authoritative Journal observation.",
            status_code=response.status_code,
        )
    try:
        projection = validate_eos_journal_reconciliation(
            response.payload,
            identity=_IdentityFromBinding(binding),
            expected_http_status=response.status_code,
        )
    except Exception as exc:
        raise EosJournalVerificationError(
            "ae.nsl_eos_journal_verification.response_invalid",
            "EOS Journal verification projection is not trustworthy.",
            status_code=response.status_code,
        ) from exc
    state = projection["commit_state"]
    verification = projection["verification_status"]
    journal = projection["journal"]
    if state == "COMMITTED" and verification == "VERIFIED":
        if journal["journal_id"] != binding["journal_id"]:
            raise EosJournalVerificationError(
                "ae.nsl_eos_journal_verification.response_invalid",
                "EOS Journal identity differs from the committed result.",
                status_code=response.status_code,
            )
        matched = True
        reason_code = None
        evidence_ref = (
            f"eos.journal_verification:{binding['business_operation_id']}:"
            f"{journal['journal_hash']}"
        )
        observation_time = projection["last_observed_at"]
    else:
        matched = False
        reason_code = (
            "EOS_JOURNAL_COMMITTED_VERIFICATION_FAILED"
            if state == "COMMITTED"
            else "EOS_JOURNAL_VERIFICATION_NOT_CONFIRMED"
        )
        evidence_ref = (
            f"eos.journal_verification_failure:{binding['business_operation_id']}:"
            f"{reason_code}"
        )
        observation_time = _utc(observed_at)
    return public_api.verification_observation(
        request_hash=binding["request_hash"],
        business_reference=binding["business_reference"],
        matched=matched,
        reason_code=reason_code,
        evidence_ref=evidence_ref,
        observed_at=observation_time,
    )


@dataclass(frozen=True)
class _IdentityFromBinding:
    tenant_id: str
    business_operation_id: str
    idempotency_key: str
    payload_hash: str

    def __init__(self, binding: Mapping[str, str]) -> None:
        object.__setattr__(self, "tenant_id", binding["tenant_id"])
        object.__setattr__(
            self, "business_operation_id", binding["business_operation_id"]
        )
        object.__setattr__(self, "idempotency_key", binding["idempotency_key"])
        object.__setattr__(self, "payload_hash", binding["payload_hash"])


def _request_binding(
    request: object, public_api: NslV02PublicApiAdapter
) -> dict[str, str]:
    if not isinstance(request, public_api.verification_request):
        raise _invalid("Journal verification requires VerificationRequest")
    identity = request.identity
    if not isinstance(identity, public_api.write_outcome_identity):
        raise _invalid("Journal verification requires WRITE outcome identity")
    if identity.tool_id != EOS_JOURNAL_POST_OPERATION:
        raise _invalid("Journal WRITE operation is unsupported")
    if request.verification_tool_id != EOS_JOURNAL_RECONCILE_OPERATION:
        raise _invalid("Journal verification operation is unsupported")
    if request.consistency_hint != "READ_AFTER_WRITE_STRONG":
        raise _invalid("Journal verification requires strong read-after-write")
    operation_id = _uuid("business_operation_id", identity.business_operation_id)
    if request.provider_transaction_id != operation_id:
        raise _invalid("Journal provider transaction identity differs")
    prefix = "eos.posted_journal:"
    if not isinstance(request.business_reference, str) or not request.business_reference.startswith(prefix):
        raise _invalid("Journal business reference is invalid")
    journal_id = _uuid("journal_id", request.business_reference[len(prefix) :])
    try:
        payload_hash = validate_hash_ref(identity.payload_hash)
        request_hash = validate_hash_ref(request.request_hash)
    except ValueError as exc:
        raise _invalid("Journal verification hash binding is invalid") from exc
    return {
        "tenant_id": _scoped_id("tenant_id", identity.tenant_id),
        "business_operation_id": operation_id,
        "invocation_id": _scoped_id("invocation_id", identity.invocation_id),
        "idempotency_key": _scoped_id("idempotency_key", identity.idempotency_key),
        "payload_hash": payload_hash,
        "request_hash": request_hash,
        "business_reference": request.business_reference,
        "journal_id": journal_id,
    }


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid(f"{field_name} has invalid stable-reference syntax")
    return value


def _utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise _invalid("Journal verification observation time must use UTC")
    return value


def _invalid(detail: str) -> EosJournalVerificationError:
    return EosJournalVerificationError(
        "ae.nsl_eos_journal_verification.invalid", detail
    )
