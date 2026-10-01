from __future__ import annotations

import json
from pathlib import Path

import run_mo_mvp_evidence_inventory as smoke


def test_repository_inventory_smoke_passes() -> None:
    result = smoke.run_mo_mvp_evidence_inventory()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "requirement_count": 9,
        "ready_count": 9,
        "issue_count": 0,
        "identity_count": 9,
        "failed_check_count": 0,
    }
    assert result["next_slice"] == "1195"


def test_inventory_smoke_fails_closed_for_empty_root(tmp_path: Path) -> None:
    result = smoke.run_mo_mvp_evidence_inventory(tmp_path)

    assert result["status"] == "FAIL"
    assert result["summary"]["ready_count"] == 0
    assert result["summary"]["issue_count"] == 18
    assert result["next_slice"] == "blocked"


def test_inventory_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_mo_mvp_evidence_inventory()
    assert smoke.summary_line(passing) == (
        "mo_mvp_evidence_inventory=pass requirements=9/9 identities=9 "
        "issues=0 next=1195"
    )
    assert "inventory=fail" in smoke.summary_line({"status": "FAIL"})

    monkeypatch.setattr(smoke, "run_mo_mvp_evidence_inventory", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "inventory=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        smoke, "run_mo_mvp_evidence_inventory", lambda: {"status": "FAIL"}
    )
    assert smoke.main([]) == 1
