#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_ae_api.chat import (  # noqa: E402
    SqlAlchemyChatInteractionStore,
    register_chat_routes,
)
from nex_ae_api.workspace import (  # noqa: E402
    build_workspace_activity,
    build_workspace_state,
)
from nex_ae_api.workspace_persistence import (  # noqa: E402
    SqlAlchemyWorkspaceRepository,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    OperationalEventEmitter,
    SqlAlchemyOperationalEventStore,
    build_service_app,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
    sqlalchemy_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ae_workspace_chat_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_WORKSPACE_CHAT_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"


class DeterministicCxClient:
    def __init__(self) -> None:
        self.call_count = 0

    def create_generation(self, payload, *, request_id, trace_id):
        self.call_count += 1
        return {
            "cx_generation_id": "cx-generation-1020",
            "status": "COMPLETED",
            "alias": payload["alias"],
            "provider_capability": "generation",
            "mo_generation_id": "mo-generation-1020",
            "request_metadata": {"grounding_required": False},
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "Synthetic PostgreSQL smoke answer.",
            },
            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
        }


def run_ae_workspace_chat_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1020",
            "requirement": "S102",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )

    try:
        migration = run_service_migrations(
            "nex-ae-api",
            database_url=database_url,
            profile="test",
        )
        evidence = _execute_postgres_smoke(database_url)
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "1020",
                "requirement": "S102",
                "profile": "test",
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
                "migration": {
                    "planned_count": len(migration.planned),
                    "applied_count": len(migration.applied),
                    "skipped_count": len(migration.skipped),
                    "latest_version": migration.planned[-1]
                    if migration.planned
                    else None,
                },
            }
        )
        migration_current = (
            bool(migration.planned)
            and migration.planned[-1] == "1014_ae_workspace_activity_persistence"
            and len(migration.planned)
            == len(migration.applied) + len(migration.skipped)
        )
        evidence["checks"] = {
            "migration_current": migration_current,
            **evidence["checks"],
        }
        evidence["status"] = (
            "PASS" if all(evidence["checks"].values()) else "FAIL"
        )
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "ae_workspace_chat_postgres_smoke_failed"
        return evidence
    except (MigrationError, SQLAlchemyError, OSError, ValueError, RuntimeError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )


