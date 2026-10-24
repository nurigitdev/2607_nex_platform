from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

import httpx
import pytest
from nex_ae_api.nsl_eos_reconciliation import (
    EOS_BUSINESS_OPERATION_PATH,
    EosBusinessOperationResponse,
    EosReconciliationError,
    HttpEosReconciliationAdapter,
    build_default_eos_reconciliation_adapter,
    map_eos_business_operation_response,
)
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter

HASH = "sha256:" + "a" * 64
PAYLOAD_HASH = "sha256:" + "b" * 64
OPERATION_ID = "86000000-0000-4000-8000-000000000060"
VOUCHER_ID = "84000000-0000-4000-8000-000000000060"
ATTACHMENT_BATCH_ID = "87000000-0000-4000-8000-000000000060"
ATTACHMENT_ID_1 = "88000000-0000-4000-8000-000000000060"
ATTACHMENT_ID_2 = "88000000-0000-4000-8000-000000000061"
ATTACHMENT_MANIFEST_HASH = "sha256:" + "e" * 64
RESULT_TYPE = object()


@dataclass(frozen=True)
class Envelope:
    value: object
    type_info: object = None
    classification: object = None
    provenance_refs: tuple[str, ...] = ()

    @classmethod
    def complete(
        cls,
        value: object,
        type_info: object,
        classification: object,
        provenance_refs: tuple[str, ...],
    ) -> Envelope:
        return cls(value, type_info, classification, provenance_refs)


class Classification(StrEnum):
    CONFIDENTIAL = "CONFIDENTIAL"


class CommitState(StrEnum):
    COMMITTED = "COMMITTED"
    NOT_COMMITTED = "NOT_COMMITTED"
    UNKNOWN_COMMIT_STATE = "UNKNOWN_COMMIT_STATE"


@dataclass(frozen=True)
class WriteCallRequest:
    tenant_id: str
    business_operation_id: str
    invocation_id: str
    node_id: str
    tool_id: str
    idempotency_key: str
    payload_hash: str
    approval_request_id: str
    write_intent_hash: str
    arguments: object


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
    committed_at: object
    evidence_refs: tuple[str, ...]


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
        post_write_verification_port=object,
        verification_request=object,
        verification_observation=object,
        runtime_policy_port=object,
        write_policy_request=object,
        policy_decision=object,
        policy_effect=object,
        runtime_preflight_validator=object,
        release_admission_hash=HASH,
        api_contract_hash=HASH,
    )


def _request(**changes: object) -> WriteCallRequest:
    values = {
        "tenant_id": "tenant-p8-s60",
        "business_operation_id": OPERATION_ID,
        "invocation_id": "invocation-p8-s60",
        "node_id": "write-voucher-draft",
        "tool_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "idempotency_key": "idem:sha256:" + "c" * 64,
        "payload_hash": PAYLOAD_HASH,
        "approval_request_id": "approval-request-p8-s60",
        "write_intent_hash": "sha256:" + "d" * 64,
        "arguments": MappingProxyType({"schema_version": Envelope("command.v1")}),
    }
    values.update(changes)
    return WriteCallRequest(**values)  # type: ignore[arg-type]


def _attachment_request(**changes: object) -> WriteCallRequest:
    arguments = {
        "schema_version": Envelope("command.v1"),
        "attachment_batch_id": Envelope(ATTACHMENT_BATCH_ID),
        "attachment_manifest_hash": Envelope(ATTACHMENT_MANIFEST_HASH),
        "attachments": Envelope(
            [
                {"attachment_id": ATTACHMENT_ID_1, "object_ref": "s3://one"},
                {"attachment_id": ATTACHMENT_ID_2, "object_ref": "s3://two"},
            ]
        ),
    }
    arguments.update(changes.pop("arguments", {}))
    return _request(arguments=MappingProxyType(arguments), **changes)


def _unknown(request: WriteCallRequest | None = None) -> WriteCommitUnknown:
    request = request or _request()
    return WriteCommitUnknown(
        WriteOutcomeIdentity.from_request(request),
        "PROVIDER_TIMEOUT",
        "Provider outcome is uncertain.",
    )


