from __future__ import annotations

import pytest

import run_postgres_backup_operator as cli
from nex_runtime.postgres_operator import PostgresOperatorCheck


READY = {
    "schema_version": "postgres_operator_check.v1",
    "state": "READY",
    "postgres_major": 16,
    "tool_count": 3,
    "non_root": True,
    "separate_mount_attested": True,
    "credential_source_count": 2,
}


def test_operator_cli_check_summary_and_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "run_check", lambda: READY)
    assert cli.main(["--check", "--summary"]) == 0
    assert "postgres_operator_check=pass postgres=16 tools=3 credentials=2" in capsys.readouterr().out
    assert cli.main(["--check"]) == 0
    assert '"state": "READY"' in capsys.readouterr().out


def test_operator_run_check_projects_runtime_result(monkeypatch) -> None:
    checked = PostgresOperatorCheck(
        schema_version="postgres_operator_check.v1",
        state="READY",
        postgres_major=16,
        tool_count=3,
        non_root=True,
        separate_mount_attested=True,
        credential_source_count=2,
    )
    monkeypatch.setattr(
        cli,
        "check_postgres_operator_runtime",
        lambda environment: checked if environment == {"MODE": "test"} else None,
    )
    assert cli.run_check({"MODE": "test"}) == READY


def test_operator_cli_requires_explicit_check() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.main([])


def test_operator_summary_reports_failure() -> None:
    assert cli.summary_line({"state": "FAILED"}).startswith("postgres_operator_check=fail")
