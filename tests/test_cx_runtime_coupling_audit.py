from __future__ import annotations

from pathlib import Path

from nex_cx.runtime_coupling_audit import build_cx_runtime_coupling_audit
import run_cx_runtime_coupling_audit as runner


def test_repository_runtime_coupling_audit_freezes_targeted_refactor() -> None:
    result = build_cx_runtime_coupling_audit()

    assert result["status"] == "PASS"
    assert result["issues"] == []
    assert result["summary"] == {
        "finding_count": 8,
        "refactor_required_count": 5,
        "accepted_for_now_count": 1,
        "good_boundary_count": 2,
        "duplicated_authorization_helper_count": 12,
        "evidence_gap_count": 0,
    }
    assert result["refactoring_readiness"] == (
        "TARGETED_REFACTOR_REQUIRED_BEFORE_S92_FEATURES"
    )
    assert len(result["ordered_refactoring"]) == 5
    assert result["target_runtime_composition"]["name"] == (
        "CxRuntimeDependencies"
    )


def test_runtime_coupling_audit_fails_closed_without_sources(
    tmp_path: Path,
) -> None:
    result = build_cx_runtime_coupling_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "cx_runtime_coupling_audit_failed"
    assert result["summary"]["evidence_gap_count"] == 8
    assert result["summary"]["duplicated_authorization_helper_count"] == 0


def test_summary_line_reports_coupling_counts() -> None:
    result = runner.run_cx_runtime_coupling_audit()

    assert runner.summary_line(result) == (
        "cx_runtime_coupling_audit=pass refactor_required=5 "
        "good_boundaries=2 auth_helpers=12 evidence_gaps=0"
    )
    assert runner.summary_line({"status": "FAIL"}) == (
        "cx_runtime_coupling_audit=fail refactor_required=0 "
        "good_boundaries=0 auth_helpers=0 evidence_gaps=0"
    )


def test_runner_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_cx_runtime_coupling_audit()
    monkeypatch.setattr(
        runner,
        "run_cx_runtime_coupling_audit",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "coupling_audit=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_cx_runtime_coupling_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
