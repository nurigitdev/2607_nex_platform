from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import run_p7_s5_postgres_smoke as smoke

AE_URL = "postgresql://nex_ae_user:test-secret@127.0.0.1:5432/nex_ae_test"
WC_URL = "postgresql://nex_wc_user:test-secret@127.0.0.1:5432/nex_wc_test"
ROOT = Path(__file__).resolve().parents[1]


def test_s5_wait_migration_preserves_executable_step_fk_type():
    executable_step = (
        ROOT / "database/nex-ae-api/migrations/2005_ae_executable_step.sql"
    ).read_text(encoding="utf-8")
    wait_registration = (
        ROOT / "database/nex-ae-api/migrations/2402_ae_wait_registration.sql"
    ).read_text(encoding="utf-8")

    assert "executable_step_id TEXT NOT NULL" in executable_step
    assert "executable_step_id TEXT NOT NULL" in wait_registration


def test_s5_protected_smoke_skips_and_rejects_non_test_targets():
    assert smoke.run_p7_s5_postgres_smoke({})["status"] == "SKIPPED"
    rejected = smoke.run_p7_s5_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: "postgresql://nex_wc_user:x@localhost/nex_wc_dev",
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"


def test_s5_smoke_composes_two_migrations_and_redacted_evidence(monkeypatch):
    migrations = {
        "nex-ae-api": SimpleNamespace(
            planned=("2403_ae_delegate_work_activation",),
            applied=(),
            skipped=("2403_ae_delegate_work_activation",),
        ),
        "nex-wc": SimpleNamespace(
            planned=("1001_wc_assignment_claim",),
            applied=(),
            skipped=("1001_wc_assignment_claim",),
        ),
    }
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service, **_kwargs: migrations[service],
    )

    def execute(_url, *, verifier):
        assert callable(verifier)
        return {
            "status": "PASS",
            "actual_postgres": True,
            "checks": {"parent_waiting_dependency": True},
            "row_counts": {"wait_registration": 1, "wc_work_item": 1},
            "cleanup_counts": {"remaining": 0},
        }

    monkeypatch.setattr(smoke.p5_s5, "_execute_postgres_smoke", execute)
    evidence = smoke.run_p7_s5_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL,
        }
    )

    assert evidence["status"] == "PASS"
    assert len(evidence["checks"]) == 3
    assert "test-secret" not in json_text(evidence["redacted_database_urls"])
    assert "checks=3/3" in smoke.summary_line(evidence)


def test_s5_smoke_redacts_execution_failure(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(AE_URL)),
    )
    evidence = smoke.run_p7_s5_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL,
        }
    )
    assert evidence["failure_code"] == "execution_failed"
    assert "test-secret" not in evidence["detail"]


def json_text(value):
    return str(value)
