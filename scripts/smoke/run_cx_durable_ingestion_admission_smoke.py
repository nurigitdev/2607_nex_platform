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

from nex_runtime import InMemoryJobQueue  # noqa: E402
from nex_cx.ingestion import build_ingestion_job  # noqa: E402
from nex_cx.ingestion_admission import admit_durable_ingestion  # noqa: E402
from nex_cx.ingestion_orchestration_repository import (  # noqa: E402
    InMemoryIngestionRunRepository,
)


def run_cx_durable_ingestion_admission_smoke() -> dict[str, Any]:
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    record = _registration()
    first = admit_durable_ingestion(
        record, job_queue=queue, run_repository=repository
    )
    duplicate_record = {**record, "dedupe": {"status": "ALREADY_EXISTS"}}
    duplicate = admit_durable_ingestion(
        duplicate_record,
        job_queue=queue,
        run_repository=repository,
    )
    serialized = json.dumps(duplicate, sort_keys=True).lower()
    checks = {
        "job_admitted": len(queue.list_jobs(job_type="cx.document_ingestion")) == 1,
        "run_admitted": len(repository.records) == 1,
        "owner_lineage": duplicate["ingestion_run"]["owner_subject_ref"]["id"]
        == "user-a",
        "job_linked": duplicate["ingestion_run"]["job_id"]
        == duplicate["job"]["job_id"],
        "idempotent_retry": duplicate["idempotent"] is True,
        "stable_identity": duplicate["ingestion_run"]["run_id"]
        == first["ingestion_run"]["run_id"],
        "partial_success_recoverable": all(
            duplicate["recovery_policy"].values()
        ),
        "private_payload_absent": all(
            token not in serialized
            for token in ("private durable", "source_text", "source_bytes", "vector")
        ),
    }
    return {
        "smoke_schema_version": "cx_durable_ingestion_admission_smoke.v1",
        "slice": "0924",
        "requirement": "S93",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "job_count": len(queue.list_jobs(job_type="cx.document_ingestion")),
        "run_count": len(repository.records),
        "postgres_required": False,
        "dgx_live_provider_required": False,
        "next_slice": "0925",
    }


def _registration() -> dict[str, Any]:
    return {
        "document_id": "11111111-1111-1111-1111-111111111111",
        "upload_id": "contract-upload",
        "trace_id": "a" * 32,
        "request_id": "contract-request",
        "created_at": "2026-09-21T00:00:00Z",
        "ownership_ref": {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
            "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
        },
        "ingestion_job": build_ingestion_job(
            document_id="11111111-1111-1111-1111-111111111111",
            upload_id="contract-upload",
            request_id="contract-request",
            trace_id="a" * 32,
            created_at="2026-09-21T00:00:00Z",
        ),
        "dedupe": {"status": "CREATED"},
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks") or {}
    return (
        "cx_durable_ingestion_admission="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"jobs={result.get('job_count', 0)} runs={result.get('run_count', 0)} "
        f"dgx_required={result.get('dgx_live_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_durable_ingestion_admission_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
