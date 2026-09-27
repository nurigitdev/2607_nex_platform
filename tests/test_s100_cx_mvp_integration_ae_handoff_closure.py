from __future__ import annotations

import json
from pathlib import Path

import run_s100_cx_mvp_integration_ae_handoff_closure as closure


def test_repository_s100_closure_passes() -> None:
    result = closure.run_s100_cx_mvp_integration_ae_handoff_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S101"
    assert result["feature_readiness"] == (
        "CX_MVP_INTEGRATION_AE_HANDOFF_READY"
    )
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert result["summary"] == {
        "component_count": 8,
        "closed_component_count": 8,
        "resolved_gap_count": 8,
        "protected_live_check_count": 11,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["boundary_status"] == "PASS"
    assert result["next_requirement"] == "S101"


def test_s100_closure_freezes_live_models_storage_and_provider_path() -> None:
    decision = closure._closure_decision()

    assert decision["provider_path"] == "cx_to_mo_capability_alias_only"
    assert decision["provider_models"] == {
        "embedding": "Qwen3-Embedding-4B",
        "reranking": "Qwen3-Reranker-4B",
        "generation": "Qwen3.5-4B",
    }
    assert decision["storage_policy"] == (
        "postgres_metadata_external_owner_private_payloads"
    )
    assert decision["new_table_added"] is False
    assert decision["protected_live_check_count"] == 11
    assert decision["next_requirement_scope"] == (
        "S101_pending_canonical_scope_review"
    )


def test_s100_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s100_cx_mvp_integration_ae_handoff_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(
        closure.REQUIRED_FILES
    )
    assert result["summary"]["missing_token_count"] == len(
        closure.TOKEN_CHECKS
    )
    assert result["summary"]["protected_live_check_count"] == 0
    assert not any(result["components"].values())
    assert result["failed_checks"]


def test_s100_closure_fails_when_boundary_is_incomplete(monkeypatch) -> None:
    monkeypatch.setattr(
        closure,
        "run_boundary",
        lambda root: {
            "status": "FAIL",
            "summary": {
                "planned_slice_count": 10,
                "gap_count": 8,
                "resolved_gap_count": 7,
                "open_gap_count": 1,
                "issue_count": 0,
            },
            "decision": {},
            "next_slice": "1000",
        },
    )

    result = closure.run_s100_cx_mvp_integration_ae_handoff_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["boundary_audit_passed"] is False
    assert result["checks"]["boundary_plan_completed"] is False
    assert result["checks"]["public_choreography_preserved"] is False
    assert result["checks"]["private_storage_boundary_preserved"] is False
    assert result["checks"]["live_provider_boundary_completed"] is False
    assert result["checks"]["tiered_quality_cadence_preserved"] is False


def test_s100_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s100_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s100_cx_mvp_integration_ae_handoff_closure()
    assert closure.summary_line(passing) == (
        "s100_cx_mvp_integration_ae_handoff_closure=pass "
        "components=8/8 gaps=8/8 live_checks=11 next=S101"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s100_cx_mvp_integration_ae_handoff_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s100_cx_mvp_integration_ae_handoff_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
