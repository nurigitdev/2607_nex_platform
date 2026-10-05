from __future__ import annotations

import json
from pathlib import Path

import run_ae_grounded_response_lineage as evidence


def test_repository_evidence_proves_ae_grounding_lineage_binding() -> None:
    result = evidence.run_ae_grounded_response_lineage()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 10,
        "passed_count": 10,
        "issue_count": 0,
    }
    assert result["decision"] == {
        "legacy_lineage_read_compatible": True,
        "grounded_ready_requires_cx_lineage": True,
        "private_evidence_persisted": False,
        "remote_provider_required": False,
        "next_slice": "1367",
    }


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = evidence.run_ae_grounded_response_lineage(tmp_path)

    assert result["status"] == "FAIL"
    assert result["summary"]["passed_count"] == 0
    assert result["summary"]["issue_count"] == 10
    assert result["decision"]["next_slice"] == "blocked"


def test_read_helpers_reject_missing_invalid_and_non_object_json(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    sequence = tmp_path / "sequence.json"
    sequence.write_text("[]", encoding="utf-8")

    assert evidence._read_text(tmp_path / "missing") == ""
    assert evidence._read_json(tmp_path / "missing") == {}
    assert evidence._read_json(invalid) == {}
    assert evidence._read_json(sequence) == {}


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = evidence.run_ae_grounded_response_lineage()
    assert evidence.summary_line(passing) == (
        "ae_grounded_response_lineage=pass checks=10/10 issues=0 next=1367"
    )
    assert "fail" in evidence.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        evidence,
        "run_ae_grounded_response_lineage",
        lambda: passing,
    )
    assert evidence.main(["--summary"]) == 0
    assert "checks=10/10" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        evidence,
        "run_ae_grounded_response_lineage",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert evidence.main([]) == 1
