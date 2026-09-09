#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ag.operator_reviews import (  # noqa: E402
    OperatorReviewNoteError,
    SqlAlchemyOperatorReviewNoteStore,
    register_operator_review_note_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_note_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_NOTE_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
RAW_NOTE = "AG operator note smoke raw text must not appear in evidence."


def run_ag_operator_review_note_postgres_smoke(
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
    request_id = f"ag-op-note-smoke-{suffix}"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    idempotency_key = f"ag-op-note-smoke-idem-{suffix}"
    operator_note_id: str | None = None
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        store = SqlAlchemyOperatorReviewNoteStore(session_factory)
        event_store = InMemoryOperationalEventStore()
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_operator_review_note_routes(
            app,
            store=store,
            audit_event_store=event_store,
        )
        client = TestClient(app)
        payload = _smoke_payload(suffix)
        headers = _admin_headers(
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        )
        create_response = client.post(
            "/admin/v1/operator-review/notes",
            headers=headers,
            json=payload,
        )
        create_body = create_response.json()
        operator_note_id = (
            create_body.get("operator_note", {}).get("operator_note_id")
            if isinstance(create_body, dict)
            else None
        )
        replay_response = client.post(
            "/admin/v1/operator-review/notes",
            headers=headers,
            json=payload,
        )
        list_response = client.get(
            "/admin/v1/operator-review/notes?target_service=nex-ag",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        detail_response = (
            client.get(
                f"/admin/v1/operator-review/notes/{operator_note_id}",
                headers=_admin_headers(request_id=request_id, trace_id=trace_id),
            )
            if operator_note_id
            else None
        )
        observations = (
            _db_observations(engine, operator_note_id) if operator_note_id else {}
        )
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "create_status": create_response.status_code == 201,
            "replay_status": replay_response.status_code == 200,
            "replay_idempotent": replay_response.json().get("idempotency_status")
            == "REPLAYED",
            "list_status": list_response.status_code == 200,
            "list_count": list_response.json().get("summary", {}).get("count") == 1,
            "detail_status": (
                detail_response is not None and detail_response.status_code == 200
            ),
            "table_present": observations.get("table_present") is True,
            "row_count": observations.get("row_count") == 1,
            "jsonb_columns": observations.get("jsonb_columns") == {
                "operator_ref": "jsonb",
                "reason_codes": "jsonb",
                "metadata": "jsonb",
            },
            "metadata_idempotency_hash_present": (
                observations.get("metadata_idempotency_hash_present") is True
            ),
            "metadata_raw_idempotency_absent": (
                observations.get("metadata_raw_idempotency_absent") is True
            ),
            "audit_event_recorded": event_store.summary()["total"] == 1,
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
            "operator_note_id": operator_note_id,
            "observations": observations,
            "checks": checks,
            "cleanup": {
                "deleted_rows": (
                    _cleanup_operator_note(engine, operator_note_id)
                    if operator_note_id
                    else 0
                )
            },
        }
    except (OperatorReviewNoteError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if operator_note_id is not None:
            _cleanup_operator_note(engine, operator_note_id)
        engine.dispose()

    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        raw_note=RAW_NOTE,
        idempotency_key=idempotency_key,
    )
    return evidence


def _smoke_payload(suffix: str) -> dict[str, Any]:
    return {
        "target_ref": {
            "target_service": "nex-ag",
            "target_kind": "operator_review_note_smoke",
            "target_id": f"ag-op-note-smoke-target-{suffix}",
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": f"smoke-operator-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "operator_note": RAW_NOTE,
        "note_type": "OBSERVATION",
        "severity": "MEDIUM",
        "reason_codes": ["postgres_smoke", "operator_review_note"],
        "metadata": {"source": "postgres_smoke"},
    }


def _admin_headers(
    *,
    request_id: str,
    trace_id: str,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="smoke-tenant",
        user_id="smoke-admin",
        audience="nex-ag",
        roles=["admin"],
    )
    headers = {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _db_observations(engine: Any, operator_note_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        table_name = connection.execute(text("SELECT to_regclass('public.ag_op_notes')")).scalar()
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        pg_typeof(operator_ref)::text AS operator_ref_type,
                        pg_typeof(reason_codes)::text AS reason_codes_type,
                        pg_typeof(metadata)::text AS metadata_type,
                        bool_or(metadata ? 'idempotency_key_hash')
                            AS metadata_idempotency_hash_present,
                        bool_or(NOT (metadata ? 'idempotency_key'))
                            AS metadata_raw_idempotency_absent
                    FROM ag_op_notes
                    WHERE operator_note_id = :operator_note_id
                    GROUP BY
                        pg_typeof(operator_ref)::text,
                        pg_typeof(reason_codes)::text,
                        pg_typeof(metadata)::text
                    """
                ),
                {"operator_note_id": operator_note_id},
            )
            .mappings()
            .first()
        )
    return {
        "table_present": table_name == "ag_op_notes",
        "row_count": int(row["row_count"]) if row else 0,
        "jsonb_columns": {
            "operator_ref": row["operator_ref_type"] if row else None,
            "reason_codes": row["reason_codes_type"] if row else None,
            "metadata": row["metadata_type"] if row else None,
        },
        "metadata_idempotency_hash_present": (
            bool(row["metadata_idempotency_hash_present"]) if row else False
        ),
        "metadata_raw_idempotency_absent": (
            bool(row["metadata_raw_idempotency_absent"]) if row else False
        ),
    }


def _cleanup_operator_note(engine: Any, operator_note_id: str) -> int:
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM ag_op_notes WHERE operator_note_id = :operator_note_id"),
                {"operator_note_id": operator_note_id},
            )
            return int(result.rowcount or 0)
    except SQLAlchemyError:
        return 0


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
    *,
    raw_note: str,
    idempotency_key: str,
) -> None:
    database_url = environ.get(DATABASE_ENV)
    if database_url and database_url in serialized_evidence:
        raise ValueError("AG operator review note smoke evidence contains raw DB URL.")
    if raw_note and raw_note in serialized_evidence:
        raise ValueError("AG operator review note smoke evidence contains raw note text.")
    if idempotency_key and idempotency_key in serialized_evidence:
        raise ValueError(
            "AG operator review note smoke evidence contains raw idempotency key."
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ag_operator_review_note_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ag_operator_review_note_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"operator_note_id={evidence['operator_note_id']} "
            f"row_count={evidence['observations']['row_count']} "
            f"deleted_rows={evidence['cleanup']['deleted_rows']}"
        )
    return (
        "ag_operator_review_note_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG operator review note PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_operator_review_note_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
