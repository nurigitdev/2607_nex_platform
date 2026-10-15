from __future__ import annotations

import json
from pathlib import Path

import pytest
import run_p6_s7_postgres_smoke as smoke

ROOT = Path(__file__).resolve().parents[1]


def test_p6_s7_postgres_smoke_is_protected_by_default() -> None:
    evidence = smoke.run_p6_s7_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["actual_postgres"] is False
    assert smoke.SMOKE_ENV in evidence["skip_reason"]


@pytest.mark.parametrize(
    ("environment", "failure_code"),
    (
        ({smoke.SMOKE_ENV: "1"}, "database_url_missing"),
        (
            {
                smoke.SMOKE_ENV: "1",
                smoke.DATABASE_ENV: "postgresql://other:secret@127.0.0.1/other",
            },
            "target_not_allowed",
        ),
        (
            {
                smoke.SMOKE_ENV: "1",
                smoke.DATABASE_ENV: (
                    "postgresql+psycopg://nex_ae_user:secret@127.0.0.1/nex_ae_test"
                ),
            },
            "nsl_source_missing",
        ),
        (
            {
                smoke.SMOKE_ENV: "1",
                smoke.DATABASE_ENV: (
                    "postgresql+psycopg://nex_ae_user:secret@127.0.0.1/nex_ae_test"
                ),
                smoke.NSL_SOURCE_ENV: str(ROOT / "missing-nsl-source"),
            },
            "nsl_source_invalid",
        ),
    ),
)
def test_p6_s7_postgres_smoke_fails_closed_before_execution(
    environment: dict[str, str], failure_code: str
) -> None:
    evidence = smoke.run_p6_s7_postgres_smoke(environment)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == failure_code
    assert evidence["actual_postgres"] is False


def test_p6_s7_summary_is_bounded() -> None:
    evidence = {
        "status": "PASS",
        "actual_postgres": True,
        "checks": {"one": True, "two": True},
        "migration": {"planned_count": 43},
        "row_counts": {
            "ae_step_result": 2,
            "ae_agent_result": 1,
            "timeline_events": 30,
        },
        "cleanup_counts": {"s7_remaining": 0},
    }

    line = smoke.summary_line(evidence)

    assert "checks=2/2" in line
    assert "step_results=2" in line
    assert "agent_results=1" in line
    assert "remaining=0" in line
    assert "secret" not in json.dumps(evidence)


def test_p6_s7_actual_postgres_smoke() -> None:
    evidence = smoke.run_p6_s7_postgres_smoke()

    if evidence["status"] == "SKIPPED":
        pytest.skip(evidence["skip_reason"])
    assert evidence["status"] == "PASS", evidence
    assert evidence["actual_postgres"] is True
    assert all(evidence["checks"].values())
    assert evidence["cleanup_counts"]["s7_remaining"] == 0