def _projection(
    *,
    state: str = "COMMITTED",
    reconciliation: str = "COMMITTED_CONFIRMED",
    voucher: object = ...,
) -> dict[str, object]:
    if voucher is ...:
        voucher = (
            {"type": "eos.voucher_draft", "id": VOUCHER_ID}
            if state == "COMMITTED"
            else None
        )
    return {
        "schema_version": "eos_business_operation_query.v1",
        "tenant_id": "tenant-p8-s60",
        "business_operation_id": OPERATION_ID,
        "operation": "FINANCE.CREATE_VOUCHER_DRAFT",
        "payload_hash": PAYLOAD_HASH,
        "commit_state": state,
        "business_transaction_ref": {
            "type": "eos.business_operation",
            "id": OPERATION_ID,
        },
        "voucher_ref": voucher,
        "attachment_batch_id": None,
        "attachment_manifest_hash": None,
        "attachment_ids": [],
        "reconciliation_status": reconciliation,
        "last_observed_at": "2026-10-22T12:00:00Z",
    }


def _adapter(transport: httpx.AsyncBaseTransport) -> HttpEosReconciliationAdapter:
    return HttpEosReconciliationAdapter(
        public_api=_public_api(),
        base_url="http://eos.test",
        service_token="signed-token",
        transport=transport,
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
    )


def _reconcile(adapter: HttpEosReconciliationAdapter, request=None, unknown=None):
    request = request or _request()
    unknown = unknown or _unknown(request)
    return asyncio.run(adapter.reconcile(request, unknown))


def test_committed_query_maps_to_nsl_committed_and_sends_read_only_request() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(
            method=request.method,
            url=str(request.url),
            headers=dict(request.headers),
        )
        return httpx.Response(200, json=_projection(), request=request)

    outcome = _reconcile(_adapter(httpx.MockTransport(handler)))

    assert isinstance(outcome, WriteCommitted)
    assert outcome.commit_state is CommitState.COMMITTED
    assert outcome.result.value.value == {"voucher_no": VOUCHER_ID}
    assert outcome.result.value.type_info is RESULT_TYPE
    assert outcome.result.value.classification is Classification.CONFIDENTIAL
    assert outcome.result.business_reference == f"eos.voucher_draft:{VOUCHER_ID}"
    assert outcome.result.provider_transaction_id == OPERATION_ID
    assert outcome.result.committed_at.isoformat() == "2026-10-22T12:00:00+00:00"
    assert observed["method"] == "GET"
    assert (
        observed["url"]
        == f"http://eos.test{EOS_BUSINESS_OPERATION_PATH}/{OPERATION_ID}"
    )
    headers = observed["headers"]
    assert headers["authorization"] == "Bearer signed-token"
    assert headers["x-nex-tenant-id"] == "tenant-p8-s60"
    assert headers["cache-control"] == "no-store, max-age=0"
    assert headers["pragma"] == "no-cache"


