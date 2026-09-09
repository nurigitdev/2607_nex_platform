#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
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

import run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke as ae_worker_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore,
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore,
)
from nex_ae_api.artifacts import register_artifact_handoff_routes  # noqa: E402
from nex_ag.artifact_operations import (  # noqa: E402
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION,
    AeArtifactOperationsError,
    register_artifact_operation_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
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
    "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = ae_worker_pg.SERVICE_ID
AG_SERVICE_ID = "nex-ag"
DEFAULT_PROFILE = ae_worker_pg.DEFAULT_PROFILE
MIGRATION_VERSION = ae_worker_pg.MIGRATION_VERSION
CHECKED_AT = "2026-09-08T08:35:00Z"
WORKER_OBSERVED_AT = "2026-09-08T08:35:20Z"
AE_EXECUTION_ROUTE = (
    "/api/v1/artifact-retention/scheduler-daemon-operator-control-executions"
)
AE_WORKER_ROUTE = (
    "/api/v1/artifact-retention/"
    "scheduler-daemon-operator-control-execution-workers"
)
AG_WORKER_ROUTE = (
    "/admin/v1/operations/artifact-retention/"
    "scheduler-daemon-operator-control-execution-workers"
)
EXPECTED_TABLES = ae_worker_pg.EXPECTED_TABLES
EXPECTED_INDEXES = ae_worker_pg.EXPECTED_INDEXES
EXPECTED_STATE_JSONB_TYPES = {
    "state.allowed_next_statuses": "jsonb",
    "state.guardrails": "jsonb",
    "state.metadata": "jsonb",
    "state.operator_control_execution_request": "jsonb",
}


class AeTestClientDaemonOperatorControlExecutionWorkerClient:
    source_kind = "ae_test_client"
    base_url = "testclient://nex-ae-api"

    def __init__(self, client: TestClient, headers: Mapping[str, str]) -> None:
        self.client = client
        self.headers = dict(headers)
        self.worker_statuses: list[int] = []

    def run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        self,
        *,
        operator_control_execution_state_id: str,
        operator_control_execution_state: Mapping[str, Any] | None = None,
        checked_at: str | None = None,
        worker_observed_at: str | None = None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operator_control_execution_state_id": operator_control_execution_state_id
        }
        if operator_control_execution_state is not None:
            payload["operator_control_execution_state"] = dict(
                operator_control_execution_state
            )
        if checked_at is not None:
            payload["checked_at"] = checked_at
        if worker_observed_at is not None:
            payload["worker_observed_at"] = worker_observed_at

        response = self.client.post(
            AE_WORKER_ROUTE,
            json=payload,
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.worker_statuses.append(response.status_code)
        return self._json_or_error(response)

    def _headers(self, *, request_id: str, trace_id: str) -> dict[str, str]:
        return {
            **self.headers,
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        }

    @staticmethod
    def _json_or_error(response: Any) -> dict[str, Any]:
        payload = _json_payload(response) if response.content else {}
        if response.status_code >= 400:
            raise AeArtifactOperationsError(
                error_code=payload.get(
                    "error_code",
                    "ag.ae_artifact_retention_daemon_operator_control_execution_worker_source_failed",
                ),
                detail=payload.get(
                    "detail",
                    "AE artifact retention scheduler daemon operator-control "
                    "execution worker source failed.",
                ),
                status_code=response.status_code,
            )
        return payload if isinstance(payload, dict) else {}


def run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for AG-to-AE worker PostgreSQL smoke.",
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
        execution = _execute_ae_ag_operator_control_execution_worker_smoke(
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


def _execute_ae_ag_operator_control_execution_worker_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    idempotency_key = f"slice-0609-worker-{suffix}"
    state_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        ae_worker_pg.ae_execution_pg.process_pg._ensure_sqlite_migration_marker(
            engine
        )
        ae_worker_pg.ae_execution_pg.supervisor_pg._ensure_sqlite_migration_marker(
            engine
        )
        ae_worker_pg._ensure_sqlite_migration_marker(engine)
        execution_store = (
            SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
                session_factory
            )
        )
        process_store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
            session_factory
        )
        supervisor_store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore(
            session_factory
        )
        process_store.ensure_schema()
        supervisor_store.ensure_schema()
        execution_store.ensure_schema()
        before = ae_worker_pg._db_observations(
            engine,
            idempotency_key=idempotency_key,
        )

        ae_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        ae_app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(
            ae_app,
            retention_scheduler_daemon_operator_control_execution_store=(
                execution_store
            ),
        )
        ae_client = TestClient(ae_app)
        ae_headers = ae_worker_pg.ae_execution_pg.artifact_pg._auth_headers(
            request_id=request_id,
            trace_id=trace_id,
        )

        admitted_response = ae_client.post(
            AE_EXECUTION_ROUTE,
            json={
                **ae_worker_pg._execution_payload(suffix=suffix),
                "persist_execution_state": True,
            },
            headers={**ae_headers, "Idempotency-Key": idempotency_key},
        )
        admitted_payload = _json_payload(admitted_response)
        state_id = _text_or_none(
            admitted_payload.get("operator_control_execution_state_id")
        )
        if state_id is not None:
            state_ids.append(state_id)

        bridge = AeTestClientDaemonOperatorControlExecutionWorkerClient(
            ae_client,
            headers=ae_headers,
        )
        ag_app = build_service_app(SERVICE_SPECS[AG_SERVICE_ID])
        register_artifact_operation_routes(ag_app, client=bridge)
        ag_client = TestClient(ag_app)
        ag_headers = _ag_auth_headers(request_id=request_id, trace_id=trace_id)
        ag_worker_response = ag_client.post(
            AG_WORKER_ROUTE,
            params={"service_id": SERVICE_ID},
            json={
                "operator_control_execution_state_id": state_id,
                "checked_at": CHECKED_AT,
                "worker_observed_at": WORKER_OBSERVED_AT,
            },
            headers=ag_headers,
        )
        ag_worker_payload = _json_payload(ag_worker_response)
        after = ae_worker_pg._db_observations(
            engine,
            state_ids=state_ids,
            scheduler_id=_text_or_none(admitted_payload.get("scheduler_id")),
            idempotency_key=idempotency_key,
        )

        checks = _smoke_checks(
            database_url=database_url,
            database_env=database_env,
            admitted_response=admitted_response.status_code,
            admitted_payload=admitted_payload,
            before=before,
            after=after,
            bridge=bridge,
            ag_worker_status=ag_worker_response.status_code,
            ag_worker=ag_worker_payload,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE/AG scheduler daemon operator-control execution worker "
                "PostgreSQL smoke checks failed: "
                f"{', '.join(failed_checks)}"
            )

        cleanup = ae_worker_pg._cleanup_execution_states(execution_store, state_ids)
        post_cleanup = ae_worker_pg._db_observations(
            engine,
            state_ids=state_ids,
            idempotency_key=idempotency_key,
        )
        if post_cleanup["scoped_row_counts"] != {
            "execution_states": 0,
            "execution_transitions": 0,
        }:
            raise RuntimeError(
                "AE/AG scheduler daemon operator-control execution worker "
                "PostgreSQL smoke cleanup verification failed."
            )

        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "persisted": {
                "execution_state_id": state_id,
            },
            "routes": {
                "ae_persisted_execution_status": admitted_response.status_code,
                "ae_worker_statuses": bridge.worker_statuses,
                "ag_worker_status": ag_worker_response.status_code,
            },
            "execution": ae_worker_pg.ae_execution_pg._execution_evidence(
                admitted_payload
            ),
            "db_observations": {
                "before": before,
                "after": after,
            },
            "ag_worker": _ag_worker_evidence(ag_worker_payload),
            "checks": checks,
            "cleanup": cleanup,
            "post_cleanup": post_cleanup,
            "live_db": True,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if state_ids:
            try:
                session_factory = build_session_factory(engine)
                execution_store = (
                    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
                        session_factory
                    )
                )
                ae_worker_pg._cleanup_execution_states(execution_store, state_ids)
            except (SQLAlchemyError, RuntimeError, ValueError):
                pass
        engine.dispose()


