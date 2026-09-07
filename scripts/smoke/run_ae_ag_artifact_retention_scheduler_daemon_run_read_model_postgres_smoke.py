#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
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

import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke as bounded_pg  # noqa: E402
import run_ae_artifact_retention_scheduler_tick_once_postgres_smoke as once_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler import (  # noqa: E402
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID,
    SqlAlchemyArtifactRetentionSchedulerLeaseStore,
)
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_DETAIL_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerDaemonRunStore,
    build_artifact_retention_scheduler_daemon_run_collection,
    build_artifact_retention_scheduler_daemon_run_detail,
    run_artifact_retention_scheduler_daemon_cli_execution,
)
from nex_ae_api.artifacts import (  # noqa: E402
    AE_ARTIFACT_RETENTION_CANDIDATE_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
    build_artifact_retention_batch_plan,
    build_artifact_retention_candidate_filter,
    build_artifact_retention_scheduler_config,
    register_artifact_handoff_routes,
)
from nex_ag.artifact_operations import (  # noqa: E402
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_DETAIL_PROJECTION_SCHEMA_VERSION,
    AeArtifactOperationsError,
    register_artifact_operation_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = (
    "ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_READ_MODEL_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_READ_MODEL_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
AG_SERVICE_ID = "nex-ag"
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
CHECKED_AT = "2026-08-31T17:30:00Z"
AS_OF = "2026-09-01T00:00:00Z"


class FakeArtifactRetentionStore:
    def __init__(self, *, candidate_count: int = 1) -> None:
        self.candidate_count = candidate_count
        self.calls: list[dict[str, Any]] = []

    def plan_retention_batch(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        candidate_filter = build_artifact_retention_candidate_filter(
            tenant_id=kwargs["tenant_id"],
            workspace_id=kwargs["workspace_id"],
            owner_user_id=kwargs["owner_user_id"],
            retention_days=kwargs.get("retention_days"),
            as_of=kwargs.get("as_of"),
            limit=kwargs.get("scan_limit"),
        )
        items = [
            {
                "artifact_id": f"artifact-retention-run-read-model-{index}",
                "display_title": f"Old artifact {index}",
                "artifact_status": "DELETED",
                "logical_purged_at": "2026-07-31T00:00:00Z",
                "purge_eligible_at": "2026-08-30T00:00:00Z",
                "age_days_after_logical_purge": 32,
                "version_count": 1,
                "file_count": 1,
                "link_count": 0,
                "render_job_count": 1,
            }
            for index in range(self.candidate_count)
        ]
        return build_artifact_retention_batch_plan(
            {
                "artifact_retention_candidate_collection_schema_version": (
                    AE_ARTIFACT_RETENTION_CANDIDATE_COLLECTION_SCHEMA_VERSION
                ),
                "filter": candidate_filter,
                "count": len(items),
                "limit": candidate_filter["limit"],
                "items": items,
            },
            max_delete_count=kwargs.get("max_delete_count"),
            checked_at=kwargs.get("checked_at"),
            requested_by=kwargs.get("requested_by"),
            idempotency_key=kwargs.get("idempotency_key"),
        )


class AeTestClientDaemonRunReadModelClient:
    source_kind = "ae_test_client"
    base_url = "testclient://nex-ae-api"

    def __init__(self, client: TestClient, headers: Mapping[str, str]) -> None:
        self.client = client
        self.headers = dict(headers)
        self.run_collection_statuses: list[int] = []
        self.run_detail_statuses: list[int] = []

    def list_artifact_retention_scheduler_daemon_runs(
        self,
        *,
        scheduler_id: str | None,
        result_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.get(
            "/api/v1/artifact-retention/scheduler-daemon-runs",
            params={
                "limit": str(limit),
                **({"scheduler_id": scheduler_id} if scheduler_id else {}),
                **({"result_status": result_status} if result_status else {}),
            },
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.run_collection_statuses.append(response.status_code)
        return self._json_or_error(response)

    def get_artifact_retention_scheduler_daemon_run_detail(
        self,
        daemon_run_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        response = self.client.get(
            "/api/v1/artifact-retention/scheduler-daemon-runs/"
            f"{daemon_run_record_id}",
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.run_detail_statuses.append(response.status_code)
        if response.status_code == 404:
            return None
        return self._json_or_error(response)

    def _headers(self, *, request_id: str, trace_id: str) -> dict[str, str]:
        return {
            **self.headers,
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        }

    @staticmethod
    def _json_or_error(response: Any) -> dict[str, Any]:
        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            raise AeArtifactOperationsError(
                error_code=payload.get(
                    "error_code",
                    "ag.ae_artifact_retention_daemon_run_source_failed",
                ),
                detail=payload.get(
                    "detail",
                    "AE artifact retention scheduler daemon run source failed.",
                ),
                status_code=response.status_code,
            )
        return payload if isinstance(payload, dict) else {}


def run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke(
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
        execution = _execute_ae_ag_artifact_retention_scheduler_daemon_run_read_model_smoke(
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
        "ag_service_id": AG_SERVICE_ID,
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


def _execute_ae_ag_artifact_retention_scheduler_daemon_run_read_model_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-daemon-run-read-model-{suffix}"
    workspace_id = f"workspace-artifact-daemon-run-read-model-{suffix}"
    owner_user_id = f"owner-artifact-daemon-run-read-model-{suffix}"
    scheduler_id = f"ae-artifact-retention-daemon-run-read-model-{suffix}"
    idempotency_key = f"retention-daemon-run-read-model-{suffix}"
    worker_id = f"ae-artifact-retention-run-read-model-worker-{suffix}"
    process_id = 5559
    host_id = f"ae-daemon-run-read-model-{suffix[:8]}"
    run_record_id: str | None = None
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        once_pg._ensure_sqlite_scheduler_lease_table(engine)
        job_queue = SqlAlchemyJobQueue(session_factory)
        lease_store = SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
        run_store = SqlAlchemyArtifactRetentionSchedulerDaemonRunStore(
            session_factory
        )
        run_store.ensure_schema()
        scheduler_config = build_artifact_retention_scheduler_config(
            job_queue=job_queue
        )
        scheduler_config["scheduler_id"] = scheduler_id
        cli_result = run_artifact_retention_scheduler_daemon_cli_execution(
            artifact_store=FakeArtifactRetentionStore(candidate_count=1),
            job_queue=job_queue,
            lease_store=lease_store,
            run_store=run_store,
            scheduler_config=scheduler_config,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            checked_at=CHECKED_AT,
            interval_seconds=120,
            jitter_seconds=0,
            max_cycles=2,
            retention_days=30,
            as_of=AS_OF,
            scan_limit=10,
            max_delete_count=1,
            trace_id=trace_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            process_id=process_id,
            host_id=host_id,
            stale_after_seconds=900,
            worker_id=worker_id,
        )
        run_record = run_store.get_run_record_by_execution_result_id(
            cli_result["daemon_cli_execution_result_id"]
        )
        if run_record is None:
            raise RuntimeError("AE daemon run record was not persisted.")
        run_record_id = run_record["daemon_run_record_id"]
        lifecycle_events = run_store.list_lifecycle_events(run_record_id)
        direct_records = run_store.list_run_records(
            scheduler_id=scheduler_id,
            result_status="SUCCEEDED",
            limit=1,
        )
        direct_collection = build_artifact_retention_scheduler_daemon_run_collection(
            direct_records,
            scheduler_id=scheduler_id,
            result_status="SUCCEEDED",
            limit=1,
        )
        direct_detail = build_artifact_retention_scheduler_daemon_run_detail(
            run_record=run_record,
            lifecycle_events=lifecycle_events,
        )
        job_observations = bounded_pg._bounded_loop_job_observations(
            engine,
            idempotency_key=idempotency_key,
        )
        lease_observation = once_pg._scheduler_once_lease_observation(
            engine,
            scheduler_id=scheduler_id,
            lease_owner_id=(
                DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID
            ),
        )

        ae_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        ae_app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory,
            job_queue=job_queue,
        )
        register_artifact_handoff_routes(ae_app)
        ae_client = TestClient(ae_app)
        ae_headers = _ae_auth_headers(request_id=request_id, trace_id=trace_id)
        bridge = AeTestClientDaemonRunReadModelClient(ae_client, headers=ae_headers)
        ag_app = build_service_app(SERVICE_SPECS[AG_SERVICE_ID])
        register_artifact_operation_routes(ag_app, client=bridge)
        ag_client = TestClient(ag_app)
        ag_headers = _ag_auth_headers(request_id=request_id, trace_id=trace_id)

        ag_collection_response = ag_client.get(
            "/admin/v1/operations/artifact-retention/scheduler-daemon-runs",
            params={
                "scheduler_id": scheduler_id,
                "result_status": "SUCCEEDED",
                "limit": "1",
            },
            headers=ag_headers,
        )
        ag_collection = (
            ag_collection_response.json()
            if ag_collection_response.status_code == 200
            else {}
        )
        ag_detail_response = ag_client.get(
            "/admin/v1/operations/artifact-retention/"
            f"scheduler-daemon-runs/{run_record_id}",
            headers=ag_headers,
        )
        ag_detail = (
            ag_detail_response.json() if ag_detail_response.status_code == 200 else {}
        )

        checks = _ag_run_read_model_checks(
            database_url=database_url,
            database_env=database_env,
            scheduler_id=scheduler_id,
            run_record_id=run_record_id,
            cli_result=cli_result,
            run_record=run_record,
            lifecycle_events=lifecycle_events,
            direct_collection=direct_collection,
            direct_detail=direct_detail,
            job_observations=job_observations,
            lease_observation=lease_observation,
            bridge=bridge,
            ag_collection_status=ag_collection_response.status_code,
            ag_collection=ag_collection,
            ag_detail_status=ag_detail_response.status_code,
            ag_detail=ag_detail,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE/AG artifact retention scheduler daemon run read-model "
                f"PostgreSQL smoke checks failed: {', '.join(failed_checks)}"
            )

        cleanup_jobs = bounded_pg._cleanup_bounded_loop_runtime_rows(
            engine,
            idempotency_key=idempotency_key,
            worker_id=worker_id,
            daemon_worker_id="",
        )
        cleanup_lease = once_pg._cleanup_scheduler_once_lease_rows(
            engine,
            scheduler_id=scheduler_id,
            lease_owner_id=(
                DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID
            ),
        )
        cleanup_run = run_store.delete_run_record(run_record_id)
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "daemon_run": {
                "daemon_run_record_id": run_record_id,
                "scheduler_id": scheduler_id,
                "result_status": run_record["result_status"],
                "run_status": run_record["run_status"],
                "cycle_count": run_record["cycle_count"],
                "job_enqueued": run_record["job_enqueued"],
                "worker_executed": run_record["worker_executed"],
                "process_id": run_record["process_id"],
                "host_id": run_record["host_id"],
            },
            "db": {
                "direct_run_records": len(direct_records),
                "direct_collection_schema_version": direct_collection[
                    "daemon_run_collection_schema_version"
                ],
                "direct_detail_schema_version": direct_detail[
                    "daemon_run_detail_schema_version"
                ],
                "lifecycle_event_count": len(lifecycle_events),
                "lifecycle_event_types": [
                    event["event_type"] for event in lifecycle_events
                ],
                "job_rows": job_observations["row_count"],
                "job_statuses": job_observations["statuses"],
                "lease_status": lease_observation["lease_status"],
                "lease_rows": lease_observation["row_count"],
            },
            "routes": {
                "ae_run_collection_statuses": bridge.run_collection_statuses,
                "ae_run_detail_statuses": bridge.run_detail_statuses,
                "ag_run_collection_status": ag_collection_response.status_code,
                "ag_run_detail_status": ag_detail_response.status_code,
            },
            "ag_run_collection": {
                "projection_schema_version": ag_collection.get(
                    "projection_schema_version"
                ),
                "projection_status": ag_collection.get("projection_status"),
                "count": ag_collection.get("count"),
                "summary": ag_collection.get("summary"),
                "source_status": ag_collection.get("source_status"),
                "operator_guidance": ag_collection.get("operator_guidance"),
                "first_item_routes": (
                    ag_collection.get("items", [{}])[0].get("routes")
                    if ag_collection.get("items")
                    else {}
                ),
            },
            "ag_run_detail": {
                "projection_schema_version": ag_detail.get(
                    "projection_schema_version"
                ),
                "projection_status": ag_detail.get("projection_status"),
                "daemon_run_record_id": ag_detail.get("daemon_run_record_id"),
                "lifecycle_event_count": ag_detail.get("lifecycle_event_count"),
                "summary": ag_detail.get("summary"),
                "source_status": ag_detail.get("source_status"),
                "operator_guidance": ag_detail.get("operator_guidance"),
            },
            "checks": checks,
            "cleanup": {
                **cleanup_jobs,
                "lease_rows": cleanup_lease,
                **cleanup_run,
            },
            "live_db": True,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        bounded_pg._cleanup_bounded_loop_runtime_rows(
            engine,
            idempotency_key=idempotency_key,
            worker_id=worker_id,
            daemon_worker_id="",
        )
        once_pg._cleanup_scheduler_once_lease_rows(
            engine,
            scheduler_id=scheduler_id,
            lease_owner_id=(
                DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID
            ),
        )
        if run_record_id:
            SqlAlchemyArtifactRetentionSchedulerDaemonRunStore(
                build_session_factory(engine)
            ).delete_run_record(run_record_id)
        engine.dispose()


def _ag_run_read_model_checks(
    *,
    database_url: str,
    database_env: str,
    scheduler_id: str,
    run_record_id: str,
    cli_result: Mapping[str, Any],
    run_record: Mapping[str, Any],
    lifecycle_events: list[dict[str, Any]],
    direct_collection: Mapping[str, Any],
    direct_detail: Mapping[str, Any],
    job_observations: Mapping[str, Any],
    lease_observation: Mapping[str, Any],
    bridge: AeTestClientDaemonRunReadModelClient,
    ag_collection_status: int,
    ag_collection: Mapping[str, Any],
    ag_detail_status: int,
    ag_detail: Mapping[str, Any],
) -> dict[str, bool]:
    collection_summary = _mapping_value(ag_collection.get("summary"))
    detail_summary = _mapping_value(ag_detail.get("summary"))
    collection_source_status = _mapping_value(ag_collection.get("source_status"))
    detail_source_status = _mapping_value(ag_detail.get("source_status"))
    return {
        "cli_execution_succeeded": cli_result.get("result_status") == "SUCCEEDED"
        and cli_result.get("stop_reason") == "max_cycles_reached",
        "run_record_persisted": run_record.get("daemon_run_record_id")
        == run_record_id
        and run_record.get("scheduler_id") == scheduler_id
        and run_record.get("result_status") == "SUCCEEDED"
        and run_record.get("run_status") == "SUCCEEDED"
        and run_record.get("job_enqueued") is True
        and run_record.get("worker_executed") is False,
        "lifecycle_events_persisted": len(lifecycle_events) == 2
        and {event.get("event_type") for event in lifecycle_events}
        == {"RUN_STARTED", "RUN_COMPLETED"},
        "direct_collection_contract": direct_collection.get(
            "daemon_run_collection_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_COLLECTION_SCHEMA_VERSION
        and direct_collection.get("count") == 1
        and direct_collection.get("items", [{}])[0].get("daemon_run_record_id")
        == run_record_id,
        "direct_detail_contract": direct_detail.get(
            "daemon_run_detail_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_DETAIL_SCHEMA_VERSION
        and direct_detail.get("daemon_run_record_id") == run_record_id
        and direct_detail.get("lifecycle_event_count") == 2,
        "db_job_and_lease_written": job_observations.get("row_count") == 2
        and job_observations.get("statuses") == ["QUEUED", "QUEUED"]
        and lease_observation.get("row_count") == 1
        and lease_observation.get("lease_status") == "RELEASED",
        "ag_collection_route_ok": ag_collection_status == 200
        and bridge.run_collection_statuses == [200],
        "ag_detail_route_ok": ag_detail_status == 200
        and bridge.run_detail_statuses == [200],
        "ag_collection_projection_ready": ag_collection.get(
            "projection_schema_version"
        )
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION
        and ag_collection.get("projection_status") == "READY"
        and ag_collection.get("count") == 1
        and collection_summary.get("run_count") == 1
        and collection_summary.get("succeeded_count") == 1
        and collection_source_status.get("source_kind") == "ae_test_client"
        and collection_source_status.get("item_count") == 1,
        "ag_detail_projection_ready": ag_detail.get("projection_schema_version")
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_DETAIL_PROJECTION_SCHEMA_VERSION
        and ag_detail.get("projection_status") == "READY"
        and ag_detail.get("daemon_run_record_id") == run_record_id
        and ag_detail.get("lifecycle_event_count") == 2
        and detail_summary.get("daemon_run_record_id") == run_record_id
        and detail_summary.get("lifecycle_event_count") == 2
        and detail_source_status.get("run_detail_loaded") is True,
        "ag_projection_read_only": _mapping_value(
            ag_collection.get("operator_guidance")
        ).get("ag_direct_database_write_allowed")
        is False
        and _mapping_value(ag_detail.get("operator_guidance")).get(
            "ag_direct_job_enqueue_allowed"
        )
        is False,
        "metadata_only_evidence": _metadata_only(
            cli_result,
            run_record,
            lifecycle_events,
            direct_collection,
            direct_detail,
            ag_collection,
            ag_detail,
            forbidden_fragments=[
                database_url,
                database_env,
                _database_url_password(database_url),
                "/data/nex-platform",
                "storage_ref",
                "content_base64",
                "rendered_payloads",
                '"database_url_included": true',
                '"storage_path_included": true',
                '"raw_execution_payload_included": true',
            ],
        ),
    }


def _ae_auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id=AG_SERVICE_ID, audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _ag_auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=AG_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
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
        "ag_service_id": AG_SERVICE_ID,
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


def _sensitive_env_values(env: Mapping[str, str]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for key, value in env.items():
        if not value:
            continue
        upper_key = key.upper()
        if (
            "PASSWORD" in upper_key
            or "SECRET" in upper_key
            or "TOKEN" in upper_key
            or upper_key.endswith("_DATABASE_URL")
        ):
            values.append((key, value))
        password = _database_url_password(value)
        if password:
            values.append((f"{key}:password", password))
    return values


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key, value in _sensitive_env_values(environ):
        if value and value in serialized_evidence:
            label = "database password" if key.endswith(":password") else key
            raise ValueError(
                "AE/AG daemon run read-model PostgreSQL smoke evidence leaked "
                f"{label}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE/AG daemon run read-model PostgreSQL smoke evidence leaked local "
            "data path."
        )


def _database_url_password(database_url: str | None) -> str | None:
    if not database_url:
        return None
    try:
        parsed = urlsplit(database_url)
    except ValueError:
        return None
    if "@" not in parsed.netloc:
        return None
    userinfo = parsed.netloc.rsplit("@", 1)[0]
    if ":" not in userinfo:
        return None
    return unquote(userinfo.split(":", 1)[1])


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke="
            "pass "
            f"service={evidence['service_id']} "
            f"ag_service={evidence['ag_service_id']} "
            f"db_env={evidence['database_env']} "
            f"db_runs={evidence['db']['direct_run_records']} "
            f"events={evidence['db']['lifecycle_event_count']} "
            f"ag_collection={evidence['routes']['ag_run_collection_status']} "
            f"ag_detail={evidence['routes']['ag_run_detail_status']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_runs={evidence['cleanup']['daemon_run_records']}"
        )
    return (
        "ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke="
        "fail "
        f"service={evidence.get('service_id')} "
        f"ag_service={evidence.get('ag_service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE/AG artifact retention daemon run read-model "
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
    evidence = (
        run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke()
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
