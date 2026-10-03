from __future__ import annotations

import json
from pathlib import Path

import run_oa_service_principal_handoff as handoff


def test_service_principal_handoff_passes() -> None:
    result = handoff.run_oa_service_principal_handoff()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["implementation_order"][0] == "migration_and_repository"
    assert result["handoff"]["credential_secret_display"] == (
        "once_at_creation_or_rotation"
    )


def test_handoff_detects_premature_schema_implementation(tmp_path: Path) -> None:
    migrations = tmp_path / "database/nex-oa/migrations"
    migrations.mkdir(parents=True)
    (migrations / "future.sql").write_text(
        "CREATE TABLE oa_service_principals ();",
        encoding="utf-8",
    )

    result = handoff.run_oa_service_principal_handoff(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_service_principal_handoff_failed"
    assert result["checks"]["no_s125_table_created"] is False


def test_summary_and_main_cover_pass_and_failure(monkeypatch, capsys) -> None:
    passing = handoff.run_oa_service_principal_handoff()
    assert handoff.summary_line(passing) == (
        "oa_service_principal_handoff=pass tables=4 target=S126 next=1248"
    )
    assert handoff.main(["--summary"]) == 0
    assert "handoff=pass" in capsys.readouterr().out
    assert handoff.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        handoff,
        "run_oa_service_principal_handoff",
        lambda: {"status": "FAIL", "handoff": {}, "next_slice": "1248"},
    )
    assert handoff.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
