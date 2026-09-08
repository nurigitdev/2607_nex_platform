from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0586@127.0.0.1:5432/"
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


def test_operator_control_postgres_smoke_skips_by_default() -> None:
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
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
        "ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_operator_control_postgres_smoke_rejects_dev_profile() -> None:
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert evidence["detail"].endswith("test for PostgreSQL smoke execution.")
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
        "fail service=nex-ae-api reason=profile_not_allowed"
    )


def test_operator_control_postgres_smoke_requires_test_database_url() -> None:
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_operator_control_postgres_smoke_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0586")
        ),
    )

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0586" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_operator_control_postgres_smoke_redacts_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_operator_control_facade_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("execution leaked secret-0586")
        ),
    )

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert "secret-0586" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_operator_control_postgres_smoke_passes_sqlite_harness(
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
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke(
            smoke_env()
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["service_id"] == "nex-ae-api"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["migration"] == {
        "planned": [smoke.MIGRATION_VERSION],
        "applied": [],
        "skipped": [smoke.MIGRATION_VERSION],
    }
    assert evidence["routes"] == {
        "policy_status": 200,
        "status_preview_status": 200,
        "start_preview_status": 200,
    }
    assert evidence["policy"]["schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION
    )
    assert evidence["policy"]["ag_direct_process_control_allowed"] is False
    assert evidence["policy"]["test_profile_required"] is True
    assert evidence["previews"]["status_probe"]["schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION
    )
    assert evidence["previews"]["status_probe"]["supervisor_actions"] == [
        "status_probe"
    ]
    assert evidence["previews"]["start_daemon"]["supervisor_actions"] == [
        "start_daemon"
    ]
    assert evidence["previews"]["status_probe"]["preview_only"] is True
    assert evidence["previews"]["start_daemon"]["preview_only"] is True
    assert evidence["previews"]["status_probe"]["database_write_performed"] is False
    assert evidence["previews"]["start_daemon"]["job_queue_enqueue_performed"] is False
    assert evidence["db_observations"]["before"]["row_counts"] == (
        evidence["db_observations"]["after"]["row_counts"]
    )
    assert set(evidence["db_observations"]["before"]["tables_present"]) == (
        smoke.EXPECTED_TABLES
    )
    assert set(evidence["db_observations"]["after"]["indexes_present"]) == (
        smoke.EXPECTED_INDEXES
    )
    assert all(evidence["checks"].values())
    assert evidence["live_db"] is True
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke="
        "pass service=nex-ae-api"
    )
    assert "routes=3" in smoke.summary_line(evidence)
    assert "preview_only=true" in smoke.summary_line(evidence)
    assert "secret-0586" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "ed6@c496em" not in serialized


def test_operator_control_postgres_smoke_failed_checks_raise(
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
        smoke,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="preview_route_kept_rows_unchanged"):
        smoke._execute_operator_control_facade_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_operator_control_postgres_smoke_wraps_route_setup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "register_artifact_handoff_routes",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("route boom")),
    )

    with pytest.raises(RuntimeError, match="route boom"):
        smoke._execute_operator_control_facade_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_operator_control_postgres_smoke_redaction_guards() -> None:
    env = smoke_env()

    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("leaked secret-0586", env)
    with pytest.raises(ValueError, match="provider API key"):
        smoke.assert_smoke_evidence_redacted("leaked ed6@c496em", env)
    assert smoke._database_name("not a url") == ""


def test_operator_control_postgres_smoke_response_and_db_helpers() -> None:
    class BadJsonResponse:
        def json(self) -> dict[str, Any]:
            raise ValueError("not json")

    class ScalarResult:
        def __init__(self, value: Any) -> None:
            self._value = value

        def scalar(self) -> Any:
            return self._value

    class PostgresConnection:
        dialect = SimpleNamespace(name="postgresql")

        def __init__(self, result: str | None) -> None:
            self.result = result
            self.params: dict[str, Any] = {}

        def execute(self, _statement: Any, params: dict[str, Any]) -> ScalarResult:
            self.params = params
            return ScalarResult(self.result)

    engine = sqlite_artifact_session_factory().kw["bind"]

    assert smoke._json_payload(BadJsonResponse()) == {}
    with engine.connect() as connection:
        assert smoke._table_count(connection, "missing_table_0586") == 0
    assert smoke._table_exists(PostgresConnection("public_table"), "public_table")
    assert not smoke._table_exists(PostgresConnection(None), "public_table")


def test_operator_control_postgres_smoke_main_outputs_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert f"skipped reason={smoke.SMOKE_ENV}" in capsys.readouterr().out


def test_operator_control_postgres_smoke_main_outputs_json_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke",
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
