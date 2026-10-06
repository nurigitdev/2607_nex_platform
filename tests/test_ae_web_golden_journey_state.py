from __future__ import annotations

import json
from pathlib import Path

import run_ae_web_golden_journey_state as audit


def test_repository_has_correlated_browser_safe_journey_state() -> None:
    result = audit.run_ae_web_golden_journey_state()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["declared_stages"] == list(audit.EXPECTED_STAGES)
    assert result["summary"] == {
        "stage_count": 9,
        "safe_ref_key_count": 13,
        "safe_detail_key_count": 8,
        "forbidden_evidence_field_count": 7,
        "issue_count": 0,
    }
    assert result["decision"]["private_payload_allowed"] is False
    assert result["decision"]["next_slice"] == "1385"


def test_journey_state_audit_fails_closed_without_repository(tmp_path: Path) -> None:
    result = audit.run_ae_web_golden_journey_state(tmp_path)

    assert result["status"] == "FAIL"
    assert result["journey_state_readiness"] == "BLOCKED"
    assert result["issues"]
    assert result["declared_stages"] == []
    assert result["decision"]["next_slice"] == "blocked"


def test_journey_state_audit_helpers_and_cli(monkeypatch, tmp_path, capsys) -> None:
    sample = tmp_path / "sample.js"
    sample.write_text(
        'const STAGES = Object.freeze(["ONE"]);\n'
        'const SAFE = new Set(["first", "second"]);',
        encoding="utf-8",
    )
    source = audit._read_text(sample)
    assert audit._set_literal_item_count(source, "SAFE") == 2
    assert audit._set_literal_item_count(source, "MISSING") == 0
    assert audit._declared_stages("") == ()
    assert audit._read_text(tmp_path / "missing") == ""
    assert audit.summary_line({"status": "FAIL", "issues": [1]}) == (
        "ae_web_golden_journey_state=fail issues=1"
    )

    passing = audit.run_ae_web_golden_journey_state()
    monkeypatch.setattr(audit, "run_ae_web_golden_journey_state", lambda: passing)
    assert audit.main(["--summary"]) == 0
    assert "next=1385" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_ae_web_golden_journey_state",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
