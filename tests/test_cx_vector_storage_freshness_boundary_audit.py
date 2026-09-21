from __future__ import annotations

import json
from pathlib import Path

import run_cx_vector_storage_freshness_boundary_audit as audit


def test_repository_vector_storage_freshness_boundary_audit_passes() -> None:
    result = audit.run_cx_vector_storage_freshness_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert all(result["gap_checks"].values())
    assert result["summary"] == {
        "foundation_count": 6,
        "gap_count": 6,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert len(result["implementation_gaps"]) == 6
    assert len(result["slice_plan"]) == 10
    assert result["next_slice"] == "0932"


def test_boundary_decision_defers_remote_provider_until_live_smoke() -> None:
    decision = audit._boundary_decision()

    assert decision["default_vector_payload_backend"] == "postgresql_pgvector"
    assert decision["vector_database_routing"].startswith(
        "NEX_CX_VECTOR_DATABASE_URL"
    )
    assert decision["fallback_backend"] == (
        "filesystem_for_deterministic_local_regression"
    )
    assert decision["manifest_table"] == "cx_vector_indexes"
    assert decision["payload_table"] == "cx_vectors"
    assert decision["retrieval_policy"] == "ready_and_compatible_indexes_only"
    assert decision["remote_embedding_required_now"] is False
    assert decision["remote_embedding_required_slice"] == "0939"
    assert decision["live_embedding_model"] == "Qwen3-Embedding-4B"
    assert decision["expected_live_dimension"] == 2560


def test_boundary_audit_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = audit.run_cx_vector_storage_freshness_boundary_audit(tmp_path)

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
    passing = audit.run_cx_vector_storage_freshness_boundary_audit()
    assert audit.summary_line(passing) == (
        "cx_vector_storage_freshness_boundary=pass foundations=6 gaps=6 "
        "backend=postgresql_pgvector remote_required_now=False issues=0"
    )
    assert "issues=0" in audit.summary_line({})

    monkeypatch.setattr(
        audit,
        "run_cx_vector_storage_freshness_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_cx_vector_storage_freshness_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
