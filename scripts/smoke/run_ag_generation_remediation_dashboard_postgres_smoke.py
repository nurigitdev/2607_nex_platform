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

from nex_ag.generation_remediation import (  # noqa: E402
    GenerationRemediationError,
    SqlAlchemyGenerationRemediationTaskStore,
    build_generation_remediation_action,
)
from nex_ag.operations import register_unified_operation_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    InMemoryServiceLogStore,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_generation_remediation_dashboard_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_GENERATION_REMEDIATION_DASHBOARD_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def run_ag_generation_remediation_dashboard_postgres_smoke(
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
        return _failure("migration_failed", _redact_detail(str(exc), database_url))

    suffix = uuid4().hex[:12]
    request_id = f"ag-remediation-dashboard-smoke-{suffix}"
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    store = SqlAlchemyGenerationRemediationTaskStore(
        session_factory,
        database_env=DATABASE_ENV,
        redacted_database_url=redact_database_url(database_url),
    )
    action_ids: list[str] = []
    cleanup_deleted = 0
    try:
        records = _build_smoke_records(suffix=suffix, request_id=request_id)
        for record in records:
            store.save(record)
            action_ids.append(str(record["remediation_action_id"]))

        persisted_row_count = _db_row_count(engine, action_ids)
        client = _build_dashboard_client(store)
        dashboard_response = client.get(
            "/admin/v1/operations/dashboard",
            params={"service_id": SERVICE_ID, "recent_limit": 10},
            headers=_auth_headers(request_id),
        )
        issue_response = client.get(
            "/admin/v1/operations/issue-candidates",
            params={"service_id": SERVICE_ID, "recent_limit": 10},
            headers=_auth_headers(request_id),
        )
        dashboard = _json_or_empty(dashboard_response)
        issue_projection = _json_or_empty(issue_response)
        remediation = dashboard.get("generation_remediation", {})
        recent_ids = _item_ids(remediation.get("recent"))
        attention_ids = _item_ids(remediation.get("attention"))
        issue_candidates = issue_projection.get("issue_candidates", [])
        remediation_candidate = _first_remediation_issue_candidate(issue_candidates)
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "dashboard_status_ok": dashboard_response.status_code == 200,
            "issue_status_ok": issue_response.status_code == 200,
            "projection_ready": dashboard.get("projection_status") == "READY",
            "source_ready": remediation.get("source_statuses", {})
            .get(SERVICE_ID, {})
            .get("status")
            == "READY",
            "rows_persisted": persisted_row_count == len(action_ids),
            "recent_contains_smoke_tasks": set(action_ids).issubset(set(recent_ids)),
            "attention_contains_open_tasks": {
                action_ids[0],
                action_ids[1],
            }.issubset(set(attention_ids)),
            "completed_task_not_attention": action_ids[2] not in attention_ids,
            "issue_candidate_present": remediation_candidate is not None,
            "issue_candidate_failed_signal": (
                remediation_candidate is not None
                and remediation_candidate.get("signal", {}).get("status") == "FAILED"
            ),
            "detail_paths_present": (
                remediation_candidate is not None
                and len(remediation_candidate.get("signal", {}).get("task_detail_paths", []))
                >= 2
            ),
        }
        cleanup_deleted = sum(store.delete(action_id) for action_id in action_ids)
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
            "trace_id": TRACE_ID,
            "remediation_action_ids": action_ids,
            "observations": {
                "persisted_row_count": persisted_row_count,
                "recent_ids": recent_ids,
                "attention_ids": attention_ids,
                "issue_candidate_id": (
                    remediation_candidate.get("candidate_id")
                    if remediation_candidate is not None
                    else None
                ),
            },
            "checks": checks,
            "cleanup": {"deleted_rows": cleanup_deleted},
        }
    except (GenerationRemediationError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure(
            "smoke_execution_failed",
            _redact_detail(str(exc), database_url),
        )
    finally:
        cleanup_deleted += _cleanup_remediation_tasks(engine, action_ids)
        engine.dispose()

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _build_smoke_records(*, suffix: str, request_id: str) -> list[dict[str, Any]]:
    base_payload = {
        "tenant_id": "smoke-tenant",
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
                "ref_id": f"cx-gen-dashboard-smoke-{suffix}",
                "relation": "caused_by",
            }
        ],
        "evidence_hashes": [
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ],
        "evidence_previews": [
            "Dashboard smoke task stores only short remediation evidence."
        ],
        "action_source": "system_policy",
    }
    specs = [
        ("assigned", "citation_repair", "ASSIGNED", "HIGH"),
        ("failed", "prompt_policy_review", "FAILED", "URGENT"),
        ("completed", "citation_repair", "COMPLETED", "NORMAL"),
    ]
    return [
        build_generation_remediation_action(
            {
                **base_payload,
                "remediation_action_id": (
                    f"ag-remediation-dashboard-smoke-{label}-{suffix}"
                ),
                "action_type": action_type,
                "action_status": action_status,
                "priority": priority,
            },
            cx_generation_id=f"cx-gen-dashboard-smoke-{suffix}",
            request_id=request_id,
            trace_id=TRACE_ID,
        )
        for label, action_type, action_status, priority in specs
    ]


