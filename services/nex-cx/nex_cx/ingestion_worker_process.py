from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import importlib
from typing import Any

from nex_runtime import JobQueue

from nex_cx.ingestion_coordinator import IngestionStepHandler
from nex_cx.ingestion_orchestration_repository import IngestionRunRepository
from nex_cx.ingestion_read_model import (
    RECOVER_EXPIRED_LEASE,
    build_ingestion_restart_plan,
)
from nex_cx.ingestion_worker import (
    CX_INGESTION_WORKER_ID,
    recover_expired_ingestion_job,
    run_ingestion_worker_once,
)


CX_INGESTION_PROCESS_SCHEMA_VERSION = "cx_ingestion_worker_process.v1"
ProcessClock = Callable[[], str]


@dataclass
class IngestionWorkerProcessError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass
class IngestionWorkerProcess:
    job_queue: JobQueue
    run_repository: IngestionRunRepository
    step_handlers: Mapping[str, IngestionStepHandler]
    profile: str
    worker_id: str = CX_INGESTION_WORKER_ID
    work_claiming_enabled: bool = True
    clock: ProcessClock | None = None
    cleanup: Callable[[], None] | None = field(default=None, repr=False)
    _startup_evidence: dict[str, Any] | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    def startup(self) -> dict[str, Any]:
        if self._closed:
            raise IngestionWorkerProcessError(
                "cx.ingestion_process.closed",
                "The ingestion worker process is already closed.",
            )
        if self._startup_evidence is not None:
            return dict(self._startup_evidence)
        observed_at = self._observed_at()
        restart_plan = build_ingestion_restart_plan(
            job_queue=self.job_queue,
            run_repository=self.run_repository,
            observed_at=observed_at,
        )
        recovered_job_ids: list[str] = []
        for item in restart_plan["items"]:
            if item["action"] != RECOVER_EXPIRED_LEASE:
                continue
            recover_expired_ingestion_job(
                str(item["job_id"]),
                job_queue=self.job_queue,
                run_repository=self.run_repository,
                observed_at=observed_at,
            )
            recovered_job_ids.append(str(item["job_id"]))
        self._startup_evidence = {
            "process_schema_version": CX_INGESTION_PROCESS_SCHEMA_VERSION,
            "worker_id": self.worker_id,
            "profile": self.profile,
            "observed_at": observed_at,
            "restart_job_count": restart_plan["job_count"],
            "restart_action_counts": restart_plan["action_counts"],
            "recovered_lease_count": len(recovered_job_ids),
            "recovered_job_ids": recovered_job_ids,
            "work_claiming_enabled": self.work_claiming_enabled,
            "private_payload_included": False,
        }
        return dict(self._startup_evidence)

    def run_once(self) -> dict[str, Any]:
        self.startup()
        if not self.work_claiming_enabled:
            return {
                "worker_result_schema_version": "cx_ingestion_worker_result.v1",
                "worker_id": self.worker_id,
                "status": "IDLE",
                "observed_at": self._observed_at(),
                "job_id": None,
                "run_id": None,
                "work_claiming_enabled": False,
            }
        return run_ingestion_worker_once(
            job_queue=self.job_queue,
            run_repository=self.run_repository,
            step_handlers=self.step_handlers,
            worker_id=self.worker_id,
            clock=self.clock,
        )

    def metadata(self) -> dict[str, object]:
        return {
            "schema_version": CX_INGESTION_PROCESS_SCHEMA_VERSION,
            "process_id": "nex-cx-ingestion-worker",
            "service_id": "nex-cx",
            "module": "nex_cx.ingestion_worker_process",
            "profile": self.profile,
            "work_claiming_enabled": self.work_claiming_enabled,
            "restart_recovery_enabled": True,
            "checkpoint_cancellation_enabled": True,
            "lifecycle_ready": True,
            "persistence_mode": (
                "postgres" if self.profile == "test" else "memory"
            ),
            "pool_workload": "worker" if self.profile == "test" else None,
        }

    def close(self) -> None:
        if self._closed:
            return
        if self.cleanup is not None:
            self.cleanup()
        self._closed = True

    def _observed_at(self) -> str:
        if self.clock is not None:
            return self.clock()
        from nex_cx.ingestion_worker import _utc_now

        return _utc_now()


def build_default_ingestion_worker_process(
    profile: str,
) -> IngestionWorkerProcess:
    if profile not in {"local_mock", "test"}:
        raise IngestionWorkerProcessError(
            "cx.ingestion_process.profile_invalid",
            "The ingestion worker process profile is not enabled.",
        )
    cx_main = importlib.import_module("nex_cx.main")

    composition = cx_main.CX_MVP_RUNTIME
    enabled = profile == "test" and composition is not None
    if profile == "test" and not enabled:
        raise IngestionWorkerProcessError(
            "cx.ingestion_process.runtime_unavailable",
            "The protected CX ingestion worker runtime is unavailable.",
        )

    persistence = cx_main.SERVICE_PERSISTENCE

    def cleanup() -> None:
        engines = (persistence.worker_engine, persistence.api_engine)
        seen: set[int] = set()
        for engine in engines:
            if engine is None or id(engine) in seen:
                continue
            engine.dispose()
            seen.add(id(engine))

    return IngestionWorkerProcess(
        job_queue=persistence.job_queue,
        run_repository=cx_main.CX_INGESTION_RUN_REPOSITORY,
        step_handlers=(
            composition.ingestion_step_handlers if composition is not None else {}
        ),
        profile=profile,
        work_claiming_enabled=enabled,
        cleanup=cleanup,
    )
