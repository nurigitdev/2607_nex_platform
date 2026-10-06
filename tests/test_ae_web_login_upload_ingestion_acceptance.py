from __future__ import annotations

import json
from pathlib import Path

import run_ae_web_login_upload_ingestion_acceptance as acceptance


def test_repository_login_upload_ingestion_acceptance_is_ready() -> None:
    result = acceptance.run_ae_web_login_upload_ingestion_acceptance()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": 5,
        "evidence_token_count": 10,
        "journey_stage_count": 3,
        "same_origin_route_count": 1,
        "issue_count": 0,
    }
    assert result["decision"]["oa_claims_owner_authoritative"] is True
    assert result["decision"]["browser_owner_scope_allowed"] is False
    assert result["decision"]["next_slice"] == "1386"


def test_login_upload_ingestion_acceptance_fails_closed_without_repo(
    tmp_path: Path,
) -> None:
    result = acceptance.run_ae_web_login_upload_ingestion_acceptance(tmp_path)

    assert result["status"] == "FAIL"
    assert result["ingestion_acceptance_readiness"] == "BLOCKED"
    assert result["issues"]
    assert result["decision"]["next_slice"] == "blocked"


def test_login_upload_ingestion_helpers_and_cli(monkeypatch, tmp_path, capsys) -> None:
    source = tmp_path / "source.js"
    source.write_text("same-origin", encoding="utf-8")
    assert acceptance._read_text(source) == "same-origin"
    assert acceptance._read_text(tmp_path / "missing") == ""
    assert acceptance.summary_line({"status": "FAIL", "issues": [1]}) == (
        "ae_web_login_upload_ingestion=fail issues=1"
    )

    passing = acceptance.run_ae_web_login_upload_ingestion_acceptance()
    monkeypatch.setattr(
        acceptance,
        "run_ae_web_login_upload_ingestion_acceptance",
        lambda: passing,
    )
    assert acceptance.main(["--summary"]) == 0
    assert "next=1386" in capsys.readouterr().out
    assert acceptance.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        acceptance,
        "run_ae_web_login_upload_ingestion_acceptance",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert acceptance.main([]) == 1
