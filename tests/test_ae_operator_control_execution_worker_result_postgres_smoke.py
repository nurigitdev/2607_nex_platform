from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_operator_control_execution_worker_result_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0614@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def _passing_migration() -> SimpleNamespace:
    return SimpleNamespace(
        planned=("0596_execution", "0612_result"),
        applied=(),
        skipped=("0596_execution", "0612_result"),
    )


def _passing_observations(
    *,
    states: int = 0,
    transitions: int = 0,
    results: int = 0,
) -> dict[str, Any]:
    scoped = {
        "execution_states": states,
        "execution_transitions": transitions,
        "worker_results": results,
    }
    return {
        "dialect": "sqlite",
        "health_probe": True,
        "tables_present": sorted(smoke.EXPECTED_TABLES),
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
        "migration_recorded": True,
        "jsonb_columns": {},
        "row_counts": scoped,
        "scoped_row_counts": scoped,
    }


def test_worker_result_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_operator_control_execution_worker_result_postgres_smoke(
        {}
    )

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_operator_control_execution_worker_result_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_worker_result_postgres_smoke_rejects_dev_profile() -> None:
    evidence = smoke.run_ae_operator_control_execution_worker_result_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert evidence["detail"].endswith("test for worker-result PostgreSQL smoke.")
    assert smoke.summary_line(evidence) == (
        "ae_operator_control_execution_worker_result_postgres_smoke="
        "fail service=nex-ae-api reason=profile_not_allowed"
    )


def test_worker_result_postgres_smoke_requires_test_db_url() -> None:
    evidence = smoke.run_ae_operator_control_execution_worker_result_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_worker_result_postgres_smoke_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0614")
        ),
    )

    evidence = smoke.run_ae_operator_control_execution_worker_result_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0614" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_worker_result_postgres_smoke_redacts_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_worker_result_route_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("worker result leaked secret-0614")
        ),
    )

    evidence = smoke.run_ae_operator_control_execution_worker_result_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert "secret-0614" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_worker_result_postgres_smoke_passes_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )

    evidence = smoke.run_ae_operator_control_execution_worker_result_postgres_smoke(
        smoke_env()
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["service_id"] == "nex-ae-api"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["routes"] == {
        "ae_persisted_execution_status": 200,
        "ae_persisted_worker_result_status": 200,
    }
    assert evidence["worker"]["worker_status"] == "SUCCEEDED"
    assert evidence["worker"]["database_write_performed"] is False
    assert evidence["worker_result_record"]["worker_status"] == "SUCCEEDED"
    assert evidence["worker_result_record"]["database_write_performed"] is True
    assert evidence["worker_result_record"]["safe_summary_only"] is True
    assert evidence["worker_result_record"][
        "stores_full_worker_result_payload"
    ] is False
    assert evidence["worker_result_record"]["hashes_present"] is True
    assert evidence["db_observations"]["after"]["scoped_row_counts"] == {
        "execution_states": 1,
        "execution_transitions": 0,
        "worker_results": 1,
    }
    assert evidence["cleanup"] == {
        "operator_control_execution_worker_results": 1,
        "execution_state_transitions": 0,
        "execution_states": 1,
    }
    assert evidence["post_cleanup"]["scoped_row_counts"] == {
        "execution_states": 0,
        "execution_transitions": 0,
        "worker_results": 0,
    }
    assert all(evidence["checks"].values())
    assert "routes=2" in smoke.summary_line(evidence)
    assert "worker=SUCCEEDED" in smoke.summary_line(evidence)
    assert "results=1" in smoke.summary_line(evidence)
    assert "cleanup_results=1" in smoke.summary_line(evidence)
    assert "secret-0614" not in serialized
    assert "postgresql+psycopg://nex_ae_user:secret-0614" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "ed6@c496em" not in serialized


def test_worker_result_postgres_smoke_failed_checks_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(),
            _passing_observations(states=1, transitions=0, results=0),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="worker result PostgreSQL smoke checks"):
        smoke._execute_worker_result_route_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_worker_result_postgres_smoke_cleanup_verification_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(),
            _passing_observations(states=1, transitions=0, results=1),
            _passing_observations(states=0, transitions=0, results=1),
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
        smoke._execute_worker_result_route_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_worker_result_postgres_smoke_wraps_sqlalchemy_or_value_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_ensure_sqlite_migration_marker",
        lambda _engine: (_ for _ in ()).throw(ValueError("bad helper")),
    )

    with pytest.raises(RuntimeError, match="bad helper"):
        smoke._execute_worker_result_route_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_worker_result_postgres_smoke_suppresses_final_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    real_cleanup = smoke._cleanup_worker_result_rows
    calls = {"count": 0}

    def flaky_cleanup(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_cleanup(*args, **kwargs)
        raise RuntimeError("final cleanup failed")

    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "_cleanup_worker_result_rows", flaky_cleanup)

    evidence = smoke._execute_worker_result_route_smoke(
        database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
        database_env="NEX_AE_TEST_DATABASE_URL",
    )

    assert evidence["live_db"] is True
    assert calls["count"] >= 2


