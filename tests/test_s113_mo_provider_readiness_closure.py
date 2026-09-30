from __future__ import annotations

import json
from pathlib import Path

import run_s113_mo_provider_readiness_closure as closure


def test_repository_s113_closure_passes() -> None:
    result = closure.run_s113_mo_provider_readiness_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S114"
    assert result["feature_readiness"] == "MO_PROVIDER_AWARE_READINESS_READY"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 8,
        "passed_evidence_count": 8,
        "component_count": 6,
        "closed_component_count": 6,
        "protected_live_check_count": 8,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S114"


def test_s113_closure_freezes_readiness_models_cache_and_storage() -> None:
    decision = closure._closure_decision()

    assert decision["required_capabilities"] == [
        "embedding",
        "reranking",
        "generation",
    ]
    assert decision["provider_models"] == {
        "embedding": "Qwen3-Embedding-4B",
        "reranking": "Qwen3-Reranker-4B",
        "generation": "Qwen3.5-4B",
    }
    assert decision["cache_policy"] == (
        "bounded_process_local_ttl_stale_never_ready"
    )
    assert decision["new_table_added"] is False
    assert decision["next_requirement_scope"] == (
        "S114_contract_and_api_drift_closure"
    )


def test_s113_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s113_mo_provider_readiness_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["protected_live_check_count"] == 0
    assert not any(result["components"].values())
    assert result["failed_checks"]


def test_s113_closure_fails_when_deterministic_evidence_regresses(
    monkeypatch,
) -> None:
    monkeypatch.setattr(closure, "run_evaluator", lambda: {"status": "FAIL"})

    result = closure.run_s113_mo_provider_readiness_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_deterministic_evidence_passed"] is False
    assert result["evidence_statuses"]["evaluator"] == "FAIL"


def test_s113_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s113_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s113_mo_provider_readiness_closure()
    assert closure.summary_line(passing) == (
        "s113_mo_provider_readiness_closure=pass evidence=8/8 "
        "components=6/6 live_checks=8 next=S114"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s113_mo_provider_readiness_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s113_mo_provider_readiness_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
