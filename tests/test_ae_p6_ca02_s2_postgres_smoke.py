from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p6_ca02_s2_postgres_smoke as smoke


def test_smoke_is_protected_and_requires_exact_test_database() -> None:
    skipped = smoke.run_p6_ca02_s2_postgres_smoke({})
    missing = smoke.run_p6_ca02_s2_postgres_smoke({smoke.SMOKE_ENV: "1"})
    rejected = smoke.run_p6_ca02_s2_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql+psycopg://wrong@localhost/other",
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False
    assert missing["failure_code"] == "database_url_missing"
    assert rejected["failure_code"] == "target_not_allowed"


def test_smoke_combines_both_profile_round_trips_and_constraint(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=("2204_ae_nsl_backend_run", smoke.REQUIRED_MIGRATION),
        applied=(smoke.REQUIRED_MIGRATION,),
        skipped=("2204_ae_nsl_backend_run",),
    )
    profile_runs = iter(
        (
            {
                "status": "PASS",
                "checks": {"exact_backend_profile_persisted": True},
                "cleanup_counts": {"remaining": 0},
            },
            {
                "status": "PASS",
                "checks": {"exact_backend_profile_persisted": True},
                "cleanup_counts": {"remaining": 0},
            },
        )
    )
    monkeypatch.setattr(
        smoke, "run_service_migrations", lambda *args, **kwargs: migration
    )
    monkeypatch.setattr(
        smoke.p5_s5,
        "_execute_postgres_smoke",
        lambda *args, **kwargs: next(profile_runs),
    )
    monkeypatch.setattr(
        smoke,
        "_database_checks",
        lambda _url: {
            "actual_test_database": True,
            "actual_test_role": True,
            "migration_recorded": True,
            "dual_profile_constraint": True,
        },
    )
    database_url = "postgresql+psycopg://nex_ae_user:secret@localhost/nex_ae_test"

    evidence = smoke.run_p6_ca02_s2_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )

    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["checks"] == {
        "migration_current": True,
        "historical_profile_round_trip": True,
        "in_process_profile_round_trip": True,
        "historical_cleanup_complete": True,
        "in_process_cleanup_complete": True,
        "actual_test_database": True,
        "actual_test_role": True,
        "migration_recorded": True,
        "dual_profile_constraint": True,
    }
    assert "p6_ca02_s2_postgres=pass" in smoke.summary_line(evidence)


def test_smoke_reports_profile_failure_and_redacts_execution_error(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=(smoke.REQUIRED_MIGRATION,),
        applied=(),
        skipped=(smoke.REQUIRED_MIGRATION,),
    )
    monkeypatch.setattr(
        smoke, "run_service_migrations", lambda *args, **kwargs: migration
    )
    monkeypatch.setattr(
        smoke.p5_s5,
        "_execute_postgres_smoke",
        lambda *args, **kwargs: {
            "status": "FAIL",
            "checks": {},
            "cleanup_counts": {"remaining": 1},
        },
    )
    monkeypatch.setattr(smoke, "_database_checks", lambda _url: {})
    database_url = "postgresql+psycopg://nex_ae_user:secret@localhost/nex_ae_test"
    failed = smoke.run_p6_ca02_s2_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )
    assert failed["status"] == "FAIL"
    assert failed["checks"]["historical_profile_round_trip"] is False

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(database_url)),
    )
    errored = smoke.run_p6_ca02_s2_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )
    assert errored["failure_code"] == "execution_failed"
    assert "secret" not in errored["detail"]


def test_database_checks_inspect_actual_identity_migration_and_constraint(
    monkeypatch,
) -> None:
    class Result:
        def __init__(self, value):
            self.value = value

        def one(self):
            return self.value

        def scalar_one(self):
            return self.value

    class Connection:
        def execute(self, statement, _params=None):
            sql = str(statement)
            if "current_database" in sql:
                return Result((smoke.EXPECTED_DATABASE, smoke.EXPECTED_ROLE))
            if "schema_migrations" in sql:
                return Result(True)
            return Result(
                "CHECK backend_profile IN "
                "(NSL_V01_IN_PROCESS, NSL_V01_PROCESS_ISOLATED)"
            )

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Engine:
        disposed = False

        def connect(self):
            return Connection()

        def dispose(self):
            self.disposed = True

    engine = Engine()
    monkeypatch.setattr(smoke, "create_engine", lambda *args, **kwargs: engine)

    checks = smoke._database_checks("postgresql+psycopg://redacted")

    assert all(checks.values())
    assert engine.disposed is True


def test_main_renders_summary_and_json(monkeypatch, capsys) -> None:
    evidence = {
        "status": "PASS",
        "actual_postgres": True,
        "checks": {"dual": True},
        "migration": {"planned_count": 44, "latest_version": smoke.REQUIRED_MIGRATION},
    }
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(smoke, "run_p6_ca02_s2_postgres_smoke", lambda: evidence)

    assert smoke.main(["--summary"]) == 0
    assert "p6_ca02_s2_postgres=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
