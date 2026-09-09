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
import run_ae_operator_control_execution_worker_result_postgres_smoke as ae_result_pg  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_RECORD_SCHEMA_VERSION,
    AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE,
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore,
)
from nex_ae_api.artifacts import register_artifact_handoff_routes  # noqa: E402
from nex_ag.artifact_operations import (  # noqa: E402
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_PROJECTION_SCHEMA_VERSION,
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
    "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_"
    "worker_result_read_model_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_"
    "WORKER_RESULT_READ_MODEL_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_"
    "WORKER_RESULT_READ_MODEL_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = ae_result_pg.SERVICE_ID
AG_SERVICE_ID = "nex-ag"
DEFAULT_PROFILE = ae_result_pg.DEFAULT_PROFILE
MIGRATION_VERSION = ae_result_pg.MIGRATION_VERSION
CHECKED_AT = "2026-09-09T00:18:00Z"
REQUESTED_AT = "2026-09-09T00:17:55Z"
WORKER_OBSERVED_AT = "2026-09-09T00:18:20Z"
EXECUTION_ROUTE = ae_result_pg.EXECUTION_ROUTE
WORKER_ROUTE = ae_result_pg.WORKER_ROUTE
AE_WORKER_RESULT_ROUTE = (
    "/api/v1/artifact-retention/"
    "scheduler-daemon-operator-control-execution-worker-results"
)
AG_WORKER_RESULT_ROUTE = (
    "/admin/v1/operations/artifact-retention/"
    "scheduler-daemon-operator-control-execution-worker-results"
)
EXPECTED_TABLES = ae_result_pg.EXPECTED_TABLES
EXPECTED_INDEXES = ae_result_pg.EXPECTED_INDEXES
EXPECTED_JSONB_TYPES = ae_result_pg.EXPECTED_JSONB_TYPES


class AeTestClientDaemonOperatorControlExecutionWorkerResultReadModelClient:
    source_kind = "ae_test_client"
    base_url = "testclient://nex-ae-api"

    def __init__(self, client: TestClient, headers: Mapping[str, str]) -> None:
        self.client = client
        self.headers = dict(headers)
        self.worker_result_collection_statuses: list[int] = []
        self.worker_result_detail_statuses: list[int] = []

    def list_artifact_retention_scheduler_daemon_operator_control_execution_worker_results(
        self,
        *,
        scheduler_id: str | None = None,
        action: str | None = None,
        worker_status: str | None = None,
        operator_control_execution_state_id: str | None = None,
        operator_control_execution_request_id: str | None = None,
        limit: int | None = None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        params = _worker_result_query_params(
            scheduler_id=scheduler_id,
            action=action,
            worker_status=worker_status,
            operator_control_execution_state_id=(
                operator_control_execution_state_id
            ),
            operator_control_execution_request_id=(
                operator_control_execution_request_id
            ),
            limit=limit,
        )
        response = self.client.get(
            AE_WORKER_RESULT_ROUTE,
            params=params,
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.worker_result_collection_statuses.append(response.status_code)
        return self._json_or_error(response)

    def get_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_detail(
        self,
        operator_control_execution_worker_result_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        response = self.client.get(
            f"{AE_WORKER_RESULT_ROUTE}/{operator_control_execution_worker_result_id}",
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.worker_result_detail_statuses.append(response.status_code)
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
                    "ag.ae_artifact_retention_daemon_operator_control_execution_worker_result_source_failed",
                ),
                detail=payload.get(
                    "detail",
                    "AE artifact retention scheduler daemon operator-control "
                    "execution worker result source failed.",
                ),
                status_code=response.status_code,
            )
        return payload if isinstance(payload, dict) else {}


def run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke(
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
            (
                f"{SMOKE_PROFILE_ENV} must be test for AG-to-AE worker-result "
                "PostgreSQL smoke."
            ),
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
        execution = _execute_ae_ag_worker_result_read_model_smoke(
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


def _execute_ae_ag_worker_result_read_model_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    idempotency_key = f"slice-0618-worker-result-{suffix}"
    state_ids: list[str] = []
    result_ids: list[str] = []
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
        ae_result_pg._ensure_sqlite_migration_marker(engine)
        execution_store = (
            SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
                session_factory
            )
        )
        result_store = (
            SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore(
                session_factory
            )
        )
        execution_store.ensure_schema()
        result_store.ensure_schema()
        before = _db_observations(engine, idempotency_key=idempotency_key)

        ae_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        ae_app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(
            ae_app,
            retention_scheduler_daemon_operator_control_execution_store=(
                execution_store
            ),
            retention_scheduler_daemon_operator_control_execution_worker_result_store=(
                result_store
            ),
        )
        ae_client = TestClient(ae_app)
        ae_headers = ae_worker_pg.ae_execution_pg.artifact_pg._auth_headers(
            request_id=request_id,
            trace_id=trace_id,
        )

        admitted_response = ae_client.post(
            EXECUTION_ROUTE,
            json={
                **_execution_payload(suffix=suffix),
                "persist_execution_state": True,
            },
            headers={**ae_headers, "Idempotency-Key": idempotency_key},
        )
        admitted_payload = _json_payload(admitted_response)
        state_id = _append_optional_text(
            state_ids,
            admitted_payload.get("operator_control_execution_state_id"),
        )

        worker_response = ae_client.post(
            WORKER_ROUTE,
            json={
                "operator_control_execution_state_id": state_id,
                "checked_at": CHECKED_AT,
                "worker_observed_at": WORKER_OBSERVED_AT,
                "persist_worker_result": True,
            },
            headers=ae_headers,
        )
        worker_payload = _json_payload(worker_response)
        result_id = _append_optional_text(
            result_ids,
            worker_payload.get("operator_control_execution_worker_result_id"),
        )
        request_filter_id = _text_or_none(
            admitted_payload.get("operator_control_execution_request_id")
        )
        query_params = _worker_result_query_params(
            scheduler_id=_text_or_none(admitted_payload.get("scheduler_id")),
            action=_text_or_none(admitted_payload.get("action")),
            worker_status="SUCCEEDED",
            operator_control_execution_state_id=state_id,
            operator_control_execution_request_id=request_filter_id,
            limit=3,
        )

        ae_collection_response = ae_client.get(
            AE_WORKER_RESULT_ROUTE,
            params=query_params,
            headers=ae_headers,
        )
        ae_collection_payload = _json_payload(ae_collection_response)
        ae_detail_response = ae_client.get(
            f"{AE_WORKER_RESULT_ROUTE}/{result_id}",
            headers=ae_headers,
        )
        ae_detail_payload = _json_payload(ae_detail_response)

        bridge = (
            AeTestClientDaemonOperatorControlExecutionWorkerResultReadModelClient(
                ae_client,
                headers=ae_headers,
            )
        )
        ag_app = build_service_app(SERVICE_SPECS[AG_SERVICE_ID])
        register_artifact_operation_routes(ag_app, client=bridge)
        ag_client = TestClient(ag_app)
        ag_headers = _ag_auth_headers(request_id=request_id, trace_id=trace_id)
        ag_collection_response = ag_client.get(
            AG_WORKER_RESULT_ROUTE,
            params={"service_id": SERVICE_ID, **query_params},
            headers=ag_headers,
        )
        ag_collection_payload = _json_payload(ag_collection_response)
        ag_detail_response = ag_client.get(
            f"{AG_WORKER_RESULT_ROUTE}/{result_id}",
            params={"service_id": SERVICE_ID},
            headers=ag_headers,
        )
        ag_detail_payload = _json_payload(ag_detail_response)

        result_record = result_store.get_worker_result(result_id) if result_id else None
        after = _db_observations(
            engine,
            state_ids=state_ids,
            result_ids=result_ids,
            idempotency_key=idempotency_key,
        )

        checks = _smoke_checks(
            database_url=database_url,
            database_env=database_env,
            admitted_response=admitted_response.status_code,
            worker_response=worker_response.status_code,
            ae_collection_status=ae_collection_response.status_code,
            ae_detail_status=ae_detail_response.status_code,
            ag_collection_status=ag_collection_response.status_code,
            ag_detail_status=ag_detail_response.status_code,
            admitted_payload=admitted_payload,
            worker_payload=worker_payload,
            result_record=result_record,
            ae_collection=ae_collection_payload,
            ae_detail=ae_detail_payload,
            ag_collection=ag_collection_payload,
            ag_detail=ag_detail_payload,
            before=before,
            after=after,
            bridge=bridge,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE/AG operator-control execution worker result PostgreSQL "
                f"smoke checks failed: {', '.join(failed_checks)}"
            )

        cleanup = ae_result_pg._cleanup_worker_result_rows(
            result_store=result_store,
            execution_store=execution_store,
            result_ids=result_ids,
            state_ids=state_ids,
        )
        post_cleanup = _db_observations(
            engine,
            state_ids=state_ids,
            result_ids=result_ids,
            idempotency_key=idempotency_key,
        )
        if post_cleanup["scoped_row_counts"] != {
            "execution_states": 0,
            "execution_transitions": 0,
            "worker_results": 0,
        }:
            raise RuntimeError(
                "AE/AG operator-control execution worker result PostgreSQL "
                "smoke cleanup verification failed."
            )

        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "persisted": {
                "execution_state_id": state_id,
                "worker_result_id": result_id,
                "stored_table": AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE,
            },
            "routes": {
                "ae_persisted_execution_status": admitted_response.status_code,
                "ae_persisted_worker_result_status": worker_response.status_code,
                "ae_worker_result_collection_status": (
                    ae_collection_response.status_code
                ),
                "ae_worker_result_detail_status": ae_detail_response.status_code,
                "ae_worker_result_collection_statuses": (
                    bridge.worker_result_collection_statuses
                ),
                "ae_worker_result_detail_statuses": (
                    bridge.worker_result_detail_statuses
                ),
                "ag_worker_result_collection_status": (
                    ag_collection_response.status_code
                ),
                "ag_worker_result_detail_status": ag_detail_response.status_code,
            },
            "execution": ae_worker_pg.ae_execution_pg._execution_evidence(
                admitted_payload
            ),
            "worker": ae_worker_pg._worker_evidence(worker_payload),
            "worker_result_record": _worker_result_record_evidence(
                result_record or {}
            ),
            "ae_worker_result_collection": _ae_collection_evidence(
                ae_collection_payload
            ),
            "ae_worker_result_detail": _ae_detail_evidence(ae_detail_payload),
            "ag_worker_result_collection": _ag_collection_evidence(
                ag_collection_payload
            ),
            "ag_worker_result_detail": _ag_detail_evidence(ag_detail_payload),
            "db_observations": {
                "before": before,
                "after": after,
            },
            "checks": checks,
            "cleanup": cleanup,
            "post_cleanup": post_cleanup,
            "live_db": True,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if state_ids or result_ids:
            try:
                session_factory = build_session_factory(engine)
                ae_result_pg._cleanup_worker_result_rows(
                    result_store=(
                        SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore(
                            session_factory
                        )
                    ),
                    execution_store=(
                        SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
                            session_factory
                        )
                    ),
                    result_ids=result_ids,
                    state_ids=state_ids,
                )
            except (SQLAlchemyError, RuntimeError, ValueError):
                pass
        engine.dispose()


def _execution_payload(*, suffix: str) -> dict[str, Any]:
    payload = ae_result_pg._execution_payload(suffix=suffix)
    reason = "slice_0618_ag_worker_result_read_model_postgresql_smoke"
    payload.update(
        {
            "checked_at": CHECKED_AT,
            "requested_at": REQUESTED_AT,
            "observed_at": CHECKED_AT,
            "reason": reason,
            "approval": {
                **_mapping_value(payload.get("approval")),
                "approved_at": REQUESTED_AT,
                "reason": reason,
            },
        }
    )
    return payload


def _worker_result_query_params(
    *,
    scheduler_id: str | None,
    action: str | None,
    worker_status: str | None,
    operator_control_execution_state_id: str | None,
    operator_control_execution_request_id: str | None,
    limit: int | None,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "scheduler_id": scheduler_id,
            "action": action,
            "worker_status": worker_status,
            "operator_control_execution_state_id": (
                operator_control_execution_state_id
            ),
            "operator_control_execution_request_id": (
                operator_control_execution_request_id
            ),
            "limit": limit,
        }.items()
        if value is not None
    }


def _worker_result_record_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    return ae_result_pg._worker_result_record_evidence(record)


def _ae_collection_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    items = _list_value(payload.get("items"))
    first_item = _mapping_value(items[0]) if items else {}
    guardrails = _mapping_value(payload.get("guardrails"))
    metadata = _mapping_value(payload.get("metadata"))
    return {
        "schema_version": payload.get(
            "operator_control_execution_worker_result_collection_schema_version"
        ),
        "service_id": payload.get("service_id"),
        "count": payload.get("count"),
        "limit": payload.get("limit"),
        "filter": _mapping_value(payload.get("filter")),
        "first_item": _worker_result_item_evidence(first_item),
        "guardrails": {
            "read_only": guardrails.get("read_only"),
            "database_write_performed": guardrails.get(
                "database_write_performed"
            ),
            "ag_direct_database_write_allowed": guardrails.get(
                "ag_direct_database_write_allowed"
            ),
        },
        "metadata": {
            "read_model": metadata.get("read_model"),
            "item_count": metadata.get("item_count"),
            "safe_for_ag_projection": metadata.get("safe_for_ag_projection"),
            "worker_result_record_only": metadata.get(
                "worker_result_record_only"
            ),
        },
    }


def _ae_detail_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping_value(payload.get("summary"))
    guardrails = _mapping_value(payload.get("guardrails"))
    metadata = _mapping_value(payload.get("metadata"))
    record = _mapping_value(payload.get("worker_result_record"))
    return {
        "schema_version": payload.get(
            "operator_control_execution_worker_result_detail_schema_version"
        ),
        "worker_result_id": payload.get(
            "operator_control_execution_worker_result_id"
        ),
        "state_id": payload.get("operator_control_execution_state_id"),
        "request_id": payload.get("operator_control_execution_request_id"),
        "summary": {
            "worker_status": summary.get("worker_status"),
            "decision_reason": summary.get("decision_reason"),
            "database_write_performed": summary.get("database_write_performed"),
            "safe_for_ag_projection": summary.get("safe_for_ag_projection"),
        },
        "record": _worker_result_item_evidence(record),
        "guardrails": {
            "read_only": guardrails.get("read_only"),
            "database_write_performed": guardrails.get(
                "database_write_performed"
            ),
            "ag_direct_database_write_allowed": guardrails.get(
                "ag_direct_database_write_allowed"
            ),
        },
        "metadata": {
            "read_model": metadata.get("read_model"),
            "stored_table": metadata.get("stored_table"),
            "safe_for_ag_projection": metadata.get("safe_for_ag_projection"),
        },
    }


def _ag_collection_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    items = _list_value(payload.get("items"))
    first_item = _mapping_value(items[0]) if items else {}
    summary = _mapping_value(payload.get("summary"))
    source_status = _mapping_value(payload.get("source_status"))
    guidance = _mapping_value(payload.get("operator_guidance"))
    return {
        "projection_schema_version": payload.get("projection_schema_version"),
        "projection_status": payload.get("projection_status"),
        "service_id": payload.get("service_id"),
        "count": payload.get("count"),
        "limit": payload.get("limit"),
        "filter": _mapping_value(payload.get("filter")),
        "first_item": _worker_result_item_evidence(first_item),
        "summary": {
            "operator_control_execution_worker_result_count": summary.get(
                "operator_control_execution_worker_result_count"
            ),
            "succeeded_count": summary.get("succeeded_count"),
            "failed_count": summary.get("failed_count"),
            "operator_attention_required": summary.get(
                "operator_attention_required"
            ),
            "metadata_only": summary.get("metadata_only"),
        },
        "source_status": {
            "source_kind": source_status.get("source_kind"),
            "worker_result_collection_loaded": source_status.get(
                "worker_result_collection_loaded"
            ),
            "worker_result_detail_loaded": source_status.get(
                "worker_result_detail_loaded"
            ),
        },
        "operator_guidance": {
            "read_model": guidance.get("read_model"),
            "ag_direct_database_write_allowed": guidance.get(
                "ag_direct_database_write_allowed"
            ),
            "ag_direct_job_enqueue_allowed": guidance.get(
                "ag_direct_job_enqueue_allowed"
            ),
            "physical_delete_automation_enabled": guidance.get(
                "physical_delete_automation_enabled"
            ),
        },
    }


def _ag_detail_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping_value(payload.get("summary"))
    worker_result = _mapping_value(payload.get("worker_result"))
    source_status = _mapping_value(payload.get("source_status"))
    guidance = _mapping_value(payload.get("operator_guidance"))
    return {
        "projection_schema_version": payload.get("projection_schema_version"),
        "projection_status": payload.get("projection_status"),
        "worker_result_id": payload.get(
            "operator_control_execution_worker_result_id"
        ),
        "state_id": payload.get("operator_control_execution_state_id"),
        "request_id": payload.get("operator_control_execution_request_id"),
        "worker_result": _worker_result_item_evidence(worker_result),
        "summary": {
            "worker_status": summary.get("worker_status"),
            "transition_terminal_status": summary.get(
                "transition_terminal_status"
            ),
            "operator_attention_required": summary.get(
                "operator_attention_required"
            ),
            "database_write_performed": summary.get("database_write_performed"),
            "metadata_only": summary.get("metadata_only"),
        },
        "source_status": {
            "source_kind": source_status.get("source_kind"),
            "worker_result_collection_loaded": source_status.get(
                "worker_result_collection_loaded"
            ),
            "worker_result_detail_loaded": source_status.get(
                "worker_result_detail_loaded"
            ),
        },
        "operator_guidance": {
            "read_model": guidance.get("read_model"),
            "ag_direct_database_write_allowed": guidance.get(
                "ag_direct_database_write_allowed"
            ),
            "ag_direct_job_enqueue_allowed": guidance.get(
                "ag_direct_job_enqueue_allowed"
            ),
            "physical_delete_automation_enabled": guidance.get(
                "physical_delete_automation_enabled"
            ),
        },
    }


def _worker_result_item_evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping_value(item.get("metadata"))
    guardrails = _mapping_value(item.get("guardrails"))
    return {
        "source_schema_version": item.get(
            "source_operator_control_execution_worker_result_schema_version"
        )
        or item.get("operator_control_execution_worker_result_record_schema_version"),
        "worker_result_id": item.get("operator_control_execution_worker_result_id"),
        "state_id": item.get("operator_control_execution_state_id"),
        "request_id": item.get("operator_control_execution_request_id"),
        "scheduler_id": item.get("scheduler_id"),
        "action": item.get("action"),
        "worker_status": item.get("worker_status"),
        "transition_terminal_status": item.get("transition_terminal_status"),
        "status_path": _list_value(item.get("status_path")),
        "supervisor_result_count": item.get("supervisor_result_count"),
        "hashes_present": _hashes_present(item),
        "safe_for_ag_projection": (
            metadata.get("safe_for_ag_projection")
            or guardrails.get("safe_for_ag_projection")
        ),
        "raw_command_present": "operator_control_execution_worker_command" in item,
        "raw_transition_plan_present": (
            "operator_control_execution_worker_transition_plan" in item
        ),
        "raw_supervisor_results_present": "supervisor_results" in item,
    }


def _hashes_present(item: Mapping[str, Any]) -> bool:
    hashes = _mapping_value(item.get("hashes"))
    return all(
        isinstance(
            hashes.get(key) or item.get(key),
            str,
        )
        and len(str(hashes.get(key) or item.get(key))) == 64
        for key in (
            "operator_control_execution_worker_command_hash",
            "operator_control_execution_worker_transition_plan_hash",
            "supervisor_results_hash",
            "worker_result_hash",
        )
    )


def _smoke_checks(
    *,
    database_url: str,
    database_env: str,
    admitted_response: int,
    worker_response: int,
    ae_collection_status: int,
    ae_detail_status: int,
    ag_collection_status: int,
    ag_detail_status: int,
    admitted_payload: Mapping[str, Any],
    worker_payload: Mapping[str, Any],
    result_record: Mapping[str, Any] | None,
    ae_collection: Mapping[str, Any],
    ae_detail: Mapping[str, Any],
    ag_collection: Mapping[str, Any],
    ag_detail: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    bridge: AeTestClientDaemonOperatorControlExecutionWorkerResultReadModelClient,
) -> dict[str, bool]:
    execution = ae_worker_pg.ae_execution_pg._execution_evidence(admitted_payload)
    worker = ae_worker_pg._worker_evidence(worker_payload)
    record = _worker_result_record_evidence(result_record or {})
    ae_collection_view = _ae_collection_evidence(ae_collection)
    ae_detail_view = _ae_detail_evidence(ae_detail)
    ag_collection_view = _ag_collection_evidence(ag_collection)
    ag_detail_view = _ag_detail_evidence(ag_detail)
    expected_rows = {
        "execution_states": 1,
        "execution_transitions": 0,
        "worker_results": 1,
    }
    result_id = worker.get("worker_result_id")
    return {
        "test_database_url": database_env == "NEX_AE_TEST_DATABASE_URL"
        and ae_worker_pg.ae_execution_pg._database_name(database_url).endswith(
            "_test"
        ),
        "database_health_probe": before.get("health_probe") is True
        and after.get("health_probe") is True,
        "migration_recorded": before.get("migration_recorded") is True
        and after.get("migration_recorded") is True,
        "tables_present": EXPECTED_TABLES.issubset(
            set(after.get("tables_present", []))
        ),
        "indexes_present": EXPECTED_INDEXES.issubset(
            set(after.get("indexes_present", []))
        ),
        "postgres_jsonb_columns": after.get("dialect") != "postgresql"
        or after.get("jsonb_columns") == EXPECTED_JSONB_TYPES,
        "ae_persisted_worker_result_written": admitted_response == 200
        and worker_response == 200
        and execution.get("execution_status") == "ADMITTED"
        and worker.get("worker_status") == "SUCCEEDED"
        and record.get("schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_RECORD_SCHEMA_VERSION
        and record.get("worker_result_id") == result_id
        and record.get("state_id") == execution.get("state_id")
        and record.get("hashes_present") is True,
        "ae_worker_result_read_model_routes": ae_collection_status == 200
        and ae_detail_status == 200
        and ae_collection_view.get("schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_SCHEMA_VERSION
        and ae_collection_view.get("count") == 1
        and ae_collection_view["first_item"].get("worker_result_id") == result_id
        and ae_detail_view.get("schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_SCHEMA_VERSION
        and ae_detail_view.get("worker_result_id") == result_id
        and ae_detail_view["record"].get("hashes_present") is True,
        "ag_worker_result_projection_routes": ag_collection_status == 200
        and ag_detail_status == 200
        and ag_collection_view.get("projection_schema_version")
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_PROJECTION_SCHEMA_VERSION
        and ag_collection_view.get("projection_status") == "READY"
        and ag_collection_view.get("count") == 1
        and ag_collection_view["summary"].get("succeeded_count") == 1
        and ag_collection_view["first_item"].get("worker_result_id") == result_id
        and ag_detail_view.get("projection_schema_version")
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_PROJECTION_SCHEMA_VERSION
        and ag_detail_view.get("projection_status") == "READY"
        and ag_detail_view.get("worker_result_id") == result_id
        and ag_detail_view["summary"].get("worker_status") == "SUCCEEDED",
        "ag_uses_ae_read_model_bridge": (
            bridge.worker_result_collection_statuses == [200]
            and bridge.worker_result_detail_statuses == [200]
            and ag_collection_view["source_status"].get("source_kind")
            == "ae_test_client"
            and ag_detail_view["source_status"].get("source_kind")
            == "ae_test_client"
        ),
        "scoped_rows_written": before.get("scoped_row_counts")
        == {
            "execution_states": 0,
            "execution_transitions": 0,
            "worker_results": 0,
        }
        and after.get("scoped_row_counts") == expected_rows,
        "read_only_projection_guardrails": ag_collection_view[
            "operator_guidance"
        ].get("ag_direct_database_write_allowed")
        is False
        and ag_detail_view["operator_guidance"].get(
            "ag_direct_database_write_allowed"
        )
        is False
        and ag_collection_view["operator_guidance"].get(
            "ag_direct_job_enqueue_allowed"
        )
        is False
        and ag_detail_view["operator_guidance"].get(
            "physical_delete_automation_enabled"
        )
        is False,
        "metadata_only_evidence": _metadata_only(
            execution,
            worker,
            record,
            ae_collection_view,
            ae_detail_view,
            ag_collection_view,
            ag_detail_view,
            forbidden_fragments=[
                database_url,
                ae_worker_pg.ae_execution_pg._database_url_password(database_url),
                "/data/nex-platform",
                "ed6@c496em",
                "slice-0618-worker-result-",
                "body-slice-0618-worker-result-",
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


def _db_observations(
    engine: Any,
    *,
    state_ids: list[str] | None = None,
    result_ids: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return ae_result_pg._db_observations(
        engine,
        state_ids=state_ids,
        result_ids=result_ids,
        idempotency_key=idempotency_key,
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


def _mapping_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_or_none(value: Any) -> str | None:
    text_value = str(value).strip() if value is not None else ""
    return text_value or None


def _append_optional_text(values: list[str], value: Any) -> str | None:
    text_value = _text_or_none(value)
    if text_value is not None:
        values.append(text_value)
    return text_value


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
    safe = ae_result_pg._safe_detail(detail, env)
    for key in (SMOKE_PROFILE_ENV,):
        value = env.get(key)
        if value:
            safe = safe.replace(value, f"<redacted:{key}>")
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    ae_result_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)
    for forbidden in (
        "slice-0618-worker-result-",
        "body-slice-0618-worker-result-",
        "DATABASE_URL_SHOULD_NOT_LEAK",
    ):
        if forbidden in serialized_evidence:
            raise ValueError(
                "AE/AG operator-control execution worker result smoke "
                "contains private operator-control request data."
            )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        scoped_rows = evidence["db_observations"]["after"]["scoped_row_counts"]
        cleanup = evidence["cleanup"]
        routes = evidence["routes"]
        return (
            "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke="
            "pass "
            f"service={evidence['service_id']} "
            f"ag_service={evidence['ag_service_id']} "
            f"db_env={evidence['database_env']} "
            f"results={scoped_rows['worker_results']} "
            f"states={scoped_rows['execution_states']} "
            f"ae_read={routes['ae_worker_result_collection_status']}/"
            f"{routes['ae_worker_result_detail_status']} "
            f"ag_read={routes['ag_worker_result_collection_status']}/"
            f"{routes['ag_worker_result_detail_status']} "
            f"worker={evidence['ag_worker_result_detail']['summary']['worker_status']} "
            f"cleanup_results={cleanup['operator_control_execution_worker_results']} "
            f"cleanup_states={cleanup['execution_states']} "
            f"live_db={str(evidence['live_db']).lower()}"
        )
    return (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke="
        "fail "
        f"service={evidence.get('service_id')} "
        f"ag_service={evidence.get('ag_service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE/AG operator-control execution worker-result "
            "read-model PostgreSQL smoke."
        )
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(args.env_file)
    evidence = (
        run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
