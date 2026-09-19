#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
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

from nex_ag.audit_evidence_api import register_audit_evidence_routes  # noqa: E402
from nex_ag.audit_evidence_operations import (  # noqa: E402
    AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
    AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
)
from nex_ag.operator_reviews import (  # noqa: E402
    OperatorReviewNoteError,
    SqlAlchemyOperatorEvidenceExportStore,
    build_operator_evidence_export_record,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_operational_event,
    build_service_app,
    build_session_factory,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_audit_evidence_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_AUDIT_EVIDENCE_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
REFERENCE_TIME = "2026-09-20T09:00:00Z"
SOURCE_EVENT_TYPE = "ag.audit_evidence.smoke_source"
RAW_EVENT_MESSAGE = "AG audit evidence smoke source message must stay private."
RAW_EVENT_CREDENTIAL = "private-audit-evidence-credential-0868"
RAW_EXPORT_BODY = "AG audit evidence smoke export body must stay private."


def run_ag_audit_evidence_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
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
        return _failure(
            "migration_failed",
            _redact_detail(str(exc), database_url=database_url),
        )

    suffix = uuid4().hex[:12]
    context = {
        "trace_id": uuid4().hex,
        "request_id": f"ag-audit-evidence-smoke-request-{suffix}",
        "source_event_id": f"ag-audit-evidence-smoke-event-{suffix}",
        "export_id": f"ag-audit-evidence-smoke-export-{suffix}",
        "target_id": f"ag-audit-evidence-smoke-target-{suffix}",
        "idempotency_key": f"ag-audit-evidence-smoke-idem-{suffix}",
        "operator_id": f"ag-audit-evidence-smoke-operator-{suffix}",
    }
    engine: Any | None = None
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        event_store = SqlAlchemyOperationalEventStore(session_factory)
        export_store = SqlAlchemyOperatorEvidenceExportStore(session_factory)
        evidence = _execute_smoke(
            engine,
            event_store=event_store,
            export_store=export_store,
            migration=migration,
            database_url=database_url,
            context=context,
        )
        cleanup = _cleanup_owned_rows(engine, context=context)
        cleanup_done = True
        evidence["cleanup"] = cleanup
        evidence["checks"]["owned_rows_deleted"] = (
            cleanup["events"] == 3
            and cleanup["exports"] == 1
            and cleanup["remaining_rows"] == 0
        )
        passed = all(evidence["checks"].values())
        evidence["status"] = "PASS" if passed else "FAIL"
        evidence["failure_code"] = None if passed else "checks_failed"
    except (
        OperatorReviewNoteError,
        SQLAlchemyError,
        RuntimeError,
        ValueError,
    ) as exc:
        evidence = _failure(
            "smoke_execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    finally:
        if engine is not None and not cleanup_done:
            _cleanup_owned_rows(engine, context=context)
        if engine is not None:
            engine.dispose()

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_smoke(
    engine: Any,
    *,
    event_store: Any,
    export_store: Any,
    migration: Any,
    database_url: str,
    context: Mapping[str, str],
) -> dict[str, Any]:
    source_event = build_operational_event(
        service_id=SERVICE_ID,
        event_type=SOURCE_EVENT_TYPE,
        severity="INFO",
        message=RAW_EVENT_MESSAGE,
        trace_id=context["trace_id"],
        request_id=context["request_id"],
        subject_ref={
            "type": "audit_evidence_smoke",
            "id": context["target_id"],
        },
        details={
            "credential": RAW_EVENT_CREDENTIAL,
            "target_id": context["target_id"],
        },
        created_at=REFERENCE_TIME,
        event_id=context["source_event_id"],
    )
    event_store.append(source_event)
    export_store.save(
        build_operator_evidence_export_record(
            _export_payload(context),
            request_id=context["request_id"],
            trace_id=context["trace_id"],
            idempotency_key=context["idempotency_key"],
            created_at=REFERENCE_TIME,
        )
    )

    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_audit_evidence_routes(
        app,
        event_store=event_store,
        export_store=export_store,
        audit_event_store=event_store,
    )
    client = TestClient(app)
    headers = _admin_headers(context)
    create_response = client.post(
        "/admin/v1/audit-integrity/evidence-packages",
        headers=headers,
        json={
            "trace_id": context["trace_id"],
            "expected_event_ids": [context["source_event_id"]],
            "required_event_types": [SOURCE_EVENT_TYPE],
        },
    )
    create_body = _mapping(create_response.json())
    package = _mapping(create_body.get("package"))
    verify_response = client.post(
        "/admin/v1/audit-integrity/evidence-packages/verify",
        headers=headers,
        json={"package": package},
    )
    verify_body = _mapping(verify_response.json())
    operations_response = client.get(
        "/admin/v1/operations/audit-integrity",
        headers=headers,
        params={"recent_limit": 10},
    )
    operations_body = _mapping(operations_response.json())
    observation = _database_observation(engine, context=context)
    serialized_responses = json.dumps(
        [create_body, verify_body, operations_body],
        default=str,
    )
    checks = {
        "migration_ran": migration.service_id == SERVICE_ID,
        "backend_is_postgresql": _engine_backend(engine).startswith("postgresql"),
        "test_database_selected": _engine_database(engine) == "nex_ag_test",
        "tables_present": all(observation["tables_present"].values()),
        "no_new_package_table": observation["package_table_absent"] is True,
        "create_status": create_response.status_code == 200,
        "server_selected_records": create_body.get("selection")
        == {
            "server_selected": True,
            "event_count": 1,
            "evidence_export_count": 1,
            "expected_event_count": 1,
            "required_event_type_count": 1,
        },
        "package_verified": package.get("verification_status") == "VERIFIED",
        "verify_status": (
            verify_response.status_code == 200
            and _mapping(verify_body.get("verification")).get(
                "verification_status"
            )
            == "VERIFIED"
        ),
        "operations_status": (
            operations_response.status_code == 200
            and operations_body.get("integrity_status") == "READY"
            and _mapping(operations_body.get("summary")).get(
                "package_generation_count"
            )
            == 1
            and _mapping(operations_body.get("summary")).get(
                "package_verification_count"
            )
            == 1
        ),
        "event_rows_selected": (
            observation["source_event_count"] == 1
            and observation["generated_event_count"] == 1
            and observation["verified_event_count"] == 1
            and observation["event_count"] == 3
        ),
        "export_row_selected": (
            observation["export_count"] == 1
            and observation["hash_ready_export_count"] == 1
        ),
        "package_id_persisted_in_audit_events": (
            observation["package_event_count"] == 2
        ),
        "responses_redacted": not any(
            value in serialized_responses
            for value in (
                RAW_EVENT_MESSAGE,
                RAW_EVENT_CREDENTIAL,
                RAW_EXPORT_BODY,
            )
        ),
    }
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PENDING",
        "failure_code": None,
        "service": SERVICE_ID,
        "profile": PROFILE,
        "database_env": DATABASE_ENV,
        "redacted_database_url": redact_database_url(database_url),
        "migration": {
            "planned": list(migration.planned),
            "applied": list(migration.applied),
            "skipped": list(migration.skipped),
        },
        "owned_context": {
            "trace_id": context["trace_id"],
            "source_event_id": context["source_event_id"],
            "export_id": context["export_id"],
            "target_id": context["target_id"],
        },
        "package": {
            "package_id": package.get("package_id"),
            "verification_status": package.get("verification_status"),
            "manifest_hash": package.get("manifest_hash"),
            "package_hash": package.get("package_hash"),
        },
        "observation": observation,
        "checks": checks,
    }


def _export_payload(context: Mapping[str, str]) -> dict[str, Any]:
    return {
        "export_id": context["export_id"],
        "target_ref": {
            "target_service": SERVICE_ID,
            "target_kind": "audit_evidence_postgres_smoke",
            "target_id": context["target_id"],
        },
        "operator_ref": {
            "operator_type": "service",
            "operator_id": context["operator_id"],
            "tenant_id": "smoke-tenant",
        },
        "export_status": "READY",
        "export_format": "json",
        "evidence_refs": [
            {
                "source_service": SERVICE_ID,
                "evidence_type": "operational_event",
                "evidence_id": context["source_event_id"],
                "content_hash": _sha256_text(RAW_EXPORT_BODY),
                "redaction_status": "REDACTED",
            }
        ],
        "metadata": {"source": "postgres_smoke", "slice": "0868"},
    }


def _admin_headers(context: Mapping[str, str]) -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="smoke-tenant",
        user_id="smoke-admin",
        audience=SERVICE_ID,
        roles=["admin"],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": context["request_id"],
        "traceparent": f"00-{context['trace_id']}-00f067aa0ba902b7-01",
    }


