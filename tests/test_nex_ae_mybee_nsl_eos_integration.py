from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

import httpx
import pytest
from nex_ae_api.nsl_eos_journal_execution import (
    EOS_JOURNAL_POST_PATH,
    EosJournalExecutionError,
    EosJournalExecutionResponse,
    HttpEosJournalExecutionPort,
    build_default_eos_journal_execution_port,
    build_eos_journal_post_command,
    map_eos_journal_execution_response,
)
from nex_ae_api.nsl_eos_journal_reconciliation import (
    EosJournalReconciliationError,
    EosJournalReconciliationResponse,
    HttpEosJournalReconciliationAdapter,
    build_default_eos_journal_reconciliation_adapter,
    map_eos_journal_reconciliation_response,
    validate_eos_journal_reconciliation,
)
from nex_ae_api.nsl_eos_journal_verification import (
    EosJournalVerificationError,
    HttpEosJournalVerificationAdapter,
    build_default_eos_journal_verification_adapter,
    map_eos_journal_verification_response,
)
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref

HASH = "sha256:" + "a" * 64
CANDIDATE_HASH = "sha256:" + "b" * 64
JOURNAL_HASH = "sha256:" + "c" * 64
ACCEPTANCE_HASH = "sha256:" + "d" * 64
EVENT_HASH = "sha256:" + "e" * 64
REQUEST_HASH = "sha256:" + "f" * 64
OPERATION_ID = "10000000-0000-4000-8000-000000000802"
CANDIDATE_ID = "20000000-0000-4000-8000-000000000802"
COMPANY_ID = "30000000-0000-4000-8000-000000000802"
EVIDENCE_ID = "40000000-0000-4000-8000-000000000802"
JOURNAL_ID = "50000000-0000-4000-8000-000000000802"
ACCEPTANCE_ID = "60000000-0000-4000-8000-000000000802"
PERIOD_ID = "70000000-0000-4000-8000-000000000802"
CONSUMPTION_ID = "80000000-0000-4000-8000-000000000802"
OUTBOX_ID = "90000000-0000-4000-8000-000000000802"
EVENT_ID = "a0000000-0000-4000-8000-000000000802"
IDEMPOTENCY_KEY = "idem:w70-s8-02"
TENANT_ID = "VO00"
PROJECT_CODE = "VO00D260001"
POSTED_AT = "2026-11-15T03:00:00Z"
NOW = datetime(2026, 11, 15, 3, 1, tzinfo=UTC)


class Classification(StrEnum):
    CONFIDENTIAL = "CONFIDENTIAL"


@dataclass(frozen=True)
class Envelope:
    value: object
    type_info: object = None
    classification: object = None
    evidence_refs: tuple[str, ...] = ()

    @classmethod
    def complete(
        cls,
        value: object,
        type_info: object,
        classification: object,
        evidence_refs: tuple[str, ...],
    ) -> Envelope:
        return cls(value, type_info, classification, evidence_refs)


@dataclass(frozen=True)
class WriteCallRequest:
    tenant_id: str
    execution_id: str
    business_operation_id: str
    invocation_id: str
    node_id: str
    tool_ref: str
    tool_id: str
    contract_hash: str
    arguments: object
    idempotency_key: str
    payload_hash: str
    approval_id: str
    approval_request_id: str
    write_intent_hash: str
    business_preconditions: object
    trace_refs: object


@dataclass(frozen=True)
class WriteOutcomeIdentity:
    tenant_id: str
    business_operation_id: str
    invocation_id: str
    node_id: str
    tool_id: str
    idempotency_key: str
    payload_hash: str
    approval_request_id: str
    write_intent_hash: str

    @classmethod
    def from_request(cls, request: WriteCallRequest) -> WriteOutcomeIdentity:
        return cls(
            request.tenant_id,
            request.business_operation_id,
            request.invocation_id,
            request.node_id,
            request.tool_id,
            request.idempotency_key,
            request.payload_hash,
            request.approval_request_id,
            request.write_intent_hash,
        )


@dataclass(frozen=True)
class WriteResultEnvelope:
    identity: WriteOutcomeIdentity
    value: Envelope
    business_reference: str
    provider_transaction_id: str | None
    committed_at: datetime
    evidence_refs: tuple[str, ...]


class CommitState(StrEnum):
    COMMITTED = "COMMITTED"
    NOT_COMMITTED = "NOT_COMMITTED"
    UNKNOWN_COMMIT_STATE = "UNKNOWN_COMMIT_STATE"


@dataclass(frozen=True)
class WriteCommitted:
    result: WriteResultEnvelope

    @property
    def identity(self) -> WriteOutcomeIdentity:
        return self.result.identity

    @property
    def commit_state(self) -> CommitState:
        return CommitState.COMMITTED


@dataclass(frozen=True)
class WriteNotCommitted:
    identity: WriteOutcomeIdentity
    reason_code: str
    message: str
    provider_transaction_id: str | None = None
    evidence_refs: tuple[str, ...] = ()

    @property
    def commit_state(self) -> CommitState:
        return CommitState.NOT_COMMITTED


@dataclass(frozen=True)
class WriteCommitUnknown:
    identity: WriteOutcomeIdentity
    reason_code: str
    message: str
    provider_transaction_id: str | None = None
    evidence_refs: tuple[str, ...] = ()

    @property
    def commit_state(self) -> CommitState:
        return CommitState.UNKNOWN_COMMIT_STATE


