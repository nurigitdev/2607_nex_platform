from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0609@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def _passing_migration() -> SimpleNamespace:
    return SimpleNamespace(
        planned=(smoke.MIGRATION_VERSION,),
        applied=(),
        skipped=(smoke.MIGRATION_VERSION,),
    )


def _passing_observations(
    *,
    scoped_states: int = 1,
    scoped_transitions: int = 0,
    process_rows: int = 0,
) -> dict[str, Any]:
    return {
        "dialect": "sqlite",
        "health_probe": True,
        "tables_present": sorted(smoke.EXPECTED_TABLES),
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
        "migration_recorded": True,
        "row_counts": {
            "process_records": process_rows,
            "process_events": process_rows,
            "supervisor_records": process_rows,
            "supervisor_events": process_rows,
            "execution_states": scoped_states,
            "execution_transitions": scoped_transitions,
        },
        "scoped_row_counts": {
            "execution_states": scoped_states,
            "execution_transitions": scoped_transitions,
        },
        "scheduler_id": "ae-artifact-retention-scheduler",
        "jsonb_columns": {},
    }


def test_ae_ag_operator_control_execution_worker_smoke_skips_by_default() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            {}
        )
    )

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_ag_operator_control_execution_worker_rejects_non_test_profile() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert "AG-to-AE worker PostgreSQL smoke" in evidence["detail"]
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
        "fail service=nex-ae-api ag_service=nex-ag reason=profile_not_allowed"
    )


