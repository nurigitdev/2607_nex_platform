from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0566@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def _passing_migration() -> SimpleNamespace:
    return SimpleNamespace(
        planned=(smoke.MIGRATION_VERSION,),
        applied=(),
        skipped=(smoke.MIGRATION_VERSION,),
    )


def _passing_observations() -> dict[str, Any]:
    return {
        "dialect": "sqlite",
        "tables_present": sorted(smoke.EXPECTED_TABLES),
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
        "migration_recorded": True,
        "row_counts": {"supervisor_records": 2, "supervisor_events": 2},
        "scheduler_counts": {"status_probe_ready": 1, "start_daemon_blocked": 1},
        "jsonb_columns": {},
    }


def test_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke_skips() -> (
    None
):
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke(
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
        "ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_scheduler_daemon_supervisor_rejects_dev_profile() -> (
    None
):
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_scheduler_daemon_supervisor_missing_db_url() -> (
    None
):
    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_retention_scheduler_daemon_supervisor_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0566")
        ),
    )

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0566" not in evidence["detail"]


def test_ae_artifact_retention_scheduler_daemon_supervisor_passes_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: _passing_migration())

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke(
            smoke_env()
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["migration"] == {
        "planned": [smoke.MIGRATION_VERSION],
        "applied": [],
        "skipped": [smoke.MIGRATION_VERSION],
    }
    assert evidence["routes"] == {
        "status_probe_dispatch_status": 200,
        "start_daemon_dispatch_status": 200,
        "collection_status": 200,
        "detail_status": 200,
    }
    assert evidence["dispatches"]["status_probe"]["schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_DISPATCH_SCHEMA_VERSION
    )
    assert evidence["dispatches"]["status_probe"]["result_status"] == "READY"
    assert evidence["dispatches"]["status_probe"]["action"] == "status_probe"
    assert evidence["dispatches"]["status_probe"]["process_started"] is False
    assert evidence["dispatches"]["status_probe"]["supervisor_adapter_invoked"] is True
    assert evidence["dispatches"]["start_daemon"]["result_status"] == "BLOCKED"
    assert evidence["dispatches"]["start_daemon"]["action"] == "start_daemon"
    assert evidence["dispatches"]["start_daemon"]["process_started"] is False
    assert evidence["dispatches"]["start_daemon"]["process_stopped"] is False
    assert evidence["dispatches"]["start_daemon"]["event_type"] == (
        "SUPERVISOR_RESULT_RECORDED"
    )
    assert evidence["collection"]["schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COLLECTION_SCHEMA_VERSION
    )
    assert evidence["collection"]["count"] == 1
    assert evidence["collection"]["actions"] == ["start_daemon"]
    assert evidence["collection"]["result_statuses"] == ["BLOCKED"]
    assert evidence["detail"]["schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_DETAIL_SCHEMA_VERSION
    )
    assert evidence["detail"]["supervisor_event_count"] == 1
    assert evidence["detail"]["event_types"] == ["SUPERVISOR_RESULT_RECORDED"]
    assert evidence["db_observations"]["migration_recorded"] is True
    assert set(evidence["db_observations"]["tables_present"]) == smoke.EXPECTED_TABLES
    assert set(evidence["db_observations"]["indexes_present"]) == smoke.EXPECTED_INDEXES
    assert evidence["db_observations"]["row_counts"] == {
        "supervisor_records": 2,
        "supervisor_events": 2,
    }
    assert evidence["db_observations"]["scheduler_counts"] == {
        "status_probe_ready": 1,
        "start_daemon_blocked": 1,
    }
    assert all(evidence["checks"].values())
    assert evidence["cleanup"] == {
        "daemon_supervisor_events": 2,
        "daemon_supervisor_records": 2,
    }
    assert evidence["post_cleanup"]["row_counts"] == {
        "supervisor_records": 0,
        "supervisor_events": 0,
    }
    assert evidence["live_db"] is True
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke=pass "
        "service=nex-ae-api"
    )
    assert "dispatches=2" in smoke.summary_line(evidence)
    assert "secret-0566" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "postgresql+psycopg://nex_ae_user:secret-0566" not in serialized


