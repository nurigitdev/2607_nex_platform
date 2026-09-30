from __future__ import annotations

import json
from pathlib import Path

import run_s114_mo_contract_api_drift_closure as closure


def test_repository_s114_closure_passes() -> None:
    result = closure.run_s114_mo_contract_api_drift_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S115"
    assert result["feature_readiness"] == "MO_CONTRACT_API_HARDENED"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 8,
        "passed_evidence_count": 8,
        "component_count": 6,
        "closed_component_count": 6,
        "runtime_operation_count": 27,
        "openapi_operation_count": 27,
        "protected_operation_count": 23,
        "contract_drift_count": 0,
        "protected_postgres_check_count": 12,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S115"


def test_s114_closure_freezes_contract_database_and_quality_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["drift"] == {"baseline": 28, "current": 0}
    assert decision["runtime_operation_count"] == 20
    assert decision["protected_operation_count"] == 16
    assert decision["mo_schema_count"] == 18
    assert decision["canonical_component_count"] == 11
    assert decision["test_database_target"] == "nex_mo_user@nex_mo_test"
    assert decision["new_table_added"] is False
    assert decision["dgx_provider_calls_required"] is False


def test_s114_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s114_mo_contract_api_drift_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["protected_postgres_check_count"] == 0
    assert not any(result["components"].values())


def test_s114_closure_fails_when_deterministic_evidence_regresses(
    monkeypatch,
) -> None:
    monkeypatch.setattr(closure, "run_parity", lambda _root: {"status": "FAIL"})

    result = closure.run_s114_mo_contract_api_drift_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_deterministic_evidence_passed"] is False
    assert result["checks"]["runtime_openapi_parity_closed"] is False
    assert result["evidence_statuses"]["parity"] == "FAIL"


def test_s114_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s114_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s114_mo_contract_api_drift_closure()
    assert closure.summary_line(passing) == (
        "s114_mo_contract_api_drift_closure=pass evidence=8/8 "
        "components=6/6 operations=27/27 drift=0 next=S115"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s114_mo_contract_api_drift_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s114_mo_contract_api_drift_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