class WriteExecutionPort(Protocol):
    async def execute(self, request: WriteCallRequest) -> object: ...


@dataclass(frozen=True)
class VerificationRequest:
    identity: WriteOutcomeIdentity
    verification_tool_id: str
    business_reference: str
    provider_transaction_id: str | None
    reference_schema: object = None
    consistency_hint: str | None = "READ_AFTER_WRITE_STRONG"
    request_hash: str = REQUEST_HASH


@dataclass(frozen=True)
class VerificationObservation:
    request_hash: str
    business_reference: str
    matched: bool
    evidence_ref: str
    observed_at: datetime
    reason_code: str | None = None


@runtime_checkable
class VerificationPort(Protocol):
    async def read(self, request: VerificationRequest) -> VerificationObservation: ...


RESULT_TYPE = object()


def _public_api() -> NslV02PublicApiAdapter:
    return NslV02PublicApiAdapter(
        approval_request=object,
        approval_evidence=object,
        approval_suspension_coordinator=object,
        approval_resume_coordinator=object,
        resume_token=object,
        checkpoint_port=object,
        resume_checkpoint_port=object,
        idempotency_coordinator=object,
        idempotency_evidence_port=object,
        idempotency_evidence_record=object,
        idempotency_reservation=object,
        idempotency_disposition=object,
        write_evidence_port=object,
        write_attempt_record=object,
        write_requested_receipt=object,
        write_call_request=WriteCallRequest,
        write_execution_port=WriteExecutionPort,
        write_outcome_identity=WriteOutcomeIdentity,
        write_result_envelope=WriteResultEnvelope,
        write_committed=WriteCommitted,
        write_not_committed=WriteNotCommitted,
        write_commit_unknown=WriteCommitUnknown,
        post_write_verification_port=VerificationPort,
        verification_request=VerificationRequest,
        verification_observation=VerificationObservation,
        runtime_policy_port=object,
        write_policy_request=object,
        policy_decision=object,
        policy_effect=object,
        runtime_preflight_validator=object,
        release_admission_hash=HASH,
        api_contract_hash=HASH,
    )


def _business_payload() -> dict[str, object]:
    return {
        "schema_version": "eos_journal_post_command.v1",
        "tenant_id": TENANT_ID,
        "company_id": COMPANY_ID,
        "candidate_id": CANDIDATE_ID,
        "expected_candidate_version": 3,
        "expected_candidate_revision": 2,
        "expected_candidate_hash": CANDIDATE_HASH,
        "accounting_approval_evidence_id": EVIDENCE_ID,
    }


def _write_request(**changes: object) -> WriteCallRequest:
    payload = _business_payload()
    arguments = MappingProxyType(
        {name: Envelope(value) for name, value in payload.items()}
    )
    values: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "execution_id": "execution-w70-s8-02",
        "business_operation_id": OPERATION_ID,
        "invocation_id": "invocation-w70-s8-02",
        "node_id": "post-journal",
        "tool_ref": "FINANCE.VOUCHER.APPROVE_AND_POST@1.0.0",
        "tool_id": "FINANCE.VOUCHER.APPROVE_AND_POST",
        "contract_hash": HASH,
        "arguments": arguments,
        "idempotency_key": IDEMPOTENCY_KEY,
        "payload_hash": nsl_write_payload_hash_ref(payload),
        "approval_id": EVIDENCE_ID,
        "approval_request_id": "approval-request-w70-s8-02",
        "write_intent_hash": HASH,
        "business_preconditions": (),
        "trace_refs": (
            "trace_id:trace-w70-s8-02",
            "correlation_id:correlation-w70-s8-02",
            "causation_id:causation-w70-s8-02",
        ),
    }
    values.update(changes)
    return WriteCallRequest(**values)  # type: ignore[arg-type]


def _post_result(**changes: object) -> dict[str, object]:
    result = {
        "business_result_ref": f"eos.posted_journal:{JOURNAL_ID}",
        "company_id": COMPANY_ID,
        "journal_id": JOURNAL_ID,
        "journal_no": "VO00-2026-000001",
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 2,
        "candidate_version": 4,
        "candidate_state": "POSTED",
        "accounting_acceptance_id": ACCEPTANCE_ID,
        "accounting_period_id": PERIOD_ID,
        "project_codes": [PROJECT_CODE],
        "consumption_id": CONSUMPTION_ID,
        "journal_hash": JOURNAL_HASH,
        "posted_at": POSTED_AT,
    }
    result.update(changes.pop("result", {}))
    value: dict[str, object] = {
        "schema_version": "eos_journal_post_result.v1",
        "operation": "FINANCE.VOUCHER.APPROVE_AND_POST",
        "idempotency_disposition": "CREATED",
        "created": True,
        "tenant_id": TENANT_ID,
        "business_operation_id": OPERATION_ID,
        "idempotency_key": IDEMPOTENCY_KEY,
        "payload_hash": _write_request().payload_hash,
        "commit_state": "COMMITTED",
        "result": result,
        "outbox": {
            "outbox_id": OUTBOX_ID,
            "event_id": EVENT_ID,
            "event_type": "FINANCE.JOURNAL_POSTED.v1",
            "event_payload_hash": EVENT_HASH,
            "delivery_state": "PENDING",
        },
    }
    value.update(changes)
    return value


