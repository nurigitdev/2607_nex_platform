from __future__ import annotations

import json

import pytest
from sqlalchemy.engine import make_url

import run_platform_test_migration_readiness as smoke
from nex_runtime.postgres_orchestration import POSTGRES_SERVICE_ORDER
from nex_runtime.postgres_targets import POSTGRES_TEST_TARGETS
from platform_test_migrations import (
    PlatformMigrationReadinessError,
    run_platform_test_migration_readiness,
)
from run_migrations import MigrationRunResult


PLANNED = ("0001_foundation", "0002_runtime")


def valid_environment() -> dict[str, str]:
    return {
        target.test_database_env: (
            f"postgresql://{target.expected_role_name}:secret@127.0.0.1/"
            f"{target.expected_database_name}"
        )
        for target in POSTGRES_TEST_TARGETS
    }


def migration_result(service_id: str, **replacements) -> MigrationRunResult:
    values = {
        "service_id": service_id,
        "planned": PLANNED,
        "applied": (),
        "skipped": PLANNED,
        "dry_run": False,
        "profile": "test",
    }
    values.update(replacements)
    return MigrationRunResult(**values)


class Cursor:
    def __init__(self, database: str, role: str, mode: str) -> None:
        self.database = database
        self.role = role
        self.mode = mode
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query: str) -> None:
        if self.mode == "execute_error":
            raise RuntimeError("private database detail")
        self.query = query

    def fetchone(self):
        if "current_database" in self.query:
            if self.mode == "identity":
                return ("wrong", "wrong")
            return (self.database, self.role)
        if self.mode == "select_one":
            return (0,)
        return (1,)

    def fetchall(self):
        versions = PLANNED[:-1] if self.mode == "versions" else PLANNED
        return [(version,) for version in versions]


class Connection:
    def __init__(self, database: str, role: str, mode: str) -> None:
        self.database = database
        self.role = role
        self.mode = mode

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return Cursor(self.database, self.role, self.mode)


def connector(mode: str = "pass", calls: list[str] | None = None):
    def connect(database_url: str, *, autocommit: bool):
        assert autocommit is True
        if mode == "connect_error":
            raise RuntimeError("private connection detail")
        parsed = make_url(database_url)
        if calls is not None:
            calls.append(parsed.database or "")
        return Connection(parsed.database or "", parsed.username or "", mode)

    return connect


def test_runs_migrations_in_order_and_requires_current_readiness() -> None:
    migration_calls = []
    connection_calls: list[str] = []

    def migrate(service_id, **kwargs):
        migration_calls.append((service_id, kwargs))
        return migration_result(service_id)

    result = run_platform_test_migration_readiness(
        valid_environment(),
        migration_runner=migrate,
        connect=connector(calls=connection_calls),
    )
    projection = result.to_public_projection()

    assert [item[0] for item in migration_calls] == list(POSTGRES_SERVICE_ORDER)
    assert connection_calls == [
        "nex_oa_test",
        "nex_mo_test",
        "nex_cx_test",
        "nex_ae_test",
        "nex_ag_test",
    ]
    assert all(item[1]["profile"] == "test" for item in migration_calls)
    assert projection["startup_allowed"] is True
    assert projection["service_count"] == 5
    assert projection["migration_count"] == 10
    assert projection["skipped_count"] == 10
    assert projection["evidence"]["record_count"] == 10
    assert "secret" not in str(projection)


def test_configuration_and_migration_failures_are_normalized() -> None:
    with pytest.raises(
        PlatformMigrationReadinessError, match="configuration_invalid"
    ) as configured:
        run_platform_test_migration_readiness({})
    assert configured.value.service_id is None

    def fail_migration(service_id, **kwargs):
        raise RuntimeError("private migration detail")

    with pytest.raises(
        PlatformMigrationReadinessError, match="migration_failed"
    ) as failed:
        run_platform_test_migration_readiness(
            valid_environment(), migration_runner=fail_migration
        )
    assert failed.value.service_id == "nex-oa"
    assert "private" not in str(failed.value)


@pytest.mark.parametrize(
    "replacements",
    [
        {"service_id": "nex-cx"},
        {"profile": "dev"},
        {"dry_run": True},
        {"planned": (), "skipped": ()},
        {"skipped": PLANNED[:1]},
    ],
)
def test_invalid_migration_result_fails_closed(replacements) -> None:
    def migrate(service_id, **kwargs):
        selected_service = replacements.get("service_id", service_id)
        remaining = {
            key: value for key, value in replacements.items() if key != "service_id"
        }
        return migration_result(selected_service, **remaining)

    with pytest.raises(PlatformMigrationReadinessError, match="migration_failed"):
        run_platform_test_migration_readiness(
            valid_environment(), migration_runner=migrate
        )


@pytest.mark.parametrize(
    ("mode", "failure_code"),
    [
        ("identity", "database_identity_mismatch"),
        ("select_one", "database_select_one_failed"),
        ("versions", "migration_head_not_current"),
        ("connect_error", "database_readiness_failed"),
        ("execute_error", "database_readiness_failed"),
    ],
)
def test_readiness_failures_are_normalized(mode, failure_code) -> None:
    with pytest.raises(
        PlatformMigrationReadinessError, match=failure_code
    ) as failed:
        run_platform_test_migration_readiness(
            valid_environment(),
            migration_runner=lambda service_id, **kwargs: migration_result(
                service_id
            ),
            connect=connector(mode),
        )
    assert failed.value.service_id == "nex-oa"


def test_smoke_guards_projection_summary_and_main(monkeypatch, capsys) -> None:
    assert smoke.run_smoke({})["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "run_platform_test_migration_readiness",
        lambda env: (_ for _ in ()).throw(
            PlatformMigrationReadinessError("migration_failed", "nex-cx")
        ),
    )
    failed = smoke.run_smoke({smoke.SMOKE_ENV: "1"})
    assert failed["failure_code"] == "migration_failed"
    assert "code=migration_failed" in smoke.summary_line(failed)

    class Result:
        def to_public_projection(self):
            return {
                "status": "PASS",
                "service_count": 5,
                "migration_count": 89,
                "applied_count": 0,
            }

    monkeypatch.setattr(
        smoke, "run_platform_test_migration_readiness", lambda env: Result()
    )
    passing = smoke.run_smoke({smoke.SMOKE_ENV: "1"})
    assert passing["next_slice"] == "1326"
    assert smoke.summary_line(passing) == (
        "platform_test_migration_readiness=pass services=5 "
        "migrations=89 applied=0 next=1326"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skip")

    monkeypatch.setattr(smoke, "run_smoke", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "services=5" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(smoke, "run_smoke", lambda: failed)
    assert smoke.main([]) == 1


@pytest.mark.skipif(
    smoke.os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required",
)
def test_actual_platform_test_migration_readiness() -> None:
    result = smoke.run_smoke()

    assert result["status"] == "PASS", result
    assert result["service_count"] == 5
    assert result["migration_count"] == 89
    assert result["startup_allowed"] is True
