from __future__ import annotations

from pathlib import Path

import run_s150_production_release_boundary as boundary


def test_repository_boundary_freezes_single_host_v1() -> None:
    result = boundary.run_production_release_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "required_path_count": 8,
        "check_count": 12,
        "mandatory_gate_count": 10,
        "backlog_count": 5,
        "slice_count": 10,
        "missing_path_count": 0,
    }
    assert result["decision"] == {
        "v1_topology": "single_host_docker_compose",
        "distributed_capabilities": "NOT_APPLICABLE_SINGLE_HOST",
        "external_notification": "EXTERNAL_NOT_ACTIVATED",
        "release_decision": "PENDING_EVALUATION",
        "production_deployment_approved": False,
        "next_slice": "1496",
    }


def test_boundary_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = boundary.run_production_release_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["required_path_count"] == 0
    assert result["summary"]["missing_path_count"] == 8
    assert result["decision"]["next_slice"] == "blocked"
    assert len(result["issues"]) == 20


def test_read_and_summary_helpers(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("content", encoding="utf-8")
    assert boundary._read_text(source) == "content"
    assert boundary._read_text(tmp_path / "missing.md") == ""

    passing = {
        "status": "PASS",
        "summary": {
            "check_count": 12,
            "mandatory_gate_count": 10,
            "backlog_count": 5,
            "slice_count": 10,
        },
        "decision": {"next_slice": "1496"},
    }
    assert boundary.summary_line(passing) == (
        "s150_release_boundary=pass checks=12/12 gates=10 backlog=5 "
        "slices=10 next=1496"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "s150_release_boundary=fail issues=1"
    )


def test_main_success_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {},
        "decision": {},
    }
    monkeypatch.setattr(boundary, "run_production_release_boundary", lambda: passing)
    assert boundary.main(["--summary"]) == 0
    assert "s150_release_boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        boundary,
        "run_production_release_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
