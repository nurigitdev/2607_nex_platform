from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

import httpx
import pytest
from nex_ae_api.nsl_eos_write_execution import (
    DEFAULT_EOS_BASE_URL,
    EOS_CREATE_VOUCHER_PATH,
    EosWriteExecutionError,
    EosWriteExecutionResponse,
    HttpEosWriteExecutionPort,
    build_default_eos_write_execution_port,
    build_eos_create_voucher_command,
    map_eos_write_execution_response,
)
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref

HASH = "sha256:" + "a" * 64
OPERATION_ID = "86000000-0000-4000-8000-000000000057"
PROJECT_ID = "82000000-0000-4000-8000-000000000057"
DEBIT_ID = "83000000-0000-4000-8000-000000000057"
CREDIT_ID = "83000000-0000-4000-8000-000000000058"
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


@dataclass(frozen=True)
class EnvelopeWithoutFactory:
    value: object


class Classification(StrEnum):
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"


class CommitState(StrEnum):
    COMMITTED = "COMMITTED"
    NOT_COMMITTED = "NOT_COMMITTED"
    UNKNOWN_COMMIT_STATE = "UNKNOWN_COMMIT_STATE"


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


def _business_payload() -> dict[str, Any]:
    return {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": "tenant-p8-s57",
        "requester_ref": {"type": "oa.user", "id": "employee-1004"},
        "project_ref": {"type": "eos.project", "id": PROJECT_ID},
        "voucher_type": "GENERAL",
        "transaction_date": "2026-10-22",
        "currency": "KRW",
        "description": "P8-S57 EOS adapter voucher",
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": DEBIT_ID},
                "signed_amount": "10000.00",
                "economic_category": "TRAVEL",
                "description": "Debit",
                "evidence_refs": ["approval-evidence-p8-s57"],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": CREDIT_ID},
                "signed_amount": "-10000.00",
                "economic_category": "CASH",
                "description": "Credit",
                "evidence_refs": ["approval-evidence-p8-s57"],
            },
        ],
        "nsl_approval_request_id": "approval-request-p8-s57",
        "nsl_approval_evidence_ref": "approval-evidence-p8-s57",
        "business_approval_proof_ref": None,
        "attachments": [],
    }


def _request(**changes: object) -> WriteCallRequest:
    payload = _business_payload()
    payload.update(changes.pop("payload_changes", {}))  # type: ignore[arg-type]
    arguments = {key: Envelope(_frozen(value)) for key, value in payload.items()}
    values: dict[str, object] = {
        "tenant_id": payload["tenant_id"],
        "execution_id": "nsl-execution-p8-s57",
        "business_operation_id": OPERATION_ID,
        "invocation_id": "write-invocation-p8-s57",
        "node_id": "write-voucher-draft",
        "tool_ref": "urn:nex:tool:finance-create-voucher-draft:v1",
        "tool_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "contract_hash": "sha256:" + "b" * 64,
        "arguments": MappingProxyType(arguments),
        "idempotency_key": "idem:sha256:" + "c" * 64,
        "payload_hash": nsl_write_payload_hash_ref(payload),
        "approval_id": "APPROVE_VOUCHER_DRAFT",
        "approval_request_id": payload["nsl_approval_request_id"],
        "write_intent_hash": "sha256:" + "d" * 64,
        "business_preconditions": object(),
        "trace_refs": (
            "trace_id:trace-p8-s57",
            "correlation_id:correlation-p8-s57",
            "causation_id:write-node-p8-s57",
            "evidence:precondition-p8-s57",
        ),
    }
    values.update(changes)
    return WriteCallRequest(**values)  # type: ignore[arg-type]


def _frozen(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_frozen(item) for item in value)
    return value


def _success(
    command: dict[str, Any], *, disposition: str = "CREATED"
) -> dict[str, Any]:
    return {
        "schema_version": "eos_create_voucher_draft_result.v1",
        "tenant_id": command["tenant_id"],
        "business_operation_id": command["business_operation_id"],
        "idempotency_key": command["idempotency_key"],
        "payload_hash": command["payload_hash"],
        "commit_state": "COMMITTED",
        "idempotency_disposition": disposition,
        "voucher_ref": {"type": "eos.voucher_draft", "id": "voucher-p8-s57"},
        "business_transaction_ref": {
            "type": "eos.business_operation",
            "id": command["business_operation_id"],
        },
        "committed_at": "2026-10-22T12:00:00Z",
        "outbox_event_ref": {"type": "eos.outbox_event", "id": "outbox-p8-s57"},
        "reason_code": None,
        "reconciliation_ref": None,
    }


