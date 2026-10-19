from __future__ import annotations

from types import SimpleNamespace

import run_p7_s7_postgres_live_e2e as smoke

AE_URL = "postgresql://nex_ae_user:secret@127.0.0.1:5432/nex_ae_test"
WC_URL = "postgresql://nex_wc_user:secret@127.0.0.1:5432/nex_wc_test"


def test_p7_s7_live_e2e_is_protected_and_test_database_scoped() -> None:
    assert smoke.run_p7_s7_postgres_live_e2e({})["status"] == "SKIPPED"

    rejected = smoke.run_p7_s7_postgres_live_e2e(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL.replace("nex_ae_test", "nex_ae_dev"),
            smoke.WC_DATABASE_ENV: WC_URL,
            smoke.NSL_SOURCE_ENV: "/tmp",
        }
    )
    assert rejected["status"] == "FAIL"
    assert rejected["failure_code"] == "target_not_allowed"


def test_p7_s7_live_e2e_composes_migrations_and_redacted_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(smoke.p65_s7, "_missing_provider_configuration", lambda _env: [])
    monkeypatch.setattr(
        smoke.p6_ca02_s3, "_installed_package_evidence", lambda *_args: {}
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service, **_kwargs: SimpleNamespace(
            planned=(
                "2405_ae_claimed_planning_source"
                if service == "nex-ae-api"
                else "1003_wc_work_item_authorization",
            ),
            applied=(),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_live_e2e",
        lambda **_kwargs: {
            "checks": {
                "claimed_execution_admitted": True,
                "wc_result_exact_ack": True,
            },
            "provider": {
                "semantic_stages": ["INTENT", "CONTEXT", "PLAN"]
            },
        },
    )
    evidence = smoke.run_p7_s7_postgres_live_e2e(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL,
            smoke.NSL_SOURCE_ENV: "/tmp",
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["actual_remote_provider"] is True
    assert evidence["checks"]["ae_migration_current"] is True
    assert evidence["checks"]["wc_migration_current"] is True
    assert "secret" not in str(evidence["redacted_database_urls"])
    assert "checks=4/4" in smoke.summary_line(evidence)


def test_p7_s7_live_e2e_reports_missing_nsl_and_provider_configuration(
    monkeypatch,
) -> None:
    missing_nsl = smoke.run_p7_s7_postgres_live_e2e(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL,
        }
    )
    assert missing_nsl["failure_code"] == "nsl_source_missing"

    monkeypatch.setattr(
        smoke.p65_s7,
        "_missing_provider_configuration",
        lambda _env: ["NEX_MO_VLLM_API_KEY"],
    )
    missing_provider = smoke.run_p7_s7_postgres_live_e2e(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: AE_URL,
            smoke.WC_DATABASE_ENV: WC_URL,
            smoke.NSL_SOURCE_ENV: "/tmp",
        }
    )
    assert missing_provider["failure_code"] == "provider_configuration_missing"
