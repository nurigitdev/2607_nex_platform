#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ag.generation_remediation import (  # noqa: E402
    GenerationRemediationError,
    SqlAlchemyGenerationRemediationTaskStore,
    build_generation_remediation_action,
    update_generation_remediation_action_status,
)
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_generation_remediation_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_GENERATION_REMEDIATION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
EXPECTED_JSONB_COLUMNS = {
    "owner_ref": "jsonb",
    "reason_codes": "jsonb",
    "source_refs": "jsonb",
    "evidence": "jsonb",
    "result_ref": "jsonb",
    "metadata": "jsonb",
}
EXPECTED_INDEXES = {
    "idx_ag_generation_remediation_tasks_generation_time",
    "idx_ag_generation_remediation_tasks_status_time",
    "idx_ag_generation_remediation_tasks_type_time",
    "idx_ag_generation_remediation_tasks_owner_time",
}


def run_ag_generation_remediation_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    database_url = env.get(DATABASE_ENV)
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")

    try:
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=PROFILE,
        )
    except MigrationError as exc:
        return _failure("migration_failed", str(exc))

    suffix = uuid4().hex[:12]
    request_id = f"ag-remediation-smoke-{suffix}"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    store = SqlAlchemyGenerationRemediationTaskStore(session_factory)
    remediation_action_id: str | None = None
    try:
        record = build_generation_remediation_action(
            {
                "remediation_action_id": f"ag-remediation-smoke-{suffix}",
                "tenant_id": "smoke-tenant",
                "action_type": "citation_repair",
                "priority": "HIGH",
                "owner_ref": {
                    "owner_type": "service",
                    "owner_id": "nex-cx",
                    "tenant_id": "smoke-tenant",
                },
                "reason_codes": ["citation_quality", "operator_requested_repair"],
                "source_refs": [
                    {
                        "source_service": "nex-ag",
                        "ref_type": "generation_quality",
                        "ref_id": f"cx-gen-smoke-{suffix}",
                        "relation": "caused_by",
                    }
                ],
                "evidence_hashes": [
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ],
                "evidence_previews": [
                    "Citation quality failed and requires a CX repair task."
                ],
                "metadata": {
                    "source": "postgres_smoke",
                    "slice": "0345",
                },
            },
            cx_generation_id=f"cx-gen-smoke-{suffix}",
            request_id=request_id,
            trace_id=trace_id,
            created_at="2026-08-25T00:00:00Z",
        )
        remediation_action_id = record["remediation_action_id"]
        saved = store.save(record)
        loaded = store.get(remediation_action_id)
        listed = store.list_for_generation(record["cx_generation_id"])
        updated = update_generation_remediation_action_status(
            saved,
            {
                "action_status": "ASSIGNED",
                "result_ref": {
                    "source_service": "nex-cx",
                    "ref_type": "repair_execution",
                    "ref_id": f"cx-repair-run-{suffix}",
                },
            },
            request_id=request_id,
            trace_id=trace_id,
            updated_at="2026-08-25T00:05:00Z",
        )
        saved_update = store.save(updated)
        reloaded = store.get(remediation_action_id)
        observations = _db_observations(engine, remediation_action_id)
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "task_saved": saved["remediation_action_id"] == remediation_action_id,
            "task_loaded": loaded == saved,
            "task_listed": [item["remediation_action_id"] for item in listed]
            == [remediation_action_id],
            "status_updated": saved_update["action_status"] == "ASSIGNED",
            "result_ref_round_tripped": reloaded
            and reloaded["result_ref"]["ref_id"] == f"cx-repair-run-{suffix}",
            "table_present": observations.get("table_present") is True,
            "row_count": observations.get("row_count") == 1,
            "jsonb_columns": observations.get("jsonb_columns") == EXPECTED_JSONB_COLUMNS,
            "indexes_present": EXPECTED_INDEXES.issubset(
                set(observations.get("index_names", []))
            ),
            "raw_generation_output_absent": "raw_generation_output" not in saved,
        }
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "failure_code": None if all(checks.values()) else "checks_failed",
            "service": SERVICE_ID,
            "profile": PROFILE,
            "database_env": DATABASE_ENV,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned": list(migration.planned),
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "request_id": request_id,
            "trace_id": trace_id,
            "remediation_action_id": remediation_action_id,
            "cx_generation_id": record["cx_generation_id"],
            "observations": observations,
            "checks": checks,
            "cleanup": {"deleted_rows": store.delete(remediation_action_id)},
        }
    except (GenerationRemediationError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if remediation_action_id is not None:
            _cleanup_remediation_task(engine, remediation_action_id)
        engine.dispose()

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _db_observations(engine: Any, remediation_action_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        table_name = connection.execute(
            text("SELECT to_regclass('public.ag_generation_remediation_tasks')")
        ).scalar()
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        pg_typeof(owner_ref)::text AS owner_ref_type,
                        pg_typeof(reason_codes)::text AS reason_codes_type,
                        pg_typeof(source_refs)::text AS source_refs_type,
                        pg_typeof(evidence)::text AS evidence_type,
                        pg_typeof(result_ref)::text AS result_ref_type,
                        pg_typeof(metadata)::text AS metadata_type
                    FROM ag_generation_remediation_tasks
                    WHERE remediation_action_id = :remediation_action_id
                    GROUP BY
                        pg_typeof(owner_ref)::text,
                        pg_typeof(reason_codes)::text,
                        pg_typeof(source_refs)::text,
                        pg_typeof(evidence)::text,
                        pg_typeof(result_ref)::text,
                        pg_typeof(metadata)::text
                    """
                ),
                {"remediation_action_id": remediation_action_id},
            )
            .mappings()
            .first()
        )
        index_rows = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'ag_generation_remediation_tasks'
                    """
                )
            )
            .mappings()
            .all()
        )
    return {
        "table_present": table_name == "ag_generation_remediation_tasks",
        "row_count": int(row["row_count"]) if row else 0,
        "jsonb_columns": {
            "owner_ref": row["owner_ref_type"] if row else None,
            "reason_codes": row["reason_codes_type"] if row else None,
            "source_refs": row["source_refs_type"] if row else None,
            "evidence": row["evidence_type"] if row else None,
            "result_ref": row["result_ref_type"] if row else None,
            "metadata": row["metadata_type"] if row else None,
        },
        "index_names": sorted(row["indexname"] for row in index_rows),
    }


def _cleanup_remediation_task(engine: Any, remediation_action_id: str) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM ag_generation_remediation_tasks "
                    "WHERE remediation_action_id = :remediation_action_id"
                ),
                {"remediation_action_id": remediation_action_id},
            )
    except SQLAlchemyError:
        return


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    database_url = environ.get(DATABASE_ENV)
    if database_url and database_url in serialized_evidence:
        raise ValueError("AG remediation smoke evidence contains raw database URL.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ag_generation_remediation_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ag_generation_remediation_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"remediation_action_id={evidence['remediation_action_id']} "
            f"row_count={evidence['observations']['row_count']} "
            f"deleted_rows={evidence['cleanup']['deleted_rows']}"
        )
    return (
        "ag_generation_remediation_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG generation remediation PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_generation_remediation_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
