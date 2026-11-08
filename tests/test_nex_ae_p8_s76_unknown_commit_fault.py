from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from p8_reliability_faults import (
    EosCommitAckLossFaultError,
    EosCommitAckLossFaultPort,
)


@dataclass(frozen=True)
class _Response:
    status_code: int
    accepted: bool


class _Delegate:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls = 0

    async def execute_raw(self, request: object) -> _Response:
        self.calls += 1
        assert request == "write-request"
        return self.response


class _Identity:
    @staticmethod
    def from_request(request: object) -> str:
        assert request == "write-request"
        return "outcome-identity"


class _PublicApi:
    write_outcome_identity = _Identity

    @staticmethod
    def write_commit_unknown(**values: object) -> SimpleNamespace:
        assert values == {
            "identity": "outcome-identity",
            "reason_code": "EOS_COMMIT_ACKNOWLEDGEMENT_LOST",
            "message": (
                "EOS committed the command but the response was deliberately "
                "discarded; reconciliation is required."
            ),
            "evidence_refs": ("fault-injection:eos-ack-loss-after-commit",),
        }
        return SimpleNamespace(
            commit_state=SimpleNamespace(value="UNKNOWN_COMMIT_STATE")
        )


def test_ack_loss_discards_one_accepted_response_and_requires_reconciliation() -> None:
    delegate = _Delegate(_Response(status_code=201, accepted=True))
    port = EosCommitAckLossFaultPort(delegate, _PublicApi())

    outcome = asyncio.run(port.execute("write-request"))

    assert outcome.commit_state.value == "UNKNOWN_COMMIT_STATE"
    assert delegate.calls == 1
    assert port.response_status == 201
    assert port.evidence.dispatch_attempts == 1
    assert port.evidence.response_status_discarded == 201
    assert port.evidence.observed_commit_state == "UNKNOWN_COMMIT_STATE"
    assert port.evidence.reconciliation_status == "RECONCILIATION_REQUIRED"


def test_ack_loss_is_one_shot_and_never_blindly_redispatches() -> None:
    delegate = _Delegate(_Response(status_code=200, accepted=True))
    port = EosCommitAckLossFaultPort(delegate, _PublicApi())

    asyncio.run(port.execute("write-request"))
    with pytest.raises(EosCommitAckLossFaultError, match="blind redispatch"):
        asyncio.run(port.execute("write-request"))

    assert port.dispatch_attempts == 1
    assert delegate.calls == 1


@pytest.mark.parametrize(
    "response",
    [
        _Response(status_code=409, accepted=False),
        _Response(status_code=202, accepted=True),
    ],
)
def test_ack_loss_rejects_noncommitted_or_invalid_response(response: _Response) -> None:
    port = EosCommitAckLossFaultPort(_Delegate(response), _PublicApi())

    with pytest.raises(EosCommitAckLossFaultError):
        asyncio.run(port.execute("write-request"))
    with pytest.raises(EosCommitAckLossFaultError, match="evidence"):
        _ = port.evidence


def test_ack_loss_rejects_invalid_dependencies_and_outcome() -> None:
    with pytest.raises(TypeError, match="execute_raw"):
        EosCommitAckLossFaultPort(object(), _PublicApi())
    with pytest.raises(TypeError, match="write_commit_unknown"):
        EosCommitAckLossFaultPort(_Delegate(_Response(201, True)), object())
    with pytest.raises(TypeError, match="identity projection"):
        EosCommitAckLossFaultPort(
            _Delegate(_Response(201, True)),
            SimpleNamespace(write_commit_unknown=lambda **_values: object()),
        )

    api = _PublicApi()
    api.write_commit_unknown = lambda **_values: SimpleNamespace(
        commit_state=SimpleNamespace(value="COMMITTED")
    )
    port = EosCommitAckLossFaultPort(_Delegate(_Response(201, True)), api)
    with pytest.raises(EosCommitAckLossFaultError, match="UNKNOWN_COMMIT_STATE"):
        asyncio.run(port.execute("write-request"))
