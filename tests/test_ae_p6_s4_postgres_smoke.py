from __future__ import annotations

import run_p6_s4_postgres_smoke as smoke


def test_smoke_is_opt_in_and_rejects_wrong_database_target() -> None:
    skipped = smoke.run_p6_s4_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False

    missing = smoke.run_p6_s4_postgres_smoke({"NEX_AE_P6_S4_POSTGRES_SMOKE": "1"})
    assert missing["failure_code"] == "database_url_missing"

    rejected = smoke.run_p6_s4_postgres_smoke(
        {
            "NEX_AE_P6_S4_POSTGRES_SMOKE": "1",
            "NEX_AE_TEST_DATABASE_URL": (
                "postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_dev"
            ),
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"


def test_summary_is_bounded() -> None:
    assert smoke.summary_line(
        {
            "status": "PASS",
            "actual_postgres": True,
            "checks": {"one": True, "two": True},
            "migration": {"planned_count": 42},
            "row_counts": {"local_skill_steps": 1},
            "cleanup_counts": {"remaining": 0},
        }
    ) == (
        "p6_s4_postgres=pass actual_postgres=true checks=2/2 "
        "migrations=42 local_steps=1 remaining=0"
    )
