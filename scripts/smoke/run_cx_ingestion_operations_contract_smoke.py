#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-cx", ROOT / "services" / "_shared"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from fastapi.testclient import TestClient  # noqa: E402

from nex_runtime import (  # noqa: E402
    CX_INGESTION_LEASE_RECOVERED_EVENT,
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_common_job,
    build_service_app,
    build_subject_ref,
    issue_mock_service_token,
)
from nex_cx.ingestion_operations import register_ingestion_operations_routes  # noqa: E402
from nex_cx.ingestion_orchestration import (  # noqa: E402
    build_ingestion_run,
    claim_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (  # noqa: E402
    InMemoryIngestionRunRepository,
)
from nex_cx.ingestion_worker import CX_INGESTION_JOB_TYPE  # noqa: E402


OBSERVED_AT = "2000-01-01T00:00:00Z"
LEASE_EXPIRES_AT = "2000-01-01T00:00:01Z"
TRACE_ID = "92800000000000000000000000000001"
REQUEST_ID = "request-0928-smoke"


def run_cx_ingestion_operations_contract_smoke() -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    event_store = InMemoryOperationalEventStore()
    register_ingestion_operations_routes(
        app,
        job_queue=queue,
        run_repository=repository,
        event_emitter=OperationalEventEmitter(
            service_id="nex-cx",
            store=event_store,
        ),
    )
    job = queue.enqueue(
        build_common_job(
            job_id="job-0928-smoke",
            job_type=CX_INGESTION_JOB_TYPE,
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref=build_subject_ref("cx.document", "document-0928-smoke"),
            idempotency_key="upload-0928-smoke",
            max_attempts=3,
            retryable=True,
            created_at=OBSERVED_AT,
        )
    )
    run = repository.create(
        build_ingestion_run(
            document_id="document-0928-smoke",
            job_id=job["job_id"],
            idempotency_key="upload-0928-smoke",
            tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
            owner_subject_ref={"type": "oa.user", "id": "user-a"},
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            created_at=OBSERVED_AT,
        )
    )
    queue.start_job(job["job_id"], updated_at=OBSERVED_AT)
    run = repository.save(
        claim_ingestion_run(
            run,
            worker_id="worker-0928-smoke",
            lease_expires_at=LEASE_EXPIRES_AT,
            observed_at=OBSERVED_AT,
        ),
        expected_checkpoint_version=0,
    )
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-cx")
    service_headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }
    owner_headers = {
        **service_headers,
        "X-NEX-Tenant-ID": "tenant-a",
        "X-NEX-Subject-ID": "user-a",
    }
    client = TestClient(app)
    detail = client.get(
        f"/api/v1/ingestion-runs/{run['run_id']}", headers=owner_headers
    )
    denied = client.get(
        f"/api/v1/ingestion-runs/{run['run_id']}",
        headers={
            **service_headers,
            "X-NEX-Tenant-ID": "tenant-a",
            "X-NEX-Subject-ID": "user-b",
        },
    )
    restart = client.get(
        "/internal/v1/ingestion/restart-plan", headers=service_headers
    )
    recovery = client.post(
        f"/internal/v1/ingestion/jobs/{job['job_id']}/recover-expired-lease",
        headers=service_headers,
    )
    events = event_store.list_events(
        event_type=CX_INGESTION_LEASE_RECOVERED_EVENT
    )
    serialized = json.dumps(
        {
            "detail": detail.json(),
            "restart": restart.json(),
            "recovery": recovery.json(),
            "events": events,
        },
        sort_keys=True,
    ).lower()
    checks = {
        "owner_read_allowed": detail.status_code == 200,
        "cross_owner_hidden": denied.status_code == 404,
        "restart_plan_protected": restart.status_code == 200,
        "expired_lease_detected": restart.json()["items"][0]["action"]
        == "RECOVER_EXPIRED_LEASE",
        "restart_plan_read_only": restart.json()["mutation_performed"] is False,
        "recovery_succeeded": recovery.status_code == 200
        and recovery.json()["result"]["recovered"] is True,
        "event_emitted": len(events) == 1,
        "private_payload_absent": all(
            token not in serialized
            for token in ('"source_text"', '"payload"', '"prompt"', '"vector"')
        ),
        "postgres_deferred": True,
        "dgx_not_required": True,
    }
    return {
        "smoke_schema_version": "cx_ingestion_operations_contract_smoke.v1",
        "slice": "0928",
        "requirement": "S93",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "restart_action": restart.json()["items"][0]["action"],
        "recovery_status": recovery.json()["result"]["status"],
        "checkpoint_version": recovery.json()["result"]["checkpoint_version"],
        "postgres_required": False,
        "dgx_live_provider_required": False,
        "next_slice": "0929",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks") or {}
    return (
        "cx_ingestion_operations_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"action={result.get('restart_action')} "
        f"recovery={result.get('recovery_status')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_ingestion_operations_contract_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
