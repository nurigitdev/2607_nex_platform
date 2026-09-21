from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_cx_private_ownership_postgres_smoke as smoke
from run_migrations import MigrationError


DATABASE_URL = (
    "postgresql+psycopg://nex_cx_user:private@127.0.0.1:5432/nex_cx_test"
)


def _passing_execution() -> dict[str, object]:
    return {
        "database": "nex_cx_test",
        "role": "nex_cx_user",
        "rows_written": 16,
        "owner_scope_count": 2,
        "checks": {"write_read": True, "cleanup": True},
        "failed_checks": [],
    }


def test_private_ownership_postgres_smoke_is_protected_and_test_only() -> None:
    skipped = smoke.run_cx_private_ownership_postgres_smoke({})
    rejected = smoke.run_cx_private_ownership_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )

    assert skipped["status"] == "SKIPPED"
    assert rejected["status"] == "FAIL"
    assert rejected["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(skipped).endswith(f"reason={smoke.SMOKE_ENV}")


def test_private_ownership_postgres_smoke_rejects_non_cx_test_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "service_database_env", lambda *args, **kwargs: "DB_ENV")
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *args, **kwargs: DATABASE_URL.replace("nex_cx_test", "nex_cx_dev"),
    )

    result = smoke.run_cx_private_ownership_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert result["failure_code"] == "target_not_allowed"
    assert smoke._target_url_allowed(DATABASE_URL) is True
    assert smoke._target_url_allowed(DATABASE_URL.replace("nex_cx_user", "postgres")) is False
    assert smoke._target_url_allowed("not-a-url") is False


def test_private_ownership_postgres_smoke_runs_migration_and_redacts_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = SimpleNamespace(
        planned=(smoke.MIGRATION_VERSION,),
        applied=(),
        skipped=(smoke.MIGRATION_VERSION,),
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(smoke, "service_database_env", lambda *args, **kwargs: "NEX_CX_TEST_DATABASE_URL")
    monkeypatch.setattr(smoke, "service_database_url", lambda *args, **kwargs: DATABASE_URL)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: calls.append((service_id, profile)) or migration,
    )
    monkeypatch.setattr(smoke, "_execute_private_ownership_smoke", lambda _url: _passing_execution())

    result = smoke.run_cx_private_ownership_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert result["status"] == "PASS"
    assert result["rows_written"] == 16
    assert result["dgx_live_provider_required"] is False
    assert result["migration"]["skipped"] == [smoke.MIGRATION_VERSION]
    assert result["redacted_database_url"].endswith("@127.0.0.1:5432/nex_cx_test")
    assert "private" not in result["redacted_database_url"]
    assert calls == [("nex-cx", "test")]


def test_private_ownership_postgres_smoke_fails_closed_on_checks_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = SimpleNamespace(planned=(), applied=(), skipped=())
    monkeypatch.setattr(smoke, "service_database_env", lambda *args, **kwargs: "DB_ENV")
    monkeypatch.setattr(smoke, "service_database_url", lambda *args, **kwargs: DATABASE_URL)
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *args, **kwargs: migration)
    monkeypatch.setattr(
        smoke,
        "_execute_private_ownership_smoke",
        lambda _url: {
            **_passing_execution(),
            "checks": {"write_read": True, "cleanup": False},
            "failed_checks": ["cleanup"],
        },
    )
    failed = smoke.run_cx_private_ownership_postgres_smoke({smoke.SMOKE_ENV: "1"})
    assert failed["failure_code"] == "ownership_smoke_failed"
    assert failed["detail"] == "cleanup"

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError(f"failed {DATABASE_URL}")
        ),
    )
    errored = smoke.run_cx_private_ownership_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_CX_TEST_DATABASE_URL": DATABASE_URL}
    )
    assert errored["failure_code"] == "execution_failed"
    assert "private" not in errored["detail"]
    assert "***" in errored["detail"]


def test_private_ownership_helpers_and_cli(monkeypatch, capsys) -> None:
    refs = smoke._build_refs()
    assert smoke._owner_tuple(refs, "owner_a") == (
        "oa.tenant",
        refs["tenant_id"],
        "oa.user",
        refs["owner_a_subject_id"],
    )
    passing = {
        "status": "PASS",
        "database": "nex_cx_test",
        "rows_written": 16,
        "owner_scope_count": 2,
        "failed_checks": [],
        "dgx_live_provider_required": False,
    }
    assert "rows=16" in smoke.summary_line(passing)
    assert "failed_checks=0" in smoke.summary_line(passing)
    assert smoke._redact_detail("plain", database_url="") == "plain"

    monkeypatch.setattr(smoke, "run_cx_private_ownership_postgres_smoke", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "postgres_smoke=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_cx_private_ownership_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