def _journal_projection() -> dict[str, object]:
    return {
        "company_id": COMPANY_ID,
        "journal_id": JOURNAL_ID,
        "journal_no": "VO00-2026-000001",
        "journal_hash": JOURNAL_HASH,
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 2,
        "accounting_acceptance_id": ACCEPTANCE_ID,
        "accounting_acceptance_hash": ACCEPTANCE_HASH,
        "accounting_period_id": PERIOD_ID,
        "project_codes": [PROJECT_CODE],
        "line_count": 2,
        "total_debit_functional": "10000.0000",
        "total_credit_functional": "10000.0000",
        "posted_at": POSTED_AT,
    }


def _reconciliation_projection(
    *,
    state: str = "COMMITTED",
    reconciliation: str = "COMMITTED_CONFIRMED",
    verification: str = "VERIFIED",
    retry: str = "DO_NOT_REPOST",
) -> dict[str, object]:
    committed = state == "COMMITTED" and verification == "VERIFIED"
    return {
        "schema_version": "eos_journal_reconciliation.v1",
        "operation": "FINANCE.JOURNAL.RECONCILE",
        "tenant_id": TENANT_ID,
        "business_operation_id": OPERATION_ID,
        "posting_operation": "FINANCE.VOUCHER.APPROVE_AND_POST",
        "idempotency_key": IDEMPOTENCY_KEY,
        "payload_hash": _write_request().payload_hash,
        "commit_state": state,
        "reconciliation_status": reconciliation,
        "verification_status": verification,
        "retry_disposition": retry,
        "new_idempotency_key_allowed": False,
        "last_observed_at": POSTED_AT,
        "journal": _journal_projection() if committed else None,
        "outbox": (
            {
                "outbox_id": OUTBOX_ID,
                "event_id": EVENT_ID,
                "event_type": "FINANCE.JOURNAL_POSTED.v1",
                "event_payload_hash": EVENT_HASH,
                "delivery_state": "PENDING",
                "attempt_count": 0,
                "projector_state": "STALE",
            }
            if committed
            else None
        ),
    }


def _verification_request(**changes: object) -> VerificationRequest:
    values: dict[str, object] = {
        "identity": WriteOutcomeIdentity.from_request(_write_request()),
        "verification_tool_id": "FINANCE.JOURNAL.RECONCILE",
        "business_reference": f"eos.posted_journal:{JOURNAL_ID}",
        "provider_transaction_id": OPERATION_ID,
        "reference_schema": RESULT_TYPE,
        "consistency_hint": "READ_AFTER_WRITE_STRONG",
        "request_hash": REQUEST_HASH,
    }
    values.update(changes)
    return VerificationRequest(**values)  # type: ignore[arg-type]


def _execution_adapter(transport: httpx.AsyncBaseTransport) -> HttpEosJournalExecutionPort:
    return HttpEosJournalExecutionPort(
        public_api=_public_api(),
        base_url="http://eos.test",
        service_token="signed-token",
        transport=transport,
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
    )


def _reconciliation_adapter(
    transport: httpx.AsyncBaseTransport,
) -> HttpEosJournalReconciliationAdapter:
    return HttpEosJournalReconciliationAdapter(
        public_api=_public_api(),
        base_url="http://eos.test",
        service_token="signed-token",
        transport=transport,
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
    )


def test_journal_execution_commits_exact_lineage_and_replay_without_reposting() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = _post_result()
        if len(calls) == 2:
            payload.update(idempotency_disposition="REPLAYED", created=False)
            return httpx.Response(200, json=payload, request=request)
        return httpx.Response(201, json=payload, request=request)

    adapter = _execution_adapter(httpx.MockTransport(handler))
    first = asyncio.run(adapter.execute(_write_request()))
    replay = asyncio.run(adapter.execute(_write_request()))

    assert isinstance(first, WriteCommitted)
    assert replay.result.value.value == first.result.value.value
    assert first.result.business_reference == f"eos.posted_journal:{JOURNAL_ID}"
    assert first.result.provider_transaction_id == OPERATION_ID
    assert first.result.value.value == {
        "journal_id": JOURNAL_ID,
        "journal_no": "VO00-2026-000001",
        "journal_hash": JOURNAL_HASH,
        "candidate_id": CANDIDATE_ID,
        "project_codes": [PROJECT_CODE],
    }
    assert len(calls) == 2
    assert calls[0].url.path == f"{EOS_JOURNAL_POST_PATH}/{CANDIDATE_ID}/posting"
    assert calls[0].headers["authorization"] == "Bearer signed-token"
    body = json.loads(calls[0].content)
    assert "candidate_id" not in body
    assert body["correlation_id"] == "correlation-w70-s8-02"


@pytest.mark.parametrize(
    ("status", "reason", "expected_type"),
    [
        (409, "EOS_JOURNAL_POST_STALE", WriteNotCommitted),
        (503, "EOS_JOURNAL_POST_UNAVAILABLE", WriteCommitUnknown),
    ],
)
def test_journal_execution_maps_authoritative_rejection_and_uncertain_failure(
    status: int, reason: str, expected_type: type
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            json={"status": status, "error_code": reason},
            request=request,
        )
    )
    outcome = asyncio.run(_execution_adapter(transport).execute(_write_request()))
    assert isinstance(outcome, expected_type)
    assert outcome.reason_code == reason
    assert f"eos.http_status:{status}" in outcome.evidence_refs


