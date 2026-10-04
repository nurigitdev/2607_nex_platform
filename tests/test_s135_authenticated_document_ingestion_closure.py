from __future__ import annotations

from pathlib import Path

import run_s135_authenticated_document_ingestion_closure as closure


def test_repository_closure_passes_and_hands_off_to_s136() -> None:
    result = closure.run_s135_authenticated_document_ingestion_closure()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["evidence_statuses"] == {
        "boundary": "PASS",
        "owner_policy": "PASS",
        "handoff": "PASS",
        "admission": "PASS",
        "hydration": "PASS",
        "vector": "PASS",
        "progress": "PASS",
        "restart": "PASS",
        "postgres": "SKIPPED",
    }
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 8,
        "protected_skip_count": 1,
        "check_count": 15,
        "passed_check_count": 15,
        "durable_stage_count": 6,
        "restart_generation_count": 2,
        "database_count": 5,
        "contract_artifact_count": 3,
    }
    assert result["decision"]["completion_signal_met"] is True
    assert result["decision"]["closure_database_or_provider_mutation_performed"] is False
    assert result["decision"]["remote_provider_required"] is False
    assert result["decision"]["s136_live_embedding_and_reranker_required"] is True
    assert result["decision"]["next_requirement"] == "S136"


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s135_authenticated_document_ingestion_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failed_checks"]
    assert result["summary"]["evidence_count"] == 0
    assert result["decision"]["next_requirement"] == "blocked"


def test_helpers_cover_mapping_text_and_noncanonical_root(tmp_path: Path) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._run_evidence(tmp_path) == {}

    source = tmp_path / "source.md"
    source.write_text("line one\n  line two", encoding="utf-8")
    assert closure._read_text(source) == "line one\n  line two"
    assert closure._normalized_text(source) == "line one line two"
    assert closure._read_text(tmp_path / "missing.md") == ""


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_evidence_count": 8,
            "protected_skip_count": 1,
            "evidence_count": 9,
            "passed_check_count": 15,
            "check_count": 15,
            "durable_stage_count": 6,
        },
        "decision": {"next_requirement": "S136"},
    }
    assert closure.summary_line(passing) == (
        "s135_authenticated_document_ingestion_closure=pass evidence=8+1/9 "
        "checks=15/15 stages=6 next=S136"
    )
    assert closure.summary_line(
        {"status": "FAIL", "failed_checks": ["a"]}
    ) == "s135_authenticated_document_ingestion_closure=fail checks=1"

    monkeypatch.setattr(
        closure,
        "run_s135_authenticated_document_ingestion_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S136" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s135_authenticated_document_ingestion_closure",
        lambda: {"status": "FAIL", "failed_checks": []},
    )
    assert closure.main([]) == 1
