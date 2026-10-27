from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime import (
    InMemoryServiceLogStore,
    JobQueue,
    ServiceLogEmitter,
    ServiceLogStore,
    WorkerBatchResult,
    WorkerHeartbeatEmitter,
    WorkerJobExecution,
    WorkerRunnerConfig,
    run_worker_batch,
    run_worker_once,
)

from .intake_contracts import (
    WA_EVIDENCE_INGEST_JOB_TYPE,
    WaIntakeContractError,
    normalize_evidence_intake_request,
)
from .job_recovery import WaFencedJobQueue
from .persistence import WaPersistenceRuntime
from .source_adapters import (
    WaEvidenceSourceAdapterRegistry,
    WaSourceAdapterError,
    normalize_source_envelope,
    require_matching_source_envelope,
)

SERVICE_ID = "nex-wa"
PROCESS_ID = "nex-wa-evidence-consumer"
WORKER_TYPE = "wa.evidence_consumer"
DEFAULT_WORKER_ID = "nex-wa-evidence-consumer-001"


@dataclass(frozen=True)
class WaEvidenceConsumerRuntime:
    persistence: WaPersistenceRuntime
    registry: WaEvidenceSourceAdapterRegistry
    config: WorkerRunnerConfig
    heartbeat_emitter: WorkerHeartbeatEmitter
    service_log_emitter: ServiceLogEmitter

    def readiness(self) -> dict[str, Any]:
        checks = (
            self.persistence.migration_readiness(),
            self.persistence.consumer_storage_readiness(),
            self.registry.readiness(),
        )
        return {
            "service_id": SERVICE_ID,
            "process_id": PROCESS_ID,
            "worker_type": WORKER_TYPE,
            "domain_processing_enabled": all(bool(check.get("ok")) for check in checks),
            "checks": list(checks),
        }

    def run_once(self, *, clock=None) -> WorkerJobExecution:
        self.require_ready()
        return run_wa_evidence_consumer_once(
            queue=self._fenced_queue(),
            registry=self.registry,
            heartbeat_emitter=self.heartbeat_emitter,
            service_log_emitter=self.service_log_emitter,
            worker_id=self.config.worker_id,
            clock=clock,
        )

    def recover_stale(
        self,
        *,
        observed_at: str,
        stale_after_seconds: int,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        self.require_ready()
        return self.persistence.job_fence_store.recover_stale(
            observed_at=observed_at,
            stale_after_seconds=stale_after_seconds,
            limit=limit,
        )

    def _fenced_queue(self) -> JobQueue:
        fence_store = getattr(self.persistence, "job_fence_store", None)
        if fence_store is None:
            return self.persistence.job_queue
        return WaFencedJobQueue(
            self.persistence.job_queue,
            fence_store,
        )

    def stop(self, *, observed_at: str | None = None) -> tuple[dict[str, Any], ...]:
        stopping = self.heartbeat_emitter.stopping(
            metadata={"graceful_stop": True},
            observed_at=observed_at,
        )
        stopped = self.heartbeat_emitter.stopped(
            metadata={"graceful_stop": True},
            observed_at=observed_at,
        )
        return stopping, stopped

    def require_ready(self) -> None:
        readiness = self.readiness()
        if readiness["domain_processing_enabled"] is not True:
            raise WaEvidenceConsumerError(
                "WA_CONSUMER_NOT_READY",
                "WA evidence consumer startup dependencies are not ready",
            )


class WaEvidenceConsumerError(Exception):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def package_readiness(
    registry: WaEvidenceSourceAdapterRegistry | None = None,
) -> dict[str, object]:
    adapter_readiness = registry.readiness() if registry is not None else None
    return {
        "service_id": SERVICE_ID,
        "process_id": PROCESS_ID,
        "worker_type": WORKER_TYPE,
        "domain_processing_enabled": bool(
            adapter_readiness is not None and adapter_readiness["ok"]
        ),
        "adapter_readiness": adapter_readiness,
    }


def build_wa_evidence_consumer_config(
    *,
    worker_id: str = DEFAULT_WORKER_ID,
    max_jobs: int = 1,
) -> WorkerRunnerConfig:
    return WorkerRunnerConfig(
        service_id=SERVICE_ID,
        worker_id=worker_id,
        worker_type=WORKER_TYPE,
        job_type=WA_EVIDENCE_INGEST_JOB_TYPE,
        max_jobs=max_jobs,
    )


def inspect_wa_evidence_job(
    job: Mapping[str, Any],
    *,
    registry: WaEvidenceSourceAdapterRegistry,
) -> dict[str, Any]:
    if not isinstance(job, Mapping) or job.get("job_type") != WA_EVIDENCE_INGEST_JOB_TYPE:
        raise WaEvidenceConsumerError(
            "WA_CONSUMER_JOB_INVALID",
            "consumer requires a WA_EVIDENCE_INGEST common Job",
        )
    payload = job.get("payload")
    if not isinstance(payload, Mapping):
        raise WaEvidenceConsumerError(
            "WA_CONSUMER_PAYLOAD_INVALID",
            "consumer Job payload must be a reference-only object",
        )
    try:
        request = normalize_evidence_intake_request(payload)
    except WaIntakeContractError as exc:
        raise WaEvidenceConsumerError(
            "WA_CONSUMER_PAYLOAD_INVALID",
            "consumer Job payload failed intake validation",
        ) from exc
    try:
        adapter = registry.resolve(request.source_type)
        envelope = normalize_source_envelope(adapter.fetch(request))
        require_matching_source_envelope(request, envelope)
    except WaSourceAdapterError as exc:
        raise WaEvidenceConsumerError(exc.error_code, exc.detail) from exc
    return {
        "source_inspection": "VERIFIED",
        "source_type": envelope.source_type,
        "source_ref": envelope.source_ref,
        "source_revision_ref": envelope.source_revision_ref,
        "source_hash": envelope.source_hash,
        "source_owner": envelope.source_owner,
    }


def run_wa_evidence_consumer_once(
    *,
    queue: JobQueue,
    registry: WaEvidenceSourceAdapterRegistry,
    heartbeat_emitter: WorkerHeartbeatEmitter,
    service_log_emitter: ServiceLogEmitter | None = None,
    worker_id: str = DEFAULT_WORKER_ID,
    clock=None,
) -> WorkerJobExecution:
    return run_worker_once(
        config=build_wa_evidence_consumer_config(worker_id=worker_id),
        queue=queue,
        heartbeat_emitter=heartbeat_emitter,
        service_log_emitter=service_log_emitter,
        handler=lambda job: inspect_wa_evidence_job(job, registry=registry),
        clock=clock,
    )


def run_wa_evidence_consumer_batch(
    *,
    queue: JobQueue,
    registry: WaEvidenceSourceAdapterRegistry,
    heartbeat_emitter: WorkerHeartbeatEmitter,
    service_log_emitter: ServiceLogEmitter | None = None,
    worker_id: str = DEFAULT_WORKER_ID,
    max_jobs: int = 1,
    stop_on_failure: bool = True,
    clock=None,
) -> WorkerBatchResult:
    return run_worker_batch(
        config=build_wa_evidence_consumer_config(
            worker_id=worker_id,
            max_jobs=max_jobs,
        ),
        queue=queue,
        heartbeat_emitter=heartbeat_emitter,
        service_log_emitter=service_log_emitter,
        handler=lambda job: inspect_wa_evidence_job(job, registry=registry),
        stop_on_failure=stop_on_failure,
        clock=clock,
    )


def build_wa_evidence_consumer_runtime(
    *,
    persistence: WaPersistenceRuntime,
    registry: WaEvidenceSourceAdapterRegistry,
    worker_id: str = DEFAULT_WORKER_ID,
    service_log_store: ServiceLogStore | None = None,
) -> WaEvidenceConsumerRuntime:
    heartbeat = WorkerHeartbeatEmitter(
        service_id=SERVICE_ID,
        worker_id=worker_id,
        worker_type=WORKER_TYPE,
        store=persistence.worker_heartbeat_store,
    )
    logger = ServiceLogEmitter(
        service_id=SERVICE_ID,
        logger_name=PROCESS_ID,
        store=service_log_store or InMemoryServiceLogStore(),
    )
    return WaEvidenceConsumerRuntime(
        persistence=persistence,
        registry=registry,
        config=build_wa_evidence_consumer_config(worker_id=worker_id),
        heartbeat_emitter=heartbeat,
        service_log_emitter=logger,
    )
