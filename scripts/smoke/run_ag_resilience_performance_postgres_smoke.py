#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
from hashlib import sha256
import json
import math
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
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
from nex_ag.resilience_performance import (  # noqa: E402
    AgConcurrencyAdmissionGuard,
    AgSourceIsolationExecutor,
    build_ag_resilience_performance_policy,
)
from nex_ag.resilience_performance_operations import (  # noqa: E402
    AG_RESILIENCE_PERFORMANCE_OPERATIONS_PATH,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_operational_event,
    build_service_app,
    build_session_factory,
    database_pool_settings,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_resilience_performance_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_RESILIENCE_PERFORMANCE_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
MIGRATION_VERSION = "0877_ag_resilience_read_indexes"
EVENT_COUNT = 25
EXPORT_COUNT = 4
PAGE_SIZE = 5
REFERENCE_DATE = "2038-01-01"
INDEX_NAMES = (
    "idx_ag_evt_type_page",
    "idx_ag_evt_trace_page",
    "idx_ag_exp_trace_page",
)
RAW_EVENT_MESSAGE = "AG bounded-load source message must stay private."
RAW_EVENT_CREDENTIAL = "private-resilience-credential-0878"
RAW_EXPORT_BODY = "AG bounded-load export body must stay private."


def run_ag_resilience_performance_postgres_smoke(
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
        policy = build_ag_resilience_performance_policy(env)
    except (MigrationError, ValueError) as exc:
        return _failure(
            "migration_or_policy_failed",
            _redact_detail(str(exc), database_url=database_url),
        )

    suffix = uuid4().hex[:12]
    context = {
        "trace_id": uuid4().hex,
        "request_id": f"ag-resilience-smoke-request-{suffix}",
        "target_id": f"ag-resilience-smoke-target-{suffix}",
        "operator_id": f"ag-resilience-smoke-operator-{suffix}",
        "event_prefix": f"ag-resilience-smoke-event-{suffix}",
        "export_prefix": f"ag-resilience-smoke-export-{suffix}",
    }
    api_engine: Any | None = None
    worker_engine: Any | None = None
    source_executor: AgSourceIsolationExecutor | None = None
    cleanup_done = False
    try:
        api_engine = build_engine(
            database_url,
            pool_settings=database_pool_settings(
                SERVICE_ID,
                workload="api",
                environ=env,
            ),
        )
        worker_engine = build_engine(
            database_url,
            pool_settings=database_pool_settings(
                SERVICE_ID,
                workload="worker",
                environ=env,
            ),
        )
        session_factory = build_session_factory(api_engine)
        guard = AgConcurrencyAdmissionGuard(
            max_in_flight=policy["admission"]["max_in_flight"],
            wait_timeout_ms=policy["admission"]["wait_timeout_ms"],
        )
        source_executor = AgSourceIsolationExecutor(
            timeout_ms=policy["source_isolation"]["timeout_ms"],
            slow_operation_ms=policy["query"]["slow_operation_ms"],
            max_workers=min(2, policy["admission"]["max_in_flight"]),
        )
        evidence = _execute_smoke(
            api_engine=api_engine,
            worker_engine=worker_engine,
            event_store=SqlAlchemyOperationalEventStore(session_factory),
            export_store=SqlAlchemyOperatorEvidenceExportStore(session_factory),
            migration=migration,
            policy=policy,
            guard=guard,
            source_executor=source_executor,
            database_url=database_url,
            context=context,
        )
        cleanup = _cleanup_owned_rows(api_engine, context=context)
        cleanup_done = True
        evidence["cleanup"] = cleanup
        evidence["checks"]["owned_rows_deleted"] = cleanup == {
            "events": EVENT_COUNT,
            "exports": EXPORT_COUNT,
            "remaining_rows": 0,
        }
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
        if api_engine is not None and not cleanup_done:
            _cleanup_owned_rows(api_engine, context=context)
        if source_executor is not None:
            source_executor.close()
        for engine in (api_engine, worker_engine):
            if engine is not None:
                engine.dispose()

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_smoke(
    *,
    api_engine: Any,
    worker_engine: Any,
    event_store: Any,
    export_store: Any,
    migration: Any,
    policy: Mapping[str, Any],
    guard: AgConcurrencyAdmissionGuard,
    source_executor: AgSourceIsolationExecutor,
    database_url: str,
    context: Mapping[str, str],
) -> dict[str, Any]:
    _seed_owned_rows(
        event_store=event_store,
        export_store=export_store,
        context=context,
    )
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_audit_evidence_routes(
        app,
        event_store=event_store,
        export_store=export_store,
        audit_event_store=event_store,
        admission_guard=guard,
        source_executor=source_executor,
        persistence_runtime=SimpleNamespace(
            api_engine=api_engine,
            worker_engine=worker_engine,
        ),
    )
    client = TestClient(app)
    headers = _admin_headers(context)
    bounded = _run_bounded_requests(
        client,
        headers=headers,
        request_count=policy["bounded_smoke"]["request_count"],
        concurrency=policy["bounded_smoke"]["concurrency"],
    )
    first_page = client.get(
        "/admin/v1/operations/audit-integrity",
        headers=headers,
        params={"recent_limit": PAGE_SIZE},
    )
    first_body = _mapping(first_page.json())
    pagination = _mapping(first_body.get("action_pagination"))
    second_page = client.get(
        "/admin/v1/operations/audit-integrity",
        headers=headers,
        params={
            "recent_limit": PAGE_SIZE,
            "cursor": pagination.get("next_cursor"),
        },
    )
    second_body = _mapping(second_page.json())
    diagnostics_response = client.get(
        AG_RESILIENCE_PERFORMANCE_OPERATIONS_PATH,
        headers=headers,
    )
    diagnostics = _mapping(diagnostics_response.json())
    observation = _database_observation(api_engine, context=context)
    admission = guard.snapshot()
    source = source_executor.snapshot()
    first_ids = _action_ids(first_body)
    second_ids = _action_ids(second_body)
    migration_versions = set(migration.applied) | set(migration.skipped)
    checks = {
        "migration_ran": (
            migration.service_id == SERVICE_ID
            and MIGRATION_VERSION in migration_versions
            and observation["migration_present"] is True
        ),
        "backend_is_postgresql": observation["backend"].startswith("postgresql"),
        "test_database_selected": observation["database"] == "nex_ag_test",
        "seed_rows_selected": (
            observation["event_count"] == EVENT_COUNT
            and observation["export_count"] == EXPORT_COUNT
        ),
        "indexes_present": all(observation["indexes_present"].values()),
        "indexes_planner_usable": all(observation["planner_indexes"].values()),
        "bounded_request_count": bounded["request_count"]
        == policy["bounded_smoke"]["request_count"],
        "bounded_concurrency": bounded["concurrency"]
        == policy["bounded_smoke"]["concurrency"],
        "all_requests_succeeded": bounded["success_count"]
        == bounded["request_count"],
        "p95_within_budget": bounded["p95_ms"]
        <= policy["bounded_smoke"]["p95_budget_ms"],
        "stable_first_page": bounded["unique_page_signatures"] == 1,
        "bounded_page_size": bounded["max_returned"] <= PAGE_SIZE,
        "cursor_pages_disjoint": (
            first_page.status_code == 200
            and second_page.status_code == 200
            and len(first_ids) == PAGE_SIZE
            and len(second_ids) == PAGE_SIZE
            and not set(first_ids).intersection(second_ids)
        ),
        "no_admission_rejections": admission["rejected_total"] == 0,
        "source_isolation_healthy": (
            source["failed_total"] == 0 and source["timed_out_total"] == 0
        ),
        "pool_projection_available": (
            diagnostics_response.status_code == 200
            and diagnostics.get("projection_status") in {"READY", "ATTENTION"}
            and _mapping(
                _mapping(_mapping(diagnostics.get("runtime")).get("database_pools")).get(
                    "api"
                )
            ).get("status")
            == "READY"
        ),
        "evidence_redacted": not any(
            marker in json.dumps((bounded, first_body, second_body, diagnostics))
            for marker in (
                RAW_EVENT_MESSAGE,
                RAW_EVENT_CREDENTIAL,
                RAW_EXPORT_BODY,
                database_url,
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
            "event_prefix": context["event_prefix"],
            "export_prefix": context["export_prefix"],
        },
        "load": bounded,
        "runtime": {
            "admission": admission,
            "source_isolation": source,
            "diagnostics_status": diagnostics.get("projection_status"),
        },
        "pagination": {
            "first_page_count": len(first_ids),
            "second_page_count": len(second_ids),
            "disjoint": not set(first_ids).intersection(second_ids),
        },
        "observation": observation,
        "checks": checks,
    }


def _seed_owned_rows(
    *,
    event_store: Any,
    export_store: Any,
    context: Mapping[str, str],
) -> None:
    package_id = f"ag-audit-package-{uuid4().hex}"
    package_hash = sha256(package_id.encode("utf-8")).hexdigest()
    for index in range(EVENT_COUNT):
        event_type = (
            AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE
            if index % 2 == 0
            else AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE
        )
        event_store.append(
            build_operational_event(
                service_id=SERVICE_ID,
                event_type=event_type,
                severity="INFO",
                message=RAW_EVENT_MESSAGE,
                trace_id=context["trace_id"],
                request_id=context["request_id"],
                subject_ref={"type": "audit_evidence_package", "id": package_id},
                details={
                    "package_id": package_id,
                    "package_hash": package_hash,
                    "verification_status": "VERIFIED",
                    "issue_count": 0,
                    "credential": RAW_EVENT_CREDENTIAL,
                },
                created_at=f"{REFERENCE_DATE}T00:00:{index:02d}Z",
                event_id=f"{context['event_prefix']}-{index:02d}",
            )
        )
    for index in range(EXPORT_COUNT):
        export_store.save(
            build_operator_evidence_export_record(
                {
                    "export_id": f"{context['export_prefix']}-{index:02d}",
                    "target_ref": {
                        "target_service": SERVICE_ID,
                        "target_kind": "resilience_performance_smoke",
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
                            "evidence_id": f"{context['event_prefix']}-{index:02d}",
                            "content_hash": sha256(
                                RAW_EXPORT_BODY.encode("utf-8")
                            ).hexdigest(),
                            "redaction_status": "REDACTED",
                        }
                    ],
                    "metadata": {"source": "postgres_smoke", "slice": "0878"},
                },
                request_id=context["request_id"],
                trace_id=context["trace_id"],
                idempotency_key=f"ag-resilience-smoke-idem-{index}-{context['trace_id']}",
                created_at=f"{REFERENCE_DATE}T00:01:{index:02d}Z",
            )
        )


def _run_bounded_requests(
    client: TestClient,
    *,
    headers: Mapping[str, str],
    request_count: int,
    concurrency: int,
) -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        started = time.perf_counter()
        response = client.get(
            "/admin/v1/operations/audit-integrity",
            headers=dict(headers),
            params={"recent_limit": PAGE_SIZE},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        body = _mapping(response.json())
        ids = _action_ids(body)
        return {
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "signature": tuple(ids),
            "returned": len(ids),
        }

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=concurrency,
        thread_name_prefix="ag-resilience-smoke",
    ) as executor:
        results = list(executor.map(lambda _index: execute(), range(request_count)))
    elapsed = [float(item["elapsed_ms"]) for item in results]
    return {
        "request_count": request_count,
        "concurrency": concurrency,
        "success_count": sum(
            1 for item in results if item["status_code"] == 200
        ),
        "p50_ms": round(_nearest_rank(elapsed, 0.50), 3),
        "p95_ms": round(_nearest_rank(elapsed, 0.95), 3),
        "max_ms": round(max(elapsed), 3),
        "unique_page_signatures": len(
            {item["signature"] for item in results}
        ),
        "max_returned": max(int(item["returned"]) for item in results),
    }


def _database_observation(
    engine: Any,
    *,
    context: Mapping[str, str],
) -> dict[str, Any]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT current_database() AS database_name,
                       current_setting('server_version_num') AS server_version_num,
                       EXISTS (
                           SELECT 1 FROM schema_migrations WHERE version = :migration
                       ) AS migration_present,
                       (SELECT count(*) FROM service_operational_events
                        WHERE trace_id = :trace_id) AS event_count,
                       (SELECT count(*) FROM ag_ev_exports
                        WHERE trace_id = :trace_id) AS export_count
                """
            ),
            {"migration": MIGRATION_VERSION, "trace_id": context["trace_id"]},
        ).mappings().one()
        index_rows = connection.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname IN (
                    'idx_ag_evt_type_page',
                    'idx_ag_evt_trace_page',
                    'idx_ag_exp_trace_page'
                  )
                """
            )
        ).mappings().all()
        indexes = {str(item["indexname"]): str(item["indexdef"]) for item in index_rows}
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        planner_indexes = {
            "event_type": _explain_uses_index(
                connection,
                """
                SELECT event_id FROM service_operational_events
                WHERE event_type = :event_type
                ORDER BY created_at DESC, event_id DESC LIMIT 5
                """,
                {"event_type": AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE},
                "idx_ag_evt_type_page",
            ),
            "event_trace": _explain_uses_index(
                connection,
                """
                SELECT event_id FROM service_operational_events
                WHERE trace_id = :trace_id
                ORDER BY created_at DESC, event_id DESC LIMIT 5
                """,
                {"trace_id": context["trace_id"]},
                "idx_ag_evt_trace_page",
            ),
            "export_trace": _explain_uses_index(
                connection,
                """
                SELECT export_id FROM ag_ev_exports
                WHERE trace_id = :trace_id
                ORDER BY updated_at DESC, export_id DESC LIMIT 5
                """,
                {"trace_id": context["trace_id"]},
                "idx_ag_exp_trace_page",
            ),
        }
    return {
        "backend": _engine_backend(engine),
        "database": str(row.get("database_name") or ""),
        "server_version_num": str(row.get("server_version_num") or ""),
        "migration_present": bool(row.get("migration_present")),
        "event_count": int(row.get("event_count") or 0),
        "export_count": int(row.get("export_count") or 0),
        "indexes_present": {name: name in indexes for name in INDEX_NAMES},
        "planner_indexes": planner_indexes,
    }


