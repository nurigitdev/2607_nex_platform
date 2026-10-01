from __future__ import annotations

import json
from pathlib import Path

import run_s121_oa_current_state_reaudit_closure as closure


def test_repository_s121_closure_passes_with_confirmed_gaps() -> None:
    result = closure.run_s121_oa_current_state_reaudit_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_TARGETED_S122_HARDENING"
    assert result["feature_readiness"] == (
        "CONFIRMED_GAPS_NOT_PRODUCTION_AUTH_COMPLETE"
    )
    assert all(result["checks"].values())
    assert result["summary"] == {
        "audit_count": 8,
        "passed_audit_count": 8,
        "traceable_requirement_count": 5,
        "lifecycle_gap_count": 2,
        "security_gap_count": 0,
        "contract_drift_count": 23,
        "trust_refactor_count": 4,
        "repaired_surface_count": 5,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert set(result["audit_statuses"].values()) == {"PASS"}
    assert all(result["postgres_evidence"].values())
    assert result["next_requirement"] == "S122"


def test_s122_handoff_orders_security_hardening_and_migration_history() -> None:
    handoff = closure._s122_handoff()

    assert handoff["target_requirement"] == "S122"
    assert [item["priority"] for item in handoff["work_items"]] == [
        "P0",
        "P0",
        "P0",
        "P0",
        "P1",
        "P1",
        "P1",
        "P1",
        "P2",
        "P2",
    ]
    assert handoff["migration_strategy"] == {
        "canonical": "versioned_sql_schema_migrations_runner",
        "alembic_status": "NOT_CONFIGURED",
        "parallel_history_allowed": False,
    }
    assert "DGX providers remain outside the OA hardening boundary" in handoff[
        "guardrails"
    ]


def test_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s121_oa_current_state_reaudit_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["checks"]["actual_postgres_evidence_passed"] is False
    assert result["failed_checks"]


def test_closure_fails_when_audit_or_quantified_gap_drifts(monkeypatch) -> None:
    monkeypatch.setattr(
        closure,
        "run_security",
        lambda _root: {"status": "FAIL", "summary": {"gap_count": 0}},
    )

    result = closure.run_s121_oa_current_state_reaudit_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_audits_passed"] is False
    assert result["checks"]["security_gaps_quantified"] is False


def test_closure_helpers_fail_closed(tmp_path: Path) -> None:
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
    passing = closure.run_s121_oa_current_state_reaudit_closure()

    assert closure.summary_line(passing) == (
        "s121_oa_current_state_reaudit_closure=pass audits=8/8 "
        "lifecycle_gaps=2 security_gaps=0 contract_drift=23 next=S122"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s121_oa_current_state_reaudit_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s121_oa_current_state_reaudit_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
