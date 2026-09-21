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

from nex_cx.ingestion_coordinator import (  # noqa: E402
    IngestionStepResult,
    execute_all_ingestion_checkpoints,
)
from nex_cx.ingestion_orchestration import (  # noqa: E402
    INGESTION_PIPELINE_STEPS,
    build_ingestion_run,
    claim_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (  # noqa: E402
    InMemoryIngestionRunRepository,
)


def run_cx_ingestion_checkpoint_coordinator_smoke() -> dict[str, Any]:
    repository = InMemoryIngestionRunRepository()
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
    run = repository.save(
        claim_ingestion_run(
            run,
            worker_id="worker-1",
            lease_expires_at="2026-09-21T00:02:00Z",
            observed_at="2026-09-21T00:00:01Z",
        ),
        expected_checkpoint_version=0,
    )
    handlers = {
        step_id: (
            lambda current, selected=step_id: IngestionStepResult(
                f"cx.{selected}:{current['document_id']}",
                skipped=selected == "summary",
            )
        )
        for step_id in INGESTION_PIPELINE_STEPS
    }
    completed = execute_all_ingestion_checkpoints(
        run,
        run_repository=repository,
        worker_id="worker-1",
        step_handlers=handlers,
        observed_at="2026-09-21T00:01:00Z",
    )
    serialized = json.dumps(completed, sort_keys=True).lower()
    checks = {
        "terminal_success": completed["status"] == "SUCCEEDED",
        "six_steps_checkpointed": len(completed["step_states"]) == 6,
        "checkpoint_monotonic": completed["checkpoint_version"] == 7,
        "skip_preserved": completed["step_states"]["summary"]["status"]
        == "SKIPPED",
        "lease_released": completed["lease_owner"] is None,
        "owner_preserved": completed["owner_subject_ref"]["id"] == "user-a",
        "repository_round_trip": repository.get(
            completed["run_id"],
            tenant_id="tenant-a",
            owner_subject_id="user-a",
        )
        == completed,
        "private_payload_absent": all(
            token not in serialized
            for token in ('"payload"', '"source_text"', '"vector"', '"prompt"')
        ),
    }
    return {
        "smoke_schema_version": "cx_ingestion_checkpoint_coordinator_smoke.v1",
        "slice": "0925",
        "requirement": "S93",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "step_count": len(completed["step_states"]),
        "checkpoint_version": completed["checkpoint_version"],
        "postgres_required": False,
        "dgx_live_provider_required": False,
        "next_slice": "0926",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks") or {}
    return (
        "cx_ingestion_checkpoint_coordinator="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"steps={result.get('step_count', 0)} "
        f"checkpoint={result.get('checkpoint_version', 0)} "
        f"dgx_required={result.get('dgx_live_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_ingestion_checkpoint_coordinator_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