def test_journal_execution_timeout_and_untrustworthy_success_are_unknown() -> None:
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    timed_out = asyncio.run(
        _execution_adapter(httpx.MockTransport(timeout)).execute(_write_request())
    )
    assert isinstance(timed_out, WriteCommitUnknown)
    assert timed_out.reason_code == "PROVIDER_TIMEOUT"

    malformed = _post_result(result={"journal_id": "wrong"})
    result = asyncio.run(
        _execution_adapter(
            httpx.MockTransport(
                lambda request: httpx.Response(201, json=malformed, request=request)
            )
        ).execute(_write_request())
    )
    assert isinstance(result, WriteCommitUnknown)
    assert result.reason_code == "EOS_JOURNAL_RESPONSE_UNTRUSTWORTHY"


@pytest.mark.parametrize(
    ("candidate_request", "message"),
    [
        (object(), "WriteCallRequest"),
        (replace(_write_request(), tool_id="FINANCE.OTHER"), "operation"),
        (replace(_write_request(), arguments={}), "business payload"),
        (
            replace(_write_request(), payload_hash="sha256:" + "0" * 64),
            "payload hash",
        ),
        (replace(_write_request(), trace_refs=()), "correlation_id"),
    ],
)
def test_journal_command_admission_fails_closed(
    candidate_request: object, message: str
) -> None:
    with pytest.raises(EosJournalExecutionError, match=message):
        build_eos_journal_post_command(candidate_request, public_api=_public_api())


def test_journal_default_execution_configuration_is_validated() -> None:
    adapter = build_default_eos_journal_execution_port(
        public_api=_public_api(),
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
        environ={
            "NEX_EOS_BASE_URL": "https://eos.example",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "token",
            "NEX_AE_EOS_JOURNAL_WRITE_TIMEOUT_SECONDS": "21",
        },
    )
    assert adapter.base_url == "https://eos.example"
    assert adapter.timeout_seconds == 21
    with pytest.raises(ValueError, match="numeric"):
        build_default_eos_journal_execution_port(
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
            environ={"NEX_AE_EOS_JOURNAL_WRITE_TIMEOUT_SECONDS": "bad"},
        )


def test_journal_unknown_reconciles_to_committed_without_second_post() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json=_reconciliation_projection(), request=request)

    request = _write_request()
    unknown = WriteCommitUnknown(
        WriteOutcomeIdentity.from_request(request),
        "PROVIDER_CONNECTION_LOST",
        "uncertain",
    )
    result = asyncio.run(
        _reconciliation_adapter(httpx.MockTransport(handler)).reconcile(
            request, unknown
        )
    )

    assert isinstance(result, WriteCommitted)
    assert result.result.value.value["journal_id"] == JOURNAL_ID
    assert result.result.business_reference == f"eos.posted_journal:{JOURNAL_ID}"
    assert methods == ["GET"]


@pytest.mark.parametrize(
    ("projection", "status", "expected_type", "reason"),
    [
        (
            _reconciliation_projection(
                state="NOT_COMMITTED",
                reconciliation="NOT_COMMITTED_CONFIRMED",
                verification="NOT_APPLICABLE",
                retry="RETRY_SAME_IDENTITY_ONLY",
            ),
            200,
            WriteNotCommitted,
            "EOS_JOURNAL_NOT_COMMITTED_CONFIRMED",
        ),
        (
            _reconciliation_projection(
                state="UNKNOWN_COMMIT_STATE",
                reconciliation="RECONCILIATION_REQUIRED",
                verification="NOT_RUN",
            ),
            202,
            WriteCommitUnknown,
            "RECONCILIATION_REQUIRED",
        ),
        (
            _reconciliation_projection(
                state="COMMITTED",
                reconciliation="COMMITTED_VERIFICATION_FAILED",
                verification="FAILED",
            ),
            200,
            WriteCommitUnknown,
            "EOS_JOURNAL_COMMITTED_VERIFICATION_FAILED",
        ),
    ],
)
def test_journal_reconciliation_preserves_typed_terminal_states(
    projection: dict[str, object],
    status: int,
    expected_type: type,
    reason: str,
) -> None:
    request = _write_request()
    identity = WriteOutcomeIdentity.from_request(request)
    result = map_eos_journal_reconciliation_response(
        EosJournalReconciliationResponse(status, projection),
        request,
        identity=identity,
        public_api=_public_api(),
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
    )
    assert isinstance(result, expected_type)
    assert result.reason_code == reason
    assert result.provider_transaction_id == OPERATION_ID


def test_journal_reconciliation_rejects_identity_drift_and_malformed_state() -> None:
    request = _write_request()
    identity = WriteOutcomeIdentity.from_request(request)
    drifted = _reconciliation_projection()
    drifted["payload_hash"] = HASH
    result = map_eos_journal_reconciliation_response(
        EosJournalReconciliationResponse(200, drifted),
        request,
        identity=identity,
        public_api=_public_api(),
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
    )
    assert isinstance(result, WriteCommitUnknown)
    assert "UNTRUSTWORTHY" in result.evidence_refs[0]

    invalid = _reconciliation_projection()
    invalid["new_idempotency_key_allowed"] = True
    with pytest.raises(EosJournalReconciliationError):
        validate_eos_journal_reconciliation(
            invalid, identity=identity, expected_http_status=200
        )


