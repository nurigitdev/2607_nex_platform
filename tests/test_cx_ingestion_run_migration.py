from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "database"
    / "nex-cx"
    / "migrations"
    / "0923_cx_ingest_run_persistence.sql"
)


def normalized_sql() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower()).strip()


def test_migration_defines_short_metadata_only_ingestion_run_table() -> None:
    sql = normalized_sql()
    assert sql.startswith("begin;") and sql.endswith("commit;")
    assert "create table if not exists cx_ingest_runs" in sql
    assert len("cx_ingest_runs") == 14
    assert "run_schema_version text not null default 'cx_ingest_run.v1'" in sql
    assert "step_states jsonb not null" in sql
    assert "checkpoint_version integer not null" in sql
    assert "lease_owner text" in sql
    assert "lease_expires_at timestamptz" in sql
    assert "retry_at timestamptz" in sql
    assert "last_error jsonb" in sql
    assert "references service_jobs(job_id)" in sql
    assert "references cx_content_objects(content_object_id)" in sql


def test_migration_enforces_owner_idempotency_and_state_invariants() -> None:
    sql = normalized_sql()
    for token in (
        "ux_cx_ingest_runs_owner_key",
        "ck_cx_ingest_runs_attempts",
        "ck_cx_ingest_runs_lease",
        "ck_cx_ingest_runs_retry",
        "ck_cx_ingest_runs_completed",
        "cx_assert_ingest_run_owner",
        "tr_cx_ingest_runs_owner",
        "ix_cx_ingest_runs_status_retry",
        "ix_cx_ingest_runs_lease",
        "ix_cx_ingest_runs_owner_doc",
        "0923_cx_ingest_run_persistence",
    ):
        assert token in sql


def test_migration_excludes_private_payload_columns_and_secrets() -> None:
    sql = normalized_sql()
    for forbidden in (
        "source_text text",
        "source_bytes bytea",
        "markdown text",
        "prompt text",
        "vector vector",
        "embedding vector",
        "api_key",
        "nuri1004",
    ):
        assert forbidden not in sql
