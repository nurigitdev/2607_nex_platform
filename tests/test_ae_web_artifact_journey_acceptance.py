from __future__ import annotations

import json
from pathlib import Path

import run_ae_web_artifact_journey_acceptance as acceptance


def test_repository_artifact_journey_acceptance_is_ready() -> None:
    result = acceptance.run_ae_web_artifact_journey_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_token_count": 10,
        "journey_stage_count": 9,
        "artifact_operation_count": 3,
        "failure_phase_count": 3,
        "issue_count": 0,
    }
    assert result["decision"]["artifact_file_lineage_required"] is True
    assert result["decision"]["next_slice"] == "1388"


def test_artifact_journey_acceptance_fails_closed_without_repo(
    tmp_path: Path,
) -> None:
    result = acceptance.run_ae_web_artifact_journey_acceptance(tmp_path)

    assert result["status"] == "FAIL"
    assert result["artifact_acceptance_readiness"] == "BLOCKED"
    assert result["issues"]
    assert result["decision"]["next_slice"] == "blocked"


def test_artifact_journey_helpers_and_cli(monkeypatch, tmp_path, capsys) -> None:
    source = tmp_path / "source.js"
    source.write_text("DOWNLOAD_READY", encoding="utf-8")
    assert acceptance._read_text(source) == "DOWNLOAD_READY"
    assert acceptance._read_text(tmp_path / "missing") == ""
    assert acceptance.summary_line({"status": "FAIL", "issues": [1]}) == (
        "ae_web_artifact_journey=fail issues=1"
    )

    passing = acceptance.run_ae_web_artifact_journey_acceptance()
    monkeypatch.setattr(
        acceptance,
        "run_ae_web_artifact_journey_acceptance",
        lambda: passing,
    )
    assert acceptance.main(["--summary"]) == 0
    assert "next=1388" in capsys.readouterr().out
    assert acceptance.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        acceptance,
        "run_ae_web_artifact_journey_acceptance",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert acceptance.main([]) == 1
