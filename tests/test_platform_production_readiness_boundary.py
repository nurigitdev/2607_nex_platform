from __future__ import annotations

from pathlib import Path

import run_platform_production_readiness_boundary as boundary


def test_repository_boundary_freezes_s141_production_reaudit() -> None:
    result = boundary.run_platform_production_readiness_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "evidence_token_count": len(boundary.TOKENS),
        "deferral_count": 9,
        "audit_count": 9,
        "missing_path_count": 0,
        "missing_token_count": 0,
    }
    assert len(result["deferral_ids"]) == 9
    assert len(result["audit_surfaces"]) == 8
    assert result["decision"] == {
        "repository_state_is_primary_evidence": True,
        "production_connection_required": False,
        "production_deployment_approved": False,
        "new_table_required": False,
        "next_slice": "1403",
        "next_requirement_after_closure": "S142",
    }


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_platform_production_readiness_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["issues"]
    assert result["summary"]["missing_path_count"] == len(boundary.REQUIRED_PATHS)
    assert result["summary"]["missing_token_count"] == len(boundary.TOKENS)
    assert result["decision"]["next_slice"] == "blocked"


def test_text_helpers_and_summary_branches(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("one\n  two", encoding="utf-8")
    assert boundary._read_text(source) == "one\n  two"
    assert boundary._normalized_text(source) == "one two"
    assert boundary._read_text(tmp_path / "missing.md") == ""

    passing = boundary.run_platform_production_readiness_boundary()
    assert boundary.summary_line(passing) == (
        "platform_production_readiness_boundary=pass "
        f"paths={len(boundary.REQUIRED_PATHS)}/{len(boundary.REQUIRED_PATHS)} "
        f"tokens={len(boundary.TOKENS)}/{len(boundary.TOKENS)} "
        "deferrals=9 audits=9 next=1403"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_production_readiness_boundary=fail issues=1"
    )


def test_main_outputs_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = boundary.run_platform_production_readiness_boundary()
    monkeypatch.setattr(
        boundary, "run_platform_production_readiness_boundary", lambda: passing
    )
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        boundary,
        "run_platform_production_readiness_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
