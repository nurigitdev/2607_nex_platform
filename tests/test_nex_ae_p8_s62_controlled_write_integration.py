from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, ClassVar

import pytest
from nex_ae_api.nsl_controlled_write_integration import (
    NslControlledWriteIntegration,
    NslControlledWriteIntegrationError,
    NslControlledWriteRequest,
)
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter

HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 22, 13, tzinfo=UTC)
EVENTS: list[str] = []


@dataclass(frozen=True)
class ProviderEvidence:
    value: str = "provider"


@dataclass(frozen=True)
class GuardRequest:
    intent: Any
    context: Any
    contract_evidence: Any
    execution_evidence: Any
    policy_decision: Any
    business_preconditions: Any

    def __post_init__(self) -> None:
        EVENTS.append("guard_request")


@dataclass(frozen=True)
class Decision:
    allowed: bool = True


class Guard:
    def evaluate(self, request: GuardRequest, *, now: datetime) -> Decision:
        EVENTS.append("guard")
        assert isinstance(request, GuardRequest)
        assert now == NOW
        return Decision()


@dataclass(frozen=True)
class Reservation:
    value: str = "reserved"


class IdempotencyCoordinator:
    def __init__(self, port: Any) -> None:
        self.port = port

    async def reserve(self, **values: Any) -> Reservation:
        EVENTS.append("idempotency")
        assert values["now"] == NOW
        assert values["required_until"] == NOW + timedelta(days=7)
        return await self.port.reserve(values)


@dataclass(frozen=True)
class WriteRequest:
    invocation_id: str


class WriteCallRequestBuilder:
    def build(self, **values: Any) -> WriteRequest:
        EVENTS.append("write_request")
        assert values["reservation"] == Reservation()
        assert values["trace_refs"] == (
            "trace_id:trace-p8-s62",
            "correlation_id:correlation-p8-s62",
            "causation_id:causation-p8-s62",
        )
        return WriteRequest(values["invocation_id"])


@dataclass(frozen=True)
class WriteCommitted:
    result: object


@dataclass(frozen=True)
class WriteNotCommitted:
    reason: str = "denied"


@dataclass(frozen=True)
class WriteCommitUnknown:
    reason: str = "unknown"


class WriteExecutionCoordinator:
    def __init__(self, write_port: Any, evidence_port: Any) -> None:
        self.write_port = write_port
        self.evidence_port = evidence_port

    async def execute(self, **values: Any) -> object:
        EVENTS.append("write_coordinator")
        await self.evidence_port.record_requested(values["request"])
        return await self.write_port.execute(values["request"])


@dataclass(frozen=True)
class VerificationResult:
    status: str = "VERIFIED"


class PostWriteVerifier:
    result: ClassVar[object] = VerificationResult()

    async def verify(self, result: object, *_args: Any) -> object:
        EVENTS.append("verification")
        assert result == "committed-result"
        return type(self).result


class Intent:
    def require_approval_identity(self, evidence: object) -> None:
        EVENTS.append("approval")
        assert evidence == "approval-evidence"


class Source:
    def authorize_write(self, request: object) -> object:
        EVENTS.append("policy")
        assert request == "policy-request"
        return "policy-decision"

    async def reserve(self, _values: object) -> Reservation:
        return Reservation()

    async def record_requested(self, request: object) -> None:
        EVENTS.append("write_evidence")
        assert isinstance(request, WriteRequest)

    async def execute(self, _request: object) -> object:
        EVENTS.append("write")
        return self.value

    async def read(self, _request: object) -> object:
        return object()

    def __init__(self, value: object | None = None) -> None:
        self.value = value


def policy_request_factory(*values: object) -> str:
    EVENTS.append("policy_request")
    assert len(values) == 3
    return "policy-request"


def _public_api() -> NslV02PublicApiAdapter:
    symbols: list[object] = [object] * 30
    symbols[7] = IdempotencyCoordinator
    symbols[19] = WriteCommitted
    symbols[20] = WriteNotCommitted
    symbols[21] = WriteCommitUnknown
    return NslV02PublicApiAdapter(
        *symbols,
        HASH,
        HASH,
        ProviderEvidence,
        Guard,
        GuardRequest,
        policy_request_factory,
        WriteCallRequestBuilder,
        WriteExecutionCoordinator,
        PostWriteVerifier,
        VerificationResult,
    )


def _request(**changes: object) -> NslControlledWriteRequest:
    values: dict[str, object] = {
        "intent": Intent(),
        "context": object(),
        "contract": object(),
        "contract_evidence": object(),
        "execution_evidence": object(),
        "business_preconditions": object(),
        "approval_evidence": "approval-evidence",
        "approval_request_id": "approval-request-p8-s62",
        "provider_idempotency_evidence": ProviderEvidence(),
        "invocation_id": "invocation-p8-s62",
        "trace_refs": (
            "trace_id:trace-p8-s62",
            "correlation_id:correlation-p8-s62",
            "causation_id:causation-p8-s62",
        ),
        "evaluated_at": NOW,
        "required_until": NOW + timedelta(days=7),
        "requested_at": NOW,
    }
    values.update(changes)
    return NslControlledWriteRequest(**values)  # type: ignore[arg-type]


