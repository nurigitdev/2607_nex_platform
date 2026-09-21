from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_s91_cx_current_state_reaudit_closure as closure


def test_repository_s91_closure_passes_with_confirmed_gaps() -> None:
    result = closure.run_s91_cx_current_state_reaudit_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_TARGETED_S92_REFACTORING"
    assert result["feature_readiness"] == "CONFIRMED_GAPS_NOT_FEATURE_COMPLETE"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "audit_count": 8,
        "passed_audit_count": 8,
        "confirmed_high_risk_ownership_gap_count": 5,
        "required_refactoring_count": 5,
        "private_adapter_count": 4,
        "contract_drift_count": 0,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert set(result["audit_statuses"].values()) == {"PASS"}
    assert all(result["postgres_evidence"].values())
    assert result["next_requirement"] == "S92"


def test_s92_handoff_orders_refactoring_and_freezes_one_migration_history() -> None:
    handoff = closure._s92_handoff()

    assert handoff["target_requirement"] == "S92"
    assert [item["priority"] for item in handoff["work_items"]] == [
        "P0",
        "P0",
        "P0",
        "P0",
        "P1",
        "P1",
    ]
    assert handoff["migration_strategy"] == {
        "canonical": "versioned_sql_schema_migrations_runner",
        "alembic_status": "DEFERRED_UNTIL_DELIBERATE_BASELINE_TRANSITION",
        "alembic_parallel_history_allowed": False,
    }


def test_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s91_cx_current_state_reaudit_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["failed_checks"]


def test_closure_fails_when_an_audit_does_not_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        closure,
        "run_ownership",
        lambda _root: {
            "status": "FAIL",
            "enforcement_readiness": "AUDIT_FAILED",
            "summary": {},
        },
    )

    result = closure.run_s91_cx_current_state_reaudit_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_audits_passed"] is False
    assert result["checks"]["ownership_gaps_confirmed"] is False


def test_safe_evidence_mapping_and_text_helpers(tmp_path: Path) -> None:
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


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s91_cx_current_state_reaudit_closure()
    assert closure.summary_line(passing) == (
        "s91_cx_current_state_reaudit_closure=pass audits=8/8 "
        "ownership_gaps=5 refactors=5 contract_drift=0 next=S92"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s91_cx_current_state_reaudit_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s91_cx_current_state_reaudit_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
