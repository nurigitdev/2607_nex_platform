from __future__ import annotations

from pathlib import Path

from nex_mo.runtime_hardening_boundary import (
    PERSISTENCE_DECISION,
    REFACTORING_BOUNDARIES,
    RefactoringBoundary,
    _inspect_boundary,
    build_mo_runtime_hardening_boundary,
)
import run_mo_runtime_hardening_boundary as runner


def test_repository_runtime_hardening_boundary_is_frozen() -> None:
    result = build_mo_runtime_hardening_boundary()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "refactoring_boundary_count": 5,
        "durable_candidate_count": 4,
        "external_metrics_candidate_count": 2,
        "forbidden_persistence_count": 6,
        "evidence_issue_count": 0,
    }
    assert result["persistence_decision"]["table_creation_slice"] is None
    assert result["next_slice"] == "1113"


def test_boundary_fails_closed_for_missing_and_duplicate_evidence(
    tmp_path: Path,
) -> None:
    boundaries = (
        RefactoringBoundary("one", "missing.py", "token", "target", "1114"),
        RefactoringBoundary("two", "missing.py", "token", "target", "1113"),
    )

    result = build_mo_runtime_hardening_boundary(tmp_path, boundaries=boundaries)

    assert result["status"] == "FAIL"
    assert result["checks"]["refactoring_boundaries_complete"] is False
    assert result["checks"]["source_evidence_present"] is False
    assert result["checks"]["target_modules_unique"] is False
    assert result["checks"]["slice_order_is_monotonic"] is False
    assert len(result["issues"]) == 2


def test_inspection_and_persistence_guardrails(tmp_path: Path) -> None:
    path = tmp_path / "source.py"
    path.write_text("expected token\n", encoding="utf-8")
    boundary = RefactoringBoundary("id", "source.py", "expected token", "target", "1")

    assert _inspect_boundary(tmp_path, boundary)["evidence_present"] is True
    assert len(REFACTORING_BOUNDARIES) == 5
    assert "provider_api_key" in PERSISTENCE_DECISION["forbidden_persistence"]


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_hardening_boundary()

    assert "hardening_boundary=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_runtime_hardening_boundary", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "boundaries=5" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_runtime_hardening_boundary", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "hardening_boundary=fail" in capsys.readouterr().out
