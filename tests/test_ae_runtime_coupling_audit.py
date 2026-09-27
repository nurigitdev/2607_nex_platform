from __future__ import annotations

from pathlib import Path

from nex_ae_api.runtime_coupling_audit import (
    CouplingFinding,
    ModuleBudget,
    build_ae_runtime_coupling_audit,
)
import run_ae_runtime_coupling_audit as runner


def test_repository_audit_freezes_ordered_refactoring() -> None:
    result = build_ae_runtime_coupling_audit()

    assert result["status"] == "PASS"
    assert result["issues"] == []
    assert result["summary"] == {
        "module_count": 4,
        "oversized_module_count": 4,
        "finding_count": 6,
        "refactor_required_count": 7,
        "good_boundary_count": 3,
        "authorization_helper_count": 6,
        "evidence_issue_count": 0,
    }
    assert result["ordered_refactoring"][0]["priority"] == "P0"
    assert result["refactoring_readiness"] == (
        "ORDERED_REFACTOR_REQUIRED_BEFORE_NEW_AE_FEATURES"
    )


def test_audit_fails_closed_when_sources_are_absent(tmp_path: Path) -> None:
    result = build_ae_runtime_coupling_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "ae_runtime_coupling_audit_failed"
    assert result["summary"]["evidence_issue_count"] == 10
    assert result["summary"]["authorization_helper_count"] == 0


def test_audit_detects_module_below_refactor_threshold(tmp_path: Path) -> None:
    source = tmp_path / "small.py"
    source.write_text("one\ntwo\n", encoding="utf-8")
    result = build_ae_runtime_coupling_audit(
        tmp_path,
        module_budgets=(ModuleBudget("small", "small.py", 3, "P1"),),
        findings=(),
    )

    assert result["status"] == "FAIL"
    assert result["modules"][0]["line_count"] == 2
    assert result["modules"][0]["over_budget"] is False


def test_custom_finding_can_preserve_a_good_boundary(tmp_path: Path) -> None:
    source = tmp_path / "port.py"
    source.write_text("class Port: pass\n", encoding="utf-8")
    result = build_ae_runtime_coupling_audit(
        tmp_path,
        module_budgets=(),
        findings=(
            CouplingFinding(
                "port", "port.py", "class Port", "GOOD_BOUNDARY", "LOW"
            ),
        ),
    )

    assert result["findings"][0]["evidence_present"] is True
    assert result["summary"]["good_boundary_count"] == 1
    assert result["status"] == "FAIL"


def test_summary_line_reports_checkpoint_counts() -> None:
    result = runner.run_ae_runtime_coupling_audit()

    assert runner.summary_line(result) == (
        "ae_runtime_coupling_audit=pass oversized=4 refactors=7 "
        "auth_helpers=6 good_boundaries=3 issues=0"
    )
    assert runner.summary_line({"status": "FAIL"}) == (
        "ae_runtime_coupling_audit=fail oversized=0 refactors=0 "
        "auth_helpers=0 good_boundaries=0 issues=0"
    )


def test_runner_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_ae_runtime_coupling_audit()
    monkeypatch.setattr(runner, "run_ae_runtime_coupling_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "runtime_coupling_audit=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_ae_runtime_coupling_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