def _execute_postgres_smoke(database_url: str) -> dict[str, Any]:
    engine = create_engine(
        sqlalchemy_database_url(database_url),
        future=True,
        pool_pre_ping=True,
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    token = uuid4().hex
    workspace_id = str(uuid4())
    chat_document_id = str(uuid4())
    interaction_id = str(uuid4())
    tenant_id = f"tenant-s102-{token[:12]}"
    owner_user_id = f"user-s102-{token[:12]}"
    trace_id = uuid4().hex
    request_id = f"request-s102-{token}"
    user_message = "Synthetic S102 workspace chat smoke prompt."
    workspace_store = SqlAlchemyWorkspaceRepository(factory)
    chat_store = SqlAlchemyChatInteractionStore(factory)
    event_store = SqlAlchemyOperationalEventStore(factory)
    cx_client = DeterministicCxClient()
    row_counts: dict[str, int] = {}
    cleanup_counts: dict[str, int] = {}
    response_status = 0
    repeated_equal = False
    cross_owner_status = 0
    loaded_workspace = None
    loaded_chat = None
    loaded_activities: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    database = ""
    role = ""

    try:
        workspace = build_workspace_state(
            {
                "workspace_id": workspace_id,
                "chat_document_id": chat_document_id,
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "title": "S102 PostgreSQL Smoke",
            },
            request_id=request_id,
            trace_id=trace_id,
        )
        initial_activity = build_workspace_activity(
            workspace_id=workspace_id,
            activity_type="workspace.created",
            request_id=request_id,
            trace_id=trace_id,
            summary="Workspace created.",
            metadata={
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
            },
        )
        workspace_store.save_workspace(workspace, initial_activity)

        app = build_service_app(SERVICE_SPECS["nex-ae-api"])
        app.state.ae_workspace_store = workspace_store
        register_chat_routes(
            app,
            store=chat_store,
            cx_client=cx_client,
            event_emitter=OperationalEventEmitter(
                service_id="nex-ae-api",
                store=event_store,
            ),
        )
        client = TestClient(app)
        request_payload = {
            "interaction_id": interaction_id,
            "workspace_id": workspace_id,
            "user_message": user_message,
        }
        owner_headers = _headers(tenant_id, owner_user_id, trace_id=trace_id)
        response = client.post(
            "/api/v1/chat/interactions",
            json=request_payload,
            headers=owner_headers,
        )
        repeated = client.post(
            "/api/v1/chat/interactions",
            json=request_payload,
            headers=owner_headers,
        )
        cross_owner = client.get(
            f"/api/v1/chat/interactions/{interaction_id}",
            headers=_headers(
                tenant_id,
                f"{owner_user_id}-other",
                trace_id=trace_id,
            ),
        )
        response_status = response.status_code
        repeated_equal = repeated.status_code == 200 and repeated.json() == response.json()
        cross_owner_status = cross_owner.status_code

        restarted_workspace_store = SqlAlchemyWorkspaceRepository(factory)
        restarted_chat_store = SqlAlchemyChatInteractionStore(factory)
        loaded_workspace = restarted_workspace_store.get_workspace(workspace_id)
        loaded_activities = restarted_workspace_store.list_activities(workspace_id) or []
        loaded_chat = restarted_chat_store.get_for_owner(
            interaction_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        hidden_chat = restarted_chat_store.get_for_owner(
            interaction_id,
            tenant_id=tenant_id,
            owner_user_id=f"{owner_user_id}-other",
        )
        events = event_store.list_events(
            service_id="nex-ae-api",
            trace_id=trace_id,
            limit=10,
        )

        with engine.connect() as connection:
            database, role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            row_counts = {
                "workspace": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_workspaces "
                            "WHERE workspace_id = :workspace_id"
                        ),
                        {"workspace_id": workspace_id},
                    ).scalar_one()
                ),
                "activities": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_workspace_activities "
                            "WHERE workspace_id = :workspace_id"
                        ),
                        {"workspace_id": workspace_id},
                    ).scalar_one()
                ),
                "chat": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_chat_interactions "
                            "WHERE chat_interaction_id = :interaction_id"
                        ),
                        {"interaction_id": interaction_id},
                    ).scalar_one()
                ),
                "events": len(events),
            }

        serialized_events = json.dumps(events, ensure_ascii=False, sort_keys=True)
        checks = {
            "actual_database_identity": database == EXPECTED_DATABASE
            and role == EXPECTED_ROLE,
            "workspace_written": row_counts.get("workspace") == 1,
            "chat_api_completed": response_status == 200
            and loaded_chat is not None
            and loaded_chat.get("status") == "COMPLETED",
            "workspace_lineage_preserved": loaded_chat is not None
            and loaded_chat.get("workspace_id") == workspace_id,
            "restart_workspace_read": loaded_workspace is not None
            and loaded_workspace.get("owner_user_id") == owner_user_id,
            "restart_activity_read": len(loaded_activities) == 3
            and [item["activity_type"] for item in loaded_activities]
            == [
                "workspace.created",
                "chat.interaction.started",
                "chat.interaction.completed",
            ],
            "restart_chat_read": loaded_chat is not None,
            "cross_owner_hidden": cross_owner_status == 404 and hidden_chat is None,
            "retry_idempotent": repeated_equal
            and cx_client.call_count == 1
            and row_counts
            == {"workspace": 1, "activities": 3, "chat": 1, "events": 2},
            "operational_events_persisted": len(events) == 2
            and {event["details"]["status"] for event in events}
            == {"PENDING", "COMPLETED"},
            "operational_events_private": user_message not in serialized_events
            and owner_user_id not in serialized_events
            and all(
                event["details"]["prompt_content_included"] is False
                and event["details"]["response_content_included"] is False
                and event["details"]["owner_identity_included"] is False
                for event in events
            ),
        }
    finally:
        try:
            with engine.begin() as connection:
                cleanup_counts["events"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM service_operational_events "
                            "WHERE trace_id = :trace_id"
                        ),
                        {"trace_id": trace_id},
                    ).rowcount
                    or 0
                )
                cleanup_counts["chat"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM ae_chat_interactions "
                            "WHERE chat_interaction_id = :interaction_id"
                        ),
                        {"interaction_id": interaction_id},
                    ).rowcount
                    or 0
                )
                cleanup_counts["workspace"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM ae_workspaces "
                            "WHERE workspace_id = :workspace_id"
                        ),
                        {"workspace_id": workspace_id},
                    ).rowcount
                    or 0
                )
            with engine.connect() as connection:
                cleanup_counts["remaining"] = sum(
                    int(value)
                    for value in connection.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM ae_workspaces WHERE workspace_id = :workspace_id), "
                            "(SELECT count(*) FROM ae_workspace_activities WHERE workspace_id = :workspace_id), "
                            "(SELECT count(*) FROM ae_chat_interactions WHERE chat_interaction_id = :interaction_id), "
                            "(SELECT count(*) FROM service_operational_events WHERE trace_id = :trace_id)"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "interaction_id": interaction_id,
                            "trace_id": trace_id,
                        },
                    ).one()
                )
        finally:
            engine.dispose()

    checks["cleanup_complete"] = cleanup_counts.get("remaining") == 0
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "execution_state": "EXECUTED",
        "actual_postgres": True,
        "database": database,
        "role": role,
        "checks": checks,
        "row_counts": row_counts,
        "cleanup_counts": cleanup_counts,
        "provider_mode": "deterministic-mock",
        "provider_call_count": cx_client.call_count,
    }


def _headers(
    tenant_id: str,
    user_id: str,
    *,
    trace_id: str | None = None,
) -> dict[str, str]:
    issued = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
    headers = {"Authorization": f"Bearer {issued.access_token}"}
    if trace_id is not None:
        headers["traceparent"] = f"00-{trace_id}-00f067aa0ba902b7-01"
    return headers


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _redact_detail(detail: str, *, database_url: str) -> str:
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1020",
        "requirement": "S102",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    passed = sum(bool(value) for value in checks.values())
    migration = evidence.get("migration") or {}
    rows = evidence.get("row_counts") or {}
    return (
        "ae_workspace_chat_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={passed}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"rows={rows.get('workspace', 0)}/{rows.get('activities', 0)}/"
        f"{rows.get('chat', 0)}/{rows.get('events', 0)} "
        f"cleanup={str((evidence.get('cleanup_counts') or {}).get('remaining', 'not-run'))}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_workspace_chat_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
