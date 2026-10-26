from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import run_p8_demo_s11_chairman_golden_journey as acceptance
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def test_s11_source_admission_is_protected_and_provider_scoped() -> None:
    result = acceptance.run_p8_demo_s11_chairman_golden_journey(
        {}, execute=False, root=ROOT
    )

    assert result["status"] == "SOURCE_ADMITTED"
    assert result["executed"] is False
    assert result["actual_postgres_required"] is True
    assert result["actual_remote_generation_required"] is True
    assert result["actual_playwright_required"] is True
    assert result["embedding_required"] is False
    assert result["reranking_required"] is False


def test_s11_source_admission_runs_in_a_standalone_process(tmp_path: Path) -> None:
    report = tmp_path / "source.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "scripts/deployment/run_p8_demo_s11_chairman_golden_journey.py"
            ),
            "--summary",
            "--report",
            str(report),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "source_admitted" in completed.stdout
    assert json.loads(report.read_text(encoding="utf-8"))["executed"] is False


def test_s11_execution_is_double_opt_in_and_contains_failure() -> None:
    calls: list[dict[str, str]] = []

    def runner(env, *, root):
        calls.append(dict(env))
        assert root == ROOT
        return {
            "status": "PASS",
            "actual_postgres": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
        }

    skipped = acceptance.run_p8_demo_s11_chairman_golden_journey(
        {}, execute=True, root=ROOT, protected_runner=runner
    )
    passed = acceptance.run_p8_demo_s11_chairman_golden_journey(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=runner,
    )
    failed = acceptance.run_p8_demo_s11_chairman_golden_journey(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("bounded failure")
        ),
    )

    assert skipped["status"] == "SOURCE_ADMITTED"
    assert passed["status"] == "PASS"
    assert passed["executed"] is True
    assert len(calls) == 1
    assert failed["status"] == "FAIL"
    assert failed["issues"] == ["bounded failure"]
    assert failed["secret_included"] is False


def test_s11_calibration_is_exact_for_all_three_semantic_stages() -> None:
    policies = json.loads(acceptance._semantic_calibration_json())

    assert [policy["semantic_stage"] for policy in policies] == [
        "INTENT",
        "CONTEXT",
        "PLAN",
    ]
    assert {policy["model_profile"] for policy in policies} == {
        "general-llm-default"
    }
    assert {policy["model_ref"] for policy in policies} == {"Qwen3.5-4B"}
    assert {policy["minimum_confidence"] for policy in policies} == {0.5}


def test_s11_public_browser_projection_strips_runtime_lineage() -> None:
    projected = acceptance._public_browser_evidence(
        {
            "status": "PASS",
            "checks": {"browser": True},
            "runtime": {"interaction_id": "private"},
        }
    )

    assert projected == {"status": "PASS", "checks": {"browser": True}}
    assert "provider=true" in acceptance.summary_line(
        {
            "status": "PASS",
            "executed": True,
            "actual_postgres": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
        }
    )


def test_s11_fixture_visibility_uses_canonical_eos_project_member_table() -> None:
    oa_engine = create_engine("sqlite+pysqlite:///:memory:")
    eos_engine = create_engine("sqlite+pysqlite:///:memory:")
    with oa_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE oa_local_credentials ("
                "tenant_id TEXT NOT NULL, status TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO oa_local_credentials (tenant_id, status) "
                "VALUES ('VO00', 'ACTIVE'), ('VO00', 'ACTIVE')"
            )
        )
    with eos_engine.begin() as connection:
        for table in (
            "eos_nvt_project",
            "eos_project",
            "eos_project_member",
            "eos_account",
            "eos_org_unit",
        ):
            connection.execute(
                text(f"CREATE TABLE {table} (tenant_id TEXT NOT NULL)")
            )
        connection.execute(text("INSERT INTO eos_nvt_project VALUES ('VO00')"))
        connection.execute(
            text("INSERT INTO eos_project VALUES ('VO00'), ('VO00')")
        )
        connection.execute(
            text("INSERT INTO eos_project_member VALUES ('VO00'), ('VO00')")
        )
        connection.execute(
            text("INSERT INTO eos_account VALUES ('VO00'), ('VO00')")
        )
        connection.execute(
            text(
                "INSERT INTO eos_org_unit VALUES "
                "('VO00'), ('VO00'), ('VO00'), ('VO00')"
            )
        )

    assert acceptance._fixture_visibility(
        {"nex-oa": oa_engine, "nex-eos": eos_engine}
    ) == {
        "active_employee_count": 2,
        "nvt_project_count": 1,
        "project_count": 2,
        "project_membership_count": 2,
        "account_count": 2,
        "organization_unit_count": 4,
    }
