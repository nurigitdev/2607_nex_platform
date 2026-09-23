from __future__ import annotations

import json
from pathlib import Path

import run_s98_cx_worker_operations_resilience_closure as closure


def test_repository_s98_closure_passes() -> None:
    result = closure.run_s98_cx_worker_operations_resilience_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S99"
    assert result["feature_readiness"] == (
        "CX_WORKER_OPERATIONS_RESILIENCE_READY"
    )
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert result["summary"] == {
        "component_count": 8,
        "closed_component_count": 8,
        "resolved_gap_count": 8,
        "protected_postgres_check_count": 23,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["boundary_status"] == "PASS"
    assert result["next_requirement"] == "S99"


def test_s98_closure_freezes_worker_runtime_and_next_scope() -> None:
    decision = closure._closure_decision()

    assert decision["execution_policy"] == "bounded_cooperative_cancellation"
    assert decision["lease_policy"] == "renewable_compare_and_swap"
    assert decision["retry_policy"] == "bounded_backoff_then_dead_letter"
    assert decision["new_table_added"] is False
    assert decision["dgx_provider_required"] is False
    assert decision["protected_postgres_evidence_completed"] is True
    assert decision["next_requirement_scope"] == (
        "cx_asynchronous_grounded_generation_execution_and_recovery"
    )


def test_s98_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s98_cx_worker_operations_resilience_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["protected_postgres_check_count"] == 0
    assert not any(result["components"].values())
    assert result["failed_checks"]


def test_s98_closure_fails_when_boundary_is_incomplete(monkeypatch) -> None:
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
            "next_slice": "0980",
        },
    )

    result = closure.run_s98_cx_worker_operations_resilience_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["boundary_audit_passed"] is False
    assert result["checks"]["boundary_plan_completed"] is False
    assert result["checks"]["queue_and_process_boundaries_preserved"] is False
    assert result["checks"]["resilience_boundaries_preserved"] is False
    assert result["checks"]["storage_scope_not_expanded"] is False
    assert result["checks"]["protected_target_confirmed"] is False
    assert result["checks"]["provider_scope_not_overclaimed"] is False
    assert result["checks"]["tiered_quality_cadence_preserved"] is False


def test_s98_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s98_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s98_cx_worker_operations_resilience_closure()
    assert closure.summary_line(passing) == (
        "s98_cx_worker_operations_resilience_closure=pass "
        "components=8/8 gaps=8/8 postgres_checks=23 next=S99"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s98_cx_worker_operations_resilience_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s98_cx_worker_operations_resilience_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
