from __future__ import annotations

import json
from pathlib import Path

import run_cx_document_intelligence_similarity_boundary_audit as audit


def test_repository_document_intelligence_boundary_audit_passes() -> None:
    result = audit.run_cx_document_intelligence_similarity_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "BOUNDARY_CURRENT"
    assert all(result["checks"].values())
    assert all(result["gap_checks"].values())
    assert result["summary"] == {
        "foundation_count": 8,
        "gap_count": 7,
        "open_gap_count": 0,
        "resolved_gap_count": 7,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert list(result["gap_states"].values()).count("OPEN") == 0
    assert result["gap_states"]["document_intelligence_observability_missing"] == (
        "RESOLVED"
    )
    assert len(result["implementation_gaps"]) == 7
    assert len(result["slice_plan"]) == 10
    assert result["next_slice"] == "0952"


def test_boundary_decision_freezes_summary_similarity_scope() -> None:
    decision = audit._boundary_decision()

    assert decision["summary_hard_limit_chars"] == 1000
    assert decision["summary_generation_model"] == (
        "Qwen3.5-122B-A10B-NVFP4"
    )
    assert decision["summary_embedding_model"] == "Qwen3-Embedding-4B"
    assert decision["summary_embedding_dimension"] == 2560
    assert decision["similarity_metric"] == "cosine"
    assert decision["cross_owner_behavior"] == (
        "not_found_or_excluded_without_disclosure"
    )
    assert decision["remote_provider_required_now"] is False
    assert decision["remote_provider_required_slice"] == "0959"


def test_boundary_audit_fails_closed_for_missing_repository(
    tmp_path: Path,
) -> None:
    result = audit.run_cx_document_intelligence_similarity_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["issue_count"] > 0
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["required_tokens_present"] is False


def test_boundary_audit_helpers(tmp_path: Path) -> None:
    tokens = [
        {"group": "ready", "present": True},
        {"group": "missing", "present": False},
    ]
    assert audit._group_present(tokens, "ready") is True
    assert audit._group_present(tokens, "missing") is False
    assert audit._group_present(tokens, "unknown") is False
    assert audit._read_text(tmp_path / "missing") == ""
    present = tmp_path / "present"
    present.write_text("value", encoding="utf-8")
    assert audit._read_text(present) == "value"


def test_boundary_audit_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = audit.run_cx_document_intelligence_similarity_boundary_audit()
    assert audit.summary_line(passing) == (
        "cx_document_intelligence_similarity_boundary=pass foundations=8 gaps=7 open=0 "
        "scope=owner_private_document_intelligence_summary_similarity "
        "remote_required_now=False issues=0"
    )
    assert "issues=0" in audit.summary_line({})

    monkeypatch.setattr(
        audit,
        "run_cx_document_intelligence_similarity_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_cx_document_intelligence_similarity_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
