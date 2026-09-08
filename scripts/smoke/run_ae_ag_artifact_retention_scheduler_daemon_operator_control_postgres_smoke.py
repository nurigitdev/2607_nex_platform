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

import run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke as ae_control_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore,
)
from nex_ae_api.artifacts import register_artifact_handoff_routes  # noqa: E402
from nex_ag.artifact_operations import (  # noqa: E402
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION,
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
    "ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = ae_control_pg.SERVICE_ID
AG_SERVICE_ID = "nex-ag"
DEFAULT_PROFILE = ae_control_pg.DEFAULT_PROFILE
MIGRATION_VERSION = ae_control_pg.MIGRATION_VERSION
CHECKED_AT = "2026-09-08T07:45:00Z"
REQUESTED_AT = "2026-09-08T07:44:55Z"
EXPECTED_TABLES = ae_control_pg.EXPECTED_TABLES
EXPECTED_INDEXES = ae_control_pg.EXPECTED_INDEXES
RESTART_PROCESS_ID = 5890


class AeTestClientDaemonOperatorControlClient:
    source_kind = "ae_test_client"
    base_url = "testclient://nex-ae-api"

    def __init__(self, client: TestClient, headers: Mapping[str, str]) -> None:
        self.client = client
        self.headers = dict(headers)
        self.policy_statuses: list[int] = []
        self.preview_statuses: list[int] = []

    def get_artifact_retention_scheduler_daemon_operator_control_policy(
        self,
        *,
        checked_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.get(
            "/api/v1/artifact-retention/scheduler-daemon-operator-control-policy",
            params=({"checked_at": checked_at} if checked_at else {}),
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        self.policy_statuses.append(response.status_code)
        return self._json_or_error(response)

    def preview_artifact_retention_scheduler_daemon_operator_control(
        self,
        *,
        action: str,
        operator_subject: Mapping[str, Any],
        idempotency_key: str,
        reason: str,
        requested_at: str | None,
        checked_at: str | None,
        profile: str,
        enabled: bool,
        explicit_opt_in: bool,
        max_cycles: int,
        run_worker: bool,
        approval: Mapping[str, Any] | None,
        current_process: Mapping[str, Any] | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        headers = self._headers(request_id=request_id, trace_id=trace_id)
        headers["Idempotency-Key"] = idempotency_key
        response = self.client.post(
            "/api/v1/artifact-retention/scheduler-daemon-operator-control-preview",
            json={
                "action": action,
                "operator_subject": dict(operator_subject),
                "idempotency_key": idempotency_key,
                "reason": reason,
                "profile": profile,
                "enabled": enabled,
                "explicit_opt_in": explicit_opt_in,
                "max_cycles": max_cycles,
                "run_worker": run_worker,
                **({"requested_at": requested_at} if requested_at else {}),
                **({"checked_at": checked_at} if checked_at else {}),
                **({"approval": dict(approval)} if approval else {}),
                **({"current_process": dict(current_process)} if current_process else {}),
            },
            headers=headers,
        )
        self.preview_statuses.append(response.status_code)
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
                    "ag.ae_artifact_retention_daemon_operator_control_source_failed",
                ),
                detail=payload.get(
                    "detail",
                    "AE artifact retention scheduler daemon operator-control source failed.",
                ),
                status_code=response.status_code,
            )
        return payload if isinstance(payload, dict) else {}


def run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for AG-to-AE PostgreSQL smoke.",
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
        execution = _execute_ae_ag_operator_control_smoke(
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


def _execute_ae_ag_operator_control_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        ae_control_pg.process_pg._ensure_sqlite_migration_marker(engine)
        process_store = SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore(
            session_factory
        )
        process_store.ensure_schema()
        before = ae_control_pg._db_observations(engine)

        ae_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        ae_app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(ae_app)
        ae_client = TestClient(ae_app)
        ae_headers = ae_control_pg.artifact_pg._auth_headers(
            request_id=request_id,
            trace_id=trace_id,
        )

        bridge = AeTestClientDaemonOperatorControlClient(
            ae_client,
            headers=ae_headers,
        )
        ag_app = build_service_app(SERVICE_SPECS[AG_SERVICE_ID])
        register_artifact_operation_routes(ag_app, client=bridge)
        ag_client = TestClient(ag_app)
        ag_headers = _ag_auth_headers(request_id=request_id, trace_id=trace_id)

        policy_response = ag_client.get(
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-policy",
            params={
                "service_id": SERVICE_ID,
                "checked_at": CHECKED_AT,
            },
            headers=ag_headers,
        )
        status_response = ag_client.post(
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview",
            json={
                "action": "status-probe",
                "requested_by": _operator_subject(suffix),
                "reason": "slice_0589_ag_status_preview",
                "requested_at": REQUESTED_AT,
                "checked_at": CHECKED_AT,
                "idempotency_key": f"body-slice-0589-status-{suffix}",
            },
            headers={
                **ag_headers,
                "Idempotency-Key": f"slice-0589-status-{suffix}",
            },
        )
        restart_response = ag_client.post(
            "/admin/v1/operations/artifact-retention/"
            "scheduler-daemon-operator-control-preview",
            json={
                "action": "restart-daemon",
                "requested_by": {
                    **_operator_subject(suffix),
                    "database_url": "DATABASE_URL_SHOULD_NOT_LEAK",
                },
                "reason": "slice_0589_ag_restart_preview",
                "requested_at": REQUESTED_AT,
                "checked_at": CHECKED_AT,
                "profile": "test",
                "enabled": True,
                "explicit_opt_in": True,
                "max_cycles": "2",
                "run_worker": True,
                "approval": {
                    "approved": True,
                    "approved_by": _operator_subject(suffix),
                    "approved_at": REQUESTED_AT,
                    "reason": "slice_0589_ag_restart_preview",
                },
                "current_process": _running_process(suffix),
                "idempotency_key": f"body-slice-0589-restart-{suffix}",
            },
            headers={
                **ag_headers,
                "Idempotency-Key": f"slice-0589-restart-{suffix}",
            },
        )
        after = ae_control_pg._db_observations(engine)

        policy_payload = _json_payload(policy_response)
        status_payload = _json_payload(status_response)
        restart_payload = _json_payload(restart_response)
        checks = _smoke_checks(
            database_url=database_url,
            database_env=database_env,
            policy_response=policy_response.status_code,
            status_response=status_response.status_code,
            restart_response=restart_response.status_code,
            policy_payload=policy_payload,
            status_payload=status_payload,
            restart_payload=restart_payload,
            before=before,
            after=after,
            bridge=bridge,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE/AG scheduler daemon operator-control PostgreSQL smoke "
                f"checks failed: {', '.join(failed_checks)}"
            )

        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "routes": {
                "ag_policy_status": policy_response.status_code,
                "ag_status_preview_status": status_response.status_code,
                "ag_restart_preview_status": restart_response.status_code,
                "ae_policy_statuses": bridge.policy_statuses,
                "ae_preview_statuses": bridge.preview_statuses,
            },
            "ag_policy": _projection_evidence(policy_payload),
            "ag_previews": {
                "status_probe": _projection_evidence(status_payload),
                "restart_daemon": _projection_evidence(restart_payload),
            },
            "db_observations": {
                "before": before,
                "after": after,
            },
            "checks": checks,
            "live_db": True,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        engine.dispose()


def _operator_subject(suffix: str) -> dict[str, str]:
    return {
        "actor_type": "operator",
        "actor_id": f"ag-retention-operator-{suffix}",
        "tenant_id": f"tenant-0589-{suffix}",
        "workspace_id": f"workspace-0589-{suffix}",
        "service_id": AG_SERVICE_ID,
    }


def _running_process(suffix: str) -> dict[str, Any]:
    return {
        "process_source": "read_model",
        "process_status": "RUNNING",
        "process_running": True,
        "daemon_supervised_process_id": f"daemon-supervised-process-0589-{suffix}",
        "daemon_supervisor_command_id": f"daemon-supervisor-command-0589-{suffix}",
        "process_id": RESTART_PROCESS_ID,
        "host_id": f"ae-worker-0589-{suffix}",
        "observed_at": CHECKED_AT,
    }


def _json_payload(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except (AttributeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _projection_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping_value(payload.get("summary"))
    source_status = _mapping_value(payload.get("source_status"))
    guidance = _mapping_value(payload.get("operator_guidance"))
    facade = _mapping_value(payload.get("facade"))
    request = _mapping_value(facade.get("operator_control_request"))
    admission = _mapping_value(facade.get("operator_control_admission"))
    command_preview = _mapping_value(
        facade.get("operator_control_command_preview")
    )
    facade_guardrails = _mapping_value(facade.get("guardrails"))
    facade_metadata = _mapping_value(facade.get("metadata"))
    current_process = _mapping_value(admission.get("current_process"))
    return {
        "projection_schema_version": payload.get("projection_schema_version"),
        "projection_status": payload.get("projection_status"),
        "policy_loaded": summary.get("policy_loaded"),
        "facade_loaded": summary.get("facade_loaded"),
        "action": summary.get("action"),
        "facade_status": summary.get("facade_status"),
        "ready_for_dispatch": summary.get("ready_for_dispatch"),
        "command_preview_count": summary.get("command_preview_count"),
        "supervisor_actions": list(summary.get("supervisor_actions", [])),
        "restart_supported": summary.get("restart_supported"),
        "operator_subject": request.get("operator_subject"),
        "idempotency_key_present": request.get("idempotency_key_present"),
        "reason_present": request.get("reason_present"),
        "admission_status": admission.get("admission_status"),
        "current_process_status": current_process.get("process_status"),
        "preview_status": command_preview.get("preview_status"),
        "preview_only": facade_guardrails.get("preview_only")
        or guidance.get("preview_only"),
        "process_control_allowed": facade_guardrails.get(
            "process_control_allowed"
        ),
        "database_write_performed": facade_metadata.get(
            "database_write_performed"
        ),
        "job_queue_enqueue_performed": facade_metadata.get(
            "job_queue_enqueue_performed"
        ),
        "source_policy_loaded": source_status.get(
            "operator_control_policy_loaded"
        ),
        "source_facade_loaded": source_status.get(
            "operator_control_facade_loaded"
        ),
        "ag_direct_process_control_allowed": guidance.get(
            "ag_direct_process_control_allowed"
        ),
        "ag_direct_database_write_allowed": guidance.get(
            "ag_direct_database_write_allowed"
        ),
        "ag_direct_job_enqueue_allowed": guidance.get(
            "ag_direct_job_enqueue_allowed"
        ),
    }


def _smoke_checks(
    *,
    database_url: str,
    database_env: str,
    policy_response: int,
    status_response: int,
    restart_response: int,
    policy_payload: Mapping[str, Any],
    status_payload: Mapping[str, Any],
    restart_payload: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    bridge: AeTestClientDaemonOperatorControlClient,
) -> dict[str, bool]:
    policy = _projection_evidence(policy_payload)
    status_preview = _projection_evidence(status_payload)
    restart_preview = _projection_evidence(restart_payload)
    return {
        "test_database_url": database_env == "NEX_AE_TEST_DATABASE_URL"
        and ae_control_pg._database_name(database_url).endswith("_test"),
        "database_health_probe": before.get("health_probe") is True
        and after.get("health_probe") is True,
        "migration_recorded": before.get("migration_recorded") is True
        and after.get("migration_recorded") is True,
        "tables_present": set(before.get("tables_present", [])) == EXPECTED_TABLES
        and set(after.get("tables_present", [])) == EXPECTED_TABLES,
        "indexes_present": set(before.get("indexes_present", [])) == EXPECTED_INDEXES
        and set(after.get("indexes_present", [])) == EXPECTED_INDEXES,
        "ag_policy_route_passed": policy_response == 200
        and policy["projection_schema_version"]
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION
        and policy["projection_status"] == "READY"
        and policy["policy_loaded"] is True
        and policy["facade_loaded"] is False
        and policy["source_policy_loaded"] is True
        and policy["source_facade_loaded"] is False
        and policy["ag_direct_process_control_allowed"] is False,
        "ag_status_preview_route_passed": status_response == 200
        and status_preview["projection_status"] == "READY"
        and status_preview["action"] == "status_probe"
        and status_preview["facade_status"] == "READY"
        and status_preview["ready_for_dispatch"] is True
        and status_preview["command_preview_count"] == 1
        and status_preview["supervisor_actions"] == ["status_probe"]
        and status_preview["source_facade_loaded"] is True
        and _operator_subject_visible(status_preview),
        "ag_restart_preview_route_passed": restart_response == 200
        and restart_preview["projection_status"] == "READY"
        and restart_preview["action"] == "restart_daemon"
        and restart_preview["facade_status"] == "READY"
        and restart_preview["ready_for_dispatch"] is True
        and restart_preview["command_preview_count"] == 2
        and restart_preview["supervisor_actions"] == [
            "stop_daemon",
            "start_daemon",
        ]
        and restart_preview["current_process_status"] == "RUNNING"
        and restart_preview["source_facade_loaded"] is True
        and _operator_subject_visible(restart_preview),
        "ae_bridge_routes_passed": bridge.policy_statuses == [200]
        and bridge.preview_statuses == [200, 200],
        "preview_only_guardrails": status_preview["preview_only"] is True
        and restart_preview["preview_only"] is True
        and status_preview["process_control_allowed"] is False
        and restart_preview["process_control_allowed"] is False
        and restart_preview["ag_direct_process_control_allowed"] is False,
        "no_database_write_or_job_enqueue": status_preview[
            "database_write_performed"
        ]
        is False
        and restart_preview["database_write_performed"] is False
        and status_preview["job_queue_enqueue_performed"] is False
        and restart_preview["job_queue_enqueue_performed"] is False,
        "preview_routes_kept_rows_unchanged": before.get("row_counts")
        == after.get("row_counts"),
        "metadata_only_evidence": _metadata_only(
            policy_payload,
            status_payload,
            restart_payload,
            forbidden_fragments=[
                database_url,
                ae_control_pg._database_url_password(database_url),
                "/data/nex-platform",
                "ed6@c496em",
                "slice-0589-status-",
                "slice-0589-restart-",
                "body-slice-0589-status-",
                "body-slice-0589-restart-",
                "DATABASE_URL_SHOULD_NOT_LEAK",
                "content_base64",
                '"database_url_included": true',
                '"storage_path_included": true',
                '"raw_artifact_payload_included": true',
                '"raw_execution_payload_included": true',
            ],
        ),
    }


def _operator_subject_visible(projection: Mapping[str, Any]) -> bool:
    subject = _mapping_value(projection.get("operator_subject"))
    return (
        subject.get("actor_type") == "operator"
        and str(subject.get("actor_id", "")).startswith("ag-retention-operator-")
        and str(subject.get("tenant_id", "")).startswith("tenant-0589-")
        and str(subject.get("workspace_id", "")).startswith("workspace-0589-")
    )


def _ag_auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=AG_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _metadata_only(*payloads: Any, forbidden_fragments: list[str | None]) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(
        fragment not in serialized for fragment in forbidden_fragments if fragment
    )


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    ae_control_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)
    for forbidden in (
        "slice-0589-status-",
        "slice-0589-restart-",
        "body-slice-0589-status-",
        "body-slice-0589-restart-",
        "DATABASE_URL_SHOULD_NOT_LEAK",
    ):
        if forbidden in serialized_evidence:
            raise ValueError(
                "AE/AG scheduler daemon operator-control smoke contains "
                "private operator-control request data."
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
    safe = ae_control_pg._safe_detail(detail, env)
    for key in (SMOKE_PROFILE_ENV,):
        value = env.get(key)
        if value:
            safe = safe.replace(value, f"<redacted:{key}>")
    return safe


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
            "pass "
            f"service={evidence['service_id']} "
            f"ag_service={evidence['ag_service_id']} "
            f"db_env={evidence['database_env']} "
            f"policy={evidence['routes']['ag_policy_status']} "
            f"previews={len(evidence['routes']['ae_preview_statuses'])} "
            f"restart={evidence['ag_previews']['restart_daemon']['facade_status']} "
            f"bridge_policy={len(evidence['routes']['ae_policy_statuses'])} "
            f"bridge_preview={len(evidence['routes']['ae_preview_statuses'])} "
            f"unchanged={str(evidence['checks']['preview_routes_kept_rows_unchanged']).lower()} "
            f"live_db={str(evidence['live_db']).lower()}"
        )
    return (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
        "fail "
        f"service={evidence.get('service_id')} "
        f"ag_service={evidence.get('ag_service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AG-to-AE scheduler daemon operator-control "
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
        run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke()
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
