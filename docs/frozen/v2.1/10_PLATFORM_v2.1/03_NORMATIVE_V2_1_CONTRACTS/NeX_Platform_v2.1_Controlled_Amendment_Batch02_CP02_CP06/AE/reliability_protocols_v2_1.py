from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Literal, Mapping, Any

RuntimeJobType = Literal[
    "START_EXECUTION","CONTINUE_EXECUTION","RESUME_EXECUTION","RETRY_EXECUTION","RECONCILE_EXECUTION",
    "PUBLISH_RESULT","RECONCILE_PUBLICATION"
]
RuntimeJobState = Literal["QUEUED","RUNNING","DONE","FAILED","CANCELLED","DEAD_LETTER"]
ReconciliationOutcomeStatus = Literal[
    "CONFIRMED_COMMITTED","CONFIRMED_NOT_COMMITTED","STILL_UNKNOWN","CONFLICT"
]
RetryDisposition = Literal[
    "RETRY_WITH_BACKOFF","DO_NOT_RETRY","RECONCILE_FIRST","REPLAN_OR_ESCALATE"
]

@dataclass(frozen=True)
class RuntimeJobV21:
    tenant_id: str
    runtime_job_id: str
    job_type: RuntimeJobType
    execution_id: str
    state: RuntimeJobState
    dedup_key: str
    attempt_no: int
    run_after: str
    correlation_id: str
    executable_step_id: str | None = None
    wait_id: str | None = None
    reconciliation_id: str | None = None
    result_delivery_id: str | None = None
    publication_reconciliation_id: str | None = None

@dataclass(frozen=True)
class ReconciliationOutcomeV21:
    reconciliation_id: str
    status: ReconciliationOutcomeStatus
    authoritative_query_ref: str
    retry_safety: str
    evidence_refs: tuple[str, ...]

@dataclass(frozen=True)
class RetryDispositionV21:
    disposition: RetryDisposition
    reason_codes: tuple[str, ...]

class RuntimeJobQueueV21(Protocol):
    def enqueue_unique(self, job: RuntimeJobV21) -> str: ...
    def claim(self, *, tenant_id: str, worker_id: str, lease_seconds: int) -> RuntimeJobV21 | None: ...
    def complete(self, *, tenant_id: str, runtime_job_id: str, lease_token: str) -> None: ...

class ReconciliationAdapterV21(Protocol):
    def reconcile(self, *, target_system: str, operation_ref: str | None,
                  business_operation_id: str, idempotency_key_ref: str,
                  business_object_ref: str | None) -> ReconciliationOutcomeV21: ...

class ReconciliationRepositoryV21(Protocol):
    def create_or_get(self, case: Mapping[str, Any]) -> str: ...
    def record_outcome(self, reconciliation_id: str, outcome: ReconciliationOutcomeV21) -> None: ...

def mandatory_retry_disposition(*, commit_state: str | None, retry_safety: str | None) -> RetryDispositionV21 | None:
    if commit_state == "COMMITTED":
        return RetryDispositionV21("DO_NOT_RETRY", ("BUSINESS_EFFECT_COMMITTED",))
    if commit_state == "UNKNOWN_COMMIT_STATE":
        return RetryDispositionV21("RECONCILE_FIRST", ("COMMIT_STATE_UNKNOWN",))
    if commit_state == "NOT_COMMITTED" and retry_safety == "SAFE_TO_RETRY":
        return RetryDispositionV21("RETRY_WITH_BACKOFF", ("NOT_COMMITTED_RETRY_SAFE",))
    if retry_safety == "UNSAFE_TO_RETRY":
        return RetryDispositionV21("DO_NOT_RETRY", ("RETRY_SAFETY_UNSAFE",))
    return None