def test_worker_result_postgres_smoke_scoped_counts_without_idempotency() -> None:
    session_factory = sqlite_artifact_session_factory()
    engine = session_factory.kw["bind"]
    execution_store = (
        smoke.SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
            session_factory
        )
    )
    result_store = (
        smoke.SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore(
            session_factory
        )
    )
    execution_store.ensure_schema()
    result_store.ensure_schema()

    with engine.connect() as connection:
        counts = smoke._scoped_row_counts(
            connection,
            state_ids=["missing-state"],
            result_ids=["missing-result"],
            idempotency_key=None,
        )

    assert counts == {
        "execution_states": 0,
        "execution_transitions": 0,
        "worker_results": 0,
    }


class _ScalarResult:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def scalars(self):
        return self

    def all(self) -> list[str]:
        return self._values


class _MappingResult:
    def __init__(self, row: dict[str, str] | None) -> None:
        self._row = row

    def mappings(self):
        return self

    def first(self) -> dict[str, str] | None:
        return self._row


class _PostgresConnection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(
        self,
        *,
        scalar_values: list[str] | None = None,
        mapping_row: dict[str, str] | None = None,
        use_mapping: bool = False,
        fail: bool = False,
    ) -> None:
        self.scalar_values = scalar_values or []
        self.mapping_row = mapping_row
        self.use_mapping = use_mapping or mapping_row is not None
        self.fail = fail

    def execute(self, *args, **kwargs):
        if self.fail:
            raise SQLAlchemyError("boom")
        if self.use_mapping:
            return _MappingResult(self.mapping_row)
        return _ScalarResult(self.scalar_values)


class _PostgresEngine:
    class _Begin:
        def __enter__(self):
            return _PostgresConnection()

        def __exit__(self, exc_type, exc, traceback) -> bool:
            return False

    def begin(self):
        return self._Begin()


def test_worker_result_postgres_smoke_low_level_postgres_helpers() -> None:
    versions = [smoke.worker_pg.MIGRATION_VERSION, smoke.MIGRATION_VERSION]
    indexes = sorted(smoke.EXPECTED_INDEXES | {"unrelated_idx"})
    jsonb_row = {
        "status_path": "jsonb",
        "supervisor_result_statuses": "jsonb",
        "supervisor_actions": "jsonb",
        "supervisor_result_ids": "jsonb",
        "guardrails": "jsonb",
        "metadata": "jsonb",
    }

    assert smoke._schema_migration_recorded(
        _PostgresConnection(scalar_values=versions)
    )
    assert not smoke._schema_migration_recorded(
        _PostgresConnection(scalar_values=[smoke.MIGRATION_VERSION])
    )
    assert not smoke._schema_migration_recorded(_PostgresConnection(fail=True))
    assert smoke._indexes_present(
        _PostgresConnection(scalar_values=indexes),
        "postgresql",
    ) == sorted(smoke.EXPECTED_INDEXES)
    assert smoke._jsonb_column_types(
        _PostgresConnection(mapping_row=jsonb_row),
        "postgresql",
        ["result-id"],
    ) == smoke.EXPECTED_JSONB_TYPES
    assert smoke._jsonb_column_types(
        _PostgresConnection(mapping_row=None, use_mapping=True),
        "postgresql",
        ["missing-result"],
    ) == {}
    smoke._ensure_sqlite_migration_marker(_PostgresEngine())


def test_worker_result_postgres_smoke_main_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_operator_control_execution_worker_result_postgres_smoke",
        lambda: {
            "status": "SKIPPED",
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "skip_reason": "test",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_operator_control_execution_worker_result_postgres_smoke",
        lambda: {"status": "FAIL", "service_id": "nex-ae-api", "failure_code": "bad"},
    )

    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_worker_result_postgres_smoke_redaction_guards() -> None:
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("secret-0614", smoke_env())

    with pytest.raises(ValueError, match="provider API key"):
        smoke.assert_smoke_evidence_redacted("ed6@c496em", smoke_env())


def test_worker_result_postgres_smoke_local_redaction_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke.worker_pg,
        "assert_smoke_evidence_redacted",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("secret-0614", smoke_env())

    with pytest.raises(ValueError, match="provider API key"):
        smoke.assert_smoke_evidence_redacted("ed6@c496em", smoke_env())


def test_worker_result_postgres_smoke_append_optional_text() -> None:
    values: list[str] = []

    assert smoke._append_optional_text(values, "result-1") == "result-1"
    assert smoke._append_optional_text(values, "") is None
    assert smoke._append_optional_text(values, None) is None
    assert values == ["result-1"]


def test_worker_result_postgres_smoke_summary_for_failure() -> None:
    assert smoke.summary_line(
        {
            "status": "FAIL",
            "service_id": "nex-ae-api",
            "failure_code": "execution_failed",
        }
    ) == (
        "ae_operator_control_execution_worker_result_postgres_smoke="
        "fail service=nex-ae-api reason=execution_failed"
    )
