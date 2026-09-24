from __future__ import annotations

import json
from pathlib import Path

import run_s99_cx_async_generation_recovery_closure as closure


def test_repository_s99_closure_passes() -> None:
    result = closure.run_s99_cx_async_generation_recovery_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S100"
    assert result["feature_readiness"] == (
        "CX_ASYNC_GENERATION_RECOVERY_READY"
    )
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert result["summary"] == {
        "component_count": 8,
        "closed_component_count": 8,
        "resolved_gap_count": 8,
        "protected_postgres_check_count": 21,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["boundary_status"] == "PASS"
    assert result["next_requirement"] == "S100"


def test_s99_closure_freezes_async_runtime_and_provider_scope() -> None:
    decision = closure._closure_decision()

    assert decision["sync_api_policy"] == "preserved"
    assert decision["queue_policy"] == (
        "service_jobs_deterministic_idempotent_job"
    )
    assert decision["request_storage_policy"] == (
        "owner_private_immutable_envelope"
    )
    assert decision["new_table_added"] is False
    assert decision["remote_provider_required"] is False
    assert decision["protected_postgres_check_count"] == 21
    assert decision["next_requirement_scope"] == (
        "S100_pending_canonical_scope_review"
    )


def test_s99_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s99_cx_async_generation_recovery_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(
        closure.REQUIRED_FILES
    )
    assert result["summary"]["missing_token_count"] == len(
        closure.TOKEN_CHECKS
    )
    assert result["summary"]["protected_postgres_check_count"] == 0
    assert not any(result["components"].values())
    assert result["failed_checks"]


def test_s99_closure_fails_when_boundary_is_incomplete(monkeypatch) -> None:
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
            "next_slice": "0990",
        },
    )

    result = closure.run_s99_cx_async_generation_recovery_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["boundary_audit_passed"] is False
    assert result["checks"]["boundary_plan_completed"] is False
    assert result["checks"][
        "compatibility_and_storage_boundaries_preserved"
    ] is False
    assert result["checks"]["queue_and_worker_reuse_preserved"] is False
    assert result["checks"]["protected_postgres_slice_completed"] is False
    assert result["checks"]["provider_scope_not_overclaimed"] is False
    assert result["checks"]["tiered_quality_cadence_preserved"] is False


def test_s99_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s99_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s99_cx_async_generation_recovery_closure()
    assert closure.summary_line(passing) == (
        "s99_cx_async_generation_recovery_closure=pass "
        "components=8/8 gaps=8/8 postgres_checks=21 next=S100"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s99_cx_async_generation_recovery_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s99_cx_async_generation_recovery_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