def _integration(outcome: object) -> NslControlledWriteIntegration:
    return NslControlledWriteIntegration(
        public_api=_public_api(),
        policy_port=Source(),
        idempotency_port=Source(),
        write_evidence_port=Source(),
        write_port=Source(outcome),
        verification_port=Source(),
    )


def test_committed_write_runs_canonical_sequence_and_verifies() -> None:
    EVENTS.clear()
    result = asyncio.run(
        _integration(WriteCommitted("committed-result")).execute(_request())
    )

    assert isinstance(result.outcome, WriteCommitted)
    assert result.verification == VerificationResult()
    assert result.reservation == Reservation()
    assert result.write_request == WriteRequest("invocation-p8-s62")
    assert EVENTS == [
        "approval",
        "policy_request",
        "policy",
        "guard_request",
        "guard",
        "idempotency",
        "write_request",
        "write_coordinator",
        "write_evidence",
        "write",
        "verification",
    ]


@pytest.mark.parametrize("outcome", [WriteNotCommitted(), WriteCommitUnknown()])
def test_noncommitted_outcome_skips_post_write_verification(outcome: object) -> None:
    EVENTS.clear()

    result = asyncio.run(_integration(outcome).execute(_request()))

    assert result.outcome is outcome
    assert result.verification is None
    assert "verification" not in EVENTS


def test_invalid_write_or_verification_result_fails_closed() -> None:
    with pytest.raises(NslControlledWriteIntegrationError, match="invalid outcome"):
        asyncio.run(_integration(object()).execute(_request()))

    PostWriteVerifier.result = object()
    try:
        with pytest.raises(
            NslControlledWriteIntegrationError,
            match="verification result",
        ):
            asyncio.run(
                _integration(WriteCommitted("committed-result")).execute(_request())
            )
    finally:
        PostWriteVerifier.result = VerificationResult()


def test_execute_rejects_invalid_request_or_intent_boundary() -> None:
    integration = _integration(WriteNotCommitted())
    with pytest.raises(NslControlledWriteIntegrationError, match="request"):
        asyncio.run(integration.execute(object()))  # type: ignore[arg-type]
    with pytest.raises(NslControlledWriteIntegrationError, match="approval binding"):
        asyncio.run(integration.execute(_request(intent=object())))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"invocation_id": ""}, "invocation_id"),
        ({"invocation_id": "x" * 257}, "invocation_id"),
        ({"trace_refs": ()}, "trace_refs"),
        ({"trace_refs": ("",)}, "trace_refs"),
        ({"trace_refs": ["trace"]}, "trace_refs"),
        ({"evaluated_at": NOW.replace(tzinfo=None)}, "evaluated_at"),
        (
            {"evaluated_at": NOW.astimezone(timezone(timedelta(hours=9)))},
            "evaluated_at",
        ),
        ({"required_until": NOW}, "required_until"),
        ({"requested_at": NOW - timedelta(seconds=1)}, "requested_at"),
    ],
)
def test_request_rejects_invalid_transport_and_time_boundary(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(NslControlledWriteIntegrationError, match=message):
        _request(**changes)


def test_error_string_is_sanitized_detail() -> None:
    error = NslControlledWriteIntegrationError("code", "safe detail")

    assert str(error) == "safe detail"


def test_constructor_requires_admitted_runtime_symbols_and_ports() -> None:
    kwargs = {
        "public_api": _public_api(),
        "policy_port": Source(),
        "idempotency_port": Source(),
        "write_evidence_port": Source(),
        "write_port": Source(),
        "verification_port": Source(),
    }
    with pytest.raises(NslControlledWriteIntegrationError, match="public API"):
        NslControlledWriteIntegration(**{**kwargs, "public_api": object()})

    for name in (
        "idempotency_coordinator",
        "provider_idempotency_evidence",
        "write_guard",
        "write_guard_request",
        "write_policy_request_factory",
        "write_call_request_builder",
        "write_execution_coordinator",
        "post_write_verifier",
        "verification_result",
    ):
        api = _public_api()
        object.__setattr__(api, name, None)
        with pytest.raises(NslControlledWriteIntegrationError, match=name):
            NslControlledWriteIntegration(**{**kwargs, "public_api": api})

    for port_name, label in (
        ("policy_port", "runtime policy"),
        ("idempotency_port", "idempotency evidence"),
        ("write_evidence_port", "WRITE_REQUESTED evidence"),
        ("write_port", "WRITE execution"),
        ("verification_port", "post-WRITE verification"),
    ):
        with pytest.raises(NslControlledWriteIntegrationError, match=label):
            NslControlledWriteIntegration(**{**kwargs, port_name: object()})
