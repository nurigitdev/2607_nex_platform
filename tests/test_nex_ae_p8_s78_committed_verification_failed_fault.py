from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from p8_reliability_faults import (
    EosVerificationMismatchFaultError,
    EosVerificationMismatchFaultPort,
)

HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 24, 5, tzinfo=UTC)


@dataclass(frozen=True)
class _Request:
    request_hash: str = HASH
    business_reference: str = "eos.voucher_draft:voucher-p8-s78"


@dataclass(frozen=True)
class _Observation:
    request_hash: str
    business_reference: str
    matched: bool
    evidence_ref: str
    observed_at: datetime
    reason_code: str | None = None


class _Delegate:
    def __init__(self, observation: object) -> None:
        self.observation = observation
        self.calls = 0

    async def read(self, request: object) -> object:
        self.calls += 1
        assert isinstance(request, _Request)
        return self.observation


class _PublicApi:
    @staticmethod
    def verification_observation(**values: object) -> _Observation:
        return _Observation(**values)  # type: ignore[arg-type]


def _healthy() -> _Observation:
    return _Observation(
        request_hash=HASH,
        business_reference="eos.voucher_draft:voucher-p8-s78",
        matched=True,
        evidence_ref="eos:voucher-p8-s78",
        observed_at=NOW,
    )


def test_fault_converts_one_exact_healthy_read_into_deterministic_mismatch() -> None:
    delegate = _Delegate(_healthy())
    port = EosVerificationMismatchFaultPort(delegate, _PublicApi())

    result = asyncio.run(port.read(_Request()))

    assert result == _Observation(
        request_hash=HASH,
        business_reference="eos.voucher_draft:voucher-p8-s78",
        matched=False,
        evidence_ref=(
            "fault-injection:eos-post-write-verification-mismatch:" + HASH
        ),
        observed_at=NOW,
        reason_code="EOS_VOUCHER_VERIFICATION_DETERMINISTIC_MISMATCH",
    )
    assert delegate.calls == 1
    assert port.read_attempts == 1
    assert port.evidence.read_attempts == 1
    assert port.evidence.baseline_matched is True
    assert port.evidence.injected_matched is False
    assert (
        port.evidence.reason_code
        == "EOS_VOUCHER_VERIFICATION_DETERMINISTIC_MISMATCH"
    )


def test_fault_is_one_shot_and_does_not_repeat_the_authoritative_read() -> None:
    delegate = _Delegate(_healthy())
    port = EosVerificationMismatchFaultPort(delegate, _PublicApi())

    asyncio.run(port.read(_Request()))
    with pytest.raises(EosVerificationMismatchFaultError, match="one-shot"):
        asyncio.run(port.read(_Request()))

    assert delegate.calls == 1


@pytest.mark.parametrize(
    "observation",
    [
        _Observation(
            HASH,
            "eos.voucher_draft:voucher-p8-s78",
            False,
            "eos:failed",
            NOW,
            "ALREADY_FAILED",
        ),
        _Observation(
            "sha256:" + "b" * 64,
            "eos.voucher_draft:voucher-p8-s78",
            True,
            "eos:wrong-hash",
            NOW,
        ),
        _Observation(
            HASH,
            "eos.voucher_draft:other",
            True,
            "eos:wrong-reference",
            NOW,
        ),
        SimpleNamespace(
            request_hash=HASH,
            business_reference="eos.voucher_draft:voucher-p8-s78",
            matched=True,
            observed_at=None,
        ),
    ],
)
def test_fault_rejects_nonhealthy_or_unbound_baseline(observation: object) -> None:
    port = EosVerificationMismatchFaultPort(_Delegate(observation), _PublicApi())

    with pytest.raises(EosVerificationMismatchFaultError, match="healthy baseline"):
        asyncio.run(port.read(_Request()))
    with pytest.raises(EosVerificationMismatchFaultError, match="evidence"):
        _ = port.evidence


def test_fault_rejects_invalid_dependencies_and_invalid_injected_result() -> None:
    with pytest.raises(TypeError, match=r"read\(\)"):
        EosVerificationMismatchFaultPort(object(), _PublicApi())
    with pytest.raises(TypeError, match=r"verification_observation\(\)"):
        EosVerificationMismatchFaultPort(_Delegate(_healthy()), object())

    public_api = _PublicApi()
    public_api.verification_observation = lambda **_values: SimpleNamespace(
        matched=True
    )
    port = EosVerificationMismatchFaultPort(_Delegate(_healthy()), public_api)
    with pytest.raises(EosVerificationMismatchFaultError, match="did not produce"):
        asyncio.run(port.read(_Request()))
