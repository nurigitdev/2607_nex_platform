from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p8_s53_approval_resume_postgres as smoke


def test_p8_s53_gate_is_explicitly_protected() -> None:
    assert smoke.run_p8_s53_approval_resume_postgres({}, execute=False)[
        "status"
    ] == "SKIPPED"
    assert smoke.run_p8_s53_approval_resume_postgres({}, execute=True)[
        "status"
    ] == "SKIPPED"


@pytest.mark.parametrize(
    ("validation", "status", "gate_passed"),
    (
        ("VALID", "APPROVED", True),
        ("VALID", "REJECTED", False),
        ("EXPIRED", "EXPIRED", False),
    ),
)
def test_scenario_outcome_requires_consumed_checkpoint_and_done_job(
    validation: str, status: str, gate_passed: bool
) -> None:
    scenario = {
        "resume": {
            "approval_validation": validation,
            "approval_status": status,
            "approval_gate_passed": gate_passed,
            "claim_consumed": True,
            "checkpoint_consumed": True,
            "runtime_job_state": "DONE",
        }
    }

    assert smoke._scenario_matches(scenario, validation, status, gate_passed)
    scenario["resume"]["checkpoint_consumed"] = False
    assert not smoke._scenario_matches(scenario, validation, status, gate_passed)


def test_database_target_and_timestamp_guards_fail_closed() -> None:
    smoke._require_database_target(
        "postgresql+psycopg://nex_ae_user:secret@localhost/nex_ae_test",
        role="nex_ae_user",
        database="nex_ae_test",
        label="AE",
    )
    with pytest.raises(smoke.P8S53SmokeError, match="must target"):
        smoke._require_database_target(
            "postgresql+psycopg://other:secret@localhost/nex_ae_test",
            role="nex_ae_user",
            database="nex_ae_test",
            label="AE",
        )
    with pytest.raises(smoke.P8S53SmokeError, match="timezone"):
        smoke._instant("2026-10-22T12:00:00")


def test_failure_evidence_redacts_database_secret(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    result = smoke.run_p8_s53_approval_resume_postgres(
        {
            smoke.SMOKE_ENV: "1",
            smoke.AE_DATABASE_ENV: (
                "postgresql+psycopg://nex_ae_user:private@localhost/wrong"
            ),
            smoke.WC_DATABASE_ENV: (
                "postgresql+psycopg://nex_wc_user:private@localhost/nex_wc_test"
            ),
        },
        execute=True,
        report_path=report,
    )

    assert result["status"] == "FAIL"
    assert "private" not in json.dumps(result)
    assert json.loads(report.read_text(encoding="utf-8")) == result


def test_summary_is_bounded() -> None:
    line = smoke.summary_line(
        {
            "status": "PASS",
            "checks_passed": 10,
            "checks_total": 10,
            "decision": {"p8_4_closed": True, "eos_mutation_count": 0},
        }
    )

    assert "checks=10/10" in line
    assert "p8_4_closed=true" in line
    assert "eos_mutations=0" in line


@pytest.mark.skipif(
    os.getenv(smoke.SMOKE_ENV) != "1"
    or not os.getenv(smoke.AE_DATABASE_ENV)
    or not os.getenv(smoke.WC_DATABASE_ENV),
    reason="Protected P8-S53 PostgreSQL gate is disabled",
)
def test_actual_postgres_and_admitted_nsl_v02_approval_resume_gate(
    tmp_path: Path,
) -> None:
    result = smoke.run_p8_s53_approval_resume_postgres(
        execute=True,
        report_path=tmp_path / "p8-s53.json",
    )

    assert result["status"] == "PASS", result
    assert result["actual_postgres"] is True
    assert result["decision"] == {
        "p8_4_closed": True,
        "eos_write_enabled": False,
        "eos_mutation_count": 0,
    }
