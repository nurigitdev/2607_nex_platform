from __future__ import annotations

from pathlib import Path

from nex_mo.runtime_coupling_audit import (
    COUPLING_FINDINGS,
    MODULE_BUDGETS,
    CouplingFinding,
    ModuleBudget,
    _inspect_finding,
    _inspect_module,
    build_mo_runtime_coupling_audit,
)
import run_mo_runtime_coupling_audit as runner


def test_repository_runtime_coupling_is_classified() -> None:
    result = build_mo_runtime_coupling_audit()

    assert result["status"] == "PASS"
    assert result["refactoring_readiness"] == (
        "ORDERED_REFACTOR_REQUIRED_BEFORE_NEW_MO_FEATURES"
    )
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "module_count": 2,
        "oversized_module_count": 2,
        "finding_count": 7,
        "refactor_required_count": 5,
        "good_boundary_count": 4,
        "evidence_issue_count": 0,
    }
    assert [item["priority"] for item in result["ordered_refactoring"]] == [
        "P0",
        "P1",
        "P1",
        "P2",
    ]


def test_audit_fails_closed_for_missing_inventory_and_evidence(tmp_path: Path) -> None:
    modules = (ModuleBudget("missing", "missing.py", 1, "P0"),)
    findings = (
        CouplingFinding(
            "missing_finding",
            "missing.py",
            "token",
            "GOOD_BOUNDARY",
            "LOW",
        ),
    )

    result = build_mo_runtime_coupling_audit(
        tmp_path,
        module_budgets=modules,
        findings=findings,
    )

    assert result["status"] == "FAIL"
    assert result["refactoring_readiness"] == "BLOCKED"
    assert result["checks"]["module_inventory_complete"] is False
    assert result["checks"]["oversized_modules_classified"] is False
    assert result["checks"]["bidirectional_coupling_classified"] is False
    assert result["checks"]["good_boundaries_preserved"] is False
    assert result["checks"]["evidence_present"] is False
    assert len(result["issues"]) == 2


def test_inspection_helpers_cover_present_and_missing(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text("first\nexpected token\nthird\n", encoding="utf-8")
    module = ModuleBudget("module", "module.py", 3, "P1")
    finding = CouplingFinding(
        "finding", "module.py", "expected token", "GOOD_BOUNDARY", "LOW"
    )

    assert _inspect_module(tmp_path, module)["over_budget"] is True
    assert _inspect_finding(tmp_path, finding)["evidence_present"] is True
    assert _inspect_module(
        tmp_path, ModuleBudget("missing", "missing.py", 1, "P0")
    )["evidence_present"] is False
    assert _inspect_finding(
        tmp_path,
        CouplingFinding("missing", "module.py", "absent", "BAD", "HIGH"),
    )["evidence_present"] is False
    assert len(MODULE_BUDGETS) == 2
    assert len(COUPLING_FINDINGS) == 7


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_coupling_audit()

    assert "coupling_audit=pass" in runner.summary_line(passing)
    assert "refactors=5" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_runtime_coupling_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "good_boundaries=4" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_runtime_coupling_audit", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "coupling_audit=fail" in capsys.readouterr().out
