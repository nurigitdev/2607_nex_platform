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

from nex_ag.operations import register_unified_operation_routes  # noqa: E402
from nex_ag.operator_review_workbench import (  # noqa: E402
    register_operator_review_workbench_routes,
)
from nex_ag.operator_reviews import (  # noqa: E402
    OperatorReviewNoteError,
    SqlAlchemyOperatorEvidenceExportStore,
    SqlAlchemyOperatorReviewNoteStore,
    register_operator_review_note_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_workbench_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_WORKBENCH_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
RAW_NOTE = "AG workbench smoke raw note must not appear in evidence."


def run_ag_operator_review_workbench_postgres_smoke(
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
    request_id = f"ag-op-workbench-smoke-{suffix}"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    target_id = f"ag-op-workbench-smoke-target-{suffix}"
    note_idempotency_key = f"ag-op-workbench-note-idem-{suffix}"
    export_idempotency_key = f"ag-op-workbench-export-idem-{suffix}"
    operator_note_id: str | None = None
    export_id: str | None = None
    engine: Any | None = None
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        note_store = SqlAlchemyOperatorReviewNoteStore(session_factory)
        export_store = SqlAlchemyOperatorEvidenceExportStore(session_factory)
        event_store = InMemoryOperationalEventStore()
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_operator_review_note_routes(
            app,
            store=note_store,
            export_store=export_store,
            audit_event_store=event_store,
        )
        register_operator_review_workbench_routes(
            app,
            note_store=note_store,
            export_store=export_store,
        )
        register_unified_operation_routes(
            app,
            event_store=event_store,
            operator_review_note_store=note_store,
            operator_review_export_store=export_store,
        )
        client = TestClient(app)
        note_response = client.post(
            "/admin/v1/operator-review/notes",
            headers=_admin_headers(
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=note_idempotency_key,
            ),
            json=_note_payload(suffix=suffix, target_id=target_id),
        )
        note_body = note_response.json()
        operator_note_id = (
            note_body.get("operator_note", {}).get("operator_note_id")
            if isinstance(note_body, dict)
            else None
        )
        export_response = client.post(
            "/admin/v1/operator-review/evidence-exports",
            headers=_admin_headers(
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=export_idempotency_key,
            ),
            json=_export_payload(suffix=suffix, target_id=target_id),
        )
        export_body = export_response.json()
        export_id = (
            export_body.get("export", {}).get("export_id")
            if isinstance(export_body, dict)
            else None
        )
        query = (
            f"target_service=nex-ag&target_kind=operator_review_workbench_smoke"
            f"&target_id={target_id}&note_status=ACTIVE&export_status=FAILED"
        )
        workbench_response = client.get(
            f"/admin/v1/operator-review/workbench?{query}",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        rollup_response = client.get(
            f"/admin/v1/operator-review/workbench/rollups?{query}",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        dashboard_response = client.get(
            "/admin/v1/operations/dashboard?service_id=nex-ag&recent_limit=5",
            headers=_service_headers(request_id=request_id, trace_id=trace_id),
        )
        issue_response = client.get(
            "/admin/v1/operations/issue-candidates?service_id=nex-ag&recent_limit=5",
            headers=_service_headers(request_id=request_id, trace_id=trace_id),
        )
        observations = _db_observations(engine, target_id)
        workbench_body = workbench_response.json()
        rollup_body = rollup_response.json()
        dashboard_body = dashboard_response.json()
        issue_body = issue_response.json()
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "note_create_status": note_response.status_code == 201,
            "export_create_status": export_response.status_code == 201,
            "workbench_status": workbench_response.status_code == 200,
            "workbench_target_count": (
                workbench_body.get("summary", {}).get("target_count") == 1
            ),
            "workbench_filters": _matches_expected_filters(
                workbench_body.get("filters", {}),
                {
                    "target_service": "nex-ag",
                    "target_kind": "operator_review_workbench_smoke",
                    "target_id": target_id,
                    "note_status": "ACTIVE",
                    "export_status": "FAILED",
                },
            ),
            "rollup_status": rollup_response.status_code == 200,
            "rollup_blocked_attention": _first_attention_status(rollup_body)
            == "BLOCKED",
            "dashboard_status": dashboard_response.status_code == 200,
            "dashboard_workbench_visible": (
                dashboard_body.get("operator_review_workbench", {})
                .get("summary", {})
                .get("target_count")
                == 1
            ),
            "issue_status": issue_response.status_code == 200,
            "issue_candidate_visible": any(
                candidate.get("rule_id") == "operator_review_attention_required.v1"
                for candidate in issue_body.get("issue_candidates", [])
            ),
            "tables_present": observations.get("tables_present") == {
                "ag_op_notes": True,
                "ag_ev_exports": True,
            },
            "table_rows": observations.get("note_count") == 1
            and observations.get("export_count") == 1,
            "jsonb_columns": observations.get("jsonb_columns") == {
                "note_operator_ref": "jsonb",
                "export_operator_ref": "jsonb",
                "evidence_manifest": "jsonb",
            },
            "failed_export_persisted": observations.get("failed_export_count") == 1,
            "active_high_note_persisted": (
                observations.get("active_high_note_count") == 1
            ),
            "audit_events_recorded": event_store.summary()["total"] == 2,
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
            "export_id": export_id,
            "target_id": target_id,
            "observations": observations,
            "checks": checks,
            "cleanup": _cleanup_workbench_rows(engine, operator_note_id, export_id),
        }
    except (OperatorReviewNoteError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if engine is not None:
            _cleanup_workbench_rows(engine, operator_note_id, export_id)
            engine.dispose()

    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        raw_note=RAW_NOTE,
        idempotency_keys=(note_idempotency_key, export_idempotency_key),
    )
    return evidence


def _note_payload(*, suffix: str, target_id: str) -> dict[str, Any]:
    return {
        "target_ref": {
            "target_service": "nex-ag",
            "target_kind": "operator_review_workbench_smoke",
            "target_id": target_id,
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": f"smoke-operator-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "operator_note": RAW_NOTE,
        "note_type": "OBSERVATION",
        "severity": "HIGH",
        "reason_codes": ["postgres_smoke", "operator_review_workbench"],
        "metadata": {"source": "postgres_smoke"},
    }


def _export_payload(*, suffix: str, target_id: str) -> dict[str, Any]:
    return {
        "target_ref": {
            "target_service": "nex-ag",
            "target_kind": "operator_review_workbench_smoke",
            "target_id": target_id,
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": f"smoke-operator-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "export_format": "json",
        "export_status": "FAILED",
        "evidence_refs": [
            {
                "source_service": "nex-ag",
                "evidence_type": "operator_note",
                "evidence_id": f"ag-op-workbench-smoke-note-{suffix}",
                "relation": "operator_context",
                "redaction_status": "METADATA_ONLY",
            }
        ],
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


def _service_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _db_observations(engine: Any, target_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        note_table = connection.execute(
            text("SELECT to_regclass('public.ag_op_notes')")
        ).scalar()
        export_table = connection.execute(
            text("SELECT to_regclass('public.ag_ev_exports')")
        ).scalar()
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*)
                            FROM ag_op_notes
                            WHERE target_id = :target_id
                        ) AS note_count,
                        (
                            SELECT count(*)
                            FROM ag_ev_exports
                            WHERE target_id = :target_id
                        ) AS export_count,
                        (
                            SELECT pg_typeof(operator_ref)::text
                            FROM ag_op_notes
                            WHERE target_id = :target_id
                            LIMIT 1
                        ) AS note_operator_ref_type,
                        (
                            SELECT pg_typeof(operator_ref)::text
                            FROM ag_ev_exports
                            WHERE target_id = :target_id
                            LIMIT 1
                        ) AS export_operator_ref_type,
                        (
                            SELECT pg_typeof(evidence_manifest)::text
                            FROM ag_ev_exports
                            WHERE target_id = :target_id
                            LIMIT 1
                        ) AS evidence_manifest_type,
                        (
                            SELECT count(*)
                            FROM ag_ev_exports
                            WHERE target_id = :target_id
                                AND export_status = 'FAILED'
                        ) AS failed_export_count,
                        (
                            SELECT count(*)
                            FROM ag_op_notes
                            WHERE target_id = :target_id
                                AND note_status = 'ACTIVE'
                                AND severity = 'HIGH'
                        ) AS active_high_note_count
                    """
                ),
                {"target_id": target_id},
            )
            .mappings()
            .one()
        )
    return {
        "tables_present": {
            "ag_op_notes": _regclass_matches(note_table, "ag_op_notes"),
            "ag_ev_exports": _regclass_matches(export_table, "ag_ev_exports"),
        },
        "note_count": int(row["note_count"]),
        "export_count": int(row["export_count"]),
        "jsonb_columns": {
            "note_operator_ref": row["note_operator_ref_type"],
            "export_operator_ref": row["export_operator_ref_type"],
            "evidence_manifest": row["evidence_manifest_type"],
        },
        "failed_export_count": int(row["failed_export_count"]),
        "active_high_note_count": int(row["active_high_note_count"]),
    }


def _matches_expected_filters(
    actual: object,
    expected: Mapping[str, Any],
) -> bool:
    if not isinstance(actual, Mapping):
        return False
    return all(actual.get(key) == value for key, value in expected.items())


def _first_attention_status(rollup_body: Mapping[str, Any]) -> str | None:
    attention = rollup_body.get("attention")
    if not isinstance(attention, Mapping):
        return None
    items = attention.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    return first.get("attention_status") if isinstance(first, Mapping) else None


def _regclass_matches(value: object, table_name: str) -> bool:
    if value is None:
        return False
    return str(value).split(".")[-1] == table_name


def _cleanup_workbench_rows(
    engine: Any,
    operator_note_id: str | None,
    export_id: str | None,
) -> dict[str, int]:
    deleted_notes = 0
    deleted_exports = 0
    if not operator_note_id and not export_id:
        return {"notes": deleted_notes, "exports": deleted_exports}
    try:
        with engine.begin() as connection:
            if operator_note_id:
                result = connection.execute(
                    text(
                        "DELETE FROM ag_op_notes "
                        "WHERE operator_note_id = :operator_note_id"
                    ),
                    {"operator_note_id": operator_note_id},
                )
                deleted_notes = int(result.rowcount or 0)
            if export_id:
                result = connection.execute(
                    text("DELETE FROM ag_ev_exports WHERE export_id = :export_id"),
                    {"export_id": export_id},
                )
                deleted_exports = int(result.rowcount or 0)
    except SQLAlchemyError:
        return {"notes": 0, "exports": 0}
    return {"notes": deleted_notes, "exports": deleted_exports}


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
    idempotency_keys: tuple[str, str],
) -> None:
    database_url = environ.get(DATABASE_ENV)
    if database_url and database_url in serialized_evidence:
        raise ValueError("AG workbench smoke evidence contains raw DB URL.")
    if raw_note and raw_note in serialized_evidence:
        raise ValueError("AG workbench smoke evidence contains raw note text.")
    for idempotency_key in idempotency_keys:
        if idempotency_key and idempotency_key in serialized_evidence:
            raise ValueError(
                "AG workbench smoke evidence contains raw idempotency key."
            )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_operator_review_workbench_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        cleanup = evidence["cleanup"]
        return (
            "ag_operator_review_workbench_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"target_id={evidence['target_id']} "
            f"notes={evidence['observations']['note_count']} "
            f"exports={evidence['observations']['export_count']} "
            f"deleted_notes={cleanup['notes']} "
            f"deleted_exports={cleanup['exports']}"
        )
    return (
        "ag_operator_review_workbench_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG operator review workbench PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_operator_review_workbench_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
