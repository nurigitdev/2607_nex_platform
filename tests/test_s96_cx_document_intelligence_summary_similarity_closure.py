from __future__ import annotations

import json
from pathlib import Path

import run_s96_cx_document_intelligence_summary_similarity_closure as closure


def test_repository_s96_closure_passes() -> None:
    result = closure.run_s96_cx_document_intelligence_summary_similarity_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S97"
    assert result["feature_readiness"] == (
        "CX_DOCUMENT_INTELLIGENCE_SUMMARY_SIMILARITY_READY"
    )
    assert all(result["checks"].values())
    assert result["summary"] == {
        "evidence_count": 8,
        "passed_evidence_count": 8,
        "deterministic_check_count": 68,
        "protected_live_check_count": 15,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert all(result["postgres_evidence"].values())
    assert all(result["live_evidence"].values())
    assert result["next_requirement"] == "S97"


def test_s96_closure_freezes_models_privacy_and_storage_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["summary_hard_limit_chars"] == 1000
    assert decision["generation_model"] == "Qwen3.5-4B"
    assert decision["generation_reasoning_mode"] == "disabled"
    assert decision["embedding_model"] == "Qwen3-Embedding-4B"
    assert decision["embedding_dimension"] == 2560
    assert decision["vector_backend"] == "owner_scoped_fresh_postgresql_pgvector"
    assert decision["similarity_metric"] == "cosine"
    assert decision["source_document_excluded_from_similarity"] is True
    assert decision["protected_live_evidence_completed"] is True
    assert "summary_topic_taxonomy_and_classification" in decision["deferred_scope"]


def test_s96_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s96_cx_document_intelligence_summary_similarity_closure(
        tmp_path
    )

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["protected_live_check_count"] == 0
    assert result["failed_checks"]


def test_s96_closure_fails_when_deterministic_evidence_does_not_pass(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_generation",
        lambda: {"status": "FAIL", "checks": {}},
    )

    result = closure.run_s96_cx_document_intelligence_summary_similarity_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["deterministic_evidence_passed"] is False
    assert result["checks"]["generation_adapter_closed"] is False
    assert result["summary"]["deterministic_check_count"] == 58


def test_s96_closure_fails_when_boundary_model_drifts(monkeypatch) -> None:
    original = closure.run_boundary

    def drifted(root: Path):
        result = original(root)
        result["decision"]["summary_generation_model"] = "legacy-model"
        return result

    monkeypatch.setattr(closure, "run_boundary", drifted)

    result = closure.run_s96_cx_document_intelligence_summary_similarity_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["canonical_models_current"] is False


def test_s96_closure_helpers_fail_closed(tmp_path: Path) -> None:
    failed = closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private detail"))
    )
    assert failed == {
        "status": "FAIL",
        "failure_code": "evidence_builder_failed",
        "detail": "RuntimeError",
    }
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._read_text(tmp_path / "missing") == ""
    present = tmp_path / "present"
    present.write_text("ok", encoding="utf-8")
    assert closure._read_text(present) == "ok"


def test_s96_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s96_cx_document_intelligence_summary_similarity_closure()
    assert closure.summary_line(passing) == (
        "s96_cx_document_intelligence_summary_similarity_closure=pass "
        "evidence=8/8 deterministic_checks=68 live_checks=15 next=S97"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s96_cx_document_intelligence_summary_similarity_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s96_cx_document_intelligence_summary_similarity_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