def _explain_uses_index(
    connection: Any,
    query: str,
    params: Mapping[str, Any],
    index_name: str,
) -> bool:
    plan = connection.execute(
        text(f"EXPLAIN (FORMAT JSON) {query}"),
        dict(params),
    ).scalar()
    return index_name in json.dumps(plan, default=str)


def _cleanup_owned_rows(
    engine: Any,
    *,
    context: Mapping[str, str],
) -> dict[str, int]:
    trace_id = context.get("trace_id", "")
    if not trace_id:
        return {"events": 0, "exports": 0, "remaining_rows": 0}
    try:
        with engine.begin() as connection:
            exports = int(
                connection.execute(
                    text("DELETE FROM ag_ev_exports WHERE trace_id = :trace_id"),
                    {"trace_id": trace_id},
                ).rowcount
                or 0
            )
            events = int(
                connection.execute(
                    text(
                        "DELETE FROM service_operational_events "
                        "WHERE trace_id = :trace_id"
                    ),
                    {"trace_id": trace_id},
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
                        " WHERE trace_id = :trace_id)"
                    ),
                    {"trace_id": trace_id},
                ).scalar()
                or 0
            )
    except (AttributeError, SQLAlchemyError):
        return {"events": 0, "exports": 0, "remaining_rows": -1}
    return {"events": events, "exports": exports, "remaining_rows": remaining}


def _action_ids(payload: Mapping[str, Any]) -> list[str]:
    actions = payload.get("recent_actions")
    if not isinstance(actions, list):
        return []
    return [
        str(item["event_id"])
        for item in actions
        if isinstance(item, Mapping) and item.get("event_id")
    ]


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile values cannot be empty")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


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
        raise ValueError("resilience PostgreSQL smoke contains a secret")


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
        return f"ag_resilience_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status != "pass":
        return (
            "ag_resilience_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    observation = _mapping(evidence.get("observation"))
    load = _mapping(evidence.get("load"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "ag_resilience_postgres_smoke=pass "
        f"database={observation.get('database')} "
        f"backend={observation.get('backend')} "
        f"requests={load.get('request_count')} "
        f"concurrency={load.get('concurrency')} "
        f"p95_ms={load.get('p95_ms')} "
        f"indexes={sum(bool(value) for value in _mapping(observation.get('indexes_present')).values())} "
        f"cleaned={cleanup.get('remaining_rows') == 0}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env.local")
    args = parser.parse_args(argv)
    load_env_file(ROOT / args.env_file)
    evidence = run_ag_resilience_performance_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
