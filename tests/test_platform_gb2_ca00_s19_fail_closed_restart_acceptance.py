from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import run_gb2_ca00_s19_fail_closed_restart_acceptance as acceptance
from nex_runtime.hidden_gap_acceptance import (
    HIDDEN_GAP_SCENARIOS,
    build_hidden_gap_evidence,
    build_hidden_gap_matrix,
    evaluate_hidden_gap_acceptance,
)

ROOT = Path(__file__).resolve().parents[1]


def _passing_components() -> dict:
    return {
        "ae": {
            "status": "PASS",
            "actual_postgres": True,
            "checks": {
                "worker_unavailable_preserved_pending_job": True,
                "canonical_worker_claimed_assignment": True,
                "restart_did_not_double_execute": True,
            },
            "cleanup_counts": {"component_remaining": 0},
        },
        "wc": {
            "status": "PASS",
            "actual_postgres": True,
            "checks": {
                "worker_unavailable_preserved_pending_event": True,
                "wrong_signed_trust_failed_closed": True,
                "restart_resumed_pending_delivery": True,
                "restart_did_not_double_deliver": True,
            },
            "cleanup_counts": {"wc_remaining": 0, "ae_remaining": 0},
        },
        "eos": {
            "status": "PASS",
            "actual_postgres": True,
            "checks": {
                "wrong_signed_trust_failed_closed": True,
                "restart_resumed_pending_publication": True,
                "restart_did_not_double_publish": True,
                "owner_business_operation_admission": True,
            },
            "cleanup_counts": {"eos_remaining": 0, "ae_remaining": 0},
        },
    }


def _runners(components: dict) -> dict:
    return {
        name: (lambda _env, result=result: result)
        for name, result in components.items()
    }


def _all_scenario_evidence() -> list[dict]:
    return acceptance._scenario_evidence(_passing_components())


def test_hidden_gap_matrix_and_evidence_are_canonical() -> None:
    matrix = build_hidden_gap_matrix()
    records = _all_scenario_evidence()
    result = evaluate_hidden_gap_acceptance({"evidence": records})

    assert matrix["slice"] == "GB2-CA00-S19"
    assert [item["scenario_id"] for item in matrix["scenarios"]] == [
        f"N{index:02d}" for index in range(1, 10)
    ]
    assert len(HIDDEN_GAP_SCENARIOS) == 9
    assert result["status"] == "PASS"
    assert result["summary"] == {
        "required_scenario_count": 9,
        "observed_scenario_count": 9,
        "passed_scenario_count": 9,
        "protected_scenario_count": 4,
    }
    assert all(result["checks"].values())
    assert result["secret_included"] is False


def test_hidden_gap_evidence_rejects_unknown_or_inexact_signals() -> None:
    with pytest.raises(ValueError, match="unknown hidden-gap scenario"):
        build_hidden_gap_evidence(
            "N10", checks={}, components=("platform",), protected_execution=False
        )

    failed = build_hidden_gap_evidence(
        "N04",
        checks={"required_dependency_missing": True},
        components=(),
        protected_execution=True,
    )

    assert failed["status"] == "FAIL"


def test_hidden_gap_evaluator_fails_for_missing_duplicate_tamper_and_secret() -> None:
    records = _all_scenario_evidence()
    records[0]["checks"]["pending_job_visible"] = False
    result = evaluate_hidden_gap_acceptance(
        {
            "evidence": [*records[:-1], records[0]],
            "database_url": "must-not-be-projected",
        }
    )

    assert result["status"] == "FAIL"
    assert result["checks"] == {
        "scenario_inventory_exact": False,
        "scenario_ids_unique": False,
        "all_scenarios_passed": False,
        "protected_restart_scenarios_present": True,
        "privacy_safe": False,
    }
    assert result["duplicate_scenario_ids"] == ["N01"]
    assert result["privacy_violations"] == ["$.database_url"]
    assert result["scenario_checks"]["N01"]["conditions"]["hash_valid"] is False


def test_hidden_gap_evaluator_ignores_malformed_record_shapes() -> None:
    result = evaluate_hidden_gap_acceptance(
        {"evidence": [None, "bad", {}, {"scenario_id": ""}]}
    )
    non_sequence = evaluate_hidden_gap_acceptance({"evidence": "bad"})

    assert result["status"] == "FAIL"
    assert result["summary"]["observed_scenario_count"] == 0
    assert result["evidence"] == []
    assert non_sequence["summary"]["observed_scenario_count"] == 0


