from __future__ import annotations

from pathlib import Path

import run_platform_authenticated_document_ingestion_boundary as boundary


def test_repository_boundary_passes_and_freezes_s135() -> None:
    result = boundary.run_platform_authenticated_document_ingestion_boundary()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["findings"] == {
        "existing_component_count": 8,
        "current_gap_count": 6,
        "durable_stage_count": 6,
        "denial_scenario_count": 4,
    }
    assert result["decision"]["oa_claims_are_owner_authority"] is True
    assert result["decision"]["ae_persists_source_bytes"] is False
    assert result["decision"]["shared_database_allowed"] is False
    assert result["decision"]["remote_embedding_provider_required"] is False
    assert result["decision"]["next_slice"] == "1343"


def test_boundary_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = boundary.run_platform_authenticated_document_ingestion_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"]
    assert result["checks"]["required_paths_present"] is False


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.md"
    source.write_text("content", encoding="utf-8")
    assert boundary._read_text(source) == "content"
    assert boundary._read_text(tmp_path / "missing.md") == ""

    passing = {
        "status": "PASS",
        "findings": {
            "existing_component_count": 8,
            "durable_stage_count": 6,
            "current_gap_count": 6,
        },
        "decision": {"next_slice": "1343"},
    }
    assert boundary.summary_line(passing) == (
        "platform_authenticated_document_ingestion_boundary=pass "
        "components=8 stages=6 gaps=6 next=1343"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_authenticated_document_ingestion_boundary=fail issues=1"
    )

    monkeypatch.setattr(
        boundary,
        "run_platform_authenticated_document_ingestion_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "next=1343" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        boundary,
        "run_platform_authenticated_document_ingestion_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