def test_committed_attachment_lineage_is_canonical_and_preserved_as_evidence() -> None:
    payload = _projection()
    payload.update(
        attachment_batch_id=ATTACHMENT_BATCH_ID,
        attachment_manifest_hash=ATTACHMENT_MANIFEST_HASH,
        attachment_ids=[ATTACHMENT_ID_1, ATTACHMENT_ID_2],
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    outcome = _reconcile(_adapter(transport), request=_attachment_request())

    assert isinstance(outcome, WriteCommitted)
    assert outcome.result.evidence_refs[-1] == (
        f"eos.attachment_manifest:{ATTACHMENT_BATCH_ID}:" f"{ATTACHMENT_MANIFEST_HASH}"
    )


@pytest.mark.parametrize(
    "changes",
    (
        {"attachment_batch_id": "87000000-0000-4000-8000-000000000061"},
        {"attachment_manifest_hash": "sha256:" + "f" * 64},
        {"attachment_ids": [ATTACHMENT_ID_1]},
        {
            "attachment_ids": [
                ATTACHMENT_ID_1,
                "88000000-0000-4000-8000-000000000062",
            ]
        },
    ),
)
def test_committed_attachment_lineage_must_match_original_write(changes) -> None:
    payload = _projection()
    payload.update(
        attachment_batch_id=ATTACHMENT_BATCH_ID,
        attachment_manifest_hash=ATTACHMENT_MANIFEST_HASH,
        attachment_ids=[ATTACHMENT_ID_1, ATTACHMENT_ID_2],
    )
    payload.update(changes)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    outcome = _reconcile(_adapter(transport), request=_attachment_request())

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.identity.payload_hash == PAYLOAD_HASH
    assert outcome.evidence_refs[0] == (
        "eos.reason:EOS_RECONCILIATION_RESPONSE_UNTRUSTWORTHY"
    )


@pytest.mark.parametrize(
    ("state", "reconciliation", "outcome_type"),
    (
        ("NOT_COMMITTED", "NOT_COMMITTED_CONFIRMED", WriteNotCommitted),
        ("UNKNOWN_COMMIT_STATE", "RECONCILIATION_REQUIRED", WriteCommitUnknown),
    ),
)
def test_nonterminal_attachment_write_preserves_original_outcome_identity(
    state: str,
    reconciliation: str,
    outcome_type: type,
) -> None:
    request = _attachment_request()
    transport = httpx.MockTransport(
        lambda http_request: httpx.Response(
            200,
            json=_projection(state=state, reconciliation=reconciliation),
            request=http_request,
        )
    )

    outcome = _reconcile(_adapter(transport), request=request)

    assert isinstance(outcome, outcome_type)
    assert outcome.identity == WriteOutcomeIdentity.from_request(request)
    assert outcome.identity.payload_hash == PAYLOAD_HASH


def test_request_attachment_order_does_not_change_identity_match() -> None:
    request = _attachment_request(
        arguments={
            "attachments": Envelope(
                [
                    {"attachment_id": ATTACHMENT_ID_2, "object_ref": "s3://two"},
                    {"attachment_id": ATTACHMENT_ID_1, "object_ref": "s3://one"},
                ]
            )
        }
    )
    payload = _projection()
    payload.update(
        attachment_batch_id=ATTACHMENT_BATCH_ID,
        attachment_manifest_hash=ATTACHMENT_MANIFEST_HASH,
        attachment_ids=[ATTACHMENT_ID_1, ATTACHMENT_ID_2],
    )

    outcome = _reconcile(
        _adapter(
            httpx.MockTransport(
                lambda http_request: httpx.Response(
                    200, json=payload, request=http_request
                )
            )
        ),
        request=request,
    )

    assert isinstance(outcome, WriteCommitted)


def test_frozen_request_attachment_sequence_matches_canonical_projection() -> None:
    request = _attachment_request(
        arguments={
            "attachments": Envelope(
                (
                    {"attachment_id": ATTACHMENT_ID_1, "object_ref": "s3://one"},
                    {"attachment_id": ATTACHMENT_ID_2, "object_ref": "s3://two"},
                )
            )
        }
    )
    payload = _projection()
    payload.update(
        attachment_batch_id=ATTACHMENT_BATCH_ID,
        attachment_manifest_hash=ATTACHMENT_MANIFEST_HASH,
        attachment_ids=[ATTACHMENT_ID_1, ATTACHMENT_ID_2],
    )

    outcome = _reconcile(
        _adapter(
            httpx.MockTransport(
                lambda http_request: httpx.Response(
                    200, json=payload, request=http_request
                )
            )
        ),
        request=request,
    )

    assert isinstance(outcome, WriteCommitted)


@pytest.mark.parametrize(
    "arguments",
    (
        object(),
        MappingProxyType({"attachments": Envelope("not-a-sequence")}),
        MappingProxyType(
            {
                "attachments": Envelope([]),
                "attachment_batch_id": Envelope(ATTACHMENT_BATCH_ID),
            }
        ),
        MappingProxyType(
            {
                "attachments": Envelope([{"attachment_id": ATTACHMENT_ID_1}]),
            }
        ),
        MappingProxyType(
            {
                "attachments": Envelope([{"attachment_id": ATTACHMENT_ID_1}]),
                "attachment_batch_id": Envelope("bad"),
                "attachment_manifest_hash": Envelope(ATTACHMENT_MANIFEST_HASH),
            }
        ),
        MappingProxyType(
            {
                "attachments": Envelope([{"attachment_id": ATTACHMENT_ID_1}]),
                "attachment_batch_id": Envelope(ATTACHMENT_BATCH_ID),
                "attachment_manifest_hash": Envelope("bad"),
            }
        ),
        MappingProxyType(
            {
                "attachments": Envelope(["bad-item"]),
                "attachment_batch_id": Envelope(ATTACHMENT_BATCH_ID),
                "attachment_manifest_hash": Envelope(ATTACHMENT_MANIFEST_HASH),
            }
        ),
        MappingProxyType(
            {
                "attachments": Envelope([{"attachment_id": "bad"}]),
                "attachment_batch_id": Envelope(ATTACHMENT_BATCH_ID),
                "attachment_manifest_hash": Envelope(ATTACHMENT_MANIFEST_HASH),
            }
        ),
        MappingProxyType(
            {
                "attachments": Envelope(
                    [
                        {"attachment_id": ATTACHMENT_ID_1},
                        {"attachment_id": ATTACHMENT_ID_1},
                    ]
                ),
                "attachment_batch_id": Envelope(ATTACHMENT_BATCH_ID),
                "attachment_manifest_hash": Envelope(ATTACHMENT_MANIFEST_HASH),
            }
        ),
    ),
)
def test_malformed_request_attachment_lineage_remains_unknown(arguments) -> None:
    request = _request(arguments=arguments)
    transport = httpx.MockTransport(
        lambda http_request: httpx.Response(
            200, json=_projection(), request=http_request
        )
    )

    outcome = _reconcile(_adapter(transport), request=request)

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.evidence_refs[0] == (
        "eos.reason:EOS_RECONCILIATION_RESPONSE_UNTRUSTWORTHY"
    )


@pytest.mark.parametrize(
    "changes",
    (
        {
            "commit_state": "NOT_COMMITTED",
            "reconciliation_status": "NOT_COMMITTED_CONFIRMED",
            "voucher_ref": None,
            "attachment_batch_id": ATTACHMENT_BATCH_ID,
            "attachment_manifest_hash": ATTACHMENT_MANIFEST_HASH,
            "attachment_ids": [ATTACHMENT_ID_1],
        },
        {
            "attachment_batch_id": ATTACHMENT_BATCH_ID,
            "attachment_manifest_hash": ATTACHMENT_MANIFEST_HASH,
            "attachment_ids": [],
        },
        {
            "attachment_batch_id": "bad",
            "attachment_manifest_hash": ATTACHMENT_MANIFEST_HASH,
            "attachment_ids": [ATTACHMENT_ID_1],
        },
        {
            "attachment_batch_id": ATTACHMENT_BATCH_ID,
            "attachment_manifest_hash": "bad",
            "attachment_ids": [ATTACHMENT_ID_1],
        },
        {
            "attachment_batch_id": ATTACHMENT_BATCH_ID,
            "attachment_manifest_hash": ATTACHMENT_MANIFEST_HASH,
            "attachment_ids": ["bad"],
        },
        {
            "attachment_batch_id": ATTACHMENT_BATCH_ID,
            "attachment_manifest_hash": ATTACHMENT_MANIFEST_HASH,
            "attachment_ids": [ATTACHMENT_ID_2, ATTACHMENT_ID_1],
        },
        {
            "attachment_batch_id": ATTACHMENT_BATCH_ID,
            "attachment_manifest_hash": ATTACHMENT_MANIFEST_HASH,
            "attachment_ids": [ATTACHMENT_ID_1, ATTACHMENT_ID_1],
        },
    ),
)
def test_untrustworthy_attachment_reconciliation_preserves_unknown(changes) -> None:
    payload = _projection()
    payload.update(changes)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    outcome = _reconcile(_adapter(transport))

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.evidence_refs[0] == (
        "eos.reason:EOS_RECONCILIATION_RESPONSE_UNTRUSTWORTHY"
    )


@pytest.mark.parametrize(
    ("state", "reconciliation", "outcome_type", "reason"),
    [
        (
            "NOT_COMMITTED",
            "NOT_COMMITTED_CONFIRMED",
            WriteNotCommitted,
            "EOS_NOT_COMMITTED_CONFIRMED",
        ),
        (
            "UNKNOWN_COMMIT_STATE",
            "RECONCILIATION_REQUIRED",
            WriteCommitUnknown,
            "RECONCILIATION_REQUIRED",
        ),
    ],
)
def test_reconciliation_maps_authoritative_noncommit_and_pending_states(
    state: str,
    reconciliation: str,
    outcome_type: type,
    reason: str,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=_projection(state=state, reconciliation=reconciliation),
            request=request,
        )
    )

    outcome = _reconcile(_adapter(transport))

    assert isinstance(outcome, outcome_type)
    assert outcome.reason_code == reason
    assert outcome.provider_transaction_id == OPERATION_ID
    assert outcome.evidence_refs == (
        f"eos.business_operation:{OPERATION_ID}",
        f"eos.reconciliation:{OPERATION_ID}",
    )


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (
            404,
            {"status": 404, "error_code": "EOS_BUSINESS_OPERATION_NOT_FOUND"},
            "EOS_BUSINESS_OPERATION_NOT_FOUND",
        ),
        (
            503,
            {"status": 503, "error_code": "EOS_BUSINESS_QUERY_UNAVAILABLE"},
            "EOS_BUSINESS_QUERY_UNAVAILABLE",
        ),
        (
            403,
            {"status": 401, "error_code": "EOS_ACCESS_DENIED"},
            "EOS_RECONCILIATION_UNAVAILABLE",
        ),
    ],
)
def test_non_success_query_never_infers_not_committed(
    status: int,
    body: dict[str, object],
    reason: str,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json=body, request=request)
    )

    outcome = _reconcile(_adapter(transport))

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert outcome.evidence_refs[0] == f"eos.reason:{reason}"
    assert outcome.evidence_refs[-1] == f"eos.http_status:{status}"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (httpx.ReadTimeout("slow"), "EOS_RECONCILIATION_TIMEOUT"),
        (httpx.ConnectError("offline"), "EOS_RECONCILIATION_CONNECTION_LOST"),
        (httpx.UnsupportedProtocol("bad"), "EOS_RECONCILIATION_UNAVAILABLE"),
    ],
)
def test_transport_failure_preserves_unknown_without_retry(
    failure: Exception,
    reason: str,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise failure

    outcome = _reconcile(_adapter(httpx.MockTransport(handler)))

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert outcome.evidence_refs == (f"eos.reason:{reason}",)
    assert calls == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(tenant_id="tenant-other"),
        lambda payload: payload.update(payload_hash="sha256:" + "f" * 64),
        lambda payload: payload.update(operation="FINANCE.DELETE_VOUCHER"),
        lambda payload: payload.update(extra="field"),
        lambda payload: payload.update(
            business_transaction_ref={"type": "wrong", "id": OPERATION_ID}
        ),
        lambda payload: payload.update(
            business_transaction_ref={
                "type": "eos.business_operation",
                "id": "86000000-0000-4000-8000-000000000061",
            }
        ),
        lambda payload: payload.update(reconciliation_status="RECONCILIATION_REQUIRED"),
        lambda payload: payload.update(voucher_ref=None),
        lambda payload: payload.update(last_observed_at=42),
        lambda payload: payload.update(last_observed_at="not-a-time"),
        lambda payload: payload.update(last_observed_at="2026-10-22T12:00:00+09:00"),
    ],
)
def test_untrustworthy_success_preserves_unknown(mutation) -> None:
    payload = _projection()
    mutation(payload)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    outcome = _reconcile(_adapter(transport))

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert outcome.evidence_refs[0] == (
        "eos.reason:EOS_RECONCILIATION_RESPONSE_UNTRUSTWORTHY"
    )


