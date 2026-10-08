from __future__ import annotations

from pathlib import Path

import run_s147_model_serving_rollout_boundary as boundary


def test_repository_boundary_freezes_s147_scope() -> None:
    result = boundary.run_model_serving_rollout_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "check_count": 11,
        "capability_count": 3,
        "gap_count": 8,
        "slice_count": 10,
        "missing_path_count": 0,
    }
    assert result["decision"]["policy_model_independent"] is True
    assert result["decision"]["protected_acceptance_mutates_providers"] is False
    assert result["decision"]["next_slice"] == "1464"


def test_capability_inventory_is_exact_and_value_free() -> None:
    result = boundary.run_model_serving_rollout_boundary()

    assert [item["provider_capability"] for item in result["capabilities"]] == [
        item.capability for item in boundary.CAPABILITIES
    ]
    assert all(
        item["policy_key"] == "immutable_revision_identity"
        for item in result["capabilities"]
    )
    assert all("current_source" not in item for item in result["capabilities"])


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_model_serving_rollout_boundary(tmp_path)

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

    passing = boundary.run_model_serving_rollout_boundary()
    assert boundary.summary_line(passing) == (
        "model_serving_rollout_boundary=pass checks=11/11 capabilities=3 "
        "gaps=8 slices=10 next=1464"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": ["one"]}) == (
        "model_serving_rollout_boundary=fail issues=1"
    )
    monkeypatch.setattr(boundary, "run_model_serving_rollout_boundary", lambda: passing)
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        boundary,
        "run_model_serving_rollout_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
