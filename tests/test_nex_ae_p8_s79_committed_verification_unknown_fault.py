from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from p8_reliability_faults import (
    EosVerificationTimeoutFaultError,
    EosVerificationTimeoutFaultPort,
)

HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 24, 6, tzinfo=UTC)


@dataclass(frozen=True)
class _Request:
    request_hash: str = HASH
    business_reference: str = "eos.voucher_draft:voucher-p8-s79"


@dataclass(frozen=True)
class _Observation:
    request_hash: str
    business_reference: str
    matched: bool
    observed_at: datetime | None


class _Delegate:
    def __init__(self, observation: object) -> None:
        self.observation = observation
        self.calls = 0

    async def read(self, request: object) -> object:
        self.calls += 1
        assert isinstance(request, _Request)
        return self.observation


def _healthy() -> _Observation:
    return _Observation(
        request_hash=HASH,
        business_reference="eos.voucher_draft:voucher-p8-s79",
        matched=True,
        observed_at=NOW,
    )


def test_fault_discards_one_exact_healthy_read_as_timeout() -> None:
    delegate = _Delegate(_healthy())
    port = EosVerificationTimeoutFaultPort(delegate)

    with pytest.raises(TimeoutError, match="deliberately discarded"):
        asyncio.run(port.read(_Request()))

    assert delegate.calls == 1
    assert port.read_attempts == 1
    assert port.evidence.read_attempts == 1
    assert port.evidence.baseline_matched is True
    assert port.evidence.injected_exception == "TimeoutError"
    assert port.evidence.expected_reason_code == "VERIFICATION_TIMEOUT"


def test_fault_is_one_shot_and_does_not_repeat_the_authoritative_read() -> None:
    delegate = _Delegate(_healthy())
    port = EosVerificationTimeoutFaultPort(delegate)

    with pytest.raises(TimeoutError):
        asyncio.run(port.read(_Request()))
    with pytest.raises(EosVerificationTimeoutFaultError, match="one-shot"):
        asyncio.run(port.read(_Request()))

    assert delegate.calls == 1


@pytest.mark.parametrize(
    "observation",
    [
        _Observation(
            HASH,
            "eos.voucher_draft:voucher-p8-s79",
            False,
            NOW,
        ),
        _Observation(
            "sha256:" + "b" * 64,
            "eos.voucher_draft:voucher-p8-s79",
            True,
            NOW,
        ),
        _Observation(HASH, "eos.voucher_draft:other", True, NOW),
        SimpleNamespace(
            request_hash=HASH,
            business_reference="eos.voucher_draft:voucher-p8-s79",
            matched=True,
            observed_at=None,
        ),
    ],
)
def test_fault_rejects_nonhealthy_or_unbound_baseline(observation: object) -> None:
    port = EosVerificationTimeoutFaultPort(_Delegate(observation))

    with pytest.raises(EosVerificationTimeoutFaultError, match="healthy baseline"):
        asyncio.run(port.read(_Request()))
    with pytest.raises(EosVerificationTimeoutFaultError, match="evidence"):
        _ = port.evidence


def test_fault_rejects_invalid_delegate() -> None:
    with pytest.raises(TypeError, match=r"read\(\)"):
        EosVerificationTimeoutFaultPort(object())
