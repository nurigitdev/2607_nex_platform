from __future__ import annotations

import json
from pathlib import Path

import run_s139_ae_web_korean_golden_journey_closure as closure


def test_repository_closure_passes_and_hands_off_to_s140() -> None:
    result = closure.run_s139_ae_web_korean_golden_journey_closure()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["closure_readiness"] == "READY_FOR_S140"
    assert result["evidence_statuses"] == {
        "boundary": "PASS",
        "messages": "PASS",
        "state": "PASS",
        "ingestion": "PASS",
        "grounding": "PASS",
        "artifact": "PASS",
        "viewport": "PASS",
        "playwright": "PASS",
        "protected": "SKIPPED",
    }
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 8,
        "protected_skip_count": 1,
        "check_count": 15,
        "passed_check_count": 15,
        "journey_stage_count": 9,
        "viewport_count": 2,
        "actual_process_count": 13,
        "protected_database_count": 3,
        "web_artifact_count": 10,
    }
    assert result["decision"]["completion_signal_met"] is True
    assert result["decision"]["same_origin_browser_boundary_preserved"] is True
    assert result["decision"]["private_payload_projection_allowed"] is False
    assert result["decision"]["next_requirement"] == "S140"


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s139_ae_web_korean_golden_journey_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["failed_checks"]
    assert result["summary"]["evidence_count"] == 0
    assert result["decision"]["next_requirement"] == "blocked"


def test_helpers_cover_mapping_text_and_noncanonical_root(tmp_path: Path) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._run_evidence(tmp_path) == {}

    source = tmp_path / "source.md"
    source.write_text("line one\n  line two", encoding="utf-8")
    assert closure._read_text(source) == "line one\n  line two"
    assert closure._normalized_text(source) == "line one line two"
    assert closure._read_text(tmp_path / "missing.md") == ""

    assert closure._contains_secret("credentials are injected separately") is False
    assert closure._contains_secret("postgresql://user:secret@db/test") is True
    assert closure._contains_secret("password=fake-secret") is True
    assert closure._contains_secret("api-key: fake-key") is True
    assert closure._contains_secret("endpoint 10.0.0.7") is True
    assert closure._contains_secret("BEGIN PRIVATE KEY") is True


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_evidence_count": 8,
            "protected_skip_count": 1,
            "evidence_count": 9,
            "passed_check_count": 15,
            "check_count": 15,
            "journey_stage_count": 9,
            "viewport_count": 2,
        },
        "decision": {"next_requirement": "S140"},
    }
    assert closure.summary_line(passing) == (
        "s139_ae_web_korean_golden_journey_closure=pass evidence=8+1/9 "
        "checks=15/15 stages=9 viewports=2 next=S140"
    )
    assert closure.summary_line(
        {"status": "FAIL", "failed_checks": ["a"]}
    ) == "s139_ae_web_korean_golden_journey_closure=fail checks=1"

    monkeypatch.setattr(
        closure,
        "run_s139_ae_web_korean_golden_journey_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S140" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        closure,
        "run_s139_ae_web_korean_golden_journey_closure",
        lambda: {"status": "FAIL", "failed_checks": []},
    )
    assert closure.main([]) == 1
