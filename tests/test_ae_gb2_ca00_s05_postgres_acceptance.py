from __future__ import annotations

import run_gb2_ca00_s05_ae_agent_runtime_worker as smoke


def test_smoke_is_protected_and_opt_in() -> None:
    result = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker({})

    assert result["status"] == "SKIPPED"
    assert result["actual_postgres"] is False


def test_smoke_rejects_missing_and_wrong_database_targets() -> None:
    missing = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker(
        {smoke.SMOKE_ENV: "1"}
    )
    wrong = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://other:secret@localhost/other",
        }
    )

    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"
    assert "postgresql://other:secret" not in str(wrong)


def test_smoke_projects_migration_and_component_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: type(
            "Migration",
            (),
            {
                "planned": ("a", "b"),
                "applied": ("b",),
                "skipped": ("a",),
            },
        )(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_protected_component",
        lambda _url: {
            "status": "PASS",
            "actual_postgres": True,
            "database": "nex_ae_test",
            "role": "nex_ae_user",
            "checks": {"worker": True},
            "row_counts": {"runtime_job": 2, "runtime_job_attempt": 2},
            "cleanup_counts": {"component_remaining": 0},
        },
    )

    result = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_ae_user:nuri1004@127.0.0.1/nex_ae_test"
            ),
        }
    )

    assert result["status"] == "PASS"
    assert result["evidence_classification"] == "PROTECTED_COMPONENT"
    assert result["checks"] == {"migration_current": True, "worker": True}
    assert result["migration"]["planned_count"] == 2
    assert "nuri1004" not in str(result)
    assert smoke.summary_line(result) == (
        "gb2_ca00_s05_ae_worker=pass classification=PROTECTED_COMPONENT "
        "checks=2/2 jobs=2 attempts=2 remaining=0"
    )


def test_smoke_fails_closed_and_redacts_password(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_test")
        ),
    )
    result = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_test"
            ),
        }
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "execution_failed"
    assert "nex_ae_user:secret" not in str(result)
    assert "***" in result["detail"]


def test_target_and_summary_fail_paths() -> None:
    assert smoke._target_url_allowed(
        "postgresql+psycopg://nex_ae_user:x@localhost/nex_ae_test"
    )
    assert not smoke._target_url_allowed(
        "sqlite:///nex_ae_test"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "gb2_ca00_s05_ae_worker=fail classification=none "
        "checks=0/0 jobs=0 attempts=0 remaining=0"
    )
