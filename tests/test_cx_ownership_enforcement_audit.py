from __future__ import annotations

from pathlib import Path

from nex_cx.ownership_enforcement_audit import (
    ENFORCEMENT_SURFACES,
    build_cx_ownership_enforcement_audit,
)
import run_cx_ownership_enforcement_audit as runner


def test_repository_ownership_audit_confirms_current_gaps() -> None:
    result = build_cx_ownership_enforcement_audit()

    assert result["status"] == "PASS"
    assert result["enforcement_readiness"] == "GAPS_CONFIRMED"
    assert result["issues"] == []
    assert result["summary"] == {
        "surface_count": 8,
        "evidence_gap_count": 0,
        "high_risk_gap_count": 5,
        "caller_asserted_filtered_count": 3,
        "service_only_count": 4,
    }
    assert result["target_refactoring"]["name"] == "CxAccessContext"
    assert result["target_refactoring"]["implementation_requirement"] == "S92"
    assert all(item["evidence_present"] for item in result["surfaces"])


def test_audit_fails_closed_when_source_evidence_is_missing(tmp_path: Path) -> None:
    result = build_cx_ownership_enforcement_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "cx_ownership_enforcement_audit_failed"
    assert result["summary"]["surface_count"] == len(ENFORCEMENT_SURFACES)
    assert result["summary"]["evidence_gap_count"] == len(ENFORCEMENT_SURFACES)
    assert len(result["issues"]) == len(ENFORCEMENT_SURFACES)


def test_summary_line_distinguishes_audit_and_enforcement_readiness() -> None:
    passing = runner.run_cx_ownership_enforcement_audit()

    assert runner.summary_line(passing) == (
        "cx_ownership_enforcement_audit=pass readiness=GAPS_CONFIRMED "
        "surfaces=8 high_risk_gaps=5 evidence_gaps=0"
    )
    assert runner.summary_line({"status": "FAIL"}) == (
        "cx_ownership_enforcement_audit=fail readiness=UNKNOWN "
        "surfaces=0 high_risk_gaps=0 evidence_gaps=0"
    )


def test_runner_main_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = runner.run_cx_ownership_enforcement_audit()
    monkeypatch.setattr(
        runner,
        "run_cx_ownership_enforcement_audit",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "readiness=GAPS_CONFIRMED" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_cx_ownership_enforcement_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
