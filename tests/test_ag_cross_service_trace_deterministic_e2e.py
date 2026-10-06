from __future__ import annotations

import json
from pathlib import Path

import run_ag_cross_service_trace_deterministic_e2e as smoke


def test_deterministic_trace_e2e_passes(tmp_path: Path) -> None:
    result = smoke.run_ag_cross_service_trace_deterministic_e2e(
        database_path=tmp_path / "ag-audit.sqlite3"
    )

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 16,
        "passed_check_count": 16,
        "success_stage_count": 9,
        "stage_family_count": 8,
        "partial_diagnostic_count": 1,
        "restart_audit_event_count": 2,
    }
    assert result["decision"] == {
        "database_mode": "sqlite_regression",
        "postgres_required": False,
        "remote_provider_required": False,
        "postgres_evidence_slice": "1380",
        "next_slice": "1380",
    }


def test_missing_contract_fails_closed(tmp_path: Path) -> None:
    result = smoke.run_ag_cross_service_trace_deterministic_e2e(
        tmp_path / "missing-root",
        database_path=tmp_path / "missing-contract.sqlite3",
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["first_route_response_is_valid"] is False
    assert result["checks"]["route_succeeds_after_restart"] is False
    assert result["decision"]["next_slice"] == "blocked"


def test_default_temporary_database_and_helpers() -> None:
    result = smoke.run_ag_cross_service_trace_deterministic_e2e()

    assert result["status"] == "PASS"
    assert smoke.summary_line(result) == (
        "ag_cross_service_trace_deterministic_e2e=pass checks=16/16 "
        "families=8 partial_diagnostics=1 restart_audits=2 next=1380"
    )
    assert smoke._source_statuses({}) == {}
    assert smoke._validates(None, {}) is False


def test_load_json_and_cli_paths(monkeypatch, capsys, tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text('{"ok": true}', encoding="utf-8")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert smoke._load_json(valid) == {"ok": True}
    assert smoke._load_json(invalid) is None
    assert smoke._load_json(tmp_path / "missing.json") is None

    passing = {
        "status": "PASS",
        "summary": {
            "check_count": 1,
            "passed_check_count": 1,
            "stage_family_count": 8,
            "partial_diagnostic_count": 1,
            "restart_audit_event_count": 2,
        },
        "decision": {"next_slice": "1380"},
    }
    monkeypatch.setattr(
        smoke,
        "run_ag_cross_service_trace_deterministic_e2e",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "checks=1/1" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_ag_cross_service_trace_deterministic_e2e",
        lambda: {"status": "FAIL", "summary": {}, "decision": {}},
    )
    assert smoke.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