def test_ae_artifact_retention_scheduler_daemon_supervisor_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: {
            "dialect": "sqlite",
            "tables_present": sorted(smoke.EXPECTED_TABLES),
            "indexes_present": sorted(smoke.EXPECTED_INDEXES),
            "migration_recorded": True,
            "row_counts": {"supervisor_records": 0, "supervisor_events": 0},
            "scheduler_counts": {"status_probe_ready": 0, "start_daemon_blocked": 0},
            "jsonb_columns": {},
        },
    )

    with pytest.raises(RuntimeError, match="supervisor_rows_persisted"):
        smoke._execute_ae_artifact_retention_scheduler_daemon_supervisor_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_daemon_supervisor_cleanup_verification_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    observations = iter(
        [
            _passing_observations(),
            {
                **_passing_observations(),
                "row_counts": {"supervisor_records": 1, "supervisor_events": 1},
            },
        ]
    )
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="cleanup verification"):
        smoke._execute_ae_artifact_retention_scheduler_daemon_supervisor_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_daemon_supervisor_execute_wraps_value_error(
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
        smoke._execute_ae_artifact_retention_scheduler_daemon_supervisor_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_daemon_supervisor_finally_swallows_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: {
            **_passing_observations(),
            "row_counts": {"supervisor_records": 0, "supervisor_events": 0},
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_supervisor_records",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cleanup boom")),
    )

    with pytest.raises(RuntimeError, match="supervisor_rows_persisted"):
        smoke._execute_ae_artifact_retention_scheduler_daemon_supervisor_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_daemon_supervisor_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: _passing_migration())
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_retention_scheduler_daemon_supervisor_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = (
        smoke.run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_artifact_retention_scheduler_daemon_supervisor_helpers() -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert smoke._database_name(env["NEX_AE_TEST_DATABASE_URL"]) == "nex_ae_test"
    assert smoke._database_name("not://valid[") == ""
    assert smoke._database_url_password(env["NEX_AE_TEST_DATABASE_URL"]) == (
        "secret-0566"
    )
    assert smoke._database_url_password(None) is None
    assert smoke._mapping_value({"ok": True}) == {"ok": True}
    assert smoke._mapping_value([]) == {}
    assert "secret-0566" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("secret-0566", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/private", {})


def test_ae_artifact_retention_scheduler_daemon_supervisor_helper_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RaisesJson:
        def json(self) -> dict[str, Any]:
            raise ValueError("bad json")

    class ListJson:
        def json(self) -> list[str]:
            return ["not", "dict"]

    assert smoke._json_payload(RaisesJson()) == {}
    assert smoke._json_payload(ListJson()) == {}
    assert smoke._record_id({}) is None
    assert smoke._record_id({"supervisor_record": {"daemon_supervisor_record_id": ""}}) is None
    assert smoke._collection_evidence({"items": "wrong"}) == {
        "schema_version": None,
        "count": None,
        "item_ids": [],
        "actions": [],
        "result_statuses": [],
    }
    assert smoke._detail_evidence({"supervisor_events": "wrong"}) == {
        "schema_version": None,
        "record_id": None,
        "action": None,
        "result_status": None,
        "supervisor_event_count": None,
        "event_types": [],
    }
    smoke._ensure_sqlite_migration_marker(
        SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )

    monkeypatch.setattr(
        smoke,
        "make_url",
        lambda _url: (_ for _ in ()).throw(SQLAlchemyError("bad url")),
    )
    assert smoke._database_name("bad") == ""
    assert smoke._database_url_password("bad") is None


def test_ae_artifact_retention_scheduler_daemon_supervisor_postgres_helpers() -> None:
    class FakeResult:
        def __init__(
            self,
            *,
            scalar_value: str | None = None,
            scalar_values: list[str] | None = None,
            row: dict[str, str] | None = None,
        ) -> None:
            self.scalar_value = scalar_value
            self.scalar_values = scalar_values or []
            self.row = row

        def scalar(self) -> str | None:
            return self.scalar_value

        def scalars(self) -> "FakeResult":
            return self

        def all(self) -> list[str]:
            return self.scalar_values

        def mappings(self) -> "FakeResult":
            return self

        def first(self) -> dict[str, str] | None:
            return self.row

    class FakePostgresConnection:
        dialect = SimpleNamespace(name="postgresql")

        def execute(self, statement: object, params: dict[str, str] | None = None) -> FakeResult:
            sql = str(statement)
            if "to_regclass" in sql:
                table_name = (params or {})["table_name"].split(".", 1)[1]
                return FakeResult(scalar_value=table_name)
            if "pg_indexes" in sql:
                return FakeResult(scalar_values=sorted(smoke.EXPECTED_INDEXES))
            if "pg_typeof" in sql:
                return FakeResult(row=smoke.EXPECTED_JSONB_TYPES)
            return FakeResult()

    class MissingSchemaMigrationConnection:
        def execute(self, statement: object, params: dict[str, str] | None = None) -> None:
            raise SQLAlchemyError("schema missing")

    connection = FakePostgresConnection()

    assert smoke._table_exists(
        connection,
        "ae_artifact_retention_scheduler_daemon_supervisor_results",
    )
    assert smoke._indexes_present(connection, "postgresql") == sorted(
        smoke.EXPECTED_INDEXES
    )
    assert smoke._jsonb_column_types(connection, "postgresql", ["record-1"]) == (
        smoke.EXPECTED_JSONB_TYPES
    )
    assert smoke._jsonb_column_types(connection, "postgresql", []) == {}
    assert smoke._jsonb_column_types(
        SimpleNamespace(
            execute=lambda *args, **kwargs: FakeResult(row=None),
        ),
        "postgresql",
        ["missing"],
    ) == {}
    assert smoke._schema_migration_recorded(MissingSchemaMigrationConnection()) is False


def test_ae_artifact_retention_scheduler_daemon_supervisor_main_outputs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skipped = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    failure = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": "nex-ae-api",
        "failure_code": "execution_failed",
    }
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke",
        lambda: skipped,
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke="
        "skipped"
    ) in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_daemon_supervisor_postgres_smoke",
        lambda: failure,
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=execution_failed" in capsys.readouterr().out
