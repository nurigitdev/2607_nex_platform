from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class EosCommitAckLossFaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class EosCommitAckLossFaultEvidence:
    dispatch_attempts: int
    response_status_discarded: int
    observed_commit_state: str
    reconciliation_status: str


class EosCommitAckLossFaultPort:
    """Discard one accepted EOS response without redispatching the command."""

    def __init__(self, delegate: Any, public_api: Any) -> None:
        if not callable(getattr(delegate, "execute_raw", None)):
            raise TypeError("EOS ACK-loss delegate must expose execute_raw().")
        if not callable(getattr(public_api, "write_commit_unknown", None)):
            raise TypeError(
                "EOS ACK-loss public API must expose write_commit_unknown()."
            )
        identity = getattr(public_api, "write_outcome_identity", None)
        if not callable(getattr(identity, "from_request", None)):
            raise TypeError(
                "EOS ACK-loss public API must expose outcome identity projection."
            )
        self._delegate = delegate
        self._public_api = public_api
        self._dispatch_attempts = 0
        self._response_status_discarded: int | None = None
        self._observed_commit_state: str | None = None

    @property
    def dispatch_attempts(self) -> int:
        return self._dispatch_attempts

    @property
    def response_status(self) -> int | None:
        return self._response_status_discarded

    @property
    def evidence(self) -> EosCommitAckLossFaultEvidence:
        if (
            self._response_status_discarded is None
            or self._observed_commit_state is None
        ):
            raise EosCommitAckLossFaultError(
                "EOS ACK-loss evidence is unavailable before successful injection."
            )
        return EosCommitAckLossFaultEvidence(
            dispatch_attempts=self._dispatch_attempts,
            response_status_discarded=self._response_status_discarded,
            observed_commit_state=self._observed_commit_state,
            reconciliation_status="RECONCILIATION_REQUIRED",
        )

    async def execute(self, request: object) -> object:
        if self._dispatch_attempts != 0:
            raise EosCommitAckLossFaultError(
                "EOS ACK-loss fault port is one-shot; blind redispatch is forbidden."
            )
        self._dispatch_attempts = 1
        response = await self._delegate.execute_raw(request)
        if not getattr(response, "accepted", False):
            raise EosCommitAckLossFaultError(
                "EOS ACK-loss injection requires a committed response."
            )
        status_code = getattr(response, "status_code", None)
        if status_code not in {200, 201}:
            raise EosCommitAckLossFaultError(
                "EOS ACK-loss injection received an invalid accepted status."
            )
        self._response_status_discarded = status_code
        outcome = self._public_api.write_commit_unknown(
            identity=self._public_api.write_outcome_identity.from_request(request),
            reason_code="EOS_COMMIT_ACKNOWLEDGEMENT_LOST",
            message=(
                "EOS committed the command but the response was deliberately "
                "discarded; reconciliation is required."
            ),
            evidence_refs=("fault-injection:eos-ack-loss-after-commit",),
        )
        commit_state = getattr(getattr(outcome, "commit_state", None), "value", None)
        if commit_state != "UNKNOWN_COMMIT_STATE":
            raise EosCommitAckLossFaultError(
                "EOS ACK-loss injection did not produce UNKNOWN_COMMIT_STATE."
            )
        self._observed_commit_state = commit_state
        return outcome


class EosVerificationMismatchFaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class EosVerificationMismatchFaultEvidence:
    read_attempts: int
    baseline_matched: bool
    injected_matched: bool
    reason_code: str


class EosVerificationMismatchFaultPort:
    """Turn one healthy EOS read-back into a bound deterministic mismatch."""

    REASON_CODE = "EOS_VOUCHER_VERIFICATION_DETERMINISTIC_MISMATCH"

    def __init__(self, delegate: Any, public_api: Any) -> None:
        if not callable(getattr(delegate, "read", None)):
            raise TypeError("EOS verification mismatch delegate must expose read().")
        if not callable(getattr(public_api, "verification_observation", None)):
            raise TypeError(
                "EOS verification mismatch public API must expose "
                "verification_observation()."
            )
        self._delegate = delegate
        self._public_api = public_api
        self._read_attempts = 0
        self._baseline_matched: bool | None = None
        self._injected_matched: bool | None = None

    @property
    def read_attempts(self) -> int:
        return self._read_attempts

    @property
    def evidence(self) -> EosVerificationMismatchFaultEvidence:
        if self._baseline_matched is None or self._injected_matched is None:
            raise EosVerificationMismatchFaultError(
                "EOS verification mismatch evidence is unavailable before injection."
            )
        return EosVerificationMismatchFaultEvidence(
            read_attempts=self._read_attempts,
            baseline_matched=self._baseline_matched,
            injected_matched=self._injected_matched,
            reason_code=self.REASON_CODE,
        )

    async def read(self, request: object) -> object:
        if self._read_attempts != 0:
            raise EosVerificationMismatchFaultError(
                "EOS verification mismatch fault port is one-shot."
            )
        self._read_attempts = 1
        baseline = await self._delegate.read(request)
        request_hash = getattr(request, "request_hash", None)
        business_reference = getattr(request, "business_reference", None)
        if (
            getattr(baseline, "matched", None) is not True
            or getattr(baseline, "request_hash", None) != request_hash
            or getattr(baseline, "business_reference", None) != business_reference
            or getattr(baseline, "observed_at", None) is None
        ):
            raise EosVerificationMismatchFaultError(
                "EOS verification mismatch injection requires an exact healthy "
                "baseline observation."
            )
        self._baseline_matched = True
        injected = self._public_api.verification_observation(
            request_hash=request_hash,
            business_reference=business_reference,
            matched=False,
            reason_code=self.REASON_CODE,
            evidence_ref=(
                "fault-injection:eos-post-write-verification-mismatch:"
                f"{request_hash}"
            ),
            observed_at=baseline.observed_at,
        )
        if getattr(injected, "matched", None) is not False:
            raise EosVerificationMismatchFaultError(
                "EOS verification mismatch injection did not produce a mismatch."
            )
        self._injected_matched = False
        return injected