def test_journal_reconciliation_transport_and_request_guards_are_fail_closed() -> None:
    request = _write_request()
    identity = WriteOutcomeIdentity.from_request(request)
    unknown = WriteCommitUnknown(identity, "TIMEOUT", "uncertain")

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    result = asyncio.run(
        _reconciliation_adapter(httpx.MockTransport(timeout)).reconcile(
            request, unknown
        )
    )
    assert isinstance(result, WriteCommitUnknown)
    assert result.reason_code == "RECONCILIATION_REQUIRED"

    adapter = _reconciliation_adapter(
        httpx.MockTransport(
            lambda req: httpx.Response(200, json=_reconciliation_projection(), request=req)
        )
    )
    with pytest.raises(EosJournalReconciliationError, match="WriteCommitUnknown"):
        asyncio.run(adapter.reconcile(request, object()))
    with pytest.raises(EosJournalReconciliationError, match="identities differ"):
        asyncio.run(
            adapter.reconcile(
                request,
                WriteCommitUnknown(
                    replace(identity, invocation_id="other"), "TIMEOUT", "uncertain"
                ),
            )
        )


def test_journal_default_reconciliation_configuration_is_validated() -> None:
    adapter = build_default_eos_journal_reconciliation_adapter(
        public_api=_public_api(),
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
        environ={"NEX_AE_EOS_JOURNAL_RECONCILIATION_TIMEOUT_SECONDS": "22"},
    )
    assert adapter.timeout_seconds == 22
    with pytest.raises(ValueError, match="numeric"):
        build_default_eos_journal_reconciliation_adapter(
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
            environ={"NEX_AE_EOS_JOURNAL_RECONCILIATION_TIMEOUT_SECONDS": "bad"},
        )


def test_journal_verification_reads_authoritative_projection_without_mutation() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json=_reconciliation_projection(), request=request)

    adapter = HttpEosJournalVerificationAdapter(
        public_api=_public_api(),
        base_url="http://eos.test",
        service_token="signed-token",
        transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
    )
    result = asyncio.run(adapter.read(_verification_request()))

    assert isinstance(adapter, VerificationPort)
    assert result.matched is True
    assert result.reason_code is None
    assert result.business_reference == f"eos.posted_journal:{JOURNAL_ID}"
    assert result.evidence_ref == (
        f"eos.journal_verification:{OPERATION_ID}:{JOURNAL_HASH}"
    )
    assert methods == ["GET"]


@pytest.mark.parametrize(
    ("projection", "status", "reason"),
    [
        (
            _reconciliation_projection(
                state="COMMITTED",
                reconciliation="COMMITTED_VERIFICATION_FAILED",
                verification="FAILED",
            ),
            200,
            "EOS_JOURNAL_COMMITTED_VERIFICATION_FAILED",
        ),
        (
            _reconciliation_projection(
                state="UNKNOWN_COMMIT_STATE",
                reconciliation="RECONCILIATION_REQUIRED",
                verification="NOT_RUN",
            ),
            202,
            "EOS_JOURNAL_VERIFICATION_NOT_CONFIRMED",
        ),
    ],
)
def test_journal_verification_failure_never_triggers_second_post(
    projection: dict[str, object], status: int, reason: str
) -> None:
    result = map_eos_journal_verification_response(
        EosJournalReconciliationResponse(status, projection),
        _verification_request(),
        public_api=_public_api(),
        observed_at=NOW,
    )
    assert result.matched is False
    assert result.reason_code == reason
    assert result.observed_at == NOW


@pytest.mark.parametrize(
    ("verification_request", "message"),
    [
        (object(), "VerificationRequest"),
        (
            _verification_request(verification_tool_id="FINANCE.JOURNAL.VERIFY"),
            "operation",
        ),
        (_verification_request(consistency_hint=None), "read-after-write"),
        (_verification_request(provider_transaction_id="bad"), "transaction"),
        (_verification_request(business_reference="bad"), "business reference"),
    ],
)
def test_journal_verification_request_binding_is_fail_closed(
    verification_request: object, message: str
) -> None:
    with pytest.raises(EosJournalVerificationError, match=message):
        map_eos_journal_verification_response(
            EosJournalReconciliationResponse(200, _reconciliation_projection()),
            verification_request,
            public_api=_public_api(),
            observed_at=NOW,
        )


def test_journal_verification_unavailable_and_configuration_fail_closed() -> None:
    with pytest.raises(EosJournalVerificationError, match="authoritative"):
        map_eos_journal_verification_response(
            EosJournalReconciliationResponse(
                503, {"status": 503, "error_code": "UNAVAILABLE"}
            ),
            _verification_request(),
            public_api=_public_api(),
            observed_at=NOW,
        )
    adapter = build_default_eos_journal_verification_adapter(
        public_api=_public_api(),
        environ={"NEX_AE_EOS_JOURNAL_VERIFICATION_TIMEOUT_SECONDS": "23"},
    )
    assert adapter.timeout_seconds == 23
    with pytest.raises(ValueError, match="numeric"):
        build_default_eos_journal_verification_adapter(
            public_api=_public_api(),
            environ={"NEX_AE_EOS_JOURNAL_VERIFICATION_TIMEOUT_SECONDS": "bad"},
        )


