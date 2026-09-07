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

import run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke as process_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore,
)
from nex_ae_api.artifacts import register_artifact_handoff_routes  # noqa: E402
from nex_ag.artifact_operations import (  # noqa: E402
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_COLLECTION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_DETAIL_PROJECTION_SCHEMA_VERSION,
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
    "ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_READ_MODEL_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_READ_MODEL_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = process_pg.SERVICE_ID
AG_SERVICE_ID = "nex-ag"
DEFAULT_PROFILE = process_pg.DEFAULT_PROFILE
RUNNING_PROCESS_ID = 57875


class AeTestClientDaemonSupervisedProcessReadModelClient:
    source_kind = "ae_test_client"
    base_url = "testclient://nex-ae-api"

    def __init__(self, client: TestClient, headers: Mapping[str, str]) -> None:
        self.client = client
        self.headers = dict(headers)
        self.process_collection_statuses: list[int] = []
        self.process_detail_statuses: list[int] = []

    def list_artifact_retention_scheduler_daemon_process_snapshots(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        process_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.get(
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
            params={
                "limit": str(limit),
                **({"scheduler_id": scheduler_id} if scheduler_id else {}),
                **({"action": action} if action else {}),
                **(
                    {"process_status": process_status}
                    if process_status
                    else {}
                ),
            },
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.process_collection_statuses.append(response.status_code)
        return self._json_or_error(response)

    def get_artifact_retention_scheduler_daemon_process_snapshot_detail(
        self,
        daemon_supervised_process_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        response = self.client.get(
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots/"
            f"{daemon_supervised_process_record_id}",
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.process_detail_statuses.append(response.status_code)
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
                    "ag.ae_artifact_retention_daemon_process_source_failed",
                ),
                detail=payload.get(
                    "detail",
                    "AE artifact retention scheduler daemon process source failed.",
                ),
                status_code=response.status_code,
            )
        return payload if isinstance(payload, dict) else {}


def run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke(
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
        execution = _execute_ae_ag_daemon_supervised_process_read_model_smoke(
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


def _execute_ae_ag_daemon_supervised_process_read_model_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    record_ids: list[str] = []
    host_id = f"ae-ag-smoke-{suffix}"
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        process_pg._ensure_sqlite_migration_marker(engine)
        process_store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
            session_factory
        )
        process_store.ensure_schema()

        ae_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        ae_app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(ae_app)
        ae_client = TestClient(ae_app)
        ae_headers = process_pg.artifact_pg._auth_headers(
            request_id=request_id,
            trace_id=trace_id,
        )

        missing_response = ae_client.post(
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
            json=process_pg._process_payload(
                action="status_probe",
                suffix=suffix,
                reason="slice_0578_ag_read_model_status_probe",
                process_status="MISSING",
                host_id=host_id,
            ),
            headers=ae_headers,
        )
        missing_payload = process_pg._json_payload(missing_response)
        missing_record_id = process_pg._record_id(missing_payload)
        if missing_record_id:
            record_ids.append(missing_record_id)

        running_response = ae_client.post(
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
            json=process_pg._process_payload(
                action="start_daemon",
                suffix=suffix,
                reason="slice_0578_ag_read_model_running_snapshot",
                enabled=True,
                explicit_opt_in=True,
                max_cycles=2,
                run_worker=True,
                process_status="RUNNING",
                process_id=RUNNING_PROCESS_ID,
                host_id=host_id,
                started_at=process_pg.STARTED_AT,
                message="observed AG read-model smoke process snapshot",
            ),
            headers=ae_headers,
        )
        running_payload = process_pg._json_payload(running_response)
        running_record_id = process_pg._record_id(running_payload)
        if running_record_id:
            record_ids.append(running_record_id)

        scheduler_id = _scheduler_id_from_dispatches(
            missing_payload,
            running_payload,
        )
        bridge = AeTestClientDaemonSupervisedProcessReadModelClient(
            ae_client,
            headers=ae_headers,
        )
        ag_app = build_service_app(SERVICE_SPECS[AG_SERVICE_ID])
        register_artifact_operation_routes(ag_app, client=bridge)
        ag_client = TestClient(ag_app)
        ag_headers = _ag_auth_headers(request_id=request_id, trace_id=trace_id)

        ag_collection_response = ag_client.get(
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-process-snapshots",
            params={
                "scheduler_id": scheduler_id,
                "action": "start_daemon",
                "process_status": "RUNNING",
                "limit": "5",
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
            "scheduler-daemon-process-snapshots/"
            f"{running_record_id or 'missing'}",
            headers=ag_headers,
        )
        ag_detail = (
            ag_detail_response.json() if ag_detail_response.status_code == 200 else {}
        )
        db_observations = process_pg._db_observations(
            engine,
            record_ids=record_ids,
            scheduler_id=scheduler_id,
            host_id=host_id,
            process_id=RUNNING_PROCESS_ID,
        )
        checks = _ag_supervised_process_read_model_checks(
            database_url=database_url,
            database_env=database_env,
            missing_response=missing_response.status_code,
            running_response=running_response.status_code,
            missing_payload=missing_payload,
            running_payload=running_payload,
            db_observations=db_observations,
            record_ids=record_ids,
            bridge=bridge,
            ag_collection_status=ag_collection_response.status_code,
            ag_collection=ag_collection,
            ag_detail_status=ag_detail_response.status_code,
            ag_detail=ag_detail,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE/AG artifact retention scheduler daemon supervised process "
                "read-model PostgreSQL smoke checks failed: "
                f"{', '.join(failed_checks)}"
            )

        cleanup = process_pg._cleanup_supervised_process_records(
            process_store,
            record_ids,
        )
        post_cleanup = process_pg._db_observations(
            engine,
            record_ids=record_ids,
            scheduler_id=scheduler_id,
            host_id=host_id,
            process_id=RUNNING_PROCESS_ID,
        )
        if post_cleanup["row_counts"] != {
            "process_records": 0,
            "process_events": 0,
        }:
            raise RuntimeError(
                "AE/AG artifact retention scheduler daemon supervised process "
                "read-model PostgreSQL smoke cleanup verification failed."
            )
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "dispatches": {
                "status_probe_missing": process_pg._dispatch_evidence(
                    missing_payload
                ),
                "start_daemon_running": process_pg._dispatch_evidence(
                    running_payload
                ),
            },
            "db_observations": db_observations,
            "routes": {
                "ae_process_collection_statuses": (
                    bridge.process_collection_statuses
                ),
                "ae_process_detail_statuses": bridge.process_detail_statuses,
                "ag_process_collection_status": ag_collection_response.status_code,
                "ag_process_detail_status": ag_detail_response.status_code,
            },
            "ag_process_collection": {
                "projection_schema_version": ag_collection.get(
                    "projection_schema_version"
                ),
                "projection_status": ag_collection.get("projection_status"),
                "count": ag_collection.get("count"),
                "filter": ag_collection.get("filter"),
                "summary": ag_collection.get("summary"),
                "source_status": ag_collection.get("source_status"),
                "operator_guidance": ag_collection.get("operator_guidance"),
                "first_item_routes": (
                    ag_collection.get("items", [{}])[0].get("routes")
                    if ag_collection.get("items")
                    else {}
                ),
            },
            "ag_process_detail": {
                "projection_schema_version": ag_detail.get(
                    "projection_schema_version"
                ),
                "projection_status": ag_detail.get("projection_status"),
                "daemon_supervised_process_record_id": ag_detail.get(
                    "daemon_supervised_process_record_id"
                ),
                "supervised_process_event_count": ag_detail.get(
                    "supervised_process_event_count"
                ),
                "summary": ag_detail.get("summary"),
                "source_status": ag_detail.get("source_status"),
                "operator_guidance": ag_detail.get("operator_guidance"),
            },
            "checks": checks,
            "cleanup": cleanup,
            "post_cleanup": post_cleanup,
            "live_db": True,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if record_ids:
            try:
                session_factory = build_session_factory(engine)
                process_store = (
                    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
                        session_factory
                    )
                )
                process_pg._cleanup_supervised_process_records(
                    process_store,
                    record_ids,
                )
            except (SQLAlchemyError, RuntimeError, ValueError):
                pass
        engine.dispose()


def _scheduler_id_from_dispatches(
    missing_payload: Mapping[str, Any],
    running_payload: Mapping[str, Any],
) -> str:
    running_record = process_pg._mapping_value(
        running_payload.get("supervised_process_record")
    )
    missing_record = process_pg._mapping_value(
        missing_payload.get("supervised_process_record")
    )
    return (
        running_record.get("scheduler_id")
        or missing_record.get("scheduler_id")
        or "ae-artifact-retention-scheduler-local-v1"
    )


def _ag_supervised_process_read_model_checks(
    *,
    database_url: str,
    database_env: str,
    missing_response: int,
    running_response: int,
    missing_payload: Mapping[str, Any],
    running_payload: Mapping[str, Any],
    db_observations: Mapping[str, Any],
    record_ids: list[str],
    bridge: AeTestClientDaemonSupervisedProcessReadModelClient,
    ag_collection_status: int,
    ag_collection: Mapping[str, Any],
    ag_detail_status: int,
    ag_detail: Mapping[str, Any],
) -> dict[str, bool]:
    missing_record = process_pg._mapping_value(
        missing_payload.get("supervised_process_record")
    )
    running_record = process_pg._mapping_value(
        running_payload.get("supervised_process_record")
    )
    collection_summary = _mapping_value(ag_collection.get("summary"))
    detail_summary = _mapping_value(ag_detail.get("summary"))
    collection_source = _mapping_value(ag_collection.get("source_status"))
    detail_source = _mapping_value(ag_detail.get("source_status"))
    collection_guidance = _mapping_value(ag_collection.get("operator_guidance"))
    detail_guidance = _mapping_value(ag_detail.get("operator_guidance"))
    rows = _mapping_value(db_observations.get("row_counts"))
    record_counts = _mapping_value(db_observations.get("record_counts"))
    jsonb_columns = _mapping_value(db_observations.get("jsonb_columns"))
    return {
        "test_database_url": database_env == "NEX_AE_TEST_DATABASE_URL"
        and process_pg._database_name(database_url).endswith("_test"),
        "missing_route_passed": missing_response == 200
        and missing_payload.get("process_status") == "MISSING"
        and missing_payload.get("action") == "status_probe"
        and missing_record.get("process_running") is False,
        "running_route_passed": running_response == 200
        and running_payload.get("process_status") == "RUNNING"
        and running_payload.get("action") == "start_daemon"
        and running_record.get("process_id") == RUNNING_PROCESS_ID
        and running_record.get("process_running") is True
        and running_record.get("process_started_observed") is True,
        "guardrails_block_process_control": _mapping_value(
            running_payload.get("guardrails")
        ).get("process_control_allowed")
        is False
        and running_record.get("subprocess_adapter_required") is True,
        "process_rows_persisted": rows
        == {"process_records": 2, "process_events": 2},
        "record_status_counts_persisted": record_counts
        == {
            "status_probe_missing": 1,
            "start_daemon_running": 1,
            "running_pid": 1,
        },
        "record_ids_collected": len(set(record_ids)) == 2,
        "postgres_jsonb_columns_verified": db_observations.get("dialect")
        != "postgresql"
        or jsonb_columns == process_pg.EXPECTED_JSONB_TYPES,
        "ag_collection_route_ok": ag_collection_status == 200
        and bridge.process_collection_statuses == [200],
        "ag_detail_route_ok": ag_detail_status == 200
        and bridge.process_detail_statuses == [200],
        "ag_collection_projection_ready": ag_collection.get(
            "projection_schema_version"
        )
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_COLLECTION_PROJECTION_SCHEMA_VERSION
        and ag_collection.get("projection_status") == "READY"
        and ag_collection.get("count") == 1
        and collection_summary.get("supervised_process_record_count") == 1
        and collection_summary.get("running_count") == 1
        and collection_summary.get("adapter_required_count") == 1
        and collection_source.get("source_kind") == "ae_test_client"
        and collection_source.get("process_snapshot_collection_loaded") is True
        and collection_source.get("item_count") == 1,
        "ag_detail_projection_ready": ag_detail.get("projection_schema_version")
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_DETAIL_PROJECTION_SCHEMA_VERSION
        and ag_detail.get("projection_status") == "READY"
        and ag_detail.get("daemon_supervised_process_record_id")
        == running_record.get("daemon_supervised_process_record_id")
        and ag_detail.get("supervised_process_event_count") == 1
        and detail_summary.get("daemon_supervised_process_record_id")
        == running_record.get("daemon_supervised_process_record_id")
        and detail_summary.get("process_status") == "RUNNING"
        and detail_summary.get("process_running") is True
        and detail_source.get("process_snapshot_detail_loaded") is True,
        "ag_projection_read_only": collection_guidance.get(
            "ag_direct_database_write_allowed"
        )
        is False
        and collection_guidance.get("ag_direct_daemon_process_control_allowed")
        is False
        and detail_guidance.get("ag_direct_job_enqueue_allowed") is False,
        "metadata_only_evidence": _metadata_only(
            missing_payload,
            running_payload,
            ag_collection,
            ag_detail,
            forbidden_fragments=[
                database_url,
                process_pg._database_url_password(database_url),
                "/data/nex-platform",
                "content_base64",
                '"database_url_included": true',
                '"storage_path_included": true',
                '"raw_artifact_payload_included": true',
                '"raw_execution_payload_included": true',
                '"raw_daemon_runtime_payload_included": true',
            ],
        ),
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
    safe = process_pg._safe_detail(detail, env)
    for key in (SMOKE_PROFILE_ENV,):
        value = env.get(key)
        if value:
            safe = safe.replace(value, f"<redacted:{key}>")
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    process_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        rows = evidence["db_observations"]["row_counts"]
        return (
            "ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke="
            "pass "
            f"service={evidence['service_id']} "
            f"ag_service={evidence['ag_service_id']} "
            f"db_env={evidence['database_env']} "
            f"db_records={rows['process_records']} "
            f"events={rows['process_events']} "
            f"running={evidence['dispatches']['start_daemon_running']['process_status']} "
            f"ag_collection={evidence['routes']['ag_process_collection_status']} "
            f"ag_detail={evidence['routes']['ag_process_detail_status']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_records={evidence['cleanup']['daemon_supervised_process_records']}"
        )
    return (
        "ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke="
        "fail "
        f"service={evidence.get('service_id')} "
        f"ag_service={evidence.get('ag_service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE/AG scheduler daemon supervised process read-model "
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
        run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke()
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
