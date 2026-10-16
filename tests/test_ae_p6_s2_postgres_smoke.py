from __future__ import annotations

import run_p6_s2_postgres_smoke as smoke


def test_smoke_is_opt_in_and_rejects_wrong_database_target() -> None:
    skipped = smoke.run_p6_s2_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False

    missing = smoke.run_p6_s2_postgres_smoke({"NEX_AE_P6_S2_POSTGRES_SMOKE": "1"})
    assert missing["failure_code"] == "database_url_missing"

    rejected = smoke.run_p6_s2_postgres_smoke(
        {
            "NEX_AE_P6_S2_POSTGRES_SMOKE": "1",
            "NEX_AE_TEST_DATABASE_URL": (
                "postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_dev"
            ),
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"


def test_summary_and_redaction_are_bounded() -> None:
    assert smoke.summary_line(
        {
            "status": "PASS",
            "actual_postgres": True,
            "checks": {"one": True, "two": True},
            "row_counts": {"artifacts": 1},
            "cleanup_counts": {"remaining": 0},
        }
    ) == (
        "p6_s2_postgres=pass actual_postgres=true checks=2/2 "
        "artifacts=1 remaining=0"
    )
    url = "postgresql://nex_ae_user:secret@127.0.0.1:5432/nex_ae_test"
    assert smoke._target_url_allowed(url) is True
    assert "secret" not in smoke._redact_detail(
        f"failed {url} secret", database_url=url
    )