def _execute(port: HttpEosWriteExecutionPort, request: object):
    return asyncio.run(port.execute_raw(request))


def _execute_outcome(port: HttpEosWriteExecutionPort, request: object):
    return asyncio.run(port.execute(request))


def test_command_projection_preserves_nsl_identities_and_canonical_values() -> None:
    request = _request()

    command = build_eos_create_voucher_command(request, public_api=_public_api())

    assert command == {
        **_business_payload(),
        "business_operation_id": request.business_operation_id,
        "idempotency_key": request.idempotency_key,
        "payload_hash": request.payload_hash,
        "trace": {
            "trace_id": "trace-p8-s57",
            "correlation_id": "correlation-p8-s57",
            "causation_id": "write-node-p8-s57",
        },
    }


def test_http_port_sends_protected_command_and_preserves_created_response() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        command = __import__("json").loads(request.content)
        observed.update(
            method=request.method,
            url=str(request.url),
            headers=dict(request.headers),
            command=command,
        )
        return httpx.Response(201, json=_success(command), request=request)

    port = HttpEosWriteExecutionPort(
        public_api=_public_api(),
        base_url="http://eos.test",
        service_token="signed-eos-token",
        transport=httpx.MockTransport(handler),
    )
    request = _request()

    result = _execute(port, request)

    assert result.accepted is True
    assert result.status_code == 201
    assert result.payload["business_operation_id"] == request.business_operation_id
    assert observed["method"] == "POST"
    assert observed["url"] == f"http://eos.test{EOS_CREATE_VOUCHER_PATH}"
    assert observed["headers"]["authorization"] == "Bearer signed-eos-token"
    assert observed["headers"]["x-nex-tenant-id"] == request.tenant_id
    assert observed["headers"]["x-request-id"] == request.invocation_id
    assert observed["headers"]["x-service-id"] == "nex-ae-api"
    assert observed["command"]["idempotency_key"] == request.idempotency_key


@pytest.mark.parametrize(
    ("status", "payload", "accepted"),
    [
        (200, "REPLAYED", True),
        (403, {"error_code": "EOS_AUTHORIZATION_DENIED", "retryable": False}, False),
        (
            503,
            {"error_code": "EOS_AUTHORIZATION_UNAVAILABLE", "retryable": True},
            False,
        ),
    ],
)
def test_port_preserves_replay_and_problem_responses(
    status: int,
    payload: object,
    accepted: bool,
) -> None:
    request = _request()
    command = build_eos_create_voucher_command(request, public_api=_public_api())
    body = (
        _success(command, disposition=payload) if isinstance(payload, str) else payload
    )
    transport = httpx.MockTransport(
        lambda incoming: httpx.Response(status, json=body, request=incoming)
    )

    result = _execute(
        HttpEosWriteExecutionPort(
            _public_api(), "http://eos.test", "token", transport=transport
        ),
        request,
    )

    assert result.status_code == status
    assert result.accepted is accepted
    if not accepted:
        assert result.payload == body


@pytest.mark.parametrize(
    ("status", "disposition"), [(201, "CREATED"), (200, "REPLAYED")]
)
def test_execution_port_maps_committed_eos_result_to_actual_nsl_outcome(
    status: int,
    disposition: str,
) -> None:
    def handler(incoming: httpx.Request) -> httpx.Response:
        command = __import__("json").loads(incoming.content)
        return httpx.Response(
            status,
            json=_success(command, disposition=disposition),
            request=incoming,
        )

    outcome = _execute_outcome(
        HttpEosWriteExecutionPort(
            _public_api(),
            "http://eos.test",
            "token",
            transport=httpx.MockTransport(handler),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        ),
        _request(),
    )

    assert isinstance(outcome, WriteCommitted)
    assert outcome.commit_state is CommitState.COMMITTED
    assert outcome.result.value.value == {"voucher_no": "voucher-p8-s57"}
    assert outcome.result.value.type_info is RESULT_TYPE
    assert outcome.result.value.classification is Classification.CONFIDENTIAL
    assert outcome.result.business_reference == "eos.voucher_draft:voucher-p8-s57"
    assert outcome.result.provider_transaction_id == OPERATION_ID
    assert outcome.result.committed_at.isoformat() == "2026-10-22T12:00:00+00:00"
    assert outcome.result.evidence_refs == (
        f"eos.business_operation:{OPERATION_ID}",
        "eos.outbox_event:outbox-p8-s57",
    )


