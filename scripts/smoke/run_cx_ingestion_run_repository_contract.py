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
    build_ingestion_run,
    claim_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (  # noqa: E402
    InMemoryIngestionRunRepository,
    IngestionRunRepositoryError,
)


MIGRATION = (
    ROOT
    / "database"
    / "nex-cx"
    / "migrations"
    / "0923_cx_ingest_run_persistence.sql"
)


def run_cx_ingestion_run_repository_contract() -> dict[str, Any]:
    repository = InMemoryIngestionRunRepository()
    initial = build_ingestion_run(
        document_id="contract-document",
        job_id="contract-job",
        idempotency_key="contract-upload",
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        trace_id="contract-trace",
        request_id="contract-request",
        created_at="2026-09-21T00:00:00Z",
    )
    created = repository.create(initial)
    duplicate = repository.create(initial)
    claimed = claim_ingestion_run(
        created,
        worker_id="worker-1",
        lease_expires_at="2026-09-21T00:02:00Z",
        observed_at="2026-09-21T00:00:01Z",
    )
    saved = repository.save(claimed, expected_checkpoint_version=0)
    migration_text = MIGRATION.read_text(encoding="utf-8")
    checks = {
        "create_round_trip": created == initial,
        "owner_idempotency": duplicate == created,
        "checkpoint_round_trip": saved == claimed,
        "cross_owner_hidden": repository.get(
            created["run_id"],
            tenant_id="tenant-a",
            owner_subject_id="user-b",
        )
        is None,
        "stale_writer_rejected": _stale_writer_rejected(repository, claimed),
        "migration_present": MIGRATION.is_file(),
        "short_table_name": "CREATE TABLE IF NOT EXISTS cx_ingest_runs" in migration_text,
        "private_columns_absent": all(
            token not in migration_text.lower()
            for token in ("source_text text", "source_bytes bytea", "prompt text")
        ),
    }
    passed = all(checks.values())
    return {
        "contract_schema_version": "cx_ingestion_run_repository_contract.v1",
        "slice": "0923",
        "requirement": "S93",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "table": "cx_ingest_runs",
        "table_name_length": len("cx_ingest_runs"),
        "postgres_required": False,
        "dgx_live_provider_required": False,
        "next_slice": "0924",
    }


def _stale_writer_rejected(
    repository: InMemoryIngestionRunRepository,
    run: Mapping[str, Any],
) -> bool:
    try:
        repository.save(run, expected_checkpoint_version=0)
    except IngestionRunRepositoryError as exc:
        return exc.error_code == "cx.ingestion_run.checkpoint_conflict"
    return False


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks") or {}
    return (
        "cx_ingestion_run_repository="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"table={result.get('table', 'unknown')} "
        f"postgres_required={result.get('postgres_required', False)} "
        f"dgx_required={result.get('dgx_live_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_ingestion_run_repository_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
