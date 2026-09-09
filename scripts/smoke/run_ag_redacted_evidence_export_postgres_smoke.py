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
    OperatorReviewNoteStore,
    SqlAlchemyOperatorEvidenceExportStore,
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


SCHEMA_VERSION = "ag_redacted_evidence_export_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_REDACTED_EVIDENCE_EXPORT_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
RAW_EVIDENCE_BODY = "AG evidence export raw body must not appear in evidence."


def run_ag_redacted_evidence_export_postgres_smoke(
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
    request_id = f"ag-ev-export-smoke-{suffix}"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    idempotency_key = f"ag-ev-export-smoke-idem-{suffix}"
    target_id = f"ag-ev-export-smoke-target-{suffix}"
    export_id: str | None = None
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        export_store = SqlAlchemyOperatorEvidenceExportStore(session_factory)
        event_store = InMemoryOperationalEventStore()
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_operator_review_note_routes(
            app,
            store=OperatorReviewNoteStore(),
            export_store=export_store,
            audit_event_store=event_store,
        )
        client = TestClient(app)
        payload = _smoke_payload(suffix=suffix, target_id=target_id)
        headers = _admin_headers(
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        )
        create_response = client.post(
            "/admin/v1/operator-review/evidence-exports",
            headers=headers,
            json=payload,
        )
        create_body = create_response.json()
        export_id = (
            create_body.get("export", {}).get("export_id")
            if isinstance(create_body, dict)
            else None
        )
        replay_response = client.post(
            "/admin/v1/operator-review/evidence-exports",
            headers=headers,
            json=payload,
        )
        list_response = client.get(
            (
                "/admin/v1/operator-review/evidence-exports"
                f"?target_service=nex-ag&target_kind=redacted_evidence_export_smoke"
                f"&target_id={target_id}"
            ),
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        detail_response = (
            client.get(
                f"/admin/v1/operator-review/evidence-exports/{export_id}",
                headers=_admin_headers(request_id=request_id, trace_id=trace_id),
            )
            if export_id
            else None
        )
        observations = _db_observations(engine, export_id) if export_id else {}
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
                "evidence_manifest": "jsonb",
                "metadata": "jsonb",
            },
            "metadata_idempotency_hash_present": (
                observations.get("metadata_idempotency_hash_present") is True
            ),
            "metadata_raw_idempotency_absent": (
                observations.get("metadata_raw_idempotency_absent") is True
            ),
            "manifest_raw_payloads_excluded": (
                observations.get("manifest_raw_payloads_excluded") is True
            ),
            "manifest_storage_paths_excluded": (
                observations.get("manifest_storage_paths_excluded") is True
            ),
            "evidence_item_count": observations.get("evidence_item_count") == 2,
            "evidence_hash_shape": observations.get("evidence_hash_shape") is True,
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
            "export_id": export_id,
            "observations": observations,
            "checks": checks,
            "cleanup": {
                "deleted_rows": (
                    _cleanup_evidence_export(engine, export_id) if export_id else 0
                )
            },
        }
    except (OperatorReviewNoteError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if export_id is not None:
            _cleanup_evidence_export(engine, export_id)
        engine.dispose()

    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        raw_evidence_body=RAW_EVIDENCE_BODY,
        idempotency_key=idempotency_key,
    )
    return evidence


def _smoke_payload(*, suffix: str, target_id: str) -> dict[str, Any]:
    return {
        "target_ref": {
            "target_service": "nex-ag",
            "target_kind": "redacted_evidence_export_smoke",
            "target_id": target_id,
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": f"smoke-operator-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "export_format": "json",
        "export_status": "READY",
        "evidence_refs": [
            {
                "source_service": "nex-ae-api",
                "evidence_type": "worker_result",
                "evidence_id": f"worker-result-smoke-{suffix}",
                "relation": "primary",
                "content_hash": "a" * 64,
                "redaction_status": "HASH_ONLY",
            },
            {
                "source_service": "nex-ag",
                "evidence_type": "operator_note",
                "evidence_id": f"ag-op-note-smoke-{suffix}",
                "relation": "operator_context",
                "redaction_status": "METADATA_ONLY",
            },
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


def _db_observations(engine: Any, export_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        table_name = connection.execute(
            text("SELECT to_regclass('public.ag_ev_exports')")
        ).scalar()
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        pg_typeof(operator_ref)::text AS operator_ref_type,
                        pg_typeof(evidence_manifest)::text
                            AS evidence_manifest_type,
                        pg_typeof(metadata)::text AS metadata_type,
                        bool_or(metadata ? 'idempotency_key_hash')
                            AS metadata_idempotency_hash_present,
                        bool_or(NOT (metadata ? 'idempotency_key'))
                            AS metadata_raw_idempotency_absent,
                        bool_or(
                            (evidence_manifest->>'raw_payloads_included')
                            = 'false'
                        ) AS manifest_raw_payloads_excluded,
                        bool_or(
                            (evidence_manifest->>'storage_paths_included')
                            = 'false'
                        ) AS manifest_storage_paths_excluded,
                        max(evidence_item_count) AS evidence_item_count,
                        bool_or(evidence_hash ~ '^[0-9a-f]{64}$')
                            AS evidence_hash_shape
                    FROM ag_ev_exports
                    WHERE export_id = :export_id
                    GROUP BY
                        pg_typeof(operator_ref)::text,
                        pg_typeof(evidence_manifest)::text,
                        pg_typeof(metadata)::text
                    """
                ),
                {"export_id": export_id},
            )
            .mappings()
            .first()
        )
    return {
        "table_present": table_name == "ag_ev_exports",
        "row_count": int(row["row_count"]) if row else 0,
        "jsonb_columns": {
            "operator_ref": row["operator_ref_type"] if row else None,
            "evidence_manifest": row["evidence_manifest_type"] if row else None,
            "metadata": row["metadata_type"] if row else None,
        },
        "metadata_idempotency_hash_present": (
            bool(row["metadata_idempotency_hash_present"]) if row else False
        ),
        "metadata_raw_idempotency_absent": (
            bool(row["metadata_raw_idempotency_absent"]) if row else False
        ),
        "manifest_raw_payloads_excluded": (
            bool(row["manifest_raw_payloads_excluded"]) if row else False
        ),
        "manifest_storage_paths_excluded": (
            bool(row["manifest_storage_paths_excluded"]) if row else False
        ),
        "evidence_item_count": int(row["evidence_item_count"] or 0) if row else 0,
        "evidence_hash_shape": bool(row["evidence_hash_shape"]) if row else False,
    }


def _cleanup_evidence_export(engine: Any, export_id: str) -> int:
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM ag_ev_exports WHERE export_id = :export_id"),
                {"export_id": export_id},
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
    raw_evidence_body: str,
    idempotency_key: str,
) -> None:
    database_url = environ.get(DATABASE_ENV)
    if database_url and database_url in serialized_evidence:
        raise ValueError("AG evidence export smoke evidence contains raw DB URL.")
    if raw_evidence_body and raw_evidence_body in serialized_evidence:
        raise ValueError("AG evidence export smoke evidence contains raw body.")
    if idempotency_key and idempotency_key in serialized_evidence:
        raise ValueError(
            "AG evidence export smoke evidence contains raw idempotency key."
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ag_redacted_evidence_export_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ag_redacted_evidence_export_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"export_id={evidence['export_id']} "
            f"row_count={evidence['observations']['row_count']} "
            f"deleted_rows={evidence['cleanup']['deleted_rows']}"
        )
    return (
        "ag_redacted_evidence_export_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG redacted evidence export PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_redacted_evidence_export_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
