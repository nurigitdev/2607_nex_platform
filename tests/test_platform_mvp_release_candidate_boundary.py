from __future__ import annotations

import json
from pathlib import Path

import run_platform_mvp_release_candidate_boundary as boundary


def test_repository_boundary_freezes_s140_release_matrix() -> None:
    result = boundary.run_platform_mvp_release_candidate_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["gap_states"] == {
        "typed_rc_evidence_gate_matrix": "OPEN",
        "named_generation_golden_scenarios": "OPEN",
        "protected_profile_admission": "OPEN",
        "five_database_restart_acceptance": "OPEN",
        "live_provider_calibrated_acceptance": "OPEN",
        "browser_trace_operations_acceptance": "OPEN",
        "failure_privacy_residue_deferrals": "OPEN",
        "protected_release_candidate_acceptance": "OPEN",
    }
    assert result["scenario_ids"] == [
        f"GEN-E2E-{index:03d}" for index in range(1, 11)
    ]
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "evidence_token_count": len(boundary.TOKENS),
        "release_gap_count": 8,
        "open_gap_count": 8,
        "scenario_count": 10,
        "database_count": 5,
        "provider_capability_count": 3,
        "viewport_count": 2,
        "missing_path_count": 0,
        "missing_token_count": 0,
    }
    assert result["decision"] == {
        "new_table_required": False,
        "database_or_provider_execution_performed": False,
        "actual_protected_execution_deferred_to_slice": "1400",
        "production_deployment_approval_claimed": False,
        "next_slice": "1393",
    }


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_platform_mvp_release_candidate_boundary(tmp_path)

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

    passing = boundary.run_platform_mvp_release_candidate_boundary()
    assert boundary.summary_line(passing) == (
        "platform_mvp_release_candidate_boundary=pass "
        f"paths={len(boundary.REQUIRED_PATHS)}/{len(boundary.REQUIRED_PATHS)} "
        f"tokens={len(boundary.TOKENS)}/{len(boundary.TOKENS)} "
        "gaps=8/8 scenarios=10 next=1393"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_mvp_release_candidate_boundary=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = boundary.run_platform_mvp_release_candidate_boundary()
    monkeypatch.setattr(
        boundary,
        "run_platform_mvp_release_candidate_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "next=1393" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        boundary,
        "run_platform_mvp_release_candidate_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
