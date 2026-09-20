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

from nex_ag.audit_retention import (  # noqa: E402
    AgAuditRetentionPolicyError,
    AgRetentionCandidateError,
    SqlAlchemyAgRetentionCandidateStore,
    build_ag_audit_retention_policy,
)
from nex_ag.audit_retention_archive import (  # noqa: E402
    AgArchiveReceiptError,
    SqlAlchemyAgArchiveReceiptStore,
    build_ag_archive_receipt,
)
from nex_ag.audit_retention_operations import (  # noqa: E402
    AG_AUDIT_RETENTION_OPERATIONS_PATH,
    AG_AUDIT_RETENTION_PURGE_PATH,
    register_ag_audit_retention_routes,
)
from nex_ag.audit_retention_purge import (  # noqa: E402
    AgRetentionPurgeError,
    SqlAlchemyAgRetentionPurgeStore,
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


SCHEMA_VERSION = "ag_audit_retention_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_AUDIT_RETENTION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
MIGRATION_VERSION = "0887_ag_retention_candidate_indexes"
INDEX_NAMES = ("idx_ag_evt_retention_time", "idx_ag_exp_retention_time")
SOURCE_TIME = "2024-01-01T00:00:00Z"
ARCHIVED_AT = "2026-08-01T00:00:00Z"
AS_OF = "2026-09-20T12:00:00Z"
RAW_EVENT_MESSAGE = "AG retention smoke event payload must stay private."
RAW_EVENT_CREDENTIAL = "private-retention-credential-0888"
RAW_EXPORT_BODY = "AG retention smoke export body must stay private."
RAW_OBJECT_REF_PREFIX = "archive://retention-smoke/"
CONFIRMATION_LEAK_MARKER = '"confirmation": "PURGE"'


def run_ag_audit_retention_postgres_smoke(
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
        policy = build_ag_audit_retention_policy(_smoke_policy_env(env))
    except (MigrationError, AgAuditRetentionPolicyError) as exc:
        return _failure(
            "migration_or_policy_failed",
            _redact_detail(str(exc), database_url=database_url),
        )

    suffix = uuid4().hex[:12]
    context = {
        "trace_id": uuid4().hex,
        "request_id": f"ag-retention-smoke-request-{suffix}",
        "event_id": f"ag-retention-smoke-event-{suffix}",
        "export_id": f"ag-retention-smoke-export-{suffix}",
        "target_id": f"ag-retention-smoke-target-{suffix}",
        "operator_id": f"ag-retention-smoke-operator-{suffix}",
    }
    engine: Any | None = None
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        evidence = _execute_smoke(
            engine=engine,
            event_store=SqlAlchemyOperationalEventStore(session_factory),
            export_store=SqlAlchemyOperatorEvidenceExportStore(session_factory),
            candidate_store=SqlAlchemyAgRetentionCandidateStore(session_factory),
            receipt_store=SqlAlchemyAgArchiveReceiptStore(session_factory),
            purge_store=SqlAlchemyAgRetentionPurgeStore(session_factory),
            migration=migration,
            policy=policy,
            database_url=database_url,
            context=context,
        )
        cleanup = _cleanup_owned_rows(engine, context=context)
        cleanup_done = True
        evidence["cleanup"] = cleanup
        evidence["checks"]["owned_rows_deleted"] = cleanup == {
            "events": 0,
            "exports": 0,
            "receipts": 2,
            "remaining_rows": 0,
        }
        passed = all(evidence["checks"].values())
        evidence["status"] = "PASS" if passed else "FAIL"
        evidence["failure_code"] = None if passed else "checks_failed"
    except (
        AgArchiveReceiptError,
        AgRetentionCandidateError,
        AgRetentionPurgeError,
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
    *,
    engine: Any,
    event_store: Any,
    export_store: Any,
    candidate_store: Any,
    receipt_store: Any,
    purge_store: Any,
    migration: Any,
    policy: Mapping[str, Any],
    database_url: str,
    context: Mapping[str, str],
) -> dict[str, Any]:
    _seed_owned_rows(event_store=event_store, export_store=export_store, context=context)
    candidates = candidate_store.list_candidates(
        policy=policy,
        as_of=AS_OF,
        limit=500,
    )
    source_ids = {context["event_id"], context["export_id"]}
    owned_candidates = [
        item for item in candidates["items"] if item.get("source_id") in source_ids
    ]
    for candidate in owned_candidates:
        receipt_store.save(
            build_ag_archive_receipt(
                candidate=candidate,
                provider_result={
                    "provider_mode": "external",
                    "content_sha256": candidate["content_sha256"],
                    "object_ref": RAW_OBJECT_REF_PREFIX + candidate["source_id"],
                    "receipt_sha256": _sha256_text(candidate["candidate_id"]),
                    "recoverable": True,
                },
                archived_at=ARCHIVED_AT,
                grace_days=policy["archive"]["grace_days"],
            )
        )

    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_ag_audit_retention_routes(
        app,
        candidate_store=candidate_store,
        receipt_store=receipt_store,
        purge_store=purge_store,
        policy=policy,
    )
    client = TestClient(app)
    headers = _admin_headers(context)
    operations_response = client.get(
        AG_AUDIT_RETENTION_OPERATIONS_PATH,
        headers=headers,
        params={"as_of": AS_OF, "limit": 500},
    )
    operations = _mapping(operations_response.json())
    dry_runs = [
        _purge_request(
            client,
            headers=headers,
            source_kind=candidate["source_kind"],
            source_id=candidate["source_id"],
            mode="DRY_RUN",
        )
        for candidate in owned_candidates
    ]
    executions = [
        _purge_request(
            client,
            headers=headers,
            source_kind=candidate["source_kind"],
            source_id=candidate["source_id"],
            mode="EXECUTE",
            confirmation="PURGE",
        )
        for candidate in owned_candidates
    ]
    retries = [
        _purge_request(
            client,
            headers=headers,
            source_kind=candidate["source_kind"],
            source_id=candidate["source_id"],
            mode="EXECUTE",
            confirmation="PURGE",
        )
        for candidate in owned_candidates
    ]
    observation = _database_observation(engine, context=context)
    migration_versions = set(migration.applied) | set(migration.skipped)
    serialized_responses = json.dumps(
        [operations, dry_runs, executions, retries],
        default=str,
    )
    checks = {
        "migration_ran": (
            migration.service_id == SERVICE_ID
            and MIGRATION_VERSION in migration_versions
            and observation["migration_present"] is True
        ),
        "backend_is_postgresql": observation["backend"].startswith("postgresql"),
        "test_database_selected": observation["database"] == "nex_ag_test",
        "seeded_candidates_found": (
            len(owned_candidates) == 2
            and {item["source_kind"] for item in owned_candidates}
            == {"operational_event", "evidence_export"}
        ),
        "indexes_present": all(observation["indexes_present"].values()),
        "indexes_planner_usable": all(observation["planner_indexes"].values()),
        "operations_status": (
            operations_response.status_code == 200
            and operations.get("projection_status") == "ATTENTION"
        ),
        "dry_run_eligible": (
            len(dry_runs) == 2
            and all(item["status_code"] == 200 for item in dry_runs)
            and all(item["body"].get("status") == "ELIGIBLE" for item in dry_runs)
        ),
        "execute_purged": (
            len(executions) == 2
            and all(item["status_code"] == 200 for item in executions)
            and all(item["body"].get("status") == "PURGED" for item in executions)
            and sum(int(item["body"].get("deleted_count") or 0) for item in executions)
            == 2
        ),
        "retry_idempotent": (
            len(retries) == 2
            and all(item["status_code"] == 200 for item in retries)
            and all(item["body"].get("status") == "NOOP" for item in retries)
            and all(item["body"].get("idempotent_noop") is True for item in retries)
        ),
        "sources_physically_deleted": (
            observation["event_count"] == 0
            and observation["export_count"] == 0
        ),
        "purge_tombstones_persisted": (
            observation["receipt_count"] == 2
            and observation["purged_receipt_count"] == 2
        ),
        "responses_redacted": not any(
            marker in serialized_responses
            for marker in (
                RAW_EVENT_MESSAGE,
                RAW_EVENT_CREDENTIAL,
                RAW_EXPORT_BODY,
                RAW_OBJECT_REF_PREFIX,
                database_url,
                CONFIRMATION_LEAK_MARKER,
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
            "event_id": context["event_id"],
            "export_id": context["export_id"],
        },
        "lifecycle": {
            "candidate_count": len(owned_candidates),
            "dry_run_statuses": [item["body"].get("status") for item in dry_runs],
            "execute_statuses": [item["body"].get("status") for item in executions],
            "retry_statuses": [item["body"].get("status") for item in retries],
        },
        "observation": observation,
        "checks": checks,
    }


def _seed_owned_rows(*, event_store: Any, export_store: Any, context: Mapping[str, str]) -> None:
    event_store.append(
        build_operational_event(
            service_id=SERVICE_ID,
            event_type="ag.audit_retention.smoke_source",
            severity="INFO",
            message=RAW_EVENT_MESSAGE,
            trace_id=context["trace_id"],
            request_id=context["request_id"],
            subject_ref={"type": "audit_retention_smoke", "id": context["target_id"]},
            details={"credential": RAW_EVENT_CREDENTIAL},
            created_at=SOURCE_TIME,
            event_id=context["event_id"],
        )
    )
    export_store.save(
        build_operator_evidence_export_record(
            {
                "export_id": context["export_id"],
                "target_ref": {
                    "target_service": SERVICE_ID,
                    "target_kind": "audit_retention_smoke",
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
                        "evidence_id": context["event_id"],
                        "content_hash": _sha256_text(RAW_EXPORT_BODY),
                        "redaction_status": "REDACTED",
                    }
                ],
                "metadata": {"source": "postgres_smoke", "slice": "0888"},
            },
            request_id=context["request_id"],
            trace_id=context["trace_id"],
            idempotency_key=f"ag-retention-smoke-{context['trace_id']}",
            created_at=SOURCE_TIME,
        )
    )


def _purge_request(
    client: TestClient,
    *,
    headers: Mapping[str, str],
    source_kind: str,
    source_id: str,
    mode: str,
    confirmation: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_kind": source_kind,
        "source_id": source_id,
        "as_of": AS_OF,
        "mode": mode,
    }
    if confirmation is not None:
        payload["confirmation"] = confirmation
    response = client.post(
        AG_AUDIT_RETENTION_PURGE_PATH,
        headers=dict(headers),
        json=payload,
    )
    return {"status_code": response.status_code, "body": _mapping(response.json())}


def _database_observation(engine: Any, *, context: Mapping[str, str]) -> dict[str, Any]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT current_database() AS database_name,
                       EXISTS (
                           SELECT 1 FROM schema_migrations WHERE version = :migration
                       ) AS migration_present,
                       (SELECT count(*) FROM service_operational_events
                        WHERE event_id = :event_id) AS event_count,
                       (SELECT count(*) FROM ag_ev_exports
                        WHERE export_id = :export_id) AS export_count,
                       (SELECT count(*) FROM ag_ret_archives
                        WHERE source_id IN (:event_id, :export_id)) AS receipt_count,
                       (SELECT count(*) FROM ag_ret_archives
                        WHERE source_id IN (:event_id, :export_id)
                          AND archive_status = 'PURGED') AS purged_receipt_count
                """
            ),
            {
                "migration": MIGRATION_VERSION,
                "event_id": context["event_id"],
                "export_id": context["export_id"],
            },
        ).mappings().one()
        index_rows = connection.execute(
            text(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname IN (
                    'idx_ag_evt_retention_time',
                    'idx_ag_exp_retention_time'
                  )
                """
            )
        ).scalars().all()
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        planner_indexes = {
            "operational_event": _explain_uses_index(
                connection,
                """
                SELECT event_id FROM service_operational_events
                WHERE created_at <= :cutoff
                ORDER BY created_at ASC, event_id ASC LIMIT 500
                """,
                "idx_ag_evt_retention_time",
            ),
            "evidence_export": _explain_uses_index(
                connection,
                """
                SELECT export_id FROM ag_ev_exports
                WHERE updated_at <= :cutoff
                ORDER BY updated_at ASC, export_id ASC LIMIT 500
                """,
                "idx_ag_exp_retention_time",
            ),
        }
    indexes = {str(name) for name in index_rows}
    return {
        "backend": _engine_backend(engine),
        "database": str(row.get("database_name") or ""),
        "migration_present": bool(row.get("migration_present")),
        "event_count": int(row.get("event_count") or 0),
        "export_count": int(row.get("export_count") or 0),
        "receipt_count": int(row.get("receipt_count") or 0),
        "purged_receipt_count": int(row.get("purged_receipt_count") or 0),
        "indexes_present": {name: name in indexes for name in INDEX_NAMES},
        "planner_indexes": planner_indexes,
    }


