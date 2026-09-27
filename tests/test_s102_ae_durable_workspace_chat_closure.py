from __future__ import annotations

import json
from pathlib import Path

import run_s102_ae_durable_workspace_chat_closure as closure


def _postgres() -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "execution_state": "EXECUTED",
        "database": "nex_ae_test",
        "role": "nex_ae_user",
        "checks": {f"check_{index}": True for index in range(13)},
        "cleanup_counts": {"remaining": 0},
    }


def _contract() -> dict:
    return {
        "status": "PASS",
        "checks": {f"check_{index}": True for index in range(12)},
    }


def test_repository_s102_closure_passes_with_actual_postgres(monkeypatch) -> None:
    monkeypatch.setattr(closure, "run_contract_observability", _contract)

    result = closure.run_s102_ae_durable_workspace_chat_closure(
        postgres_evidence=_postgres()
    )

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S103"
    assert result["feature_readiness"] == "AE_DURABLE_WORKSPACE_CHAT_READY"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert result["summary"] == {
        "component_count": 8,
        "closed_component_count": 8,
        "resolved_gap_count": 8,
        "contract_check_count": 12,
        "postgres_check_count": 13,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["postgres_executed"] is True
    assert result["next_requirement"] == "S103"


def test_closure_allows_unrequested_protected_smoke_to_remain_skipped(
    monkeypatch,
) -> None:
    monkeypatch.delenv(closure.POSTGRES_SMOKE_ENV, raising=False)
    monkeypatch.setattr(closure, "run_contract_observability", _contract)
    monkeypatch.setattr(
        closure,
        "run_postgres",
        lambda: {"status": "SKIPPED", "checks": {}, "actual_postgres": False},
    )

    result = closure.run_s102_ae_durable_workspace_chat_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_WITH_PROTECTED_POSTGRES_PENDING"
    assert result["postgres_executed"] is False
    assert result["summary"]["postgres_check_count"] == 0


def test_closure_fails_when_requested_postgres_did_not_execute(monkeypatch) -> None:
    monkeypatch.setenv(closure.POSTGRES_SMOKE_ENV, "1")
    monkeypatch.setattr(closure, "run_contract_observability", _contract)
    monkeypatch.setattr(
        closure,
        "run_postgres",
        lambda: {"status": "SKIPPED", "checks": {}, "actual_postgres": False},
    )

    result = closure.run_s102_ae_durable_workspace_chat_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["postgres_policy_satisfied"] is False
    assert result["closure_readiness"] == "BLOCKED"


def test_closure_fails_closed_for_missing_repository(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(closure, "run_contract_observability", _contract)
    result = closure.run_s102_ae_durable_workspace_chat_closure(
        tmp_path,
        postgres_evidence=_postgres(),
    )

    assert result["status"] == "FAIL"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert not any(result["components"].values())
    assert result["checks"]["boundary_audit_passed"] is False


def test_closure_decision_and_helpers_fail_closed(tmp_path: Path) -> None:
    decision = closure._closure_decision()
    assert decision["owner_policy"] == "oa_claim_authoritative_cross_owner_not_found"
    assert decision["remote_provider_required"] is False
    assert decision["new_tables_added"] == [
        "ae_workspaces",
        "ae_workspace_activities",
    ]
    assert decision["next_requirement_scope"] == (
        "S103_ae_upload_document_workflow_hardening"
    )

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


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    monkeypatch.setattr(closure, "run_contract_observability", _contract)
    passing = closure.run_s102_ae_durable_workspace_chat_closure(
        postgres_evidence=_postgres()
    )
    assert closure.summary_line(passing) == (
        "s102_ae_durable_workspace_chat_closure=pass components=8/8 "
        "gaps=8/8 postgres=pass postgres_checks=13 next=S103"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s102_ae_durable_workspace_chat_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s102_ae_durable_workspace_chat_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
