#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_ROOT = ROOT / "services" / "nex-cx"
if str(CX_ROOT) not in sys.path:
    sys.path.insert(0, str(CX_ROOT))

from nex_cx.ingestion_orchestration import (  # noqa: E402
    INGESTION_PIPELINE_STEPS,
    IngestionOrchestrationError,
    build_ingestion_run,
    claim_ingestion_run,
    complete_ingestion_step,
    fail_ingestion_step,
    requeue_ingestion_run,
)


def run_cx_ingestion_orchestration_contract() -> dict[str, Any]:
    run = build_ingestion_run(
        document_id="contract-document",
        job_id="contract-job",
        idempotency_key="contract-upload",
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        trace_id="contract-trace",
        request_id="contract-request",
        created_at="2026-09-21T00:00:00Z",
    )
    run = claim_ingestion_run(
        run,
        worker_id="contract-worker",
        lease_expires_at="2026-09-21T00:02:00Z",
        observed_at="2026-09-21T00:00:01Z",
    )
    failed = fail_ingestion_step(
        run,
        worker_id="contract-worker",
        error_code="contract.temporary",
        retryable=True,
        retry_at="2026-09-21T00:01:00Z",
        observed_at="2026-09-21T00:00:02Z",
    )
    resumed = requeue_ingestion_run(
        failed,
        observed_at="2026-09-21T00:01:00Z",
    )
    resumed = claim_ingestion_run(
        resumed,
        worker_id="contract-worker-2",
        lease_expires_at="2026-09-21T00:03:00Z",
        observed_at="2026-09-21T00:01:01Z",
    )
    for index, step_id in enumerate(INGESTION_PIPELINE_STEPS):
        resumed = complete_ingestion_step(
            resumed,
            worker_id="contract-worker-2",
            output_ref=f"{step_id}-metadata-ref",
            observed_at=f"2026-09-21T00:01:{index + 2:02d}Z",
        )

    checks = {
        "terminal_success": resumed["status"] == "SUCCEEDED",
        "all_steps_terminal": all(
            step["status"] in {"SUCCEEDED", "SKIPPED"}
            for step in resumed["step_states"].values()
        ),
        "checkpoint_monotonic": resumed["checkpoint_version"] == 10,
        "retry_preserved": resumed["attempt_count"] == 2,
        "lease_released": resumed["lease_owner"] is None,
        "owner_lineage_preserved": (
            resumed["tenant_ref"]["id"] == "tenant-a"
            and resumed["owner_subject_ref"]["id"] == "user-a"
        ),
        "private_payload_absent": all(
            token not in json.dumps(resumed, sort_keys=True).lower()
            for token in ('"payload"', '"source_text"', '"vector"', '"prompt"')
        ),
        "invalid_claim_rejected": _invalid_claim_rejected(resumed),
    }
    passed = all(checks.values())
    return {
        "contract_schema_version": "cx_ingestion_orchestration_contract.v1",
        "slice": "0922",
        "requirement": "S93",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "pipeline_step_count": len(INGESTION_PIPELINE_STEPS),
        "transition_count": 10,
        "dgx_live_provider_required": False,
        "postgres_required": False,
        "next_slice": "0923",
    }


def _invalid_claim_rejected(run: Mapping[str, Any]) -> bool:
    try:
        claim_ingestion_run(
            run,
            worker_id="late-worker",
            lease_expires_at="2026-09-21T00:04:00Z",
        )
    except IngestionOrchestrationError:
        return True
    return False


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks") or {}
    return (
        "cx_ingestion_orchestration_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"steps={result.get('pipeline_step_count', 0)} "
        f"transitions={result.get('transition_count', 0)} "
        f"dgx_required={result.get('dgx_live_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_ingestion_orchestration_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
