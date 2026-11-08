from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import run_p7_s8_postgres_failure_smoke as smoke

AE_URL = "postgresql://nex_ae_user:test-secret@127.0.0.1:5432/nex_ae_test"
WC_URL = "postgresql://nex_wc_user:test-secret@127.0.0.1:5432/nex_wc_test"


@pytest.mark.skipif(
    not os.getenv(smoke.AE_DATABASE_ENV)
    or not os.getenv(smoke.WC_DATABASE_ENV),
    reason="AE and WC test database URLs are required for protected smoke",
)
def test_s8_actual_postgres_failure_recovery_and_zero_residue() -> None:
    evidence = smoke.run_p7_s8_postgres_failure_smoke(
        {**os.environ, smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["actual_remote_provider"] is False
    assert all(evidence["checks"].values())
    assert evidence["cleanup_counts"]["delegate_runtime_remaining"] == 0


def test_s8_smoke_is_protected_and_rejects_non_test_targets() -> None:
    assert smoke.run_p7_s8_postgres_failure_smoke({})["status"] == "SKIPPED"
    rejected = smoke.run_p7_s8_postgres_failure_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL.replace("nex_wc_test", "nex_wc_dev"),
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"


def test_s8_smoke_composes_current_migrations_and_redacted_evidence(
    monkeypatch,
) -> None:
    migrations = {
        "nex-ae-api": SimpleNamespace(
            planned=("2405_ae_claimed_planning_source",),
            applied=(),
            skipped=("2405_ae_claimed_planning_source",),
        ),
        "nex-wc": SimpleNamespace(
            planned=("1003_wc_work_item_authorization",),
            applied=(),
            skipped=("1003_wc_work_item_authorization",),
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
            "checks": {"resume_exactly_once_semantics": True},
            "row_counts": {"ae_resume_attempt": 2},
            "cleanup_counts": {"delegate_runtime_remaining": 0},
        },
    )

    evidence = smoke.run_p7_s8_postgres_failure_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL,
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["migration"]["ae_latest"] == "2405_ae_claimed_planning_source"
    assert evidence["migration"]["wc_latest"] == "1003_wc_work_item_authorization"
    assert "test-secret" not in str(evidence["redacted_database_urls"])
    assert "checks=3/3" in smoke.summary_line(evidence)


def test_s8_smoke_redacts_execution_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(AE_URL)),
    )
    evidence = smoke.run_p7_s8_postgres_failure_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL,
        }
    )

    assert evidence["failure_code"] == "execution_failed"
    assert "test-secret" not in evidence["detail"]