def test_s19_source_admission_is_nonexecuting_and_fail_closed(tmp_path: Path) -> None:
    admitted = acceptance.run_gb2_ca00_s19_fail_closed_restart_acceptance(
        {}, root=ROOT
    )
    missing = acceptance.run_gb2_ca00_s19_fail_closed_restart_acceptance(
        {}, root=tmp_path
    )

    assert admitted["status"] == "SOURCE_ADMITTED"
    assert admitted["executed"] is False
    assert all(admitted["source_checks"].values())
    assert missing["status"] == "FAIL"
    assert missing["source_checks"]["component_sources_present"] is False


def test_s19_protected_execution_aggregates_component_evidence() -> None:
    result = acceptance.run_gb2_ca00_s19_fail_closed_restart_acceptance(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        component_runners=_runners(_passing_components()),
    )

    assert result["status"] == "PASS"
    assert result["executed"] is True
    assert result["actual_postgres"] is True
    assert result["cleanup_remaining"] == 0
    assert all(result["execution_checks"].values())
    assert set(result["component_statuses"]) == {"ae", "wc", "eos"}
    assert acceptance.summary_line(result) == (
        "gb2_ca00_s19_fail_closed_restart=pass executed=true "
        "scenarios=9/9 postgres=true remaining=0"
    )


def test_s19_component_failure_and_residue_fail_closed() -> None:
    components = _passing_components()
    components["wc"]["status"] = "FAIL"
    components["wc"]["checks"]["restart_resumed_pending_delivery"] = False
    components["wc"]["cleanup_counts"]["wc_remaining"] = 1

    result = acceptance.run_gb2_ca00_s19_fail_closed_restart_acceptance(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        component_runners=_runners(components),
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "gb2_s19_acceptance_failed"
    assert result["execution_checks"]["component_acceptance_passed"] is False
    assert result["execution_checks"]["scenario_matrix_passed"] is False
    assert result["execution_checks"]["zero_residue"] is False
    assert result["cleanup_remaining"] == 1


def test_s19_runner_exception_is_bounded_and_secret_free() -> None:
    result = acceptance.run_gb2_ca00_s19_fail_closed_restart_acceptance(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        component_runners={"ae": lambda _env: {}},
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "gb2_s19_execution_failed"
    assert result["detail"] == "KeyError"
    assert result["secret_included"] is False


def test_s19_helpers_and_cli_report(tmp_path: Path) -> None:
    assert acceptance._missing_dependency_blocked(
        "openbao.required", "OPENBAO", "platform"
    )
    assert acceptance._unknown_activator_rejected()
    assert acceptance._forbidden_fixture_detected()
    assert acceptance._remaining_count({"cleanup_counts": None}) == 0
    assert acceptance._mapping(None) == {}
    assert acceptance.summary_line({"status": "FAIL"}) == (
        "gb2_ca00_s19_fail_closed_restart=fail executed=false "
        "scenarios=0/9 postgres=false remaining=0"
    )

    report = tmp_path / "s19.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "scripts/smoke/"
                "run_gb2_ca00_s19_fail_closed_restart_acceptance.py"
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
    evidence = json.loads(report.read_text(encoding="utf-8"))
    assert evidence["status"] == "SOURCE_ADMITTED"
    assert evidence["secret_included"] is False


def test_s19_direct_report_main_and_non_rejecting_activator_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class NonRejectingRegistry:
        def resolve(self, *_args, **_kwargs):
            return object()

    monkeypatch.setattr(acceptance, "DomainIntentActivatorRegistry", NonRejectingRegistry)
    assert acceptance._unknown_activator_rejected() is False

    report = tmp_path / "direct.json"
    assert acceptance.main(["--summary", "--report", str(report)]) == 0
    assert "source_admitted" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "SOURCE_ADMITTED"

    monkeypatch.setattr(
        acceptance,
        "run_gb2_ca00_s19_fail_closed_restart_acceptance",
        lambda *_args, **_kwargs: {"status": "FAIL"},
    )
    assert acceptance.main(["--report", str(report)]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


@pytest.mark.skipif(
    os.environ.get(acceptance.EXECUTION_ENV) != "1",
    reason=f"{acceptance.EXECUTION_ENV}=1 is required for protected PostgreSQL smoke",
)
def test_actual_postgres_fail_closed_restart_acceptance() -> None:
    result = acceptance.run_gb2_ca00_s19_fail_closed_restart_acceptance(
        os.environ, execute=True
    )

    assert result["status"] == "PASS", result
    assert result["actual_postgres"] is True
    assert result["cleanup_remaining"] == 0