@pytest.mark.parametrize(
    ("status", "body", "outcome_type", "state", "reason"),
    [
        (
            403,
            {"status": 403, "error_code": "EOS_AUTHORIZATION_DENIED"},
            WriteNotCommitted,
            CommitState.NOT_COMMITTED,
            "EOS_AUTHORIZATION_DENIED",
        ),
        (
            422,
            {"status": 409, "error_code": "EOS_INVALID"},
            WriteNotCommitted,
            CommitState.NOT_COMMITTED,
            "EOS_COMMAND_REJECTED",
        ),
        (
            503,
            {"status": 503, "error_code": "EOS_TRANSACTION_UNAVAILABLE"},
            WriteCommitUnknown,
            CommitState.UNKNOWN_COMMIT_STATE,
            "EOS_TRANSACTION_UNAVAILABLE",
        ),
    ],
)
def test_execution_port_separates_business_rejection_from_commit_uncertainty(
    status: int,
    body: dict[str, object],
    outcome_type: type,
    state: CommitState,
    reason: str,
) -> None:
    transport = httpx.MockTransport(
        lambda incoming: httpx.Response(status, json=body, request=incoming)
    )

    outcome = _execute_outcome(
        HttpEosWriteExecutionPort(
            _public_api(),
            "http://eos.test",
            "token",
            transport=transport,
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        ),
        _request(),
    )

    assert isinstance(outcome, outcome_type)
    assert outcome.commit_state is state
    assert outcome.reason_code == reason
    assert outcome.provider_transaction_id is None
    assert outcome.evidence_refs[-1] == f"eos.http_status:{status}"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (httpx.ReadTimeout("slow"), "PROVIDER_TIMEOUT"),
        (httpx.ConnectError("offline"), "PROVIDER_CONNECTION_LOST"),
        (httpx.UnsupportedProtocol("bad"), "EOS_RESPONSE_UNTRUSTWORTHY"),
    ],
)
def test_execution_port_maps_transport_ambiguity_without_retry(
    failure: Exception,
    reason: str,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise failure

    outcome = _execute_outcome(
        HttpEosWriteExecutionPort(
            _public_api(),
            "http://eos.test",
            "token",
            transport=httpx.MockTransport(handler),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        ),
        _request(),
    )

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.reason_code == reason
    assert outcome.commit_state is CommitState.UNKNOWN_COMMIT_STATE
    assert calls == 1


def test_execution_port_maps_untrustworthy_success_to_unknown() -> None:
    def handler(incoming: httpx.Request) -> httpx.Response:
        command = __import__("json").loads(incoming.content)
        payload = _success(command)
        payload["commit_state"] = "NOT_COMMITTED"
        return httpx.Response(201, json=payload, request=incoming)

    outcome = _execute_outcome(
        HttpEosWriteExecutionPort(
            _public_api(),
            "http://eos.test",
            "token",
            transport=httpx.MockTransport(handler),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        ),
        _request(),
    )

    assert isinstance(outcome, WriteCommitUnknown)
    assert outcome.reason_code == "EOS_RESPONSE_UNTRUSTWORTHY"


def test_execution_port_maps_pre_dispatch_failure_to_not_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "SIGNED_ONLY")
    monkeypatch.delenv("NEX_AE_TO_EOS_SERVICE_TOKEN", raising=False)

    outcome = _execute_outcome(
        HttpEosWriteExecutionPort(
            _public_api(),
            "http://eos.test",
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        ),
        _request(),
    )

    assert isinstance(outcome, WriteNotCommitted)
    assert outcome.reason_code == "EOS_COMMAND_NOT_DISPATCHED"
    assert outcome.evidence_refs == ("eos.reason:EOS_COMMAND_NOT_DISPATCHED",)


