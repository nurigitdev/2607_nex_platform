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
from nex_cx.ingestion_orchestration import (  # noqa: E402
    build_ingestion_run,
    claim_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (  # noqa: E402
    InMemoryIngestionRunRepository,
)
from nex_cx.ingestion_read_model import (  # noqa: E402
    RECOVER_EXPIRED_LEASE,
    build_ingestion_restart_plan,
    get_ingestion_run_read_model,
)
from nex_cx.ingestion_worker import CX_INGESTION_JOB_TYPE  # noqa: E402


def run_cx_ingestion_restart_read_model_smoke() -> dict[str, Any]:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    job = queue.enqueue(
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
    run = repository.create(
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
    queue.start_job(str(job["job_id"]), updated_at="2026-09-21T00:00:00Z")
    claimed = claim_ingestion_run(
        run,
        worker_id="contract-worker",
        lease_expires_at="2026-09-21T00:00:10Z",
        observed_at="2026-09-21T00:00:00Z",
    )
    repository.save(claimed, expected_checkpoint_version=0)
    plan = build_ingestion_restart_plan(
        job_queue=queue,
        run_repository=repository,
        observed_at="2026-09-21T00:00:11Z",
    )
    read_model = get_ingestion_run_read_model(
        claimed["run_id"],
        tenant_id="tenant-a",
        owner_subject_id="user-a",
        run_repository=repository,
    )
    denied = get_ingestion_run_read_model(
        claimed["run_id"],
        tenant_id="tenant-a",
        owner_subject_id="user-b",
        run_repository=repository,
    )
    serialized = json.dumps(
        {"plan": plan, "read_model": read_model}, sort_keys=True
    ).lower()
    checks = {
        "expired_lease_detected": plan["items"][0]["action"]
        == RECOVER_EXPIRED_LEASE,
        "read_only_hydration": plan["mutation_performed"] is False,
        "active_run_visible": read_model["status"] == "RUNNING",
        "six_steps_projected": read_model["step_total"] == 6,
        "checkpoint_preserved": read_model["checkpoint_version"] == 1,
        "cross_owner_hidden": denied is None,
        "private_payload_absent": all(
            token not in serialized
            for token in ('"payload"', '"source_text"', '"vector"', '"prompt"')
        ),
        "dgx_not_required": True,
    }
    return {
        "smoke_schema_version": "cx_ingestion_restart_read_model_smoke.v1",
        "slice": "0927",
        "requirement": "S93",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "restart_action": plan["items"][0]["action"],
        "checkpoint_version": read_model["checkpoint_version"],
        "postgres_required": False,
        "dgx_live_provider_required": False,
        "next_slice": "0928",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks") or {}
    return (
        "cx_ingestion_restart_read_model="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"action={result.get('restart_action')} "
        f"checkpoint={result.get('checkpoint_version', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_ingestion_restart_read_model_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
