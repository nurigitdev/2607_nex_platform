from __future__ import annotations

import json
from pathlib import Path

import run_s117_mo_gpu_model_runtime_observability_closure as closure


def test_repository_s117_closure_passes() -> None:
    result = closure.run_s117_mo_gpu_model_runtime_observability_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S118"
    assert result["feature_readiness"] == "MO_GPU_MODEL_RUNTIME_OBSERVABLE"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "model_count": 3,
        "contract_check_count": 9,
        "live_model_count": 3,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S118"


def test_s117_closure_freezes_traceability_runtime_and_handoff_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["traceability"] == {
        "requirement_id": "MO-FR-005",
        "s111_baseline_status": "PARTIAL",
        "s117_current_status": "IMPLEMENTED",
    }
    assert decision["required_capabilities"] == (
        "embedding",
        "reranking",
        "generation",
    )
    assert decision["default_ttl_seconds"] == 30
    assert decision["persistence"] == "process_local_ttl_no_table"
    assert decision["new_table_added"] is False
    assert decision["postgres_smoke_required"] is False
    assert decision["protected_dgx_live_required"] is True
    assert decision["next_requirement_scope"].startswith("S118_")


def test_s117_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s117_mo_gpu_model_runtime_observability_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["components"]["protected_live_and_quality"] is False


def test_s117_closure_fails_when_service_evidence_regresses(monkeypatch) -> None:
    monkeypatch.setattr(closure, "run_service", lambda: {"status": "FAIL"})

    result = closure.run_s117_mo_gpu_model_runtime_observability_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_evidence_passed"] is False
    assert result["checks"]["ttl_service_closed"] is False
    assert result["evidence_statuses"]["service"] == "FAIL"


def test_s117_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s117_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s117_mo_gpu_model_runtime_observability_closure()
    assert closure.summary_line(passing) == (
        "s117_mo_gpu_model_runtime_observability_closure=pass evidence=9/9 "
        "components=5/5 models=3 live=3 next=S118"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s117_mo_gpu_model_runtime_observability_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s117_mo_gpu_model_runtime_observability_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