def test_ae_ag_operator_control_execution_worker_requires_test_database_url() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_ag_operator_control_execution_worker_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0609")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0609" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_ae_ag_operator_control_execution_worker_redacts_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_ag_operator_control_execution_worker_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("worker leaked secret-0609")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert "secret-0609" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_ae_ag_operator_control_execution_worker_passes_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            smoke_env()
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    summary = smoke.summary_line(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["service_id"] == "nex-ae-api"
    assert evidence["ag_service_id"] == "nex-ag"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["routes"] == {
        "ae_persisted_execution_status": 200,
        "ae_worker_statuses": [200],
        "ag_worker_status": 200,
    }
    assert evidence["execution"]["execution_status"] == "ADMITTED"
    assert evidence["execution"]["database_write_performed"] is False
    assert evidence["ag_worker"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_worker"]["projection_status"] == "READY"
    assert evidence["ag_worker"]["worker_result"]["source_schema_version"] == (
        smoke.ae_worker_pg.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION
    )
    assert evidence["ag_worker"]["worker_result"]["worker_status"] == "SUCCEEDED"
    assert evidence["ag_worker"]["worker_result"]["status_path"] == [
        "ADMITTED",
        "EXECUTING",
        "SUCCEEDED",
    ]
    assert evidence["ag_worker"]["summary"]["worker_status"] == "SUCCEEDED"
    assert evidence["ag_worker"]["summary"]["operator_attention_required"] is False
    assert evidence["ag_worker"]["source_status"]["source_kind"] == "ae_test_client"
    assert (
        evidence["ag_worker"]["source_status"]["execution_worker_result_loaded"]
        is True
    )
    assert evidence["ag_worker"]["operator_guidance"][
        "ag_direct_database_write_allowed"
    ] is False
    assert evidence["db_observations"]["before"]["scoped_row_counts"] == {
        "execution_states": 0,
        "execution_transitions": 0,
    }
    assert evidence["db_observations"]["after"]["scoped_row_counts"] == {
        "execution_states": 1,
        "execution_transitions": 0,
    }
    assert evidence["cleanup"] == {
        "execution_state_transitions": 0,
        "execution_states": 1,
    }
    assert evidence["post_cleanup"]["scoped_row_counts"] == {
        "execution_states": 0,
        "execution_transitions": 0,
    }
    assert all(evidence["checks"].values())
    assert evidence["live_db"] is True
    assert summary.startswith(
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
        "pass service=nex-ae-api ag_service=nex-ag"
    )
    assert "states=1" in summary
    assert "transitions=0" in summary
    assert "worker=SUCCEEDED" in summary
    assert "cleanup_states=1" in summary
    assert "secret-0609" not in serialized
    assert "slice-0609-worker-" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "ed6@c496em" not in serialized


def test_ae_ag_operator_control_execution_worker_failed_checks_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(scoped_states=0, scoped_transitions=0),
            _passing_observations(scoped_states=0, scoped_transitions=0),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_state_jsonb_verified",
        lambda _observations: True,
    )
    monkeypatch.setattr(
        smoke.ae_worker_pg,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="scoped_state_written_without_transition"):
        smoke._execute_ae_ag_operator_control_execution_worker_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_operator_control_execution_worker_cleanup_verification_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(scoped_states=0, scoped_transitions=0),
            _passing_observations(scoped_states=1, scoped_transitions=0),
            _passing_observations(scoped_states=1, scoped_transitions=0),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke.ae_worker_pg,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="cleanup verification"):
        smoke._execute_ae_ag_operator_control_execution_worker_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_operator_control_execution_worker_wraps_setup_failure_and_suppresses_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "register_artifact_operation_routes",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("route boom")),
    )
    monkeypatch.setattr(
        smoke.ae_worker_pg,
        "_cleanup_execution_states",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cleanup boom")),
    )

    with pytest.raises(RuntimeError, match="route boom"):
        smoke._execute_ae_ag_operator_control_execution_worker_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_operator_control_execution_worker_allows_missing_state_id_without_final_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200
        content = b"{}"

        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def json(self) -> dict[str, Any]:
            return self.payload

    class FakeAeClient:
        def post(self, *args: Any, **kwargs: Any) -> Response:
            return Response(admitted_payload())

    class FakeAgClient:
        def post(self, *args: Any, **kwargs: Any) -> Response:
            return Response(ag_worker_payload())

    class FakeBridge:
        source_kind = "ae_test_client"
        base_url = "testclient://nex-ae-api"

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.worker_statuses = [200]

    def admitted_payload() -> dict[str, Any]:
        return {
            "operator_control_execution_state_schema_version": (
                smoke.ae_worker_pg.ae_execution_pg.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION
            ),
            "operator_control_execution_state_id": None,
            "operator_control_execution_request_id": "request-0609",
            "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
            "action": "start_daemon",
            "execution_mode": "fake_dry_run_supervisor_persistent_dispatch",
            "execution_status": "ADMITTED",
            "idempotency_status": "NEW",
            "decision_reason": "missing_state_id_branch_probe",
            "allowed_next_statuses": ["EXECUTING", "BLOCKED"],
            "guardrails": {"metadata_only": True, "state_machine_only": True},
            "metadata": {
                "database_write_performed": False,
                "job_queue_enqueue_performed": False,
                "worker_execution_performed": False,
                "safe_for_ag_projection": True,
            },
        }

    def worker_projection_payload() -> dict[str, Any]:
        return {
            "source_operator_control_execution_worker_result_schema_version": (
                smoke.ae_worker_pg.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION
            ),
            "operator_control_execution_worker_result_id": "worker-result-0609",
            "operator_control_execution_state_id": None,
            "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
            "action": "start_daemon",
            "execution_mode": "fake_dry_run_supervisor_persistent_dispatch",
            "worker_mode": "fake_dry_run_supervisor_persistent_dispatch_worker",
            "worker_status": "SUCCEEDED",
            "worker_plan_status": "READY",
            "worker_command_status": "READY",
            "transition_plan_status": "READY",
            "transition_terminal_status": "SUCCEEDED",
            "transition_count": 2,
            "status_path": ["ADMITTED", "EXECUTING", "SUCCEEDED"],
            "supervisor_result_count": 1,
            "supervisor_result_statuses": ["BLOCKED"],
            "metadata": {
                "worker_execution_performed": True,
                "database_write_performed": False,
                "transition_persistence_performed": False,
            },
            "guardrails": {
                "supervisor_adapter_invoked": True,
                "subprocess_started": False,
            },
        }

    def ag_worker_payload() -> dict[str, Any]:
        worker_result = worker_projection_payload()
        return {
            "projection_schema_version": (
                smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION
            ),
            "projection_status": "READY",
            "service_id": "nex-ae-api",
            "operation_type": (
                "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker"
            ),
            "operator_control_execution_state_id": None,
            "operator_control_execution_worker_result_id": "worker-result-0609",
            "worker_result": worker_result,
            "summary": {
                **worker_result,
                "operator_attention_required": False,
                "metadata_only": True,
                "worker_execution_performed": True,
                "supervisor_adapter_invoked": True,
                "subprocess_started": False,
                "database_write_performed": False,
                "transition_persistence_performed": False,
            },
            "source_status": {
                "source_kind": "ae_test_client",
                "execution_worker_result_loaded": True,
            },
            "operator_guidance": {
                "ag_direct_database_write_allowed": False,
                "ag_direct_process_control_allowed": False,
                "ag_direct_daemon_process_control_allowed": False,
                "ag_direct_job_enqueue_allowed": False,
                "physical_delete_automation_enabled": False,
            },
        }

    observations = iter(
        [
            _passing_observations(scoped_states=0, scoped_transitions=0),
            _passing_observations(scoped_states=1, scoped_transitions=0),
            _passing_observations(scoped_states=0, scoped_transitions=0),
        ]
    )
    clients = iter([FakeAeClient(), FakeAgClient()])
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "build_service_app",
        lambda _spec: SimpleNamespace(state=SimpleNamespace()),
    )
    monkeypatch.setattr(smoke, "register_artifact_handoff_routes", lambda *a, **k: None)
    monkeypatch.setattr(smoke, "register_artifact_operation_routes", lambda *a, **k: None)
    monkeypatch.setattr(smoke, "TestClient", lambda _app: next(clients))
    monkeypatch.setattr(
        smoke,
        "AeTestClientDaemonOperatorControlExecutionWorkerClient",
        FakeBridge,
    )
    monkeypatch.setattr(
        smoke.ae_worker_pg,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    evidence = smoke._execute_ae_ag_operator_control_execution_worker_smoke(
        database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
        database_env="NEX_AE_TEST_DATABASE_URL",
    )

    assert evidence["persisted"]["execution_state_id"] is None
    assert evidence["cleanup"] == {
        "execution_state_transitions": 0,
        "execution_states": 0,
    }
    assert evidence["post_cleanup"]["scoped_row_counts"] == {
        "execution_states": 0,
        "execution_transitions": 0,
    }


def test_ae_ag_operator_control_execution_worker_bridge_error_payload() -> None:
    class ErrorResponse:
        status_code = 503
        content = b"{}"

        def json(self) -> dict[str, str]:
            return {
                "error_code": "ae.operator_control_execution_worker_unavailable",
                "detail": "operator-control execution worker unavailable",
            }

    class ListJsonResponse:
        status_code = 200
        content = b"[]"

        def json(self) -> list[str]:
            return ["not", "a", "dict"]

    class EmptyResponse:
        status_code = 200
        content = b""

    with pytest.raises(smoke.AeArtifactOperationsError) as exc_info:
        smoke.AeTestClientDaemonOperatorControlExecutionWorkerClient._json_or_error(
            ErrorResponse()
        )

    assert exc_info.value.error_code == (
        "ae.operator_control_execution_worker_unavailable"
    )
    assert (
        smoke.AeTestClientDaemonOperatorControlExecutionWorkerClient._json_or_error(
            ListJsonResponse()
        )
        == {}
    )
    assert (
        smoke.AeTestClientDaemonOperatorControlExecutionWorkerClient._json_or_error(
            EmptyResponse()
        )
        == {}
    )


def test_ae_ag_operator_control_execution_worker_bridge_optional_payloads() -> None:
    class SuccessResponse:
        status_code = 200
        content = b"{}"

        def json(self) -> dict[str, str]:
            return {"status": "ok"}

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def post(
            self,
            route: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> SuccessResponse:
            self.calls.append({"route": route, "json": json, "headers": headers})
            return SuccessResponse()

    fake_client = FakeClient()
    bridge = smoke.AeTestClientDaemonOperatorControlExecutionWorkerClient(
        fake_client,  # type: ignore[arg-type]
        headers={"Authorization": "Bearer token"},
    )

    result = bridge.run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        operator_control_execution_state_id="state-0609",
        operator_control_execution_state={"execution_status": "ADMITTED"},
        checked_at=None,
        worker_observed_at=None,
        request_id="request-0609",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert result == {"status": "ok"}
    assert bridge.worker_statuses == [200]
    assert fake_client.calls[0]["route"] == smoke.AE_WORKER_ROUTE
    assert fake_client.calls[0]["json"] == {
        "operator_control_execution_state_id": "state-0609",
        "operator_control_execution_state": {"execution_status": "ADMITTED"},
    }
    assert fake_client.calls[0]["headers"]["X-Request-ID"] == "request-0609"


def test_ae_ag_operator_control_execution_worker_helpers_and_redaction() -> None:
    env = smoke_env()

    assert smoke._json_payload(object()) == {}
    assert smoke._mapping_value(None) == {}
    assert smoke._list_value(None) == []
    assert smoke._text_or_none("  ") is None
    assert smoke._ag_worker_evidence({})["projection_status"] is None
    assert smoke._state_jsonb_verified({"dialect": "sqlite"}) is True
    assert smoke._state_jsonb_verified(
        {
            "dialect": "postgresql",
            "jsonb_columns": smoke.EXPECTED_STATE_JSONB_TYPES,
        }
    ) is True
    assert smoke._state_jsonb_verified(
        {
            "dialect": "postgresql",
            "jsonb_columns": {"state.metadata": "text"},
        }
    ) is False
    assert smoke._metadata_only({"safe": True}, forbidden_fragments=["secret"])
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("leaked secret-0609", env)
    with pytest.raises(ValueError, match="private operator-control request data"):
        smoke.assert_smoke_evidence_redacted("slice-0609-worker-leak", env)
    with pytest.raises(ValueError, match="private operator-control request data"):
        smoke.assert_smoke_evidence_redacted("body-slice-0609-worker-leak", env)
    with pytest.raises(ValueError, match="private operator-control request data"):
        smoke.assert_smoke_evidence_redacted("DATABASE_URL_SHOULD_NOT_LEAK", env)


def test_ae_ag_operator_control_execution_worker_main_outputs_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert f"skipped reason={smoke.SMOKE_ENV}" in capsys.readouterr().out


def test_ae_ag_operator_control_execution_worker_main_outputs_json_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke",
        lambda: smoke._failure(
            "configuration_invalid",
            "missing NEX_AE_TEST_DATABASE_URL",
            profile=smoke.DEFAULT_PROFILE,
            env={},
        ),
    )

    assert smoke.main([]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FAIL"
    assert payload["failure_code"] == "configuration_invalid"
