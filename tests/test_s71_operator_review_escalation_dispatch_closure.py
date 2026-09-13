from __future__ import annotations

from pathlib import Path

import pytest

import run_s71_operator_review_escalation_dispatch_closure as closure


def test_s71_operator_review_escalation_dispatch_closure_passes_repo() -> None:
    evidence = closure.run_s71_operator_review_escalation_dispatch_closure()

    assert evidence["status"] == "PASS"
    assert evidence["slice_range"] == "0701-0711"
    assert evidence["boundary"] == "ag_owned_operator_review_escalation_outbound_dispatch"
    assert evidence["persisted_table"] == "ag_op_esc_dispatches"
    assert evidence["provider_execution"] == "mock_first_only"
    assert evidence["live_notification_delivery"] == "deferred"
    assert evidence["external_incident_sync"] == "deferred"
    assert evidence["dispatch_history"] == "service_operational_events_first"
    assert evidence["postgres_smoke"] == "test_db_protected"
    assert evidence["privacy_regression"] == "route_surface_regression"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == 0
    assert set(evidence["source_tables"]) == {
        "ag_op_cases",
        "ag_op_escalations",
        "ag_op_esc_dispatches",
        "service_operational_events",
    }


def test_s71_operator_review_escalation_dispatch_closure_summary() -> None:
    evidence = closure.run_s71_operator_review_escalation_dispatch_closure()
    summary = closure.summary_line(evidence)

    assert summary.startswith("s71_operator_review_escalation_dispatch_closure=pass")
    assert "slice_range=0701-0711" in summary
    assert "table=ag_op_esc_dispatches" in summary
    assert "provider=mock_first_only" in summary
    assert "smoke=test_db_protected" in summary
    assert "privacy=route_surface_regression" in summary


def test_s71_operator_review_escalation_dispatch_closure_reports_missing_file(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)

    evidence = closure.run_s71_operator_review_escalation_dispatch_closure(root)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "s71_closure_failed"
    assert evidence["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert "missing_files=" in closure.summary_line(evidence)


def test_s71_operator_review_escalation_dispatch_closure_reports_token_failure(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)
    for relative_path in closure.REQUIRED_FILES:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = closure.run_s71_operator_review_escalation_dispatch_closure(root)

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)


def test_s71_operator_review_escalation_dispatch_closure_main_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert closure.main(["--summary"]) == 0

    captured = capsys.readouterr()
    assert "s71_operator_review_escalation_dispatch_closure=pass" in captured.out


def test_s71_operator_review_escalation_dispatch_closure_main_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert closure.main([]) == 0

    captured = capsys.readouterr()
    assert (
        '"closure_schema_version": '
        '"s71_operator_review_escalation_dispatch_closure.v1"'
    ) in captured.out


def _minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root