def test_outcome_mapper_rejects_non_response_value() -> None:
    with pytest.raises(TypeError, match="EosWriteExecutionResponse"):
        map_eos_write_execution_response(
            object(),  # type: ignore[arg-type]
            _request(),
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        )


@pytest.mark.parametrize(
    ("result_type", "classification"),
    [
        (None, Classification.CONFIDENTIAL),
        (RESULT_TYPE, None),
        (RESULT_TYPE, "CONFIDENTIAL"),
    ],
)
def test_execution_port_requires_canonical_result_contract(
    result_type: object,
    classification: object,
) -> None:
    port = HttpEosWriteExecutionPort(
        _public_api(),
        "http://eos.test",
        "token",
        result_type=result_type,
        result_classification=classification,
    )

    with pytest.raises(ValueError, match="result"):
        _execute_outcome(port, _request())


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.ReadTimeout("slow"), TimeoutError),
        (httpx.ConnectError("offline"), ConnectionError),
        (httpx.UnsupportedProtocol("bad"), EosWriteExecutionError),
    ],
)
def test_port_classifies_transport_failures(failure: Exception, expected: type) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise failure

    port = HttpEosWriteExecutionPort(
        _public_api(),
        "http://eos.test",
        "token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(expected) as caught:
        _execute(port, _request())
    if isinstance(caught.value, EosWriteExecutionError):
        assert caught.value.outcome_uncertain is True
        assert caught.value.retryable is True


@pytest.mark.parametrize(
    ("status", "body", "code", "uncertain"),
    [
        (201, "not-json", "ae.nsl_eos.response_invalid", True),
        (422, "not-json", "ae.nsl_eos.response_invalid", False),
        (201, ["not", "object"], "ae.nsl_eos.response_invalid", True),
        (302, {"redirect": True}, "ae.nsl_eos.response_status_invalid", True),
    ],
)
def test_port_rejects_untrustworthy_http_responses(
    status: int,
    body: object,
    code: str,
    uncertain: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body, request=request)
        return httpx.Response(status, json=body, request=request)

    port = HttpEosWriteExecutionPort(
        _public_api(),
        "http://eos.test",
        "token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(EosWriteExecutionError) as caught:
        _execute(port, _request())
    assert caught.value.error_code == code
    assert caught.value.outcome_uncertain is uncertain
    assert caught.value.status_code == status


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda payload: payload.update(tenant_id="tenant-other"), "response_lineage"),
        (
            lambda payload: payload.update(payload_hash="sha256:" + "f" * 64),
            "response_lineage",
        ),
        (
            lambda payload: payload.update(idempotency_disposition="REPLAYED"),
            "response_disposition",
        ),
        (lambda payload: payload.update(extra=1.5), "response_invalid"),
    ],
)
def test_port_rejects_invalid_success_lineage(
    mutation,
    code: str,
) -> None:
    def handler(incoming: httpx.Request) -> httpx.Response:
        command = __import__("json").loads(incoming.content)
        payload = _success(command)
        mutation(payload)
        return httpx.Response(201, json=payload, request=incoming)

    port = HttpEosWriteExecutionPort(
        _public_api(),
        "http://eos.test",
        "token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(EosWriteExecutionError) as caught:
        _execute(port, _request())
    assert code in caught.value.error_code
    assert caught.value.outcome_uncertain is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(
            business_transaction_ref={
                "type": "eos.business_operation",
                "id": "operation-other",
            }
        ),
        lambda payload: payload.update(voucher_ref={"type": "wrong", "id": "voucher"}),
        lambda payload: payload.update(committed_at=42),
        lambda payload: payload.update(committed_at="not-a-time"),
        lambda payload: payload.update(committed_at="2026-10-22T12:00:00+09:00"),
    ],
)
def test_port_rejects_invalid_success_references_and_commit_time(mutation) -> None:
    def handler(incoming: httpx.Request) -> httpx.Response:
        command = __import__("json").loads(incoming.content)
        payload = _success(command)
        mutation(payload)
        return httpx.Response(201, json=payload, request=incoming)

    port = HttpEosWriteExecutionPort(
        _public_api(),
        "http://eos.test",
        "token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(EosWriteExecutionError) as caught:
        _execute(port, _request())
    assert caught.value.outcome_uncertain is True


def test_committed_mapping_requires_admitted_value_envelope_factory() -> None:
    request = _request()
    arguments = {
        name: EnvelopeWithoutFactory(envelope.value)
        for name, envelope in request.arguments.items()
    }
    request = replace(request, arguments=arguments)
    command = build_eos_create_voucher_command(_request(), public_api=_public_api())
    response = EosWriteExecutionResponse(201, _success(command))

    with pytest.raises(EosWriteExecutionError) as caught:
        map_eos_write_execution_response(
            response,
            request,
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
        )
    assert caught.value.error_code == "ae.nsl_eos.result_envelope_unavailable"


def test_port_fails_closed_when_signed_service_token_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "SIGNED_ONLY")
    monkeypatch.delenv("NEX_AE_TO_EOS_SERVICE_TOKEN", raising=False)
    port = HttpEosWriteExecutionPort(_public_api(), "http://eos.test")

    with pytest.raises(EosWriteExecutionError) as caught:
        _execute(port, _request())
    assert caught.value.error_code == "ae.nsl_eos.service_token_unavailable"
    assert caught.value.outcome_uncertain is False


