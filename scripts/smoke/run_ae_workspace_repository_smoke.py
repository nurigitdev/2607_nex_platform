#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_ae_api.workspace_persistence import SqlAlchemyWorkspaceRepository  # noqa: E402


def run_workspace_repository_smoke() -> dict[str, Any]:
    factory = _session_factory()
    repository = SqlAlchemyWorkspaceRepository(factory)
    workspace = _workspace()
    initial = _activity()
    created = repository.create_workspace(workspace, initial)
    repeated = repository.create_workspace(workspace, initial)
    completed = _activity(
        activity_id="44444444-4444-4444-8444-444444444444",
        activity_type="chat.interaction.completed",
        summary="Chat completed.",
        created_at="2026-09-27T00:01:00Z",
    )
    repository.append_activity(completed)
    loaded = repository.get_workspace(workspace["workspace_id"])
    activities = repository.list_activities(workspace["workspace_id"])
    checks = {
        "created": created["workspace_id"] == workspace["workspace_id"],
        "retry_idempotent": repeated == created,
        "restart_reload": loaded is not None,
        "owner_preserved": loaded["owner_user_id"] == "user-a",
        "runtime_defaults_preserved": loaded["runtime_defaults"]["execution_mode"]
        == "GROUNDED_ANSWER",
        "activity_count_updated": loaded["activity_summary"]["activity_count"] == 2,
        "activity_ordered": [item["activity_type"] for item in activities]
        == ["workspace.created", "chat.interaction.completed"],
        "missing_fails_closed": repository.get_workspace("missing") is None,
    }
    return {
        "smoke_schema_version": "ae_workspace_repository_smoke.v1",
        "slice": "1015",
        "requirement": "S102",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "workspace_count": 1,
        "activity_count": len(activities),
        "postgres_required": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    passed = sum(bool(value) for value in result.get("checks", {}).values())
    total = len(result.get("checks", {}))
    return (
        "ae_workspace_repository="
        f"{str(result.get('status', 'FAIL')).lower()} checks={passed}/{total} "
        f"workspaces={result.get('workspace_count', 0)} "
        f"activities={result.get('activity_count', 0)}"
    )


def _session_factory():
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_workspaces (
                workspace_id TEXT PRIMARY KEY, workspace_schema_version TEXT NOT NULL,
                tenant_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, title TEXT NOT NULL,
                locale TEXT NOT NULL, chat_document_id TEXT NOT NULL UNIQUE,
                runtime_defaults TEXT NOT NULL, activity_count INTEGER NOT NULL,
                last_activity_type TEXT, trace_id TEXT NOT NULL, request_id TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_workspace_activities (
                activity_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                activity_schema_version TEXT NOT NULL, activity_type TEXT NOT NULL,
                trace_id TEXT NOT NULL, request_id TEXT NOT NULL, summary TEXT NOT NULL,
                metadata TEXT NOT NULL, created_at TEXT NOT NULL
            )
        """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _workspace() -> dict[str, Any]:
    return {
        "workspace_schema_version": "ae_workspace_state.v1",
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "title": "Workspace A",
        "locale": "ko-KR",
        "chat_document_id": "22222222-2222-4222-8222-222222222222",
        "runtime_defaults": {"execution_mode": "GROUNDED_ANSWER"},
        "activity_summary": {"activity_count": 1, "last_activity_type": "workspace.created"},
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-a",
        "created_at": "2026-09-27T00:00:00Z",
        "updated_at": "2026-09-27T00:00:00Z",
    }


def _activity(**overrides: Any) -> dict[str, Any]:
    record = {
        "activity_schema_version": "ae_workspace_activity.v1",
        "activity_id": "33333333-3333-4333-8333-333333333333",
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "activity_type": "workspace.created",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-a",
        "summary": "Workspace created.",
        "metadata": {},
        "created_at": "2026-09-27T00:00:00Z",
    }
    return {**record, **overrides}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_workspace_repository_smoke()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
