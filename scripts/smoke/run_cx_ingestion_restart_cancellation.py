#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-cx", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_runtime import InMemoryJobQueue, build_common_job, build_subject_ref  # noqa: E402
from nex_cx.ingestion_coordinator import IngestionStepResult  # noqa: E402
from nex_cx.ingestion_orchestration import (  # noqa: E402
    INGESTION_PIPELINE_STEPS,
    IngestionOrchestrationPolicy,
    build_ingestion_run,
    claim_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (  # noqa: E402
    InMemoryIngestionRunRepository,
)
from nex_cx.ingestion_worker import (  # noqa: E402
    CX_INGESTION_JOB_TYPE,
    run_ingestion_worker_once,
)
from nex_cx.ingestion_worker_process import IngestionWorkerProcess  # noqa: E402


SCHEMA_VERSION = "cx_ingestion_restart_cancellation_evidence.v1"
NOW = "2026-10-05T03:00:00Z"


def run_cx_ingestion_restart_cancellation() -> dict[str, Any]:
    recovery_queue, recovery_repository, recovery_run = _dependencies("recovery")
    recovery_queue.claim_next_job("dead-worker", updated_at=NOW)
    recovery_repository.save(
        claim_ingestion_run(
            recovery_run,
            worker_id="dead-worker",
            lease_expires_at="2026-10-05T03:00:01Z",
            observed_at=NOW,
        ),
        expected_checkpoint_version=0,
    )
    cleaned: list[bool] = []
    recovery_process = IngestionWorkerProcess(
        recovery_queue,
        recovery_repository,
        _handlers(),
        profile="test",
        clock=lambda: "2026-10-05T03:00:02Z",
        cleanup=lambda: cleaned.append(True),
    )
    startup = recovery_process.startup()
    recovery_process.close()

    work_queue, work_repository, _ = _dependencies("work")
    work_process = IngestionWorkerProcess(
        work_queue,
        work_repository,
        _handlers(),
        profile="test",
        clock=lambda: NOW,
    )
    completed = work_process.run_once()
    work_process.close()

    cancel_queue, cancel_repository, _ = _dependencies("cancel")
    cancel_handlers = _handlers()

    def cancel_after_first(run):
        cancel_queue.cancel_job("job-cancel", updated_at=NOW)
        return IngestionStepResult(f"cx.extraction:{run['document_id']}")

    cancel_handlers["extraction"] = cancel_after_first
    cancelled = run_ingestion_worker_once(
        job_queue=cancel_queue,
        run_repository=cancel_repository,
        step_handlers=cancel_handlers,
        worker_id="worker-cancel",
        clock=lambda: NOW,
    )
    cancelled_run = cancel_repository.find_by_job_id("job-cancel")

    evidence = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1349",
        "requirement": "S135",
        "recovered_lease_count": startup["recovered_lease_count"],
        "work_status": completed["status"],
        "cancel_status": cancelled["status"],
        "cancelled_checkpoint_version": cancelled["checkpoint_version"],
        "next_slice": "1350",
    }
    serialized = json.dumps(evidence, sort_keys=True).lower()
    current_step = cancelled_run["step_states"][cancelled_run["current_step"]]
    checks = {
        "restart_plan_loaded": startup["restart_job_count"] == 1,
        "expired_lease_detected": startup["restart_action_counts"]
        == {"RECOVER_EXPIRED_LEASE": 1},
        "expired_lease_recovered": startup["recovered_lease_count"] == 1,
        "recovery_is_retryable": recovery_repository.find_by_job_id(
            "job-recovery"
        )["status"]
        == "WAITING_RETRY",
        "queued_work_claimed": completed["status"] == "SUCCEEDED",
        "all_checkpoints_completed": completed["checkpoint_version"] == 7,
        "job_completed": completed["job_status"] == "SUCCEEDED",
        "run_completed": completed["run_status"] == "SUCCEEDED",
        "cancellation_settled": cancelled["status"] == "CANCELLED",
        "cancelled_step_not_running": current_step["status"] == "PENDING",
        "resource_cleanup_called": cleaned == [True],
        "private_payload_absent": all(
            token not in serialized
            for token in ('"source_text"', '"chunk_text"', '"embedding"', '"token"')
        ),
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        **evidence,
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "actual_postgres_deferred_to": "1350",
        "private_payload_in_evidence": False,
    }


def _dependencies(suffix: str):
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    job_id = f"job-{suffix}"
    document_id = f"document-{suffix}"
    queue.enqueue(
        build_common_job(
            job_id=job_id,
            job_type=CX_INGESTION_JOB_TYPE,
            trace_id=f"trace-{suffix}",
            request_id=f"request-{suffix}",
            subject_ref=build_subject_ref("cx.document", document_id),
            idempotency_key=f"upload-{suffix}",
            max_attempts=3,
            created_at=NOW,
        )
    )
    run = repository.create(
        build_ingestion_run(
            document_id=document_id,
            job_id=job_id,
            idempotency_key=f"upload-{suffix}",
            tenant_ref={"type": "oa.tenant", "id": "tenant-1349"},
            owner_subject_ref={"type": "oa.user", "id": "owner-1349"},
            trace_id=f"trace-{suffix}",
            request_id=f"request-{suffix}",
            created_at=NOW,
            policy=IngestionOrchestrationPolicy(max_attempts=3),
        )
    )
    return queue, repository, run


def _handlers():
    return {
        step_id: (
            lambda run, selected=step_id: IngestionStepResult(
                f"cx.{selected}:{run['document_id']}"
            )
        )
        for step_id in INGESTION_PIPELINE_STEPS
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"cx_ingestion_restart=fail issues={len(evidence.get('issues') or [])}"
    checks = evidence.get("checks") or {}
    return (
        "cx_ingestion_restart=pass "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"recovered={evidence.get('recovered_lease_count')} "
        f"work={evidence.get('work_status')} cancel={evidence.get('cancel_status')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_ingestion_restart_cancellation()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
