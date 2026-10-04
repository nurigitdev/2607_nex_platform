from __future__ import annotations

import json
from pathlib import Path

import run_oa_mvp_acceptance_policy_traceability as smoke


def test_repository_policy_traceability_passes() -> None:
    result = smoke.run_oa_mvp_acceptance_policy_traceability()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "requirement_count": 5,
        "ready_count": 5,
        "evidence_count": 26,
        "live_gate_count": 6,
        "new_table_count": 0,
    }
    assert result["next_slice"] == "1295"


def test_inventory_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = smoke.run_oa_mvp_acceptance_policy_traceability(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["all_repository_evidence_present"] is False
    assert result["inventory"]["ready_count"] == 0
    assert result["inventory"]["missing_evidence_count"] == 26
    assert result["next_slice"] == "blocked"


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_mvp_acceptance_policy_traceability()
    assert smoke.summary_line(passing) == (
        "oa_mvp_acceptance_policy_traceability=pass requirements=5/5 "
        "evidence=26 live_gates=6 tables=0 next=1295"
    )
    monkeypatch.setattr(
        smoke, "run_oa_mvp_acceptance_policy_traceability", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "requirements=5/5" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(
        smoke, "run_oa_mvp_acceptance_policy_traceability", lambda: failing
    )
    assert smoke.main([]) == 1