def _explain_uses_index(connection: Any, query: str, index_name: str) -> bool:
    plan = connection.execute(
        text(f"EXPLAIN (FORMAT JSON) {query}"),
        {"cutoff": AS_OF},
    ).scalar()
    return index_name in json.dumps(plan, default=str)


def _cleanup_owned_rows(engine: Any, *, context: Mapping[str, str]) -> dict[str, int]:
    if not context.get("event_id") or not context.get("export_id"):
        return {"events": 0, "exports": 0, "receipts": 0, "remaining_rows": 0}
    try:
        with engine.begin() as connection:
            receipts = int(
                connection.execute(
                    text(
                        "DELETE FROM ag_ret_archives "
                        "WHERE source_id IN (:event_id, :export_id)"
                    ),
                    dict(context),
                ).rowcount
                or 0
            )
            exports = int(
                connection.execute(
                    text("DELETE FROM ag_ev_exports WHERE export_id = :export_id"),
                    dict(context),
                ).rowcount
                or 0
            )
            events = int(
                connection.execute(
                    text(
                        "DELETE FROM service_operational_events "
                        "WHERE event_id = :event_id"
                    ),
                    dict(context),
                ).rowcount
                or 0
            )
            remaining = int(
                connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM service_operational_events "
                        " WHERE event_id = :event_id) + "
                        "(SELECT count(*) FROM ag_ev_exports "
                        " WHERE export_id = :export_id) + "
                        "(SELECT count(*) FROM ag_ret_archives "
                        " WHERE source_id IN (:event_id, :export_id))"
                    ),
                    dict(context),
                ).scalar()
                or 0
            )
    except (AttributeError, SQLAlchemyError):
        return {"events": 0, "exports": 0, "receipts": 0, "remaining_rows": -1}
    return {
        "events": events,
        "exports": exports,
        "receipts": receipts,
        "remaining_rows": remaining,
    }


