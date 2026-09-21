from __future__ import annotations

import json
from pathlib import Path

import run_cx_permission_hybrid_retrieval_boundary_audit as audit


def test_repository_permission_hybrid_retrieval_boundary_audit_passes() -> None:
    result = audit.run_cx_permission_hybrid_retrieval_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert all(result["gap_checks"].values())
    assert result["summary"] == {
        "foundation_count": 7,
        "gap_count": 7,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert len(result["implementation_gaps"]) == 7
    assert len(result["slice_plan"]) == 10
    assert result["next_slice"] == "0942"


def test_boundary_decision_filters_permissions_before_ranking() -> None:
    decision = audit._boundary_decision()

    assert decision["mvp_permission_model"] == "private_tenant_owner_exact_match"
    assert decision["eligible_content_state"] == "ACTIVE"
    assert decision["cross_owner_behavior"] == (
        "not_found_before_candidate_generation"
    )
    assert decision["permission_filter_order"][-2:] == [
        "rank_bm25_and_vector",
        "rerank_authorized_candidates_only",
    ]
    assert decision["hybrid_policy"] == "weighted_rrf_vector_0_7_bm25_0_3"
    assert decision["shared_acl_scope"] == "deferred_until_oa_claim_contract"
    assert decision["remote_provider_required_now"] is False
    assert decision["remote_provider_required_slice"] == "0949"


def test_boundary_audit_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = audit.run_cx_permission_hybrid_retrieval_boundary_audit(tmp_path)

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
    passing = audit.run_cx_permission_hybrid_retrieval_boundary_audit()
    assert audit.summary_line(passing) == (
        "cx_permission_hybrid_retrieval_boundary=pass foundations=7 gaps=7 "
        "permission=private_tenant_owner_exact_match "
        "remote_required_now=False issues=0"
    )
    assert "issues=0" in audit.summary_line({})

    monkeypatch.setattr(
        audit,
        "run_cx_permission_hybrid_retrieval_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_cx_permission_hybrid_retrieval_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