@pytest.mark.parametrize(
    "candidate",
    [
        object(),
        replace(_request(), tool_id="FINANCE.DELETE_VOUCHER"),
        replace(_request(), arguments=[]),
        replace(_request(), arguments={}),
        _request(payload_changes={"schema_version": "other"}),
        replace(_request(), tenant_id="tenant-other"),
        replace(_request(), approval_request_id="approval-other"),
        replace(_request(), payload_hash="sha256:" + "f" * 64),
        replace(
            _request(),
            arguments={**dict(_request().arguments), "description": object()},
        ),
        replace(_request(), trace_refs=[]),
        replace(_request(), trace_refs=(1,)),
        replace(_request(), trace_refs=("trace_id:",)),
        replace(
            _request(),
            trace_refs=(
                "trace_id:a",
                "trace_id:b",
                "correlation_id:c",
                "causation_id:d",
            ),
        ),
        replace(_request(), trace_refs=("evidence:only",)),
    ],
)
def test_command_projection_rejects_noncanonical_requests(candidate: object) -> None:
    with pytest.raises(EosWriteExecutionError) as caught:
        build_eos_create_voucher_command(candidate, public_api=_public_api())
    assert caught.value.error_code == "ae.nsl_eos.request_invalid"
    assert caught.value.outcome_uncertain is False


@pytest.mark.parametrize(
    "base_url",
    ["", " eos.test", "ftp://eos.test", "http://user:secret@eos.test"],
)
def test_port_rejects_invalid_base_url(base_url: str) -> None:
    with pytest.raises(ValueError):
        HttpEosWriteExecutionPort(_public_api(), base_url)


@pytest.mark.parametrize("timeout", [True, 0, -1, "15"])
def test_port_rejects_invalid_timeout(timeout: object) -> None:
    with pytest.raises(ValueError):
        HttpEosWriteExecutionPort(
            _public_api(),
            timeout_seconds=timeout,  # type: ignore[arg-type]
        )


def test_default_builder_reads_only_eos_boundary_configuration() -> None:
    port = build_default_eos_write_execution_port(
        public_api=_public_api(),
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
        environ={
            "NEX_EOS_BASE_URL": "https://eos.internal",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "token-p8-s57",
            "NEX_AE_EOS_WRITE_TIMEOUT_SECONDS": "22.5",
        },
    )
    assert port.base_url == "https://eos.internal"
    assert port.service_token == "token-p8-s57"
    assert port.timeout_seconds == 22.5

    default = build_default_eos_write_execution_port(
        public_api=_public_api(),
        result_type=RESULT_TYPE,
        result_classification=Classification.CONFIDENTIAL,
        environ={},
    )
    assert default.base_url == DEFAULT_EOS_BASE_URL
    assert default.service_token is None
    assert default.timeout_seconds == 15.0

    with pytest.raises(ValueError):
        build_default_eos_write_execution_port(
            public_api=_public_api(),
            result_type=RESULT_TYPE,
            result_classification=Classification.CONFIDENTIAL,
            environ={"NEX_AE_EOS_WRITE_TIMEOUT_SECONDS": "slow"},
        )
