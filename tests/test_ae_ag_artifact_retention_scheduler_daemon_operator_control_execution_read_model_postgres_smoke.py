from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0599@127.0.0.1:5432/"
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
    scoped_transitions: int = 1,
) -> dict[str, Any]:
    return {
        "dialect": "sqlite",
        "health_probe": True,
        "tables_present": sorted(smoke.EXPECTED_TABLES),
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
        "migration_recorded": True,
        "row_counts": {
            "process_records": 0,
            "process_events": 0,
            "supervisor_records": 0,
            "supervisor_events": 0,
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


def test_ae_ag_operator_control_execution_read_model_smoke_skips_by_default() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke(
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
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_ag_operator_control_execution_read_model_rejects_non_test_profile() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert "AG-to-AE PostgreSQL smoke" in evidence["detail"]
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke="
        "fail service=nex-ae-api ag_service=nex-ag reason=profile_not_allowed"
    )


def test_ae_ag_operator_control_execution_read_model_requires_test_database_url() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_ag_operator_control_execution_read_model_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0599")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0599" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_ae_ag_operator_control_execution_read_model_redacts_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_ag_operator_control_execution_read_model_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("execution leaked secret-0599")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert "secret-0599" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_ae_ag_operator_control_execution_read_model_passes_sqlite_harness(
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
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke(
            smoke_env()
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    summary = smoke.summary_line(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["service_id"] == "nex-ae-api"
    assert evidence["ag_service_id"] == "nex-ag"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["migration"] == {
        "planned": [smoke.MIGRATION_VERSION],
        "applied": [],
        "skipped": [smoke.MIGRATION_VERSION],
    }
    assert evidence["routes"] == {
        "ae_persisted_execution_status": 200,
        "ae_persisted_transition_status": 200,
        "ae_execution_collection_statuses": [200],
        "ae_execution_detail_statuses": [200],
        "ag_execution_collection_status": 200,
        "ag_execution_detail_status": 200,
    }
    assert evidence["executions"]["admitted"]["execution_mode"] == (
        "fake_dry_run_supervisor_persistent_dispatch"
    )
    assert evidence["executions"]["admitted"]["execution_status"] == "ADMITTED"
    assert evidence["transition"]["from_status"] == "ADMITTED"
    assert evidence["transition"]["to_status"] == "EXECUTING"
    assert evidence["db_observations"]["before"]["scoped_row_counts"] == {
        "execution_states": 0,
        "execution_transitions": 0,
    }
    assert evidence["db_observations"]["after"]["scoped_row_counts"] == {
        "execution_states": 1,
        "execution_transitions": 1,
    }
    assert evidence["ag_execution_collection"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_execution_collection"]["projection_status"] == "READY"
    assert evidence["ag_execution_collection"]["count"] == 1
    assert evidence["ag_execution_collection"]["filter"]["action"] == "start_daemon"
    assert evidence["ag_execution_collection"]["summary"]["admitted_count"] == 1
    assert evidence["ag_execution_collection"]["first_item"][
        "request_hash_present"
    ] is False
    assert evidence["ag_execution_collection"]["first_item"][
        "idempotency_key_present"
    ] is False
    assert evidence["ag_execution_detail"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_execution_detail"]["projection_status"] == "READY"
    assert evidence["ag_execution_detail"]["transition_count"] == 1
    assert evidence["ag_execution_detail"]["transition_statuses"] == [
        "ADMITTED->EXECUTING"
    ]
    assert evidence["ag_execution_detail"]["execution_state"][
        "raw_request_present"
    ] is False
    assert evidence["cleanup"] == {
        "execution_state_transitions": 1,
        "execution_states": 1,
    }
    assert evidence["post_cleanup"]["scoped_row_counts"] == {
        "execution_states": 0,
        "execution_transitions": 0,
    }
    assert all(evidence["checks"].values())
    assert evidence["live_db"] is True
    assert summary.startswith(
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke="
        "pass service=nex-ae-api ag_service=nex-ag"
    )
    assert "states=1" in summary
    assert "transitions=1" in summary
    assert "cleanup_states=1" in summary
    assert "secret-0599" not in serialized
    assert "slice-0599-admitted-" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "ed6@c496em" not in serialized


def test_ae_ag_operator_control_execution_read_model_failed_checks_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(scoped_states=0, scoped_transitions=0),
            _passing_observations(scoped_states=0, scoped_transitions=1),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: next(observations))

    with pytest.raises(RuntimeError, match="scoped_rows_persisted"):
        smoke._execute_ae_ag_operator_control_execution_read_model_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_operator_control_execution_read_model_cleanup_verification_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(scoped_states=0, scoped_transitions=0),
            _passing_observations(scoped_states=1, scoped_transitions=1),
            _passing_observations(scoped_states=1, scoped_transitions=0),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: next(observations))

    with pytest.raises(RuntimeError, match="cleanup verification"):
        smoke._execute_ae_ag_operator_control_execution_read_model_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_operator_control_execution_read_model_bridge_error_payload() -> None:
    class ErrorResponse:
        status_code = 503
        content = b"{}"

        def json(self) -> dict[str, str]:
            return {
                "error_code": "ae.operator_control_execution_unavailable",
                "detail": "operator-control execution unavailable",
            }

    class ListJsonResponse:
        status_code = 200
        content = b"[]"

        def json(self) -> list[str]:
            return ["not", "a", "dict"]

    with pytest.raises(smoke.AeArtifactOperationsError) as exc_info:
        smoke.AeTestClientDaemonOperatorControlExecutionReadModelClient._json_or_error(
            ErrorResponse()
        )

    assert exc_info.value.error_code == "ae.operator_control_execution_unavailable"
    assert (
        smoke.AeTestClientDaemonOperatorControlExecutionReadModelClient._json_or_error(
            ListJsonResponse()
        )
        == {}
    )


def test_ae_ag_operator_control_execution_read_model_helpers_and_redaction() -> None:
    env = smoke_env()

    assert smoke._json_payload(object()) == {}
    assert smoke._mapping_value(None) == {}
    assert smoke._list_value(None) == []
    assert smoke._text_or_none("  ") is None
    assert smoke._collection_evidence({})["projection_status"] is None
    assert smoke._detail_evidence({})["transition_statuses"] == []
    assert smoke._metadata_only({"safe": True}, forbidden_fragments=["secret"])
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("leaked secret-0599", env)
    with pytest.raises(ValueError, match="private operator-control request data"):
        smoke.assert_smoke_evidence_redacted("slice-0599-admitted-leak", env)


def test_ae_ag_operator_control_execution_read_model_db_helpers() -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    smoke._ensure_sqlite_migration_marker(engine)
    with engine.connect() as connection:
        assert smoke._schema_migration_recorded(connection) is False
    smoke.ae_execution_pg.process_pg._ensure_sqlite_migration_marker(engine)
    smoke.ae_execution_pg.supervisor_pg._ensure_sqlite_migration_marker(engine)
    with engine.connect() as connection:
        assert smoke._schema_migration_recorded(connection) is True
        assert smoke._jsonb_column_types(connection, "sqlite", ["state-id"]) == {}


def test_ae_ag_operator_control_execution_read_model_main_outputs_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert f"skipped reason={smoke.SMOKE_ENV}" in capsys.readouterr().out


def test_ae_ag_operator_control_execution_read_model_main_outputs_json_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke",
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
