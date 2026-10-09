from __future__ import annotations

from pathlib import Path

import run_s149_preproduction_acceptance_boundary as boundary


def test_repository_boundary_freezes_s149_scope() -> None:
    result = boundary.run_preproduction_acceptance_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "check_count": 12,
        "workload_class_count": 3,
        "fault_class_count": 5,
        "backlog_count": 5,
        "slice_count": 10,
        "missing_path_count": 0,
    }
    assert result["decision"]["distributed_failover_evidence"] == (
        "NOT_APPLICABLE_SINGLE_HOST"
    )
    assert result["decision"]["next_slice"] == "1484"


def test_boundary_lists_are_exact_and_private_values_absent() -> None:
    result = boundary.run_preproduction_acceptance_boundary()

    assert result["workload_classes"] == list(boundary.WORKLOAD_CLASSES)
    assert result["fault_classes"] == list(boundary.FAULT_CLASSES)
    assert result["backlog_capabilities"] == list(boundary.BACKLOG_CAPABILITIES)
    assert "endpoint" not in result["decision"]
    assert "credential" not in result["decision"]


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_preproduction_acceptance_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["missing_path_count"] == len(boundary.REQUIRED_PATHS)
    assert result["decision"]["next_slice"] == "blocked"
    assert result["issues"]


def test_helpers_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    assert boundary._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert boundary._read_text(source) == "value"

    passing = boundary.run_preproduction_acceptance_boundary()
    assert boundary.summary_line(passing) == (
        "s149_acceptance_boundary=pass checks=12/12 workloads=3 faults=5 "
        "backlog=5 slices=10 next=1484"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": ["one"]}) == (
        "s149_acceptance_boundary=fail issues=1"
    )
    monkeypatch.setattr(
        boundary,
        "run_preproduction_acceptance_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        boundary,
        "run_preproduction_acceptance_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1