def _ag_worker_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    worker_result = _mapping_value(payload.get("worker_result"))
    summary = _mapping_value(payload.get("summary"))
    source_status = _mapping_value(payload.get("source_status"))
    guidance = _mapping_value(payload.get("operator_guidance"))
    metadata = _mapping_value(worker_result.get("metadata"))
    guardrails = _mapping_value(worker_result.get("guardrails"))
    return {
        "projection_schema_version": payload.get("projection_schema_version"),
        "projection_status": payload.get("projection_status"),
        "service_id": payload.get("service_id"),
        "operation_type": payload.get("operation_type"),
        "operator_control_execution_state_id": payload.get(
            "operator_control_execution_state_id"
        ),
        "operator_control_execution_worker_result_id": payload.get(
            "operator_control_execution_worker_result_id"
        ),
        "request_trace_id": payload.get("request_trace_id"),
        "worker_result": {
            "source_schema_version": worker_result.get(
                "source_operator_control_execution_worker_result_schema_version"
            ),
            "operator_control_execution_worker_result_id": worker_result.get(
                "operator_control_execution_worker_result_id"
            ),
            "operator_control_execution_state_id": worker_result.get(
                "operator_control_execution_state_id"
            ),
            "scheduler_id": worker_result.get("scheduler_id"),
            "action": worker_result.get("action"),
            "execution_mode": worker_result.get("execution_mode"),
            "worker_mode": worker_result.get("worker_mode"),
            "worker_status": worker_result.get("worker_status"),
            "worker_plan_status": worker_result.get("worker_plan_status"),
            "worker_command_status": worker_result.get("worker_command_status"),
            "transition_plan_status": worker_result.get("transition_plan_status"),
            "transition_terminal_status": worker_result.get(
                "transition_terminal_status"
            ),
            "transition_count": worker_result.get("transition_count"),
            "status_path": _list_value(worker_result.get("status_path")),
            "supervisor_result_count": worker_result.get("supervisor_result_count"),
            "supervisor_result_statuses": _list_value(
                worker_result.get("supervisor_result_statuses")
            ),
            "worker_execution_performed": metadata.get(
                "worker_execution_performed"
            ),
            "supervisor_adapter_invoked": guardrails.get(
                "supervisor_adapter_invoked"
            )
            or metadata.get("supervisor_adapter_invoked"),
            "subprocess_started": guardrails.get("subprocess_started"),
            "database_write_performed": metadata.get("database_write_performed"),
            "transition_persistence_performed": metadata.get(
                "transition_persistence_performed"
            ),
            "raw_command_present": (
                "operator_control_execution_worker_command" in worker_result
            ),
            "raw_supervisor_results_present": "supervisor_results" in worker_result,
        },
        "summary": {
            "operator_control_execution_state_id": summary.get(
                "operator_control_execution_state_id"
            ),
            "worker_status": summary.get("worker_status"),
            "transition_terminal_status": summary.get(
                "transition_terminal_status"
            ),
            "transition_count": summary.get("transition_count"),
            "status_path": _list_value(summary.get("status_path")),
            "supervisor_result_count": summary.get("supervisor_result_count"),
            "supervisor_result_statuses": _list_value(
                summary.get("supervisor_result_statuses")
            ),
            "worker_execution_performed": summary.get(
                "worker_execution_performed"
            ),
            "supervisor_adapter_invoked": summary.get(
                "supervisor_adapter_invoked"
            ),
            "subprocess_started": summary.get("subprocess_started"),
            "database_write_performed": summary.get("database_write_performed"),
            "transition_persistence_performed": summary.get(
                "transition_persistence_performed"
            ),
            "operator_attention_required": summary.get(
                "operator_attention_required"
            ),
            "metadata_only": summary.get("metadata_only"),
        },
        "source_status": source_status,
        "operator_guidance": guidance,
        "raw_worker_result_present": "operator_control_execution_worker_command"
        in payload,
    }


