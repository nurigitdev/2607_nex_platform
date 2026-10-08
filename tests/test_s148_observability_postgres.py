from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

import run_s148_observability_postgres as smoke
from run_s148_alert_persistence_restart import SQLITE_SCHEMA


def test_postgres_smoke_is_opt_in_and_requires_database_url(monkeypatch) -> None:
    skipped = smoke.run_observability_postgres_smoke({})
    missing = smoke.run_observability_postgres_smoke({smoke.SMOKE_ENV: "1"})
    assert skipped["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in skipped["skip_reason"]
    assert missing["status"] == "FAIL"
    assert missing["failure_code"] == "DATABASE_URL_MISSING"


def test_postgres_smoke_maps_migration_failure(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise smoke.MigrationError("private migration detail")

    monkeypatch.setattr(smoke, "run_service_migrations", fail)
    result = smoke.run_observability_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: "postgresql://private"}
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "MIGRATION_FAILED"


def test_postgres_smoke_full_flow_with_sqlite_test_double(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 's148.db'}"

    def migrate(*args, **kwargs):
        engine = create_engine(database_url)
        with engine.begin() as connection:
            for statement in SQLITE_SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(text(statement))
        engine.dispose()
        return SimpleNamespace(
            service_id="nex-ag",
            planned=("1477_ag_platform_alert_persistence",),
            applied=("1477_ag_platform_alert_persistence",),
            skipped=(),
        )

    def observations(engine, alert_ids):
        with engine.connect() as connection:
            counts = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM ag_alerts WHERE alert_id IN (:a, :b)) AS alerts, "
                    "(SELECT count(*) FROM ag_notify_outbox WHERE alert_id IN (:a, :b)) AS notifications, "
                    "(SELECT count(*) FROM ag_notify_attempts t JOIN ag_notify_outbox o "
                    "ON o.notify_id = t.notify_id WHERE o.alert_id IN (:a, :b)) AS attempts"
                ),
                {"a": alert_ids[0], "b": alert_ids[1]},
            ).mappings().one()
        return {
            "table_count": 3,
            "migration_recorded": True,
            "claim_index_present": True,
            "alert_count": int(counts["alerts"]),
            "notification_count": int(counts["notifications"]),
            "attempt_count": int(counts["attempts"]),
        }

    monkeypatch.setattr(smoke, "run_service_migrations", migrate)
    monkeypatch.setattr(smoke, "build_engine", create_engine)
    monkeypatch.setattr(smoke, "_database_name", lambda engine: "nex_ag_test")
    monkeypatch.setattr(smoke, "_is_postgresql", lambda engine: True)
    monkeypatch.setattr(smoke, "_db_observations", observations)
    monkeypatch.setattr(smoke, "redact_database_url", lambda value: "<redacted>")
    result = smoke.run_observability_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["cleanup"] == {"deleted_alerts": 2, "residue": 0}
    assert result["observations"]["attempt_count"] == 3
    assert result["redacted_database_url"] == "<redacted>"


def test_wrong_database_and_initial_execution_failure_are_safe(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'empty.db'}"
    migration = SimpleNamespace(service_id="nex-ag", planned=(), applied=(), skipped=())
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *args, **kwargs: migration)
    monkeypatch.setattr(smoke, "build_engine", create_engine)
    monkeypatch.setattr(smoke, "_database_name", lambda engine: "wrong_db")
    wrong = smoke.run_observability_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )
    assert wrong["failure_code"] == "TEST_DATABASE_REQUIRED"
    monkeypatch.setattr(smoke, "_database_name", lambda engine: "nex_ag_test")
    failed = smoke.run_observability_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )
    assert failed["failure_code"] == "INITIAL_EXECUTION_FAILED"
    assert "SQL" not in failed["detail"]


def test_evidence_redaction_summary_and_cli(monkeypatch, capsys) -> None:
    raw = "postgresql://user:secret@localhost/nex_ag_test"
    with pytest.raises(ValueError):
        smoke.assert_evidence_redacted(raw, {smoke.DATABASE_ENV: raw})
    with pytest.raises(ValueError):
        smoke.assert_evidence_redacted("secret", {"DB_PASSWORD": "secret"})
    assert "skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "reason=BAD" in smoke.summary_line({"status": "FAIL", "failure_code": "BAD"})
    passed = {
        "status": "PASS",
        "observations": {"alert_count": 2, "notification_count": 2, "attempt_count": 3},
        "cleanup": {"residue": 0},
        "checks": {str(index): True for index in range(18)},
        "next_slice": "1481",
    }
    assert smoke.summary_line(passed).endswith("checks=18/18 next=1481")
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(smoke, "run_observability_postgres_smoke", lambda: {"status": "SKIPPED"})
    assert smoke.main(["--summary"]) == 0
    assert "skipped" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_observability_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "BAD"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def one(self):
        return self.value


class _Connection:
    def __init__(self, values):
        self.values = iter(values)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, params=None):
        return _Result(next(self.values))


class _Engine:
    def __init__(self, values, dialect_name="postgresql"):
        self.values = values
        self.dialect = SimpleNamespace(name=dialect_name)

    def connect(self):
        return _Connection(self.values)


def test_postgres_catalog_helpers_and_safe_error_mapping() -> None:
    observations = smoke._db_observations(
        _Engine([3, True, True, {"alerts": 2, "notifications": 2, "attempts": 3}]),
        ("alert:a", "alert:b"),
    )
    assert observations == {
        "table_count": 3,
        "migration_recorded": True,
        "claim_index_present": True,
        "alert_count": 2,
        "notification_count": 2,
        "attempt_count": 3,
    }
    assert smoke._database_name(_Engine(["nex_ag_test"])) == "nex_ag_test"
    assert smoke._is_postgresql(_Engine([])) is True
    assert smoke._is_postgresql(_Engine([], "sqlite")) is False
    assert smoke._safe_detail(SQLAlchemyError("private")) == (
        "PostgreSQL observability operation failed."
    )
