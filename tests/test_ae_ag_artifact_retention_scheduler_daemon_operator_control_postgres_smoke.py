from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0589@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def _passing_migration() -> SimpleNamespace:
    return SimpleNamespace(
        planned=(smoke.MIGRATION_VERSION,),
        applied=(),
        skipped=(smoke.MIGRATION_VERSION,),
    )


def _passing_observations(row_count: int = 0) -> dict[str, Any]:
    return {
        "dialect": "sqlite",
        "health_probe": True,
        "tables_present": sorted(smoke.EXPECTED_TABLES),
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
        "migration_recorded": True,
        "row_counts": {
            "process_records": row_count,
            "process_events": row_count,
        },
    }


def test_ae_ag_operator_control_postgres_smoke_skips_by_default() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
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
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_ag_operator_control_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert "AG-to-AE PostgreSQL smoke" in evidence["detail"]
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
        "fail service=nex-ae-api ag_service=nex-ag reason=profile_not_allowed"
    )


def test_ae_ag_operator_control_postgres_smoke_requires_test_database_url() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_ag_operator_control_postgres_smoke_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0589")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0589" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_ae_ag_operator_control_postgres_smoke_redacts_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_ag_operator_control_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("execution leaked secret-0589")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert "secret-0589" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_ae_ag_operator_control_postgres_smoke_passes_sqlite_harness(
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
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
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
        "ag_policy_status": 200,
        "ag_status_preview_status": 200,
        "ag_restart_preview_status": 200,
        "ae_policy_statuses": [200],
        "ae_preview_statuses": [200, 200],
    }
    assert evidence["ag_policy"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_policy"]["projection_status"] == "READY"
    assert evidence["ag_policy"]["policy_loaded"] is True
    assert evidence["ag_policy"]["facade_loaded"] is False
    assert evidence["ag_policy"]["ag_direct_process_control_allowed"] is False
    assert evidence["ag_previews"]["status_probe"]["action"] == "status_probe"
    assert evidence["ag_previews"]["status_probe"]["facade_status"] == "READY"
    assert evidence["ag_previews"]["status_probe"]["command_preview_count"] == 1
    assert evidence["ag_previews"]["status_probe"]["supervisor_actions"] == [
        "status_probe"
    ]
    assert evidence["ag_previews"]["restart_daemon"]["action"] == "restart_daemon"
    assert evidence["ag_previews"]["restart_daemon"]["facade_status"] == "READY"
    assert evidence["ag_previews"]["restart_daemon"]["command_preview_count"] == 2
    assert evidence["ag_previews"]["restart_daemon"]["supervisor_actions"] == [
        "stop_daemon",
        "start_daemon",
    ]
    assert evidence["ag_previews"]["restart_daemon"][
        "current_process_status"
    ] == "RUNNING"
    assert evidence["ag_previews"]["restart_daemon"]["preview_only"] is True
    assert evidence["ag_previews"]["restart_daemon"][
        "database_write_performed"
    ] is False
    assert evidence["db_observations"]["before"]["row_counts"] == (
        evidence["db_observations"]["after"]["row_counts"]
    )
    assert set(evidence["db_observations"]["before"]["tables_present"]) == (
        smoke.EXPECTED_TABLES
    )
    assert all(evidence["checks"].values())
    assert evidence["live_db"] is True
    assert summary.startswith(
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
        "pass service=nex-ae-api ag_service=nex-ag"
    )
    assert "previews=2" in summary
    assert "restart=READY" in summary
    assert "unchanged=true" in summary
    assert "secret-0589" not in serialized
    assert "slice-0589-status-" not in serialized
    assert "slice-0589-restart-" not in serialized
    assert "DATABASE_URL_SHOULD_NOT_LEAK" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "ed6@c496em" not in serialized


def test_ae_ag_operator_control_postgres_smoke_failed_checks_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(0),
            _passing_observations(1),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke.ae_control_pg,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="preview_routes_kept_rows_unchanged"):
        smoke._execute_ae_ag_operator_control_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_operator_control_postgres_smoke_bridge_error_payload() -> None:
    class ErrorResponse:
        status_code = 503
        content = b"{}"

        def json(self) -> dict[str, str]:
            return {
                "error_code": "ae.operator_control_unavailable",
                "detail": "operator control unavailable",
            }

    class ListJsonResponse:
        status_code = 200
        content = b"[]"

        def json(self) -> list[str]:
            return ["not", "a", "dict"]

    with pytest.raises(smoke.AeArtifactOperationsError) as exc_info:
        smoke.AeTestClientDaemonOperatorControlClient._json_or_error(ErrorResponse())

    assert exc_info.value.error_code == "ae.operator_control_unavailable"
    assert (
        smoke.AeTestClientDaemonOperatorControlClient._json_or_error(
            ListJsonResponse()
        )
        == {}
    )


def test_ae_ag_operator_control_postgres_smoke_helpers_and_redaction() -> None:
    env = smoke_env()

    assert smoke._json_payload(object()) == {}
    assert smoke._projection_evidence({})["projection_status"] is None
    assert smoke._operator_subject_visible({}) is False
    assert smoke._operator_subject("abc")["service_id"] == "nex-ag"
    assert smoke._running_process("abc")["process_id"] == smoke.RESTART_PROCESS_ID
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("leaked secret-0589", env)
    with pytest.raises(ValueError, match="private operator-control request data"):
        smoke.assert_smoke_evidence_redacted("slice-0589-status-leak", env)


def test_ae_ag_operator_control_postgres_smoke_main_outputs_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert f"skipped reason={smoke.SMOKE_ENV}" in capsys.readouterr().out


def test_ae_ag_operator_control_postgres_smoke_main_outputs_json_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke",
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
