from __future__ import annotations

import json
from pathlib import Path

import run_s104_ae_cx_async_generation_closure as closure


def _postgres() -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "execution_state": "EXECUTED",
        "database_identity": {
            "ae": {"database": "nex_ae_test", "role": "nex_ae_user"},
            "cx": {"database": "nex_cx_test", "role": "nex_cx_user"},
        },
        "checks": {f"check_{index}": True for index in range(17)},
        "cleanup_counts": {"ae_remaining": 0, "cx_remaining": 0},
        "remote_provider_required": False,
    }


def _contract() -> dict:
    return {
        "status": "PASS",
        "schema_count": 98,
        "example_count": 153,
        "negative_example_count": 116,
        "openapi_count": 7,
        "failure_count": 0,
    }


def test_repository_s104_closure_passes_with_actual_postgres() -> None:
    result = closure.run_s104_ae_cx_async_generation_closure(
        postgres_evidence=_postgres(),
        contract_evidence=_contract(),
    )

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S105"
    assert result["feature_readiness"] == "AE_CX_ASYNC_GENERATION_READY"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert result["summary"] == {
        "component_count": 10,
        "closed_component_count": 10,
        "resolved_gap_count": 8,
        "contract_schema_count": 98,
        "contract_example_count": 153,
        "contract_negative_count": 116,
        "postgres_check_count": 17,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["postgres_executed"] is True
    assert result["next_requirement"] == "S105"


def test_closure_allows_unrequested_protected_smoke_to_remain_skipped(
    monkeypatch,
) -> None:
    monkeypatch.delenv(closure.POSTGRES_SMOKE_ENV, raising=False)
    monkeypatch.setattr(
        closure,
        "run_postgres",
        lambda: {"status": "SKIPPED", "checks": {}, "actual_postgres": False},
    )
    result = closure.run_s104_ae_cx_async_generation_closure(
        contract_evidence=_contract()
    )

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_WITH_PROTECTED_POSTGRES_PENDING"
    assert result["postgres_executed"] is False
    assert result["summary"]["postgres_check_count"] == 0


def test_closure_fails_when_requested_postgres_did_not_execute(monkeypatch) -> None:
    monkeypatch.setenv(closure.POSTGRES_SMOKE_ENV, "1")
    monkeypatch.setattr(
        closure,
        "run_postgres",
        lambda: {"status": "SKIPPED", "checks": {}, "actual_postgres": False},
    )
    result = closure.run_s104_ae_cx_async_generation_closure(
        contract_evidence=_contract()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["postgres_policy_satisfied"] is False
    assert result["closure_readiness"] == "BLOCKED"


def test_closure_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = closure.run_s104_ae_cx_async_generation_closure(
        tmp_path,
        postgres_evidence=_postgres(),
        contract_evidence=_contract(),
    )

    assert result["status"] == "FAIL"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert not any(result["components"].values())
    assert result["checks"]["boundary_audit_passed"] is False


def test_closure_fails_for_contract_validation_failure() -> None:
    result = closure.run_s104_ae_cx_async_generation_closure(
        postgres_evidence=_postgres(),
        contract_evidence={"status": "FAIL", "failure_count": 1},
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["contract_tree_valid"] is False
    assert result["contract_status"] == "FAIL"


def test_closure_decision_contract_evidence_and_helpers(tmp_path: Path) -> None:
    decision = closure._closure_decision()
    assert decision["feature_scope"] == (
        "ae_to_cx_asynchronous_generation_integration"
    )
    assert decision["remote_provider_required"] is False
    assert decision["new_tables_added"] == []
    assert decision["next_requirement_scope"] == "S105"

    contract = closure._contract_evidence(closure.ROOT)
    assert contract["status"] == "PASS"
    assert contract["schema_count"] == 98
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
    passing = closure.run_s104_ae_cx_async_generation_closure(
        postgres_evidence=_postgres(),
        contract_evidence=_contract(),
    )
    assert closure.summary_line(passing) == (
        "s104_ae_cx_async_generation_closure=pass components=10/10 "
        "gaps=8/8 postgres=pass postgres_checks=17 next=S105"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s104_ae_cx_async_generation_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s104_ae_cx_async_generation_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
