from __future__ import annotations

from collections.abc import Callable, Mapping
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


class WorkerCrashAfterCheckpointFaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerCrashAfterCheckpointFaultEvidence:
    publication_attempts: int
    injected_crashes: int
    restart_attempts: int
    downstream_publications: int
    checkpoint_hash: str | None
    checkpoint_integrity_hash: str | None
    checkpoint_version: int | None
    approval_request_hash: str | None
    approval_request_id: str | None
    payload_hash: str | None
    protected_payload_ref: str | None


class WorkerCrashAfterCheckpointFaultPort:
    """Crash once after a durable checkpoint and publish on exact restart."""

    def __init__(self, delegate: Any, checkpoint_loader: Callable[[], object]) -> None:
        if not callable(getattr(delegate, "publish", None)):
            raise TypeError("Worker-crash approval delegate must expose publish().")
        if not callable(checkpoint_loader):
            raise TypeError("Worker-crash checkpoint loader must be callable.")
        self._delegate = delegate
        self._checkpoint_loader = checkpoint_loader
        self._publication_attempts = 0
        self._injected_crashes = 0
        self._restart_attempts = 0
        self._downstream_publications = 0
        self._checkpoint_hash: str | None = None
        self._checkpoint_integrity_hash: str | None = None
        self._checkpoint_version: int | None = None
        self._approval_request_hash: str | None = None
        self._approval_request_id: str | None = None
        self._payload_hash: str | None = None
        self._protected_payload_ref: str | None = None

    @property
    def evidence(self) -> WorkerCrashAfterCheckpointFaultEvidence:
        return WorkerCrashAfterCheckpointFaultEvidence(
            publication_attempts=self._publication_attempts,
            injected_crashes=self._injected_crashes,
            restart_attempts=self._restart_attempts,
            downstream_publications=self._downstream_publications,
            checkpoint_hash=self._checkpoint_hash,
            checkpoint_integrity_hash=self._checkpoint_integrity_hash,
            checkpoint_version=self._checkpoint_version,
            approval_request_hash=self._approval_request_hash,
            approval_request_id=self._approval_request_id,
            payload_hash=self._payload_hash,
            protected_payload_ref=self._protected_payload_ref,
        )

    async def publish(self, request: object) -> object:
        self._publication_attempts += 1
        checkpoint = self._checkpoint()
        approval_request = self._approval_request(request)
        self._require_lineage(checkpoint, approval_request)
        checkpoint_hash = semantic_sha256_hash_ref(checkpoint)
        request_hash = semantic_sha256_hash_ref(approval_request)

        if self._checkpoint_hash is None:
            self._remember(checkpoint, approval_request, checkpoint_hash, request_hash)
            self._injected_crashes = 1
            raise WorkerCrashAfterCheckpointFaultError(
                "Worker crashed after durable checkpoint persistence."
            )
        if (
            checkpoint_hash != self._checkpoint_hash
            or request_hash != self._approval_request_hash
        ):
            raise WorkerCrashAfterCheckpointFaultError(
                "Worker restart changed checkpoint or ApprovalRequest semantics."
            )
        self._restart_attempts += 1
        result = await self._delegate.publish(request)
        self._downstream_publications += 1
        return result

    async def publish_after_restart(self, request: object) -> object:
        try:
            await self.publish(request)
        except WorkerCrashAfterCheckpointFaultError:
            if self._injected_crashes != 1:
                raise
        else:
            raise WorkerCrashAfterCheckpointFaultError(
                "Worker-crash injection did not stop the first publication."
            )
        return await self.publish(request)

    def _checkpoint(self) -> dict[str, Any]:
        try:
            raw = self._checkpoint_loader()
            checkpoint = dict(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise WorkerCrashAfterCheckpointFaultError(
                "Durable NSL checkpoint is not an object."
            ) from exc
        required = {
            "execution_id",
            "business_operation_id",
            "checkpoint_version",
            "semantic_hash",
            "integrity_hash",
        }
        if not required.issubset(checkpoint):
            raise WorkerCrashAfterCheckpointFaultError(
                "Durable NSL checkpoint identity is incomplete."
            )
        version = checkpoint["checkpoint_version"]
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise WorkerCrashAfterCheckpointFaultError(
                "Durable NSL checkpoint version is invalid."
            )
        for field in ("execution_id", "business_operation_id"):
            if not isinstance(checkpoint[field], str) or not checkpoint[field].strip():
                raise WorkerCrashAfterCheckpointFaultError(
                    "Durable NSL checkpoint identity is incomplete."
                )
        for field in ("semantic_hash", "integrity_hash"):
            if not _hash_ref(checkpoint[field]):
                raise WorkerCrashAfterCheckpointFaultError(
                    f"Durable NSL checkpoint {field} is invalid."
                )
        return checkpoint

    @staticmethod
    def _approval_request(request: object) -> dict[str, Any]:
        try:
            raw = request.to_data()  # type: ignore[attr-defined]
            approval_request = dict(raw)
        except (AttributeError, TypeError, ValueError) as exc:
            raise WorkerCrashAfterCheckpointFaultError(
                "ApprovalRequest restart input is not canonical."
            ) from exc
        required = (
            "execution_id",
            "business_operation_id",
            "approval_request_id",
            "skill_semantic_hash",
            "payload_hash",
            "protected_payload_ref",
        )
        if any(
            not isinstance(approval_request.get(field), str)
            or not str(approval_request[field]).strip()
            for field in required
        ):
            raise WorkerCrashAfterCheckpointFaultError(
                "ApprovalRequest restart identity is incomplete."
            )
        for field in ("skill_semantic_hash", "payload_hash"):
            if not _hash_ref(approval_request[field]):
                raise WorkerCrashAfterCheckpointFaultError(
                    f"ApprovalRequest {field} is invalid."
                )
        return approval_request

    @staticmethod
    def _require_lineage(
        checkpoint: Mapping[str, Any], approval_request: Mapping[str, Any]
    ) -> None:
        expected = {
            "execution_id": approval_request["execution_id"],
            "business_operation_id": approval_request["business_operation_id"],
            "semantic_hash": approval_request["skill_semantic_hash"],
        }
        if any(checkpoint[field] != value for field, value in expected.items()):
            raise WorkerCrashAfterCheckpointFaultError(
                "Durable checkpoint and ApprovalRequest lineage differ."
            )

    def _remember(
        self,
        checkpoint: Mapping[str, Any],
        request: Mapping[str, Any],
        checkpoint_hash: str,
        request_hash: str,
    ) -> None:
        self._checkpoint_hash = checkpoint_hash
        self._checkpoint_integrity_hash = str(checkpoint["integrity_hash"])
        self._checkpoint_version = int(checkpoint["checkpoint_version"])
        self._approval_request_hash = request_hash
        self._approval_request_id = str(request["approval_request_id"])
        self._payload_hash = str(request["payload_hash"])
        self._protected_payload_ref = str(request["protected_payload_ref"])


def _hash_ref(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


class WorkerCrashAfterWriteRequestedFaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerCrashAfterWriteRequestedFaultEvidence:
    provider_dispatches: int
    injected_crashes: int
    response_discarded: bool
    provider_commit_state: str | None
    write_request_hash: str | None
    write_evidence_record_hash: str | None
    business_operation_id: str | None
    idempotency_key: str | None
    payload_hash: str | None


class WorkerCrashAfterWriteRequestedFaultPort:
    """Lose one provider outcome after exact durable WRITE_REQUESTED evidence."""

    def __init__(
        self,
        delegate: Any,
        evidence_loader: Callable[[object], object],
        public_api: Any,
    ) -> None:
        if not callable(getattr(delegate, "execute", None)):
            raise TypeError("WRITE_REQUESTED crash delegate must expose execute().")
        if not callable(evidence_loader):
            raise TypeError("WRITE_REQUESTED evidence loader must be callable.")
        _require_write_recovery_api(public_api)
        self._delegate = delegate
        self._evidence_loader = evidence_loader
        self._public_api = public_api
        self._provider_dispatches = 0
        self._injected_crashes = 0
        self._response_discarded = False
        self._provider_commit_state: str | None = None
        self._write_request_hash: str | None = None
        self._write_evidence_record_hash: str | None = None
        self._business_operation_id: str | None = None
        self._idempotency_key: str | None = None
        self._payload_hash: str | None = None

    @property
    def evidence(self) -> WorkerCrashAfterWriteRequestedFaultEvidence:
        if self._injected_crashes != 1:
            raise WorkerCrashAfterWriteRequestedFaultError(
                "WRITE_REQUESTED worker-crash evidence is unavailable."
            )
        return WorkerCrashAfterWriteRequestedFaultEvidence(
            provider_dispatches=self._provider_dispatches,
            injected_crashes=self._injected_crashes,
            response_discarded=self._response_discarded,
            provider_commit_state=self._provider_commit_state,
            write_request_hash=self._write_request_hash,
            write_evidence_record_hash=self._write_evidence_record_hash,
            business_operation_id=self._business_operation_id,
            idempotency_key=self._idempotency_key,
            payload_hash=self._payload_hash,
        )

    async def execute(self, request: object) -> object:
        if self._provider_dispatches:
            raise WorkerCrashAfterWriteRequestedFaultError(
                "Worker restart attempted a blind WRITE redispatch."
            )
        binding = _bound_write_requested_evidence(
            request,
            self._evidence_loader(request),
            public_api=self._public_api,
        )
        self._provider_dispatches = 1
        outcome = await self._delegate.execute(request)
        commit_state = _commit_state(outcome)
        self._provider_commit_state = commit_state
        self._write_request_hash = binding["write_request_hash"]
        self._write_evidence_record_hash = binding["record_hash"]
        self._business_operation_id = binding["business_operation_id"]
        self._idempotency_key = binding["idempotency_key"]
        self._payload_hash = binding["payload_hash"]
        self._response_discarded = True
        self._injected_crashes = 1
        raise WorkerCrashAfterWriteRequestedFaultError(
            "Worker crashed after durable WRITE_REQUESTED and provider dispatch."
        )


@dataclass(frozen=True)
class WorkerRestartAfterWriteRequestedEvidence:
    evidence_loads: int
    reconciliation_attempts: int
    live_write_dispatches: int
    assumed_not_committed: bool
    reconciled_commit_state: str | None
    write_request_hash: str | None
    write_evidence_record_hash: str | None
    business_operation_id: str | None
    idempotency_key: str | None
    payload_hash: str | None


class WorkerRestartAfterWriteRequestedRecovery:
    """Recover a crashed WRITE only through the authoritative EOS read model."""

    def __init__(
        self,
        reconciliation_port: Any,
        evidence_loader: Callable[[object], object],
        public_api: Any,
    ) -> None:
        if not callable(getattr(reconciliation_port, "reconcile", None)):
            raise TypeError("WRITE_REQUESTED recovery port must expose reconcile().")
        if not callable(evidence_loader):
            raise TypeError("WRITE_REQUESTED evidence loader must be callable.")
        _require_write_recovery_api(public_api)
        self._reconciliation_port = reconciliation_port
        self._evidence_loader = evidence_loader
        self._public_api = public_api
        self._evidence_loads = 0
        self._reconciliation_attempts = 0
        self._reconciled_commit_state: str | None = None
        self._binding: dict[str, str] | None = None

    @property
    def evidence(self) -> WorkerRestartAfterWriteRequestedEvidence:
        binding = self._binding or {}
        return WorkerRestartAfterWriteRequestedEvidence(
            evidence_loads=self._evidence_loads,
            reconciliation_attempts=self._reconciliation_attempts,
            live_write_dispatches=0,
            assumed_not_committed=False,
            reconciled_commit_state=self._reconciled_commit_state,
            write_request_hash=binding.get("write_request_hash"),
            write_evidence_record_hash=binding.get("record_hash"),
            business_operation_id=binding.get("business_operation_id"),
            idempotency_key=binding.get("idempotency_key"),
            payload_hash=binding.get("payload_hash"),
        )

    async def recover(self, request: object) -> object:
        if self._reconciliation_attempts:
            raise WorkerCrashAfterWriteRequestedFaultError(
                "WRITE_REQUESTED recovery is one-shot."
            )
        self._binding = _bound_write_requested_evidence(
            request,
            self._evidence_loader(request),
            public_api=self._public_api,
        )
        self._evidence_loads = 1
        identity = self._public_api.write_outcome_identity.from_request(request)
        unknown = self._public_api.write_commit_unknown(
            identity=identity,
            reason_code="WORKER_CRASH_AFTER_WRITE_REQUESTED",
            message=(
                "The worker stopped after durable WRITE_REQUESTED; EOS must be "
                "queried before any further WRITE action."
            ),
            evidence_refs=("ae.write_requested:" + self._binding["record_hash"],),
        )
        self._reconciliation_attempts = 1
        outcome = await self._reconciliation_port.reconcile(request, unknown)
        if not isinstance(
            outcome,
            (
                self._public_api.write_committed,
                self._public_api.write_not_committed,
                self._public_api.write_commit_unknown,
            ),
        ):
            raise WorkerCrashAfterWriteRequestedFaultError(
                "WRITE_REQUESTED reconciliation returned an invalid outcome."
            )
        self._reconciled_commit_state = _commit_state(outcome)
        return outcome


def _require_write_recovery_api(public_api: object) -> None:
    identity = getattr(public_api, "write_outcome_identity", None)
    if not callable(getattr(identity, "from_request", None)):
        raise TypeError("WRITE recovery identity projection is unavailable.")
    if not callable(getattr(public_api, "write_commit_unknown", None)):
        raise TypeError("WRITE recovery unknown outcome is unavailable.")
    for name in ("write_call_request", "write_committed", "write_not_committed"):
        if not isinstance(getattr(public_api, name, None), type):
            raise TypeError(f"WRITE recovery {name} type is unavailable.")


def _bound_write_requested_evidence(
    request: object,
    saved: object,
    *,
    public_api: Any,
) -> dict[str, str]:
    if not isinstance(request, public_api.write_call_request):
        raise WorkerCrashAfterWriteRequestedFaultError(
            "Worker recovery requires an admitted WRITE request."
        )
    if not isinstance(saved, Mapping):
        raise WorkerCrashAfterWriteRequestedFaultError(
            "Durable WRITE_REQUESTED evidence is unavailable."
        )
    expected = {
        "tenant_id": str(request.tenant_id),
        "nsl_execution_id": str(request.execution_id),
        "business_operation_id": str(request.business_operation_id),
        "invocation_id": str(request.invocation_id),
        "write_node_id": str(request.node_id),
        "tool_id": str(request.tool_id),
        "contract_hash": str(request.contract_hash),
        "approval_request_id": str(request.approval_request_id),
        "idempotency_key": str(request.idempotency_key),
        "payload_hash": str(request.payload_hash),
        "write_intent_hash": str(request.write_intent_hash),
        "precondition_evidence_id": str(request.business_preconditions.evidence_id),
    }
    if any(saved.get(field) != value for field, value in expected.items()):
        raise WorkerCrashAfterWriteRequestedFaultError(
            "Durable WRITE_REQUESTED evidence differs from the restart request."
        )
    record_hash = saved.get("record_hash")
    if not _hash_ref(record_hash):
        raise WorkerCrashAfterWriteRequestedFaultError(
            "Durable WRITE_REQUESTED record hash is invalid."
        )
    return {
        "write_request_hash": semantic_sha256_hash_ref(expected),
        "record_hash": str(record_hash),
        "business_operation_id": expected["business_operation_id"],
        "idempotency_key": expected["idempotency_key"],
        "payload_hash": expected["payload_hash"],
    }


def _commit_state(outcome: object) -> str:
    value = getattr(getattr(outcome, "commit_state", None), "value", None)
    if value not in {"COMMITTED", "NOT_COMMITTED", "UNKNOWN_COMMIT_STATE"}:
        raise WorkerCrashAfterWriteRequestedFaultError(
            "WRITE recovery outcome commit state is invalid."
        )
    return str(value)
