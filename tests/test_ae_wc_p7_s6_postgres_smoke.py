from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import run_p7_s6_postgres_smoke as smoke

AE_URL = "postgresql://nex_ae_user:test-secret@127.0.0.1:5432/nex_ae_test"
WC_URL = "postgresql://nex_wc_user:test-secret@127.0.0.1:5432/nex_wc_test"


@pytest.mark.skipif(
    not os.getenv(smoke.AE_DATABASE_ENV)
    or not os.getenv(smoke.WC_DATABASE_ENV),
    reason="AE and WC test database URLs are required for protected smoke",
)
def test_s6_actual_postgres_work_result_resume_and_zero_residue():
    evidence = smoke.run_p7_s6_postgres_smoke(
        {
            **os.environ,
            smoke.SMOKE_ENV: "1",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert all(evidence["checks"].values())
    assert evidence["cleanup_counts"]["remaining"] == 0


def test_s6_protected_smoke_skips_and_rejects_non_test_targets():
    assert smoke.run_p7_s6_postgres_smoke({})["status"] == "SKIPPED"
    rejected = smoke.run_p7_s6_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL.replace("nex_wc_test", "nex_wc_dev"),
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"


def test_s6_smoke_composes_current_migrations_and_redacted_evidence(monkeypatch):
    migrations = {
        "nex-ae-api": SimpleNamespace(
            planned=("2404_ae_work_result_resume",),
            applied=(),
            skipped=("2404_ae_work_result_resume",),
        ),
        "nex-wc": SimpleNamespace(
            planned=("1002_wc_work_result",),
            applied=(),
            skipped=("1002_wc_work_result",),
        ),
    }
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service, **_kwargs: migrations[service],
    )
    monkeypatch.setattr(
        smoke.p5_s5,
        "_execute_postgres_smoke",
        lambda _url, *, verifier: {
            "status": "PASS",
            "checks": {"work_result_event_matched": True},
            "row_counts": {"wc_work_result": 1, "ae_resume_runtime_job": 1},
            "cleanup_counts": {"remaining": 0},
        },
    )
    evidence = smoke.run_p7_s6_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL,
        }
    )
    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["migration"]["ae_latest"] == "2404_ae_work_result_resume"
    assert "test-secret" not in str(evidence["redacted_database_urls"])
    assert "checks=3/3" in smoke.summary_line(evidence)


def test_s6_smoke_redacts_execution_failure(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(AE_URL)),
    )
    evidence = smoke.run_p7_s6_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL,
        }
    )
    assert evidence["failure_code"] == "execution_failed"
    assert "test-secret" not in evidence["detail"]