def _build_dashboard_client(store: Any) -> TestClient:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_unified_operation_routes(
        app,
        job_queues={SERVICE_ID: InMemoryJobQueue()},
        event_store=InMemoryOperationalEventStore(),
        service_log_stores={SERVICE_ID: InMemoryServiceLogStore()},
        generation_remediation_task_stores={SERVICE_ID: store},
    )
    return TestClient(app)


def _auth_headers(request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _json_or_empty(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _item_ids(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [
        str(item["remediation_action_id"])
        for item in items
        if isinstance(item, Mapping) and item.get("remediation_action_id")
    ]


def _first_remediation_issue_candidate(items: Any) -> Mapping[str, Any] | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if (
            isinstance(item, Mapping)
            and item.get("rule_id")
            == "generation_remediation_attention_required.v1"
        ):
            return item
    return None


def _db_row_count(engine: Any, remediation_action_ids: list[str]) -> int:
    if not remediation_action_ids:
        return 0
    with engine.connect() as connection:
        return sum(
            int(
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM ag_generation_remediation_tasks
                        WHERE remediation_action_id = :remediation_action_id
                        """
                    ),
                    {"remediation_action_id": remediation_action_id},
                ).scalar()
                or 0
            )
            for remediation_action_id in remediation_action_ids
        )


def _cleanup_remediation_tasks(engine: Any, remediation_action_ids: list[str]) -> int:
    deleted_rows = 0
    for remediation_action_id in remediation_action_ids:
        try:
            with engine.begin() as connection:
                result = connection.execute(
                    text(
                        "DELETE FROM ag_generation_remediation_tasks "
                        "WHERE remediation_action_id = :remediation_action_id"
                    ),
                    {"remediation_action_id": remediation_action_id},
                )
                deleted_rows += int(result.rowcount or 0)
        except SQLAlchemyError:
            continue
    return deleted_rows


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def _redact_detail(detail: str, database_url: str) -> str:
    return detail.replace(database_url, redact_database_url(database_url))


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    database_url = environ.get(DATABASE_ENV)
    if database_url and database_url in serialized_evidence:
        raise ValueError(
            "AG remediation dashboard smoke evidence contains raw database URL."
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_generation_remediation_dashboard_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ag_generation_remediation_dashboard_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"tasks={len(evidence['remediation_action_ids'])} "
            f"deleted_rows={evidence['cleanup']['deleted_rows']}"
        )
    return (
        "ag_generation_remediation_dashboard_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG remediation dashboard PostgreSQL smoke."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_generation_remediation_dashboard_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
