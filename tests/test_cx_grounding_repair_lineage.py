from __future__ import annotations

import json
from pathlib import Path

import run_cx_grounding_repair_lineage as smoke


def test_repository_grounding_repair_lineage_passes() -> None:
    result = smoke.run_cx_grounding_repair_lineage()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "check_count": 10,
        "passed_count": 10,
        "issue_count": 0,
    }
    assert result["decision"] == {
        "private_evidence_persisted": False,
        "repair_attempt_limit": 1,
        "remote_provider_required": False,
        "next_slice": "1366",
    }


def test_empty_root_fails_lineage_evidence(tmp_path: Path) -> None:
    result = smoke.run_cx_grounding_repair_lineage(tmp_path)

    assert result["status"] == "FAIL"
    assert result["summary"]["passed_count"] == 0
    assert result["summary"]["issue_count"] == 10
    assert result["decision"]["next_slice"] == "blocked"


def test_lineage_evidence_helpers_and_main(monkeypatch, tmp_path, capsys) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert smoke._read_json(invalid) == {}
    assert smoke._read_json(malformed) == {}
    assert smoke._read_json(tmp_path / "missing.json") == {}
    assert smoke._read_text(tmp_path / "missing.txt") == ""

    passing = smoke.run_cx_grounding_repair_lineage()
    assert smoke.summary_line(passing) == (
        "cx_grounding_repair_lineage=pass checks=10/10 issues=0 next=1366"
    )
    monkeypatch.setattr(smoke, "run_cx_grounding_repair_lineage", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "checks=10/10" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_cx_grounding_repair_lineage",
        lambda: {"status": "FAIL", "summary": {}, "decision": {}},
    )
    assert smoke.main([]) == 1