def _database_observation(
    engine: Any,
    *,
    context: Mapping[str, str],
) -> dict[str, Any]:
    with engine.connect() as connection:
        tables = {
            table_name: _regclass_matches(
                connection.execute(
                    text(f"SELECT to_regclass('public.{table_name}')")
                ).scalar(),
                table_name,
            )
            for table_name in ("service_operational_events", "ag_ev_exports")
        }
        package_table_absent = connection.execute(
            text("SELECT to_regclass('public.ag_audit_evidence_packages')")
        ).scalar() is None
        row = connection.execute(
            text(
                """
                SELECT current_database() AS database_name,
                       (SELECT count(*) FROM service_operational_events
                        WHERE trace_id = :trace_id) AS event_count,
                       (SELECT count(*) FROM service_operational_events
                        WHERE event_id = :source_event_id
                          AND event_type = :source_event_type)
                          AS source_event_count,
                       (SELECT count(*) FROM service_operational_events
                        WHERE trace_id = :trace_id
                          AND event_type = :generated_event_type)
                          AS generated_event_count,
                       (SELECT count(*) FROM service_operational_events
                        WHERE trace_id = :trace_id
                          AND event_type = :verified_event_type)
                          AS verified_event_count,
                       (SELECT count(*) FROM service_operational_events
                        WHERE trace_id = :trace_id
                          AND details->>'package_id' LIKE 'ag-audit-package-%')
                          AS package_event_count,
                       (SELECT count(*) FROM ag_ev_exports
                        WHERE export_id = :export_id
                          AND trace_id = :trace_id) AS export_count,
                       (SELECT count(*) FROM ag_ev_exports
                        WHERE export_id = :export_id
                          AND evidence_hash ~ '^[0-9a-f]{64}$')
                          AS hash_ready_export_count
                """
            ),
            {
                **context,
                "source_event_type": SOURCE_EVENT_TYPE,
                "generated_event_type": AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
                "verified_event_type": AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
            },
        ).mappings().one()
    return {
        "backend": _engine_backend(engine),
        "database": str(row.get("database_name") or ""),
        "tables_present": tables,
        "package_table_absent": package_table_absent,
        "event_count": int(row.get("event_count") or 0),
        "source_event_count": int(row.get("source_event_count") or 0),
        "generated_event_count": int(row.get("generated_event_count") or 0),
        "verified_event_count": int(row.get("verified_event_count") or 0),
        "package_event_count": int(row.get("package_event_count") or 0),
        "export_count": int(row.get("export_count") or 0),
        "hash_ready_export_count": int(row.get("hash_ready_export_count") or 0),
    }


