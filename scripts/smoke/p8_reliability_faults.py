from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


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


class EosVerificationTimeoutFaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class EosVerificationTimeoutFaultEvidence:
    read_attempts: int
    baseline_matched: bool
    injected_exception: str
    expected_reason_code: str


class EosVerificationTimeoutFaultPort:
    """Discard one healthy EOS verification response as a timeout."""

    EXPECTED_REASON_CODE = "VERIFICATION_TIMEOUT"

    def __init__(self, delegate: Any) -> None:
        if not callable(getattr(delegate, "read", None)):
            raise TypeError("EOS verification timeout delegate must expose read().")
        self._delegate = delegate
        self._read_attempts = 0
        self._baseline_matched: bool | None = None
        self._injected_exception: str | None = None

    @property
    def read_attempts(self) -> int:
        return self._read_attempts

    @property
    def evidence(self) -> EosVerificationTimeoutFaultEvidence:
        if self._baseline_matched is None or self._injected_exception is None:
            raise EosVerificationTimeoutFaultError(
                "EOS verification timeout evidence is unavailable before injection."
            )
        return EosVerificationTimeoutFaultEvidence(
            read_attempts=self._read_attempts,
            baseline_matched=self._baseline_matched,
            injected_exception=self._injected_exception,
            expected_reason_code=self.EXPECTED_REASON_CODE,
        )

    async def read(self, request: object) -> object:
        if self._read_attempts != 0:
            raise EosVerificationTimeoutFaultError(
                "EOS verification timeout fault port is one-shot."
            )
        self._read_attempts = 1
        baseline = await self._delegate.read(request)
        if (
            getattr(baseline, "matched", None) is not True
            or getattr(baseline, "request_hash", None)
            != getattr(request, "request_hash", None)
            or getattr(baseline, "business_reference", None)
            != getattr(request, "business_reference", None)
            or getattr(baseline, "observed_at", None) is None
        ):
            raise EosVerificationTimeoutFaultError(
                "EOS verification timeout injection requires an exact healthy "
                "baseline observation."
            )
        self._baseline_matched = True
        self._injected_exception = "TimeoutError"
        raise TimeoutError(
            "EOS post-WRITE verification response was deliberately discarded."
        )


class EosOutboxAckLossFaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class EosOutboxAckLossFaultEvidence:
    publication_attempts: int
    downstream_acceptances: int
    acknowledged_attempts: int
    unique_event_count: int


class EosOutboxAckLossFaultTransport:
    """Lose the first downstream ACK after semantic event acceptance."""

    def __init__(self, delegate: Any) -> None:
        if not callable(getattr(delegate, "publish", None)):
            raise TypeError("EOS outbox ACK-loss delegate must expose publish().")
        self._delegate = delegate
        self._publication_attempts = 0
        self._downstream_acceptances = 0
        self._acknowledged_attempts = 0
        self._event_ids: set[str] = set()

    @property
    def evidence(self) -> EosOutboxAckLossFaultEvidence:
        return EosOutboxAckLossFaultEvidence(
            publication_attempts=self._publication_attempts,
            downstream_acceptances=self._downstream_acceptances,
            acknowledged_attempts=self._acknowledged_attempts,
            unique_event_count=len(self._event_ids),
        )

    def publish(self, event: object) -> object:
        self._publication_attempts += 1
        receipt = self._delegate.publish(event)
        self._downstream_acceptances += 1
        event_id = getattr(event, "event_id", None)
        if not isinstance(event_id, str):
            raise EosOutboxAckLossFaultError(
                "EOS outbox ACK-loss event identity is unavailable."
            )
        self._event_ids.add(event_id)
        if self._publication_attempts == 1:
            raise TimeoutError(
                "EOS outbox publication was accepted but its ACK was discarded."
            )
        self._acknowledged_attempts += 1
        return receipt


class ApprovalEventAckLossFaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApprovalEventAckLossFaultEvidence:
    delivery_attempts: int
    downstream_acceptances: int
    acknowledged_attempts: int
    unique_event_count: int
    unique_resume_job_count: int
    approval_binding_hash: str | None


class ApprovalEventAckLossFaultClient:
    """Lose one ACK after AE durably admits an exact approval event."""

    _BINDING_FIELDS = (
        "tenant_id",
        "approval_request_id",
        "approval_work_item_ref",
        "approval_evidence_ref",
        "evidence_integrity",
        "nsl_execution_id",
        "business_operation_id",
        "decision",
    )

    def __init__(self, delegate: Any) -> None:
        if not callable(getattr(delegate, "deliver", None)):
            raise TypeError("Approval event ACK-loss delegate must expose deliver().")
        self._delegate = delegate
        self._delivery_attempts = 0
        self._downstream_acceptances = 0
        self._acknowledged_attempts = 0
        self._event_ids: set[str] = set()
        self._resume_job_ids: set[str] = set()
        self._event_hash: str | None = None
        self._binding_hash: str | None = None

    @property
    def evidence(self) -> ApprovalEventAckLossFaultEvidence:
        return ApprovalEventAckLossFaultEvidence(
            delivery_attempts=self._delivery_attempts,
            downstream_acceptances=self._downstream_acceptances,
            acknowledged_attempts=self._acknowledged_attempts,
            unique_event_count=len(self._event_ids),
            unique_resume_job_count=len(self._resume_job_ids),
            approval_binding_hash=self._binding_hash,
        )

    def deliver(self, event: object) -> object:
        self._delivery_attempts += 1
        normalized, event_hash, binding_hash = self._event_identity(event)
        if self._event_hash is not None and (
            event_hash != self._event_hash or binding_hash != self._binding_hash
        ):
            raise ApprovalEventAckLossFaultError(
                "Approval event retry changed its semantic or approval binding."
            )
        response = self._delegate.deliver(normalized)
        event_id, resume_job_id = self._accepted_response(response, normalized)
        self._downstream_acceptances += 1
        self._event_ids.add(event_id)
        self._resume_job_ids.add(resume_job_id)
        if self._event_hash is None:
            self._event_hash = event_hash
            self._binding_hash = binding_hash
            raise TimeoutError(
                "AE accepted the approval event but its acknowledgement was discarded."
            )
        self._acknowledged_attempts += 1
        return response

    @classmethod
    def _event_identity(cls, event: object) -> tuple[dict[str, Any], str, str]:
        if not isinstance(event, Mapping):
            raise ApprovalEventAckLossFaultError(
                "Approval event ACK-loss input must be an object."
            )
        normalized = dict(event)
        required = ("event_id", *cls._BINDING_FIELDS)
        if any(
            not isinstance(normalized.get(field), str)
            or not str(normalized[field]).strip()
            for field in required
        ):
            raise ApprovalEventAckLossFaultError(
                "Approval event ACK-loss identity is incomplete."
            )
        binding = {field: normalized[field] for field in cls._BINDING_FIELDS}
        return (
            normalized,
            semantic_sha256_hash_ref(normalized),
            semantic_sha256_hash_ref(binding),
        )

    @staticmethod
    def _accepted_response(
        response: object, event: Mapping[str, Any]
    ) -> tuple[str, str]:
        if not isinstance(response, Mapping):
            raise ApprovalEventAckLossFaultError(
                "AE approval event acknowledgement is not an object."
            )
        event_id = response.get("event_id")
        resume_job_id = response.get("resume_runtime_job_id")
        if (
            event_id != event["event_id"]
            or response.get("inbox_state") != "MATCHED"
            or response.get("wait_state") != "RESUME_QUEUED"
            or not isinstance(resume_job_id, str)
            or not resume_job_id.strip()
        ):
            raise ApprovalEventAckLossFaultError(
                "AE approval event acknowledgement is not durably matched."
            )
        return str(event_id), resume_job_id.strip()
