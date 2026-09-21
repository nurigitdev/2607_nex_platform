#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-cx", ROOT / "services" / "_shared"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from nex_runtime import InMemoryJobQueue, build_common_job, build_subject_ref  # noqa: E402
from nex_cx.ingestion_coordinator import IngestionStepResult  # noqa: E402
from nex_cx.ingestion_orchestration import (  # noqa: E402
    INGESTION_PIPELINE_STEPS,
    build_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (  # noqa: E402
    InMemoryIngestionRunRepository,
)
from nex_cx.ingestion_worker import (  # noqa: E402
    CX_INGESTION_JOB_TYPE,
    run_ingestion_worker_once,
)


def run_cx_ingestion_worker_retry_recovery_smoke() -> dict[str, Any]:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    queue.enqueue(
        build_common_job(
            job_id="contract-job",
            job_type=CX_INGESTION_JOB_TYPE,
            trace_id="contract-trace",
            request_id="contract-request",
            subject_ref=build_subject_ref("cx.document", "contract-document"),
            idempotency_key="contract-upload",
            max_attempts=3,
            retryable=True,
            links={"document": "/api/v1/documents/contract-document"},
            created_at="2026-09-21T00:00:00Z",
        )
    )
    repository.create(
        build_ingestion_run(
            document_id="contract-document",
            job_id="contract-job",
            idempotency_key="contract-upload",
            tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
            owner_subject_ref={"type": "oa.user", "id": "user-a"},
            trace_id="contract-trace",
            request_id="contract-request",
            created_at="2026-09-21T00:00:00Z",
        )
    )
    handlers = {
        step_id: (
            lambda run, selected=step_id: IngestionStepResult(
                f"cx.{selected}:{run['document_id']}"
            )
        )
        for step_id in INGESTION_PIPELINE_STEPS
    }
    result = run_ingestion_worker_once(
        job_queue=queue,
        run_repository=repository,
        step_handlers=handlers,
        worker_id="contract-worker",
        clock=lambda: "2026-09-21T00:00:01Z",
    )
    serialized = json.dumps(result, sort_keys=True).lower()
    checks = {
        "worker_succeeded": result["status"] == "SUCCEEDED",
        "job_succeeded": result["job_status"] == "SUCCEEDED",
        "run_succeeded": result["run_status"] == "SUCCEEDED",
        "six_steps_checkpointed": result["checkpoint_version"] == 7,
        "job_linked": result["job_id"] == "contract-job",
        "run_linked": isinstance(result["run_id"], str),
        "not_recovered": result["recovered"] is False,
        "no_failure": result["error_code"] is None,
        "private_payload_absent": all(
            token not in serialized
            for token in ('"payload"', '"source_text"', '"vector"', '"prompt"')
        ),
        "dgx_not_required": True,
    }
    return {
        "smoke_schema_version": "cx_ingestion_worker_retry_recovery_smoke.v1",
        "slice": "0926",
        "requirement": "S93",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "checkpoint_version": result["checkpoint_version"],
        "job_status": result["job_status"],
        "run_status": result["run_status"],
        "postgres_required": False,
        "dgx_live_provider_required": False,
        "next_slice": "0927",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks") or {}
    return (
        "cx_ingestion_worker_retry_recovery="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"job={result.get('job_status')} run={result.get('run_status')} "
        f"checkpoint={result.get('checkpoint_version', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_ingestion_worker_retry_recovery_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