def _smoke_policy_env(env: Mapping[str, str]) -> dict[str, str]:
    selected = dict(env)
    selected.update(
        {
            "NEX_AG_AUDIT_EVENT_RETENTION_DAYS": "365",
            "NEX_AG_EVIDENCE_EXPORT_RETENTION_DAYS": "365",
            "NEX_AG_ARCHIVE_GRACE_DAYS": "1",
            "NEX_AG_RETENTION_BATCH_SIZE": "500",
            "NEX_AG_ARCHIVE_PROVIDER_MODE": "external",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": "true",
        }
    )
    return selected


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


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _engine_backend(engine: Any) -> str:
    url = getattr(engine, "url", None)
    get_backend_name = getattr(url, "get_backend_name", None)
    return str(get_backend_name()) if callable(get_backend_name) else "unknown"


def _redact_detail(detail: str, *, database_url: str) -> str:
    return detail.replace(database_url, redact_database_url(database_url))


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    env: Mapping[str, str],
) -> None:
    forbidden = (
        env.get(DATABASE_ENV, ""),
        RAW_EVENT_MESSAGE,
        RAW_EVENT_CREDENTIAL,
        RAW_EXPORT_BODY,
        RAW_OBJECT_REF_PREFIX,
        CONFIRMATION_LEAK_MARKER,
    )
    if any(value and value in serialized_evidence for value in forbidden):
        raise ValueError("audit retention PostgreSQL smoke contains a secret")


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
        return f"ag_audit_retention_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status != "pass":
        return (
            "ag_audit_retention_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    observation = _mapping(evidence.get("observation"))
    lifecycle = _mapping(evidence.get("lifecycle"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "ag_audit_retention_postgres_smoke=pass "
        f"database={observation.get('database')} "
        f"backend={observation.get('backend')} "
        f"candidates={lifecycle.get('candidate_count')} "
        f"purged={observation.get('purged_receipt_count')} "
        f"indexes={sum(bool(value) for value in _mapping(observation.get('indexes_present')).values())} "
        f"cleaned={cleanup.get('remaining_rows') == 0}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env.local")
    args = parser.parse_args(argv)
    load_env_file(ROOT / args.env_file)
    evidence = run_ag_audit_retention_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
