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
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_artifact_collection_postgres_smoke as collection_pg  # noqa: E402
import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_artifact_retention_batch_plan_postgres_smoke as batch_plan_pg  # noqa: E402
import run_ae_artifact_retention_candidate_postgres_smoke as candidate_pg  # noqa: E402
import run_ae_artifact_retention_history_postgres_smoke as history_pg  # noqa: E402
import run_ae_artifact_retention_scheduled_worker_postgres_smoke as worker_pg  # noqa: E402
import run_ae_artifact_retention_scheduler_tick_once_postgres_smoke as once_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
)
from nex_ae_api.artifacts import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
    SqlAlchemyArtifactRetentionExecutionHistoryStore,
    register_artifact_handoff_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
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


SCHEMA_VERSION = "ae_artifact_retention_scheduler_daemon_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
TICK_AT = "2026-08-31T17:30:00Z"
CUTOFF_AT = "2026-08-02T00:00:00Z"
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT


def run_ae_artifact_retention_scheduler_daemon_postgres_smoke(
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
        execution = _execute_ae_artifact_retention_scheduler_daemon_smoke(
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


def _execute_ae_artifact_retention_scheduler_daemon_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-scheduler-daemon-{suffix}"
    workspace_id = f"workspace-artifact-scheduler-daemon-{suffix}"
    owner_user_id = f"owner-artifact-scheduler-daemon-{suffix}"
    worker_id = f"ae-artifact-retention-scheduler-daemon-worker-{suffix}"
    idempotency_key = f"retention-scheduler-daemon-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    job_id: str | None = None
    scheduler_id = ""
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        once_pg._ensure_sqlite_scheduler_lease_table(engine)
        job_queue = SqlAlchemyJobQueue(session_factory)
        history_store = SqlAlchemyArtifactRetentionExecutionHistoryStore(
            session_factory
        )
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-scheduler-daemon-smoke-",
        ) as storage_dir:
            storage_root = Path(storage_dir) / "artifact-storage"
            with artifact_pg._temporary_env(
                "NEX_AE_ARTIFACT_STORAGE_ROOT",
                str(storage_root),
            ):
                app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                app.state.nex_persistence = SimpleNamespace(
                    api_session_factory=session_factory,
                    job_queue=job_queue,
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
                    label="daemon-old-first",
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
                    label="daemon-old-second",
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
                    label="daemon-recent",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at=RECENT_LOGICAL_PURGE_AT,
                )
                for created in (first_old, second_old, recent):
                    artifact_ids.append(created["artifact_id"])
                    handoff_ids.append(created["artifact_handoff_id"])

                before = batch_plan_pg._db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                materialized_before = candidate_pg._count_files(storage_root)
                scheduler_config_response = client.get(
                    "/api/v1/artifact-retention/scheduler-config",
                    headers=headers,
                )
                scheduler_config = (
                    scheduler_config_response.json()
                    if scheduler_config_response.status_code == 200
                    else {}
                )
                daemon_config_response = client.get(
                    "/api/v1/artifact-retention/scheduler-daemon-config",
                    headers=headers,
                )
                daemon_config = (
                    daemon_config_response.json()
                    if daemon_config_response.status_code == 200
                    else {}
                )
                blocked_start_response = client.post(
                    "/api/v1/artifact-retention/scheduler-daemon-controls",
                    json={
                        "action": "start_daemon",
                        "requested_at": TICK_AT,
                        "requested_by": {
                            "actor_type": "operator",
                            "actor_id": "ag-retention-operator",
                        },
                    },
                    headers=headers,
                )
                blocked_start = (
                    blocked_start_response.json()
                    if blocked_start_response.status_code == 200
                    else {}
                )
                manual_response = client.post(
                    "/api/v1/artifact-retention/scheduler-daemon-controls",
                    json={
                        "action": "manual_tick_once",
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "retention_days": 30,
                        "as_of": AS_OF,
                        "scan_limit": 10,
                        "max_delete_count": 1,
                        "tick_at": TICK_AT,
                        "requested_at": TICK_AT,
                        "requested_by": {
                            "actor_type": "operator",
                            "actor_id": "ag-retention-operator",
                        },
                        "reason": "protected daemon route postgres smoke",
                        "run_worker": True,
                        "worker_id": worker_id,
                    },
                    headers={**headers, "Idempotency-Key": idempotency_key},
                )
                manual_dispatch = (
                    manual_response.json() if manual_response.status_code == 200 else {}
                )
                tick_once_result = _mapping_value(
                    manual_dispatch.get("tick_once_result")
                )
                scheduler_id = str(
                    manual_dispatch.get("scheduler_id")
                    or scheduler_config.get("scheduler_id")
                    or ""
                )
                scheduled_enqueue = _mapping_value(
                    _mapping_value(tick_once_result.get("enqueue_result")).get(
                        "scheduled_job_enqueue_result"
                    )
                )
                job_id = str(scheduled_enqueue.get("job_id") or "")
                job_observation = (
                    worker_pg._job_observation(
                        engine,
                        job_id=job_id,
                        idempotency_key=idempotency_key,
                    )
                    if job_id
                    else {"row_count": 0, "status": None}
                )
                lease_observation = once_pg._scheduler_once_lease_observation(
                    engine,
                    scheduler_id=scheduler_id,
                    lease_owner_id=DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
                )
                history_rows = history_store.list_executions(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    limit=5,
                )
                after = batch_plan_pg._db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                materialized_after = candidate_pg._count_files(storage_root)
                checks = _scheduler_daemon_checks(
                    database_url=database_url,
                    database_env=database_env,
                    storage_root=storage_root,
                    scheduler_config_response=scheduler_config_response.status_code,
                    scheduler_config=scheduler_config,
                    daemon_config_response=daemon_config_response.status_code,
                    daemon_config=daemon_config,
                    blocked_start_response=blocked_start_response.status_code,
                    blocked_start=blocked_start,
                    manual_response=manual_response.status_code,
                    manual_dispatch=manual_dispatch,
                    tick_once_result=tick_once_result,
                    lease_observation=lease_observation,
                    job_observation=job_observation,
                    history_rows=history_rows,
                    before=before,
                    after=after,
                    materialized_before=materialized_before,
                    materialized_after=materialized_after,
                )
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE artifact retention scheduler daemon PostgreSQL "
                        f"smoke checks failed: {', '.join(failed_checks)}"
                    )
                cleanup_history = history_pg._cleanup_history_rows(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                cleanup_worker = worker_pg._cleanup_worker_rows(
                    engine,
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                    worker_id=worker_id,
                )
                cleanup_lease = once_pg._cleanup_scheduler_once_lease_rows(
                    engine,
                    scheduler_id=scheduler_id,
                    lease_owner_id=DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
                )
                cleanup = collection_pg._cleanup_smoke_rows(
                    engine,
                    artifact_ids=artifact_ids,
                    artifact_handoff_ids=handoff_ids,
                )
                batch_plan = _mapping_value(tick_once_result.get("batch_plan"))
                tick_plan = _mapping_value(tick_once_result.get("tick_plan"))
                enqueue_result = _mapping_value(tick_once_result.get("enqueue_result"))
                worker_result = _mapping_value(tick_once_result.get("worker_result"))
                return {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "artifact_ids": artifact_ids,
                    "routes": {
                        "scheduler_config_status": scheduler_config_response.status_code,
                        "daemon_config_status": daemon_config_response.status_code,
                        "blocked_start_status": blocked_start_response.status_code,
                        "manual_tick_once_status": manual_response.status_code,
                    },
                    "daemon_config": {
                        "schema_version": daemon_config[
                            "daemon_config_schema_version"
                        ],
                        "scheduler_id": daemon_config["scheduler_id"],
                        "lease_available": daemon_config["lease_repository"][
                            "available"
                        ],
                        "lease_backend": daemon_config["lease_repository"]["backend"],
                        "scheduler_daemon_started": daemon_config["runtime"][
                            "scheduler_daemon_started"
                        ],
                    },
                    "blocked_start": {
                        "dispatch_status": blocked_start["dispatch_status"],
                        "block_reason": blocked_start["control_plan"][
                            "block_reason"
                        ],
                        "tick_once_result": blocked_start["tick_once_result"],
                    },
                    "manual_dispatch": {
                        "schema_version": manual_dispatch[
                            "daemon_dispatch_result_schema_version"
                        ],
                        "dispatch_status": manual_dispatch["dispatch_status"],
                        "control_status": manual_dispatch["control_plan"][
                            "decision_status"
                        ],
                        "tick_once_dispatched": manual_dispatch["metadata"][
                            "tick_once_dispatched"
                        ],
                    },
                    "tick_once": {
                        "schema_version": tick_once_result[
                            "tick_once_result_schema_version"
                        ],
                        "result_status": tick_once_result["result_status"],
                        "skip_reason": tick_once_result["skip_reason"],
                        "scheduler_id": tick_once_result["scheduler_id"],
                        "lease_owner_id": tick_once_result["lease_owner_id"],
                        "lease_acquired": tick_once_result["lease_decision"][
                            "lease_acquired"
                        ],
                        "lease_released": tick_once_result["metadata"][
                            "lease_released"
                        ],
                        "job_enqueued": tick_once_result["metadata"][
                            "job_enqueued"
                        ],
                        "worker_executed": tick_once_result["metadata"][
                            "worker_executed"
                        ],
                        "history_write_executed": tick_once_result["metadata"][
                            "history_write_executed"
                        ],
                    },
                    "batch_plan": {
                        "plan_status": batch_plan["plan_status"],
                        "scheduler_status": batch_plan["scheduler_status"],
                        "candidate_count": batch_plan["candidate_count"],
                        "selected_count": batch_plan["selected_count"],
                        "selected_artifact_ids": batch_plan_pg._selected_artifact_ids(
                            batch_plan
                        ),
                    },
                    "scheduler_tick": {
                        "tick_status": tick_plan["tick_status"],
                        "skip_reason": tick_plan["skip_reason"],
                        "tick_id": tick_plan["tick_id"],
                        "source_plan_id": tick_plan["source_plan_id"],
                        "enqueue_status": enqueue_result["enqueue_status"],
                        "job_enqueued": enqueue_result["job_enqueued"],
                        "admission_performed": enqueue_result[
                            "admission_performed"
                        ],
                    },
                    "lease": lease_observation,
                    "job": {
                        "job_id": job_id,
                        "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
                        "status": job_observation["status"],
                        "attempt_count": job_observation["attempt_count"],
                        "payload_command_status": job_observation[
                            "payload_command_status"
                        ],
                    },
                    "worker": {
                        "worker_id": worker_id,
                        "runner_status": worker_result.get("status"),
                    },
                    "history": {
                        "row_count": len(history_rows),
                        "retention_execution_id": once_pg._history_execution_id(
                            tick_once_result
                        ),
                        "mode": history_rows[0]["mode"] if history_rows else None,
                        "execution_status": (
                            history_rows[0]["execution_status"]
                            if history_rows
                            else None
                        ),
                    },
                    "db_before": before,
                    "db_after_worker": after,
                    "materialized_file_count": {
                        "before": materialized_before,
                        "after_worker": materialized_after,
                    },
                    "checks": checks,
                    "cleanup": {
                        **cleanup,
                        "history_rows": cleanup_history,
                        **cleanup_worker,
                        "lease_rows": cleanup_lease,
                    },
                    "live_db": True,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if job_id:
            worker_pg._cleanup_worker_rows(
                engine,
                job_id=job_id,
                idempotency_key=idempotency_key,
                worker_id=worker_id,
            )
        history_pg._cleanup_history_rows(
            engine,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        if scheduler_id:
            once_pg._cleanup_scheduler_once_lease_rows(
                engine,
                scheduler_id=scheduler_id,
                lease_owner_id=DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
            )
        collection_pg._cleanup_smoke_rows(
            engine,
            artifact_ids=artifact_ids,
            artifact_handoff_ids=handoff_ids,
        )
        engine.dispose()


def _scheduler_daemon_checks(
    *,
    database_url: str,
    database_env: str,
    storage_root: Path,
    scheduler_config_response: int,
    scheduler_config: Mapping[str, Any],
    daemon_config_response: int,
    daemon_config: Mapping[str, Any],
    blocked_start_response: int,
    blocked_start: Mapping[str, Any],
    manual_response: int,
    manual_dispatch: Mapping[str, Any],
    tick_once_result: Mapping[str, Any],
    lease_observation: Mapping[str, Any],
    job_observation: Mapping[str, Any],
    history_rows: list[dict[str, Any]],
    before: Mapping[str, int],
    after: Mapping[str, int],
    materialized_before: int,
    materialized_after: int,
) -> dict[str, bool]:
    tick_once_checks = once_pg._scheduler_tick_once_checks(
        database_url=database_url,
        database_env=database_env,
        storage_root=storage_root,
        scheduler_config_response=scheduler_config_response,
        scheduler_config=scheduler_config,
        tick_once_result=tick_once_result,
        lease_observation=lease_observation,
        job_observation=job_observation,
        history_rows=history_rows,
        before=before,
        after=after,
        materialized_before=materialized_before,
        materialized_after=materialized_after,
    )
    api_routes = _mapping_value(scheduler_config.get("api_routes"))
    daemon_runtime = _mapping_value(daemon_config.get("runtime"))
    daemon_lease = _mapping_value(daemon_config.get("lease_repository"))
    blocked_control = _mapping_value(blocked_start.get("control_plan"))
    manual_control = _mapping_value(manual_dispatch.get("control_plan"))
    manual_metadata = _mapping_value(manual_dispatch.get("metadata"))
    return {
        "daemon_config_route_ok": daemon_config_response == 200,
        "blocked_start_route_ok": blocked_start_response == 200,
        "manual_tick_once_route_ok": manual_response == 200,
        "scheduler_route_map_advertises_daemon": api_routes.get(
            "scheduler_daemon_config"
        )
        == "/api/v1/artifact-retention/scheduler-daemon-config"
        and api_routes.get("scheduler_daemon_controls")
        == "/api/v1/artifact-retention/scheduler-daemon-controls",
        "daemon_config_contract": daemon_config.get("daemon_config_schema_version")
        == "ae_artifact_retention_scheduler_daemon_config.v1"
        and daemon_runtime.get("scheduler_daemon_started") is False
        and daemon_runtime.get("continuous_loop_started") is False
        and daemon_lease.get("available") is True
        and daemon_lease.get("backend") == "sqlalchemy",
        "blocked_start_guardrail": blocked_start.get("dispatch_status") == "BLOCKED"
        and blocked_control.get("decision_status") == "BLOCKED"
        and blocked_control.get("block_reason") == "daemon_disabled_by_policy"
        and blocked_start.get("tick_once_result") is None,
        "manual_dispatch_contract": manual_dispatch.get(
            "daemon_dispatch_result_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION
        and manual_dispatch.get("dispatch_status") == "DISPATCHED"
        and manual_control.get("decision_status") == "READY"
        and manual_dispatch.get("tick_once_result") is not None
        and manual_metadata.get("tick_once_dispatched") is True
        and manual_metadata.get("job_enqueued") is True
        and manual_metadata.get("worker_executed") is True
        and manual_metadata.get("scheduler_daemon_started") is False
        and manual_metadata.get("continuous_loop_started") is False,
        "tick_once_route_contract": tick_once_result.get(
            "tick_once_result_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION,
        "metadata_only_evidence": _metadata_only(
            scheduler_config,
            daemon_config,
            blocked_start,
            manual_dispatch,
            lease_observation,
            job_observation,
            history_rows,
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
        **tick_once_checks,
    }


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _metadata_only(*payloads: Any, forbidden_fragments: list[str | None]) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(
        fragment not in serialized for fragment in forbidden_fragments if fragment
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
                    "AE artifact retention scheduler daemon smoke contains "
                    "a database password."
                )
            raise ValueError(
                "AE artifact retention scheduler daemon smoke contains raw "
                f"{key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention scheduler daemon smoke contains a local data path."
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
            "ae_artifact_retention_scheduler_daemon_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduler_daemon_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"dispatch={evidence['manual_dispatch']['dispatch_status']} "
            f"tick_once={evidence['tick_once']['result_status']} "
            f"lease={evidence['lease']['lease_status']} "
            f"job={evidence['job']['status']} "
            f"history_rows={evidence['history']['row_count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_leases={evidence['cleanup']['lease_rows']}"
        )
    return (
        "ae_artifact_retention_scheduler_daemon_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE artifact retention scheduler daemon PostgreSQL smoke."
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
    evidence = run_ae_artifact_retention_scheduler_daemon_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
