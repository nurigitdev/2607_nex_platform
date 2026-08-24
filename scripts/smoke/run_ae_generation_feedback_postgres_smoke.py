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
AE_PATH = ROOT / "services" / "nex-ae-api"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ae_api.generation_feedback import (  # noqa: E402
    GenerationFeedbackError,
    SqlAlchemyGenerationFeedbackStore,
    build_generation_feedback_record,
)
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ae_generation_feedback_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_GENERATION_FEEDBACK_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
SERVICE_ID = "nex-ae-api"
PROFILE = "test"


def run_ae_generation_feedback_postgres_smoke(
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
    request_id = f"ae-feedback-smoke-{suffix}"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    store = SqlAlchemyGenerationFeedbackStore(session_factory)
    feedback_id: str | None = None
    try:
        record = build_generation_feedback_record(
            {
                "feedback_id": f"ae-feedback-smoke-{suffix}",
                "tenant_id": "smoke-tenant",
                "user_id": f"smoke-user-{suffix}",
                "interaction_id": f"ae-chat-smoke-{suffix}",
                "chat_document_id": f"ae-chat-doc-smoke-{suffix}",
                "cx_generation_id": f"cx-gen-smoke-{suffix}",
                "feedback_value": "negative",
                "feedback_reasons": ["citation_issue", "incomplete"],
                "feedback_comment": "Citation [2] did not support the answer.",
                "quality_issue_refs": [
                    {
                        "source_service": "nex-cx",
                        "issue_type": "citation_quality",
                        "issue_code": "citation_missing",
                        "issue_ref_id": f"cx-gen-smoke-{suffix}",
                    }
                ],
            },
            request_id=request_id,
            trace_id=trace_id,
        )
        feedback_id = record["feedback_id"]
        saved = store.save(record)
        loaded = store.get(feedback_id)
        listed = store.list_for_interaction(record["interaction_id"])
        observations = _db_observations(engine, feedback_id)
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "feedback_saved": saved["feedback_id"] == feedback_id,
            "feedback_loaded": loaded == saved,
            "feedback_listed": [item["feedback_id"] for item in listed] == [feedback_id],
            "table_present": observations.get("table_present") is True,
            "row_count": observations.get("row_count") == 1,
            "jsonb_columns": observations.get("jsonb_columns") == {
                "feedback_reasons": "jsonb",
                "quality_issue_refs": "jsonb",
                "metadata": "jsonb",
            },
            "raw_comment_absent": "feedback_comment" not in saved,
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
            "feedback_id": feedback_id,
            "interaction_id": record["interaction_id"],
            "observations": observations,
            "checks": checks,
            "cleanup": {"deleted_rows": store.delete(feedback_id)},
        }
    except (GenerationFeedbackError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if feedback_id is not None:
            _cleanup_feedback(engine, feedback_id)
        engine.dispose()

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _db_observations(engine: Any, feedback_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        table_name = connection.execute(
            text("SELECT to_regclass('public.ae_generation_feedback')")
        ).scalar()
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        pg_typeof(feedback_reasons)::text AS feedback_reasons_type,
                        pg_typeof(quality_issue_refs)::text AS quality_issue_refs_type,
                        pg_typeof(metadata)::text AS metadata_type
                    FROM ae_generation_feedback
                    WHERE feedback_id = :feedback_id
                    GROUP BY
                        pg_typeof(feedback_reasons)::text,
                        pg_typeof(quality_issue_refs)::text,
                        pg_typeof(metadata)::text
                    """
                ),
                {"feedback_id": feedback_id},
            )
            .mappings()
            .first()
        )
    return {
        "table_present": table_name == "ae_generation_feedback",
        "row_count": int(row["row_count"]) if row else 0,
        "jsonb_columns": {
            "feedback_reasons": row["feedback_reasons_type"] if row else None,
            "quality_issue_refs": row["quality_issue_refs_type"] if row else None,
            "metadata": row["metadata_type"] if row else None,
        },
    }


def _cleanup_feedback(engine: Any, feedback_id: str) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ae_generation_feedback WHERE feedback_id = :feedback_id"),
                {"feedback_id": feedback_id},
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
        raise ValueError("AE feedback smoke evidence contains raw database URL.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_generation_feedback_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_generation_feedback_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"feedback_id={evidence['feedback_id']} "
            f"row_count={evidence['observations']['row_count']} "
            f"deleted_rows={evidence['cleanup']['deleted_rows']}"
        )
    return (
        "ae_generation_feedback_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE generation feedback PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_generation_feedback_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