@pytest.mark.parametrize(
    ("state", "reconciliation"),
    [
        ("NOT_COMMITTED", "NOT_COMMITTED_CONFIRMED"),
        ("UNKNOWN_COMMIT_STATE", "RECONCILIATION_REQUIRED"),
    ],
)
def test_noncommitted_projection_rejects_voucher_reference(
    state: str,
    reconciliation: str,
) -> None:
    payload = _projection(
        state=state,
        reconciliation=reconciliation,
        voucher={"type": "eos.voucher_draft", "id": VOUCHER_ID},
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    outcome = _reconcile(_adapter(transport))

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert outcome.evidence_refs[0] == (
        "eos.reason:EOS_RECONCILIATION_RESPONSE_UNTRUSTWORTHY"
    )


@pytest.mark.parametrize(
    "arguments",
    [{}, {"schema_version": object()}],
)
def test_committed_reconciliation_requires_value_envelope_factory(
    arguments: object,
) -> None:
    request = _request(arguments=arguments)
    response = EosBusinessOperationResponse(200, _projection())

    with pytest.raises(EosReconciliationError, match="ValueEnvelope"):
        map_eos_business_operation_response(
            response,
            request,
            identity=WriteOutcomeIdentity.from_request(request),
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        )


@pytest.mark.parametrize("body", ["not-json", ["not", "an", "object"]])
def test_invalid_http_body_preserves_unknown(body: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(200, text=body, request=request)
        return httpx.Response(200, json=body, request=request)

    outcome = _reconcile(_adapter(httpx.MockTransport(handler)))

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert outcome.evidence_refs == ("eos.reason:EOS_RECONCILIATION_UNAVAILABLE",)


def test_reconciliation_rejects_non_unknown_and_cross_request_identity() -> None:
    adapter = _adapter(httpx.MockTransport(lambda request: httpx.Response(500)))
    with pytest.raises(EosReconciliationError, match="WriteCommitUnknown"):
        _reconcile(adapter, unknown=object())

    other = _request(invocation_id="different-invocation")
    with pytest.raises(EosReconciliationError, match="identities differ"):
        _reconcile(adapter, unknown=_unknown(other))

    with pytest.raises(EosReconciliationError, match="WriteCallRequest"):
        asyncio.run(adapter.reconcile(object(), _unknown()))


@pytest.mark.parametrize(
    ("result_type", "classification"),
    [
        (None, Classification.CONFIDENTIAL),
        (RESULT_TYPE, None),
        (RESULT_TYPE, "CONFIDENTIAL"),
    ],
)
def test_reconciliation_requires_result_contract(
    result_type: object,
    classification: object,
) -> None:
    adapter = HttpEosReconciliationAdapter(
        _public_api(),
        "http://eos.test",
        "token",
        result_type=result_type,
        result_classification=classification,
    )

    with pytest.raises(ValueError, match="result"):
        _reconcile(adapter)


def test_signed_token_failure_preserves_reconciliation_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "SIGNED_ONLY")
    monkeypatch.delenv("NEX_AE_TO_EOS_SERVICE_TOKEN", raising=False)
    adapter = HttpEosReconciliationAdapter(
        _public_api(),
        "http://eos.test",
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
    )

    outcome = _reconcile(adapter)

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.reason_code == "RECONCILIATION_REQUIRED"
    assert outcome.evidence_refs == ("eos.reason:EOS_RECONCILIATION_UNAVAILABLE",)


def test_mapper_rejects_non_response_value() -> None:
    request = _request()
    with pytest.raises(TypeError, match="EosBusinessOperationResponse"):
        map_eos_business_operation_response(
            object(),  # type: ignore[arg-type]
            request,
            identity=WriteOutcomeIdentity.from_request(request),
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        )


@pytest.mark.parametrize(
    "base_url",
    ["", " eos.test", "ftp://eos.test", "http://user:secret@eos.test"],
)
def test_adapter_rejects_invalid_base_url(base_url: str) -> None:
    with pytest.raises(ValueError):
        HttpEosReconciliationAdapter(_public_api(), base_url)


@pytest.mark.parametrize("timeout", [True, 0, -1, "15"])
def test_adapter_rejects_invalid_timeout(timeout: object) -> None:
    with pytest.raises(ValueError):
        HttpEosReconciliationAdapter(
            _public_api(),
            timeout_seconds=timeout,  # type: ignore[arg-type]
        )


def test_default_builder_reads_reconciliation_configuration() -> None:
    adapter = build_default_eos_reconciliation_adapter(
        public_api=_public_api(),
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
        environ={
            "NEX_EOS_BASE_URL": "https://eos.internal",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "token-p8-s60",
            "NEX_AE_EOS_RECONCILIATION_TIMEOUT_SECONDS": "12.5",
        },
    )
    assert adapter.base_url == "https://eos.internal"
    assert adapter.service_token == "token-p8-s60"
    assert adapter.timeout_seconds == 12.5

    with pytest.raises(ValueError, match="must be numeric"):
        build_default_eos_reconciliation_adapter(
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
            environ={"NEX_AE_EOS_RECONCILIATION_TIMEOUT_SECONDS": "slow"},
        )


def test_raw_query_rejects_invalid_business_operation_id() -> None:
    adapter = _adapter(httpx.MockTransport(lambda request: httpx.Response(500)))

    with pytest.raises(EosReconciliationError, match="UUID"):
        asyncio.run(adapter.query_raw(_request(business_operation_id="bad")))

    with pytest.raises(EosReconciliationError, match="tenant_id"):
        asyncio.run(adapter.query_raw(_request(tenant_id="bad value")))


def test_adapter_normalizes_url_parser_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_value: object):
        raise ValueError("private parser detail")

    monkeypatch.setattr(httpx, "URL", fail)

    with pytest.raises(ValueError, match="bounded HTTP URL"):
        HttpEosReconciliationAdapter(_public_api(), "http://eos.test")


def test_raw_query_exposes_typed_response() -> None:
    adapter = _adapter(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_projection(), request=request)
        )
    )

    response = asyncio.run(adapter.query_raw(_request()))

    assert isinstance(response, EosBusinessOperationResponse)
    assert response.status_code == 200
    assert response.payload["reconciliation_status"] == "COMMITTED_CONFIRMED"