def _cleanup_owned_rows(
    engine: Any,
    *,
    context: Mapping[str, str],
) -> dict[str, int]:
    if not context.get("trace_id") and not context.get("export_id"):
        return {"events": 0, "exports": 0, "remaining_rows": 0}
    params = {
        "trace_id": context.get("trace_id", ""),
        "export_id": context.get("export_id", ""),
    }
    try:
        with engine.begin() as connection:
            events = int(
                connection.execute(
                    text(
                        "DELETE FROM service_operational_events "
                        "WHERE trace_id = :trace_id"
                    ),
                    params,
                ).rowcount
                or 0
            )
            exports = int(
                connection.execute(
                    text("DELETE FROM ag_ev_exports WHERE export_id = :export_id"),
                    params,
                ).rowcount
                or 0
            )
            remaining = int(
                connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM service_operational_events "
                        " WHERE trace_id = :trace_id) + "
                        "(SELECT count(*) FROM ag_ev_exports "
                        " WHERE export_id = :export_id)"
                    ),
                    params,
                ).scalar()
                or 0
            )
    except (AttributeError, SQLAlchemyError):
        return {"events": 0, "exports": 0, "remaining_rows": -1}
    return {
        "events": events,
        "exports": exports,
        "remaining_rows": remaining,
    }


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _regclass_matches(value: object, expected: str) -> bool:
    return str(value or "").rsplit(".", 1)[-1] == expected


def _engine_backend(engine: Any) -> str:
    url = getattr(engine, "url", None)
    get_backend_name = getattr(url, "get_backend_name", None)
    return str(get_backend_name()) if callable(get_backend_name) else "unknown"


def _engine_database(engine: Any) -> str | None:
    database = getattr(getattr(engine, "url", None), "database", None)
    return str(database) if database else None


def _redact_detail(detail: str, *, database_url: str) -> str:
    return detail.replace(database_url, redact_database_url(database_url))


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    env: Mapping[str, str],
) -> None:
    forbidden = (
        env.get(DATABASE_ENV, ""),
        RAW_EVENT_MESSAGE,
        RAW_EVENT_CREDENTIAL,
        RAW_EXPORT_BODY,
    )
    if any(value and value in serialized_evidence for value in forbidden):
        raise ValueError("audit evidence PostgreSQL smoke contains a secret")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status == "skipped":
        return f"ag_audit_evidence_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status != "pass":
        return (
            "ag_audit_evidence_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    observation = _mapping(evidence.get("observation"))
    cleanup = _mapping(evidence.get("cleanup"))
    package = _mapping(evidence.get("package"))
    return (
        "ag_audit_evidence_postgres_smoke=pass "
        f"database={observation.get('database')} "
        f"backend={observation.get('backend')} "
        f"events={observation.get('event_count')} "
        f"exports={observation.get('export_count')} "
        f"package_status={package.get('verification_status')} "
        f"cleaned={cleanup.get('remaining_rows') == 0}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env.local")
    args = parser.parse_args(argv)
    load_env_file(ROOT / args.env_file)
    evidence = run_ag_audit_evidence_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