def test_mapping_type_guards_remain_explicit() -> None:
    request = _write_request()
    identity = WriteOutcomeIdentity.from_request(request)
    with pytest.raises(TypeError):
        map_eos_journal_execution_response(
            object(),
            request,
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        )
    with pytest.raises(TypeError):
        map_eos_journal_reconciliation_response(
            object(),
            request,
            identity=identity,
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        )
    with pytest.raises(TypeError):
        map_eos_journal_verification_response(
            object(),
            _verification_request(),
            public_api=_public_api(),
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("operation"),
        lambda value: value.update(operation="FINANCE.OTHER"),
        lambda value: value.update(idempotency_disposition="CREATED", created=False),
        lambda value: value.update(result=[]),
        lambda value: value.update(outbox=[]),
        lambda value: value["result"].update(journal_id="bad"),
        lambda value: value["result"].update(business_result_ref="bad"),
        lambda value: value["result"].update(candidate_id=JOURNAL_ID),
        lambda value: value["result"].update(company_id=JOURNAL_ID),
        lambda value: value["result"].update(candidate_revision=3),
        lambda value: value["result"].update(candidate_version=3),
        lambda value: value["result"].update(candidate_state="APPROVED"),
        lambda value: value["result"].update(journal_hash="bad"),
        lambda value: value["result"].update(posted_at="bad"),
        lambda value: value["result"].update(project_codes=[]),
        lambda value: value["result"].update(accounting_period_id="bad"),
        lambda value: value["outbox"].update(delivery_state="PUBLISHED"),
        lambda value: value["outbox"].update(outbox_id="bad"),
        lambda value: value["outbox"].update(event_payload_hash="bad"),
    ],
)
def test_journal_success_response_nested_lineage_is_fail_closed(mutation) -> None:
    payload = _post_result()
    mutation(payload)
    with pytest.raises(EosJournalExecutionError):
        map_eos_journal_execution_response(
            EosJournalExecutionResponse(201, payload),
            _write_request(),
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        )


@pytest.mark.parametrize(
    "payload_change",
    [
        {"schema_version": "bad"},
        {"tenant_id": "OTHER"},
        {"candidate_id": "bad"},
        {"company_id": "bad"},
        {"expected_candidate_version": 0},
        {"expected_candidate_revision": True},
        {"expected_candidate_hash": "bad"},
        {"accounting_approval_evidence_id": "bad"},
        {"company_id": {"not": {"json"}}},
    ],
)
def test_journal_business_payload_validation_is_fail_closed(payload_change) -> None:
    payload = _business_payload()
    payload.update(payload_change)
    try:
        payload_hash = nsl_write_payload_hash_ref(payload)
    except TypeError:
        payload_hash = _write_request().payload_hash
    request = replace(
        _write_request(),
        arguments=MappingProxyType(
            {name: Envelope(value) for name, value in payload.items()}
        ),
        payload_hash=payload_hash,
    )
    with pytest.raises(EosJournalExecutionError):
        build_eos_journal_post_command(request, public_api=_public_api())


@pytest.mark.parametrize(
    "request_change",
    [
        {"business_operation_id": "bad"},
        {"idempotency_key": ""},
        {"payload_hash": "bad"},
        {"trace_refs": []},
        {
            "trace_refs": (
                "correlation_id:one",
                "correlation_id:two",
            )
        },
        {"trace_refs": ("correlation_id:",)},
    ],
)
def test_journal_transport_identity_validation_is_fail_closed(request_change) -> None:
    with pytest.raises(EosJournalExecutionError):
        build_eos_journal_post_command(
            replace(_write_request(), **request_change), public_api=_public_api()
        )


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (302, {"redirect": True}),
        (201, ["not", "object"]),
        (201, None),
    ],
)
def test_journal_http_response_shape_is_fail_closed(status: int, body: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if body is None:
            return httpx.Response(status, content=b"not-json", request=request)
        return httpx.Response(status, json=body, request=request)

    result = asyncio.run(
        _execution_adapter(httpx.MockTransport(handler)).execute(_write_request())
    )
    assert isinstance(result, WriteCommitUnknown)


def test_journal_execution_connection_loss_and_pre_dispatch_rejection() -> None:
    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    result = asyncio.run(
        _execution_adapter(httpx.MockTransport(disconnected)).execute(_write_request())
    )
    assert isinstance(result, WriteCommitUnknown)
    assert result.reason_code == "PROVIDER_CONNECTION_LOST"

    adapter = _execution_adapter(
        httpx.MockTransport(
            lambda request: httpx.Response(201, json=_post_result(), request=request)
        )
    )
    object.__setattr__(adapter, "service_token", "")
    # Invalid requests fail before any provider mutation and are confirmed not dispatched.
    result = asyncio.run(adapter.execute(replace(_write_request(), tool_id="bad")))
    assert isinstance(result, WriteNotCommitted)
    assert result.reason_code == "EOS_JOURNAL_COMMAND_NOT_DISPATCHED"

    missing_token = _execution_adapter(httpx.MockTransport(disconnected))
    object.__setattr__(missing_token, "service_token", "")
    result = asyncio.run(missing_token.execute(_write_request()))
    assert isinstance(result, WriteNotCommitted)


def test_journal_adapter_constructor_and_result_contract_guards() -> None:
    with pytest.raises(ValueError, match="timeout"):
        HttpEosJournalExecutionPort(public_api=_public_api(), timeout_seconds=0)
    with pytest.raises(ValueError, match="URL"):
        HttpEosJournalExecutionPort(public_api=_public_api(), base_url="ftp://bad")
    with pytest.raises(ValueError, match="URL"):
        HttpEosJournalExecutionPort(public_api=_public_api(), base_url=" bad ")
    with pytest.raises(ValueError, match="credentials"):
        HttpEosJournalExecutionPort(
            public_api=_public_api(), base_url="http://user:pass@eos.test"
        )
    with pytest.raises(ValueError, match="result type"):
        asyncio.run(
            HttpEosJournalExecutionPort(
                public_api=_public_api(),
                result_classification=Classification.CONFIDENTIAL,
            ).execute(_write_request())
        )
    with pytest.raises(ValueError, match="classification"):
        asyncio.run(
            HttpEosJournalExecutionPort(
                public_api=_public_api(), result_type=RESULT_TYPE
            ).execute(_write_request())
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("operation"),
        lambda value: value.update(operation="FINANCE.OTHER"),
        lambda value: value.update(business_operation_id="bad"),
        lambda value: value.update(payload_hash="bad"),
        lambda value: value.update(last_observed_at="bad"),
        lambda value: value["journal"].pop("journal_no"),
        lambda value: value["journal"].update(company_id="bad"),
        lambda value: value["journal"].update(journal_hash="bad"),
        lambda value: value["journal"].update(candidate_revision=0),
        lambda value: value["journal"].update(line_count=1),
        lambda value: value["journal"].update(project_codes=[]),
        lambda value: value["journal"].update(total_credit_functional="1.0000"),
        lambda value: value["journal"].update(posted_at="bad"),
        lambda value: value["outbox"].pop("event_id"),
        lambda value: value["outbox"].update(outbox_id="bad"),
        lambda value: value["outbox"].update(event_payload_hash="bad"),
        lambda value: value["outbox"].update(event_type="OTHER"),
        lambda value: value["outbox"].update(delivery_state="FAILED"),
        lambda value: value["outbox"].update(projector_state="CURRENT"),
        lambda value: value["outbox"].update(attempt_count=-1),
    ],
)
def test_journal_reconciliation_nested_lineage_is_fail_closed(mutation) -> None:
    projection = copy.deepcopy(_reconciliation_projection())
    mutation(projection)
    with pytest.raises((EosJournalReconciliationError, ValueError)):
        validate_eos_journal_reconciliation(
            projection,
            identity=WriteOutcomeIdentity.from_request(_write_request()),
            expected_http_status=200,
        )