def _smoke_checks(
    *,
    database_url: str,
    database_env: str,
    admitted_response: int,
    admitted_payload: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    bridge: AeTestClientDaemonOperatorControlExecutionWorkerClient,
    ag_worker_status: int,
    ag_worker: Mapping[str, Any],
) -> dict[str, bool]:
    admitted = ae_worker_pg.ae_execution_pg._execution_evidence(admitted_payload)
    worker = _ag_worker_evidence(ag_worker)
    worker_result = _mapping_value(worker.get("worker_result"))
    summary = _mapping_value(worker.get("summary"))
    source = _mapping_value(worker.get("source_status"))
    guidance = _mapping_value(worker.get("operator_guidance"))
    side_effect_keys = (
        "process_records",
        "process_events",
        "supervisor_records",
        "supervisor_events",
    )
    return {
        "test_database_url": database_env == "NEX_AE_TEST_DATABASE_URL"
        and ae_worker_pg.ae_execution_pg._database_name(database_url).endswith(
            "_test"
        ),
        "database_health_probe": before.get("health_probe") is True
        and after.get("health_probe") is True,
        "migration_recorded": before.get("migration_recorded") is True
        and after.get("migration_recorded") is True,
        "tables_present": set(before.get("tables_present", [])) == EXPECTED_TABLES
        and set(after.get("tables_present", [])) == EXPECTED_TABLES,
        "indexes_present": set(before.get("indexes_present", [])) == EXPECTED_INDEXES
        and set(after.get("indexes_present", [])) == EXPECTED_INDEXES,
        "postgres_state_jsonb_columns_verified": _state_jsonb_verified(after),
        "persisted_execution_state_route_passed": admitted_response == 200
        and admitted["schema_version"]
        == ae_worker_pg.ae_execution_pg.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION
        and admitted["execution_mode"]
        == "fake_dry_run_supervisor_persistent_dispatch"
        and admitted["execution_status"] == "ADMITTED"
        and admitted["idempotency_status"] == "NEW"
        and admitted["database_write_performed"] is False,
        "ag_worker_route_ok": ag_worker_status == 200
        and bridge.worker_statuses == [200],
        "ag_worker_projection_ready": worker.get("projection_schema_version")
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION
        and worker.get("projection_status") == "READY"
        and worker.get("operator_control_execution_state_id")
        == admitted["state_id"]
        and worker_result.get("source_schema_version")
        == ae_worker_pg.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION
        and worker_result.get("operator_control_execution_state_id")
        == admitted["state_id"]
        and worker_result.get("worker_status") == "SUCCEEDED"
        and worker_result.get("worker_plan_status") == "READY"
        and worker_result.get("worker_command_status") == "READY"
        and worker_result.get("transition_plan_status") == "READY"
        and worker_result.get("transition_terminal_status") == "SUCCEEDED"
        and worker_result.get("transition_count") == 2
        and worker_result.get("status_path")
        == ["ADMITTED", "EXECUTING", "SUCCEEDED"]
        and worker_result.get("supervisor_result_count") == 1
        and summary.get("worker_status") == "SUCCEEDED"
        and summary.get("operator_attention_required") is False
        and source.get("source_kind") == "ae_test_client"
        and source.get("execution_worker_result_loaded") is True,
        "ag_worker_guardrails_hold": summary.get("worker_execution_performed")
        is True
        and summary.get("supervisor_adapter_invoked") is True
        and summary.get("subprocess_started") is False
        and summary.get("database_write_performed") is False
        and summary.get("transition_persistence_performed") is False
        and worker_result.get("raw_command_present") is False
        and worker_result.get("raw_supervisor_results_present") is False,
        "ag_projection_read_only": guidance.get("ag_direct_database_write_allowed")
        is False
        and guidance.get("ag_direct_process_control_allowed") is False
        and guidance.get("ag_direct_daemon_process_control_allowed") is False
        and guidance.get("ag_direct_job_enqueue_allowed") is False
        and guidance.get("physical_delete_automation_enabled") is False,
        "scoped_state_written_without_transition": before.get("scoped_row_counts")
        == {"execution_states": 0, "execution_transitions": 0}
        and after.get("scoped_row_counts")
        == {"execution_states": 1, "execution_transitions": 0},
        "no_process_or_supervisor_rows_added": all(
            _mapping_value(before.get("row_counts")).get(key)
            == _mapping_value(after.get("row_counts")).get(key)
            for key in side_effect_keys
        ),
        "metadata_only_evidence": _metadata_only(
            admitted,
            worker,
            forbidden_fragments=[
                database_url,
                ae_worker_pg.ae_execution_pg._database_url_password(database_url),
                "/data/nex-platform",
                "ed6@c496em",
                "slice-0609-worker-",
                "content_base64",
                '"database_url_included": true',
                '"storage_path_included": true',
                '"raw_artifact_payload_included": true',
                '"raw_execution_payload_included": true',
                '"raw_daemon_runtime_payload_included": true',
                '"raw_supervised_process_snapshot_included": true',
            ],
        ),
    }


