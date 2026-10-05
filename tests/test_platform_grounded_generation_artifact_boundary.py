from __future__ import annotations

import json
from pathlib import Path

import run_platform_grounded_generation_artifact_boundary as boundary


def test_repository_boundary_freezes_s137_gaps() -> None:
    result = boundary.run_platform_grounded_generation_artifact_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["gap_states"] == {
        "restart_safe_retrieval_materialization": "OPEN",
        "cx_generation_runtime_composition": "OPEN",
        "citation_repair_handoff_binding": "OPEN",
        "ae_generated_response_lineage": "OPEN",
        "artifact_render_lifecycle_connection": "OPEN",
        "preview_download_restart_recovery": "OPEN",
        "contract_operations_deterministic_e2e": "OPEN",
        "protected_postgres_live_generation_e2e": "OPEN",
    }
    assert result["summary"] == {
        "required_path_count": 12,
        "evidence_token_count": 10,
        "integration_gap_count": 8,
        "open_gap_count": 8,
        "missing_path_count": 0,
        "missing_token_count": 0,
    }
    assert result["decision"] == {
        "new_table_required": False,
        "remote_generation_provider_required": False,
        "protected_live_deferred_to_slice": "1370",
        "next_slice": "1363",
    }


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_platform_grounded_generation_artifact_boundary(tmp_path)

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

    passing = boundary.run_platform_grounded_generation_artifact_boundary()
    assert boundary.summary_line(passing) == (
        "platform_grounded_generation_artifact_boundary=pass "
        "paths=12/12 tokens=10/10 gaps=8/8 next=1363"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_grounded_generation_artifact_boundary=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = boundary.run_platform_grounded_generation_artifact_boundary()
    monkeypatch.setattr(
        boundary,
        "run_platform_grounded_generation_artifact_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "next=1363" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        boundary,
        "run_platform_grounded_generation_artifact_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