def test_journal_nonterminal_projection_cannot_carry_journal_lineage() -> None:
    projection = _reconciliation_projection(
        state="UNKNOWN_COMMIT_STATE",
        reconciliation="RECONCILIATION_REQUIRED",
        verification="NOT_RUN",
    )
    projection["journal"] = _journal_projection()
    with pytest.raises(EosJournalReconciliationError, match="inconsistent"):
        validate_eos_journal_reconciliation(
            projection,
            identity=WriteOutcomeIdentity.from_request(_write_request()),
            expected_http_status=202,
        )


def test_journal_reconciliation_http_and_constructor_guards() -> None:
    request = _write_request()
    identity = WriteOutcomeIdentity.from_request(request)
    unknown = WriteCommitUnknown(identity, "TIMEOUT", "uncertain")
    adapter = _reconciliation_adapter(
        httpx.MockTransport(
            lambda req: httpx.Response(503, content=b"not-json", request=req)
        )
    )
    result = asyncio.run(adapter.reconcile(request, unknown))
    assert isinstance(result, WriteCommitUnknown)

    result = map_eos_journal_reconciliation_response(
        EosJournalReconciliationResponse(
            503, {"status": 503, "error_code": "EOS_UNAVAILABLE"}
        ),
        request,
        identity=identity,
        public_api=_public_api(),
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
    )
    assert "EOS_UNAVAILABLE" in result.evidence_refs[0]

    with pytest.raises(ValueError, match="timeout"):
        HttpEosJournalReconciliationAdapter(
            public_api=_public_api(), timeout_seconds=False
        )
    with pytest.raises(ValueError, match="URL"):
        HttpEosJournalReconciliationAdapter(
            public_api=_public_api(), base_url="http://user:pass@eos.test"
        )
    with pytest.raises(ValueError, match="URL"):
        HttpEosJournalReconciliationAdapter(
            public_api=_public_api(), base_url=" bad "
        )
    with pytest.raises(ValueError, match="URL"):
        HttpEosJournalReconciliationAdapter(
            public_api=_public_api(), base_url="ftp://eos.test"
        )
    with pytest.raises(ValueError, match="result type"):
        asyncio.run(
            HttpEosJournalReconciliationAdapter(
                public_api=_public_api(),
                result_classification=Classification.CONFIDENTIAL,
            ).reconcile(request, unknown)
        )
    with pytest.raises(ValueError, match="classification"):
        asyncio.run(
            HttpEosJournalReconciliationAdapter(
                public_api=_public_api(), result_type=RESULT_TYPE
            ).reconcile(request, unknown)
        )


def test_journal_reconciliation_request_and_connection_guards() -> None:
    request = _write_request()
    identity = WriteOutcomeIdentity.from_request(request)
    unknown = WriteCommitUnknown(identity, "TIMEOUT", "uncertain")

    def disconnected(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=req)

    result = asyncio.run(
        _reconciliation_adapter(httpx.MockTransport(disconnected)).reconcile(
            request, unknown
        )
    )
    assert isinstance(result, WriteCommitUnknown)
    tokenless = _reconciliation_adapter(httpx.MockTransport(disconnected))
    object.__setattr__(tokenless, "service_token", "")
    assert isinstance(
        asyncio.run(tokenless.reconcile(request, unknown)), WriteCommitUnknown
    )
    with pytest.raises(EosJournalReconciliationError, match="WriteCallRequest"):
        asyncio.run(
            _reconciliation_adapter(httpx.MockTransport(disconnected)).reconcile(
                object(), unknown
            )
        )
    with pytest.raises(EosJournalReconciliationError, match="unsupported"):
        asyncio.run(
            _reconciliation_adapter(httpx.MockTransport(disconnected)).reconcile(
                replace(request, tool_id="OTHER"), unknown
            )
        )