def _state_jsonb_verified(observations: Mapping[str, Any]) -> bool:
    if observations.get("dialect") != "postgresql":
        return True
    jsonb_columns = _mapping_value(observations.get("jsonb_columns"))
    return all(
        jsonb_columns.get(key) == value
        for key, value in EXPECTED_STATE_JSONB_TYPES.items()
    )


def _ag_auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=AG_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _json_payload(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except (AttributeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_or_none(value: Any) -> str | None:
    text_value = str(value).strip() if value is not None else ""
    return text_value or None


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
    safe = ae_worker_pg._safe_detail(detail, env)
    for key in (SMOKE_PROFILE_ENV,):
        value = env.get(key)
        if value:
            safe = safe.replace(value, f"<redacted:{key}>")
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    ae_worker_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)
    for forbidden in (
        "slice-0609-worker-",
        "body-slice-0609-worker-",
        "DATABASE_URL_SHOULD_NOT_LEAK",
    ):
        if forbidden in serialized_evidence:
            raise ValueError(
                "AE/AG operator-control execution worker smoke contains private "
                "operator-control request data."
            )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        scoped_rows = evidence["db_observations"]["after"]["scoped_row_counts"]
        return (
            "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
            "pass "
            f"service={evidence['service_id']} "
            f"ag_service={evidence['ag_service_id']} "
            f"db_env={evidence['database_env']} "
            f"states={scoped_rows['execution_states']} "
            f"transitions={scoped_rows['execution_transitions']} "
            f"ag_worker={evidence['routes']['ag_worker_status']} "
            f"ae_worker={evidence['routes']['ae_worker_statuses']} "
            f"worker={evidence['ag_worker']['summary']['worker_status']} "
            f"cleanup_states={evidence['cleanup']['execution_states']} "
            f"cleanup_transitions={evidence['cleanup']['execution_state_transitions']} "
            f"live_db={str(evidence['live_db']).lower()}"
        )
    return (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
        "fail "
        f"service={evidence.get('service_id')} "
        f"ag_service={evidence.get('ag_service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE/AG scheduler daemon operator-control execution "
            "worker PostgreSQL smoke."
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
        run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke()
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
