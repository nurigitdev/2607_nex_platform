from __future__ import annotations

import run_p6_s6_postgres_smoke as smoke


def test_smoke_is_opt_in_and_rejects_untrusted_targets() -> None:
    skipped = smoke.run_p6_s6_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False

    missing = smoke.run_p6_s6_postgres_smoke({smoke.SMOKE_ENV: "1"})
    assert missing["failure_code"] == "database_url_missing"

    rejected = smoke.run_p6_s6_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_dev"
            ),
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"

    missing_source = smoke.run_p6_s6_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_test"
            ),
        }
    )
    assert missing_source["failure_code"] == "nsl_source_missing"


def test_summary_is_bounded() -> None:
    assert smoke.summary_line(
        {
            "status": "PASS",
            "actual_postgres": True,
            "checks": {"one": True, "two": True},
            "migration": {"planned_count": 43},
            "row_counts": {"ae_step_result": 1, "timeline_events": 12},
            "cleanup_counts": {"s6_remaining": 0},
        }
    ) == (
        "p6_s6_postgres=pass actual_postgres=true checks=2/2 "
        "migrations=43 results=1 events=12 remaining=0"
    )