@pytest.mark.parametrize("observed_at", [None, "bad", "2026-11-15T03:00:00"])
def test_journal_reconciliation_timestamp_variants_fail_closed(observed_at) -> None:
    projection = _reconciliation_projection()
    projection["last_observed_at"] = observed_at
    with pytest.raises(EosJournalReconciliationError):
        validate_eos_journal_reconciliation(
            projection,
            identity=WriteOutcomeIdentity.from_request(_write_request()),
            expected_http_status=200,
        )


def test_journal_reconciliation_non_object_response_is_unknown() -> None:
    request = _write_request()
    identity = WriteOutcomeIdentity.from_request(request)
    unknown = WriteCommitUnknown(identity, "TIMEOUT", "uncertain")
    adapter = _reconciliation_adapter(
        httpx.MockTransport(
            lambda req: httpx.Response(503, json=["bad"], request=req)
        )
    )
    assert isinstance(asyncio.run(adapter.reconcile(request, unknown)), WriteCommitUnknown)

    result = map_eos_journal_reconciliation_response(
        EosJournalReconciliationResponse(503, {"status": 400, "error_code": "BAD"}),
        request,
        identity=identity,
        public_api=_public_api(),
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
    )
    assert "EOS_JOURNAL_RECONCILIATION_UNAVAILABLE" in result.evidence_refs[0]


def test_journal_verification_drift_malformed_and_transport_fail_closed() -> None:
    drifted = _reconciliation_projection()
    drifted["journal"]["journal_id"] = CANDIDATE_ID
    with pytest.raises(EosJournalVerificationError, match="identity differs"):
        map_eos_journal_verification_response(
            EosJournalReconciliationResponse(200, drifted),
            _verification_request(),
            public_api=_public_api(),
            observed_at=NOW,
        )
    malformed = _reconciliation_projection()
    malformed["payload_hash"] = "bad"
    with pytest.raises(EosJournalVerificationError, match="not trustworthy"):
        map_eos_journal_verification_response(
            EosJournalReconciliationResponse(200, malformed),
            _verification_request(),
            public_api=_public_api(),
            observed_at=NOW,
        )

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    adapter = HttpEosJournalVerificationAdapter(
        public_api=_public_api(),
        base_url="http://eos.test",
        service_token="signed-token",
        transport=httpx.MockTransport(timeout),
    )
    with pytest.raises(EosJournalVerificationError, match="unavailable"):
        asyncio.run(adapter.read(_verification_request()))

    tokenless = HttpEosJournalVerificationAdapter(
        public_api=_public_api(),
        base_url="http://eos.test",
        service_token="",
        transport=httpx.MockTransport(timeout),
    )
    with pytest.raises(EosJournalVerificationError, match="unavailable"):
        asyncio.run(tokenless.read(_verification_request()))


def test_journal_verification_constructor_and_identity_guards() -> None:
    with pytest.raises(TypeError, match="clock"):
        HttpEosJournalVerificationAdapter(
            public_api=_public_api(), clock=None  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="timeout"):
        HttpEosJournalVerificationAdapter(
            public_api=_public_api(), timeout_seconds=0
        )
    wrong_identity = replace(
        WriteOutcomeIdentity.from_request(_write_request()), tool_id="OTHER"
    )
    with pytest.raises(EosJournalVerificationError, match="WRITE operation"):
        map_eos_journal_verification_response(
            EosJournalReconciliationResponse(200, _reconciliation_projection()),
            _verification_request(identity=wrong_identity),
            public_api=_public_api(),
            observed_at=NOW,
        )
    with pytest.raises(EosJournalVerificationError, match="outcome identity"):
        map_eos_journal_verification_response(
            EosJournalReconciliationResponse(200, _reconciliation_projection()),
            _verification_request(identity=object()),  # type: ignore[arg-type]
            public_api=_public_api(),
            observed_at=NOW,
        )
    bad_uuid_identity = replace(
        WriteOutcomeIdentity.from_request(_write_request()),
        business_operation_id="bad",
    )
    with pytest.raises(EosJournalVerificationError, match="UUID"):
        map_eos_journal_verification_response(
            EosJournalReconciliationResponse(200, _reconciliation_projection()),
            _verification_request(identity=bad_uuid_identity),
            public_api=_public_api(),
            observed_at=NOW,
        )
    bad_hash_identity = replace(
        WriteOutcomeIdentity.from_request(_write_request()), payload_hash="bad"
    )
    with pytest.raises(EosJournalVerificationError, match="hash binding"):
        map_eos_journal_verification_response(
            EosJournalReconciliationResponse(200, _reconciliation_projection()),
            _verification_request(identity=bad_hash_identity),
            public_api=_public_api(),
            observed_at=NOW,
        )
    with pytest.raises(EosJournalVerificationError, match="observation time"):
        map_eos_journal_verification_response(
            EosJournalReconciliationResponse(
                202,
                _reconciliation_projection(
                    state="UNKNOWN_COMMIT_STATE",
                    reconciliation="RECONCILIATION_REQUIRED",
                    verification="NOT_RUN",
                ),
            ),
            _verification_request(),
            public_api=_public_api(),
            observed_at=NOW.replace(tzinfo=None),
        )
