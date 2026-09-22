from __future__ import annotations

import json
from pathlib import Path

import run_s95_cx_permission_hybrid_retrieval_closure as closure


def test_repository_s95_closure_passes() -> None:
    result = closure.run_s95_cx_permission_hybrid_retrieval_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S96"
    assert result["feature_readiness"] == (
        "CX_PERMISSION_FILTERED_HYBRID_RETRIEVAL_READY"
    )
    assert all(result["checks"].values())
    assert result["summary"] == {
        "evidence_count": 7,
        "passed_evidence_count": 7,
        "contract_check_count": 55,
        "postgres_check_count": 25,
        "live_check_count": 16,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert all(result["postgres_evidence"].values())
    assert all(result["live_evidence"].values())
    assert result["next_requirement"] == "S96"


def test_s95_closure_freezes_current_models_and_privacy_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["permission_policy"] == "cx.private_owner_active.v1"
    assert decision["lexical_policy"] == "postgresql_bm25_k1_1_2_b_0_75"
    assert decision["fusion_policy"] == (
        "weighted_rrf_vector_0_7_bm25_0_3_k_60"
    )
    assert decision["embedding_model"] == "Qwen3-Embedding-4B"
    assert decision["embedding_dimension"] == 2560
    assert decision["reranker_model"] == "Qwen3-Reranker-4B"
    assert decision["persistence_payload_policy"] == "hash_only_private_owner"
    assert decision["protected_live_evidence_completed"] is True
    assert "shared_group_acl_expansion" in decision["deferred_scope"]


def test_s95_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s95_cx_permission_hybrid_retrieval_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["failed_checks"]


def test_s95_closure_fails_when_deterministic_evidence_does_not_pass(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_ranking_contract",
        lambda: {"status": "FAIL", "checks": {}},
    )

    result = closure.run_s95_cx_permission_hybrid_retrieval_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["deterministic_evidence_passed"] is False
    assert result["checks"]["weighted_rrf_and_rerank_closed"] is False
    assert result["summary"]["contract_check_count"] == 45


def test_s95_closure_fails_when_boundary_model_drifts(monkeypatch) -> None:
    original = closure.run_boundary

    def drifted(root: Path):
        result = original(root)
        result["decision"]["live_reranker_model"] = "legacy-model"
        return result

    monkeypatch.setattr(closure, "run_boundary", drifted)

    result = closure.run_s95_cx_permission_hybrid_retrieval_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["canonical_models_current"] is False


def test_s95_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s95_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s95_cx_permission_hybrid_retrieval_closure()
    assert closure.summary_line(passing) == (
        "s95_cx_permission_hybrid_retrieval_closure=pass evidence=7/7 "
        "contracts=55 postgres_checks=25 live_checks=16 next=S96"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s95_cx_permission_hybrid_retrieval_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s95_cx_permission_hybrid_retrieval_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
