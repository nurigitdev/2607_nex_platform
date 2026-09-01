#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AE_PATH = ROOT / "services" / "nex-ae-api"
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_artifact_collection_postgres_smoke as collection_pg  # noqa: E402
import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_artifact_retention_batch_plan_postgres_smoke as batch_plan_pg  # noqa: E402
import run_ae_artifact_retention_candidate_postgres_smoke as candidate_pg  # noqa: E402
import run_ae_artifact_retention_history_postgres_smoke as history_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifacts import (  # noqa: E402
    SqlAlchemyArtifactRecordStore,
    SqlAlchemyArtifactRetentionExecutionHistoryStore,
    build_artifact_retention_scheduled_execution_command,
    build_default_rendered_artifact_storage,
    register_artifact_handoff_routes,
    run_artifact_retention_scheduled_execution_mock_worker,
    summarize_artifact_retention_scheduled_execution_worker_result,
)
from nex_ag.artifact_operations import (  # noqa: E402
    InMemoryAeArtifactOperationsClient,
    build_artifact_operation_retention_batch_projection,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "ae_artifact_retention_scheduled_execution_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
CHECKED_AT = batch_plan_pg.CHECKED_AT
COMMAND_CREATED_AT = "2026-09-01T02:35:00Z"
CUTOFF_AT = "2026-08-02T00:00:00Z"
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT


def run_ae_artifact_retention_scheduled_execution_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
            env=env,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        base_auth._require_test_database_url(database_url, env_name=database_env)
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_artifact_retention_scheduled_execution_smoke(
            database_url=database_url,
            database_env=database_env,
        )
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile, env=env)
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        return _failure("execution_failed", detail, profile=profile, env=env)

    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_id": SERVICE_ID,
        "profile": profile,
        "database_env": database_env,
        "redacted_database_url": redact_database_url(database_url),
        "migration": {
            "planned": list(migration.planned),
            "applied": list(migration.applied),
            "skipped": list(migration.skipped),
        },
        **execution,
    }
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_ae_artifact_retention_scheduled_execution_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-scheduled-{suffix}"
    workspace_id = f"workspace-artifact-scheduled-{suffix}"
    owner_user_id = f"owner-artifact-scheduled-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-scheduled-execution-smoke-",
        ) as storage_dir:
            storage_root = Path(storage_dir) / "artifact-storage"
            with artifact_pg._temporary_env(
                "NEX_AE_ARTIFACT_STORAGE_ROOT",
                str(storage_root),
            ):
                app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                app.state.nex_persistence = SimpleNamespace(
                    api_session_factory=session_factory
                )
                cx_client = artifact_pg.FakeCxArtifactSourceClient(
                    suffix=suffix,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                register_artifact_handoff_routes(app, cx_client=cx_client)
                client = TestClient(app)
                headers = artifact_pg._auth_headers(
                    request_id=request_id,
                    trace_id=trace_id,
                )

                first_old = batch_plan_pg._create_deleted_artifact(
                    client,
                    headers,
                    engine=engine,
                    suffix=suffix,
                    label="old-first",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at=OLD_LOGICAL_PURGE_AT,
                )
                second_old = batch_plan_pg._create_deleted_artifact(
                    client,
                    headers,
                    engine=engine,
                    suffix=suffix,
                    label="old-second",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at="2026-07-31T01:00:00Z",
                )
                recent = batch_plan_pg._create_deleted_artifact(
                    client,
                    headers,
                    engine=engine,
                    suffix=suffix,
                    label="recent",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at=RECENT_LOGICAL_PURGE_AT,
                )
                for created in (first_old, second_old, recent):
                    artifact_ids.append(created["artifact_id"])
                    handoff_ids.append(created["artifact_handoff_id"])

                before = _db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                materialized_before = _count_files(storage_root)
                plan_response = client.get(
                    "/api/v1/artifact-retention/batch-plan",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "retention_days": "30",
                        "as_of": AS_OF,
                        "checked_at": CHECKED_AT,
                        "scan_limit": "10",
                        "max_delete_count": "1",
                    },
                    headers={
                        **headers,
                        "Idempotency-Key": f"retention-scheduled-plan-{suffix}",
                    },
                )
                plan_payload = (
                    plan_response.json() if plan_response.status_code == 200 else {}
                )
                command = build_artifact_retention_scheduled_execution_command(
                    plan_payload,
                    trigger_type="scheduler_tick",
                    command_created_at=COMMAND_CREATED_AT,
                    requested_by={"actor_type": "service", "actor_id": "nex-ag"},
                    idempotency_key=f"retention-scheduled-command-{suffix}",
                )
                artifact_store = SqlAlchemyArtifactRecordStore(
                    session_factory,
                    rendered_storage=build_default_rendered_artifact_storage(),
                )
                history_store = SqlAlchemyArtifactRetentionExecutionHistoryStore(
                    session_factory
                )
                worker_result = run_artifact_retention_scheduled_execution_mock_worker(
                    command,
                    artifact_store=artifact_store,
                    history_store=history_store,
                    trace_id=trace_id,
                    request_id=request_id,
                )
                worker_summary = (
                    summarize_artifact_retention_scheduled_execution_worker_result(
                        worker_result
                    )
                )
                history_rows = history_store.list_executions(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    limit=5,
                )
                after = _db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                materialized_after = _count_files(storage_root)
                ag_projection = build_artifact_operation_retention_batch_projection(
                    plan=plan_payload,
                    source_client=InMemoryAeArtifactOperationsClient(),
                    request_trace_id=trace_id,
                )
                checks = {
                    "plan_route_ok": plan_response.status_code == 200,
                    "plan_ready": plan_payload.get("plan_status") == "READY",
                    "plan_selected_one": plan_payload.get("selected_count") == 1,
                    "command_ready": command.get("command_status") == "READY",
                    "command_dry_run": command.get("execution_mode") == "DRY_RUN",
                    "worker_succeeded": worker_result.get("worker_status")
                    == "SUCCEEDED",
                    "worker_dry_run_execution": _worker_dry_run_execution(
                        worker_result
                    ),
                    "history_written": worker_summary["history_written"] is True,
                    "history_row_persisted": _history_row_matches_worker(
                        history_rows,
                        worker_result,
                    ),
                    "db_rows_retained": after == before,
                    "storage_files_retained": materialized_after
                    == materialized_before
                    and materialized_before >= 6,
                    "ag_projection_ready": (
                        ag_projection["projection_status"] == "READY"
                        and ag_projection["summary"]["dispatch_available"] is True
                    ),
                    "metadata_only_evidence": _metadata_only(
                        plan_payload,
                        command,
                        worker_summary,
                        ag_projection,
                        before,
                        after,
                        forbidden_fragments=[
                            database_url,
                            database_env,
                            _database_url_password(database_url),
                            str(storage_root),
                            "/data/nex-platform",
                            "storage_ref",
                            "content_base64",
                            "rendered_payloads",
                        ],
                    ),
                }
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE artifact retention scheduled execution PostgreSQL "
                        f"smoke checks failed: {', '.join(failed_checks)}"
                    )
                cleanup_history = history_pg._cleanup_history_rows(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                cleanup = collection_pg._cleanup_smoke_rows(
                    engine,
                    artifact_ids=artifact_ids,
                    artifact_handoff_ids=handoff_ids,
                )
                return {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "artifact_ids": artifact_ids,
                    "batch_plan": {
                        "plan_status": plan_payload["plan_status"],
                        "scheduler_status": plan_payload["scheduler_status"],
                        "candidate_count": plan_payload["candidate_count"],
                        "selected_count": plan_payload["selected_count"],
                        "selected_artifact_ids": batch_plan_pg._selected_artifact_ids(
                            plan_payload
                        ),
                    },
                    "command": {
                        "command_status": command["command_status"],
                        "trigger_type": command["trigger_type"],
                        "execution_mode": command["execution_mode"],
                        "selected_count": command["selected_count"],
                    },
                    "worker": worker_summary,
                    "history": {
                        "row_count": len(history_rows),
                        "retention_execution_id": worker_summary[
                            "retention_execution_id"
                        ],
                    },
                    "ag_projection": {
                        "projection_status": ag_projection["projection_status"],
                        "dispatch_available": ag_projection["summary"][
                            "dispatch_available"
                        ],
                        "selected_count": ag_projection["summary"][
                            "selected_count"
                        ],
                    },
                    "db_before": before,
                    "db_after_worker": after,
                    "materialized_file_count": {
                        "before": materialized_before,
                        "after_worker": materialized_after,
                    },
                    "checks": checks,
                    "cleanup": {**cleanup, "history_rows": cleanup_history},
                    "live_db": True,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        history_pg._cleanup_history_rows(
            engine,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        collection_pg._cleanup_smoke_rows(
            engine,
            artifact_ids=artifact_ids,
            artifact_handoff_ids=handoff_ids,
        )
        engine.dispose()


def _db_observations(
    engine: Any,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    cutoff_at: str,
) -> dict[str, int]:
    return batch_plan_pg._db_observations(
        engine,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        cutoff_at=cutoff_at,
    )


def _count_files(root: Path) -> int:
    return candidate_pg._count_files(root)


def _worker_dry_run_execution(worker_result: Mapping[str, Any]) -> bool:
    execution = worker_result.get("execution")
    if not isinstance(execution, Mapping):
        return False
    deleted_counts = execution.get("deleted_counts")
    return (
        execution.get("mode") == "DRY_RUN"
        and execution.get("delete_enabled") is False
        and execution.get("storage_mutation_enabled") is False
        and execution.get("database_row_delete_enabled") is False
        and isinstance(deleted_counts, Mapping)
        and not any(deleted_counts.values())
    )


def _history_row_matches_worker(
    history_rows: list[dict[str, Any]],
    worker_result: Mapping[str, Any],
) -> bool:
    execution = worker_result.get("execution")
    if not isinstance(execution, Mapping) or len(history_rows) != 1:
        return False
    row = history_rows[0]
    return (
        row.get("execution", {}).get("execution_id") == execution.get("execution_id")
        and row.get("retention_execution_id") == execution.get("execution_id")
        and row.get("mode") == "DRY_RUN"
        and row.get("execution_status") == "SUCCEEDED"
    )


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    env: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": _safe_detail(detail, env),
    }


def _metadata_only(*payloads: Any, forbidden_fragments: list[str | None]) -> bool:
    return batch_plan_pg._metadata_only(
        *payloads,
        forbidden_fragments=forbidden_fragments,
    )


def _safe_detail(detail: str, env: Mapping[str, str]) -> str:
    safe = detail
    for key, value in _sensitive_env_values(env):
        replacement = "***" if key.endswith(":password") else f"<redacted:{key}>"
        safe = safe.replace(value, replacement)
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key, value in _sensitive_env_values(environ):
        if value in serialized_evidence:
            if key.endswith(":password"):
                raise ValueError(
                    "AE artifact retention scheduled execution smoke contains "
                    "a database password."
                )
            raise ValueError(
                "AE artifact retention scheduled execution smoke contains raw "
                f"{key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention scheduled execution smoke contains a local "
            "data path."
        )


def _sensitive_env_values(environ: Mapping[str, str]) -> list[tuple[str, str]]:
    sensitive: list[tuple[str, str]] = []
    for key in (
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE),
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
    ):
        value = environ.get(key)
        if value:
            sensitive.append((key, value))
            password = _database_url_password(value)
            if password:
                sensitive.append((f"{key}:password", password))
    return sensitive


def _database_url_password(database_url: str | None) -> str | None:
    if database_url is None:
        return None
    try:
        parsed = urlsplit(database_url)
    except ValueError:
        return None
    if parsed.password is None:
        return None
    return unquote(parsed.password)


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_artifact_retention_scheduled_execution_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduled_execution_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"plan_selected={evidence['batch_plan']['selected_count']} "
            f"worker_status={evidence['worker']['worker_status']} "
            f"history_written={str(evidence['worker']['history_written']).lower()} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_history={evidence['cleanup']['history_rows']}"
        )
    return (
        "ae_artifact_retention_scheduled_execution_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE artifact retention scheduled execution "
            "PostgreSQL smoke."
        )
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
    evidence = run_ae_artifact_retention_scheduled_execution_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
