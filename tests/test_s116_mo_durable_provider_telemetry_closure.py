from __future__ import annotations

import json
from pathlib import Path

import run_s116_mo_durable_provider_telemetry_closure as closure


def test_repository_s116_closure_passes() -> None:
    result = closure.run_s116_mo_durable_provider_telemetry_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S117"
    assert result["feature_readiness"] == "MO_PROVIDER_TELEMETRY_RESTART_SAFE"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 8,
        "passed_evidence_count": 8,
        "component_count": 5,
        "closed_component_count": 5,
        "wire_field_count": 26,
        "table_column_count": 24,
        "restart_worker_count": 8,
        "restart_mutation_count": 40,
        "protected_postgres_check_count": 11,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S117"


def test_s116_closure_freezes_persistence_and_handoff_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["telemetry_persistence"] == {
        "memory": "process_local",
        "postgres": "restart_safe",
    }
    assert decision["table_name"] == "mo_provider_telemetry"
    assert decision["wire_field_count"] == 26
    assert decision["test_database_target"] == "nex_mo_user@nex_mo_test"
    assert decision["protected_postgres_check_count"] == 11
    assert decision["new_table_added"] is True
    assert decision["external_dgx_call_required"] is False
    assert decision["next_requirement_scope"].startswith("S117_")


def test_s116_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s116_mo_durable_provider_telemetry_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["components"]["postgres_and_quality_evidence"] is False


def test_s116_closure_fails_when_restart_evidence_regresses(monkeypatch) -> None:
    monkeypatch.setattr(closure, "run_restart", lambda: {"status": "FAIL"})

    result = closure.run_s116_mo_durable_provider_telemetry_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_deterministic_evidence_passed"] is False
    assert result["checks"]["restart_concurrency_closed"] is False
    assert result["evidence_statuses"]["restart_concurrency"] == "FAIL"


def test_s116_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s116_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s116_mo_durable_provider_telemetry_closure()
    assert closure.summary_line(passing) == (
        "s116_mo_durable_provider_telemetry_closure=pass evidence=8/8 "
        "components=5/5 wire=26 postgres=11 next=S117"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s116_mo_durable_provider_telemetry_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s116_mo_durable_provider_telemetry_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
