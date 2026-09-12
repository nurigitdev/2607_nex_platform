from __future__ import annotations

from pathlib import Path

import pytest

import run_s69_operator_review_case_sla_escalation_closure as closure


def test_s69_operator_review_case_sla_escalation_closure_passes_repo() -> None:
    evidence = closure.run_s69_operator_review_case_sla_escalation_closure()

    assert evidence["status"] == "PASS"
    assert evidence["slice_range"] == "0681-0690"
    assert evidence["boundary"] == "ag_owned_operator_review_case_sla_escalation"
    assert evidence["sla_escalation_storage"] == "read_model_only_not_persisted"
    assert evidence["notification_delivery"] == "deferred"
    assert evidence["external_incident_sync"] == "deferred"
    assert evidence["postgres_smoke"] == "test_db_protected"
    assert evidence["privacy_regression"] == "route_surface_regression"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == 0
    assert set(evidence["source_tables"]) == {
        "ag_op_cases",
        "service_operational_events",
    }


def test_s69_operator_review_case_sla_escalation_closure_summary() -> None:
    evidence = closure.run_s69_operator_review_case_sla_escalation_closure()
    summary = closure.summary_line(evidence)

    assert summary.startswith(
        "s69_operator_review_case_sla_escalation_closure=pass"
    )
    assert "slice_range=0681-0690" in summary
    assert "storage=read_model_only_not_persisted" in summary
    assert "privacy=route_surface_regression" in summary


def test_s69_operator_review_case_sla_escalation_closure_reports_missing_file(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)

    evidence = closure.run_s69_operator_review_case_sla_escalation_closure(root)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "s69_closure_failed"
    assert evidence["summary"]["missing_file_count"] > 0
    assert "missing_files=" in closure.summary_line(evidence)


def test_s69_operator_review_case_sla_escalation_closure_reports_token_failure(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)
    for relative_path in closure.REQUIRED_FILES:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = closure.run_s69_operator_review_case_sla_escalation_closure(root)

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)


def test_s69_operator_review_case_sla_escalation_closure_main(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert closure.main(["--summary"]) == 0

    captured = capsys.readouterr()
    assert "s69_operator_review_case_sla_escalation_closure=pass" in captured.out


def _minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root
