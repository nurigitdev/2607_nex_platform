from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0606@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def _passing_migration() -> SimpleNamespace:
    return SimpleNamespace(
        planned=("0566_supervisor", "0575_process", "0596_execution"),
        applied=(),
        skipped=("0566_supervisor", "0575_process", "0596_execution"),
    )


def _passing_observations(
    *,
    scoped_states: int = 0,
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


def test_operator_control_execution_worker_postgres_smoke_skips_by_default() -> None:
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
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
        "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_operator_control_execution_worker_postgres_smoke_rejects_dev_profile() -> None:
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert evidence["detail"].endswith("test for worker PostgreSQL smoke.")
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke="
        "fail service=nex-ae-api reason=profile_not_allowed"
    )


def test_operator_control_execution_worker_postgres_smoke_requires_test_db_url() -> None:
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_operator_control_execution_worker_postgres_smoke_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0606")
        ),
    )

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0606" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_operator_control_execution_worker_postgres_smoke_redacts_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_operator_control_execution_worker_route_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("worker route leaked secret-0606")
        ),
    )

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert "secret-0606" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_operator_control_execution_worker_postgres_smoke_passes_sqlite_harness(
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
        smoke.run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke(
            smoke_env()
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["service_id"] == "nex-ae-api"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["routes"] == {
        "ae_persisted_execution_status": 200,
        "ae_worker_status": 200,
        "ae_persisted_transition_status": 200,
        "ae_execution_detail_status": 200,
    }
    assert evidence["execution"]["execution_status"] == "ADMITTED"
    assert evidence["execution"]["database_write_performed"] is False
    assert evidence["worker"]["schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION
    )
    assert evidence["worker"]["worker_status"] == "SUCCEEDED"
    assert evidence["worker"]["plan_status"] == "READY"
    assert evidence["worker"]["command_status"] == "READY"
    assert evidence["worker"]["transition_plan_status"] == "READY"
    assert evidence["worker"]["status_path"] == [
        "ADMITTED",
        "EXECUTING",
        "SUCCEEDED",
    ]
    assert evidence["worker"]["supervisor_result_count"] == 1
    assert evidence["worker"]["worker_execution_performed"] is True
    assert evidence["worker"]["database_write_performed"] is False
    assert evidence["worker"]["transition_persistence_performed"] is False
    assert evidence["worker"]["subprocess_started"] is False
    assert evidence["transition"]["from_status"] == "ADMITTED"
    assert evidence["transition"]["to_status"] == "EXECUTING"
    assert evidence["transition"]["database_write_performed"] is False
    assert evidence["detail"]["transition_count"] == 1
    assert evidence["detail"]["transition_statuses"] == ["ADMITTED->EXECUTING"]
    assert evidence["db_observations"]["after"]["scoped_row_counts"] == {
        "execution_states": 1,
        "execution_transitions": 1,
    }
    assert evidence["cleanup"] == {
        "execution_state_transitions": 1,
        "execution_states": 1,
    }
    assert evidence["post_cleanup"]["scoped_row_counts"] == {
        "execution_states": 0,
        "execution_transitions": 0,
    }
    assert all(evidence["checks"].values())
    assert "routes=4" in smoke.summary_line(evidence)
    assert "worker=SUCCEEDED" in smoke.summary_line(evidence)
    assert "states=1" in smoke.summary_line(evidence)
    assert "cleanup_states=1" in smoke.summary_line(evidence)
    assert "secret-0606" not in serialized
    assert "postgresql+psycopg://nex_ae_user:secret-0606" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "ed6@c496em" not in serialized


def test_operator_control_execution_worker_postgres_smoke_failed_checks_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(scoped_states=0, scoped_transitions=0),
            _passing_observations(scoped_states=1, scoped_transitions=1, process_rows=1),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="no_process_or_supervisor_rows_added"):
        smoke._execute_operator_control_execution_worker_route_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_operator_control_execution_worker_postgres_smoke_cleanup_verification_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(scoped_states=0, scoped_transitions=0),
            _passing_observations(scoped_states=1, scoped_transitions=1),
            _passing_observations(scoped_states=1, scoped_transitions=1),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="cleanup verification failed"):
        smoke._execute_operator_control_execution_worker_route_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_operator_control_execution_worker_postgres_smoke_wraps_route_setup_failure(
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
        smoke._execute_operator_control_execution_worker_route_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_operator_control_execution_worker_postgres_smoke_redaction_guards() -> None:
    env = smoke_env()

    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("leaked secret-0606", env)
    with pytest.raises(ValueError, match="provider API key"):
        smoke.assert_smoke_evidence_redacted("leaked ed6@c496em", env)
    assert smoke._safe_detail("profile dev secret-0606", env) == (
        "profile dev ***"
    )


def test_operator_control_execution_worker_postgres_smoke_redaction_local_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = smoke_env()
    monkeypatch.setattr(
        smoke.ae_execution_pg,
        "assert_smoke_evidence_redacted",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("leaked secret-0606", env)
    with pytest.raises(ValueError, match="provider API key"):
        smoke.assert_smoke_evidence_redacted("leaked ed6@c496em", env)


def test_operator_control_execution_worker_postgres_smoke_db_helper_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ScalarResult:
        def __init__(self, value: Any) -> None:
            self._value = value

        def scalar(self) -> Any:
            return self._value

    class FailingConnection:
        def execute(self, *args: Any, **kwargs: Any) -> ScalarResult:
            raise SQLAlchemyError("schema unavailable")

    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
            self.sql.append(str(statement))
            if "pg_indexes" in str(statement):
                return SimpleNamespace(
                    scalars=lambda: SimpleNamespace(
                        all=lambda: sorted(smoke.EXPECTED_EXECUTION_INDEXES)
                    )
                )
            return ScalarResult(1)

    monkeypatch.setattr(
        smoke.ae_execution_pg.process_pg,
        "_indexes_present",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        smoke.ae_execution_pg.supervisor_pg,
        "_indexes_present",
        lambda *args, **kwargs: [],
    )

    assert smoke._schema_migration_recorded(FailingConnection()) is False
    assert smoke._indexes_present(FakeConnection(), "postgresql") == sorted(
        smoke.EXPECTED_EXECUTION_INDEXES
    )
    assert smoke._mapping_value({"a": 1}) == {"a": 1}
    assert smoke._mapping_value(None) == {}
    assert smoke._text_or_none(" state ") == " state "
    assert smoke._text_or_none("") is None


def test_operator_control_execution_worker_postgres_smoke_scoped_counts_without_idempotency() -> None:
    class ScalarResult:
        def __init__(self, value: Any) -> None:
            self._value = value

        def scalar(self) -> Any:
            return self._value

    class FakeConnection:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute(self, statement: Any, params: dict[str, Any]) -> ScalarResult:
            self.queries.append(str(statement))
            if "ae_daemon_operator_control_execution_states" in str(statement):
                return ScalarResult(1)
            return ScalarResult(2)

    connection = FakeConnection()

    assert smoke._scoped_row_counts(
        connection,
        state_ids=["state-1"],
        idempotency_key=None,
    ) == {"execution_states": 1, "execution_transitions": 2}
    assert any(
        "operator_control_execution_state_id" in query
        for query in connection.queries
    )


def test_operator_control_execution_worker_postgres_smoke_jsonb_column_types() -> None:
    class MappingResult:
        def __init__(self, row: dict[str, str] | None) -> None:
            self._row = row

        def mappings(self) -> "MappingResult":
            return self

        def first(self) -> dict[str, str] | None:
            return self._row

    class FakeConnection:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, *args: Any, **kwargs: Any) -> MappingResult:
            self.calls += 1
            if self.calls == 1:
                return MappingResult(
                    {
                        "allowed_next_statuses": "jsonb",
                        "guardrails": "jsonb",
                        "metadata": "jsonb",
                        "operator_control_execution_request": "jsonb",
                    }
                )
            return MappingResult(
                {
                    "operator_control_execution_state": "jsonb",
                    "guardrails": "jsonb",
                    "metadata": "jsonb",
                }
            )

    assert smoke._jsonb_column_types(
        FakeConnection(),
        "postgresql",
        ["state-1"],
    ) == smoke.EXPECTED_JSONB_TYPES
    assert smoke._jsonb_column_types(FakeConnection(), "postgresql", []) == {}
    assert smoke._jsonb_column_types(FakeConnection(), "sqlite", ["state-1"]) == {}


def test_operator_control_execution_worker_postgres_smoke_jsonb_column_types_empty_rows() -> None:
    class MappingResult:
        def mappings(self) -> "MappingResult":
            return self

        def first(self) -> None:
            return None

    class FakeConnection:
        def execute(self, *args: Any, **kwargs: Any) -> MappingResult:
            return MappingResult()

    assert smoke._jsonb_column_types(
        FakeConnection(),
        "postgresql",
        ["missing-state"],
    ) == {}


def test_operator_control_execution_worker_postgres_smoke_sqlite_marker_noops_for_postgres() -> None:
    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def execute(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("postgres marker should not write")

    class FakeEngine:
        def begin(self) -> FakeConnection:
            return FakeConnection()

    smoke._ensure_sqlite_migration_marker(FakeEngine())


def test_operator_control_execution_worker_postgres_smoke_main_outputs_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert f"skipped reason={smoke.SMOKE_ENV}" in capsys.readouterr().out


def test_operator_control_execution_worker_postgres_smoke_main_outputs_json_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke",
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
