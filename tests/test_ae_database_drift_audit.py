from __future__ import annotations

from pathlib import Path

from nex_ae_api.database_drift_audit import (
    _declared_table_names,
    _sql_identifiers,
    build_ae_database_drift_audit,
)
import run_ae_database_drift_audit as runner


def test_repository_database_drift_audit_classifies_identifier_drift() -> None:
    result = build_ae_database_drift_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"]["migration_count"] == 22
    assert result["summary"]["core_table_count"] == 15
    assert result["summary"]["overlength_identifier_count"] > 0
    assert result["summary"]["drift_finding_count"] == 1
    assert result["database_readiness"] == (
        "STATIC_CHAIN_VALID_DRIFT_REMEDIATION_REQUIRED"
    )
    assert result["actual_database_comparison"]["status"] == (
        "DEFERRED_TO_SLICE_1010"
    )


def test_identifier_parser_handles_multiline_index_and_constraint() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS ae_one (
        id TEXT CONSTRAINT ck_ae_one_id CHECK (id <> '')
    );
    CREATE UNIQUE INDEX IF NOT EXISTS
        ux_ae_one_id
        ON ae_one (id);
    """

    assert _sql_identifiers(sql) == {"ae_one", "ck_ae_one_id", "ux_ae_one_id"}
    assert _declared_table_names(sql) == {"ae_one"}


def test_database_drift_audit_fails_closed_without_repository(
    tmp_path: Path,
) -> None:
    result = build_ae_database_drift_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "ae_database_drift_audit_failed"
    assert result["checks"]["migration_count_expected"] is False
    assert result["checks"]["core_tables_declared"] is False
    assert result["checks"]["repository_core_table_refs_complete"] is False
    assert result["checks"]["migration_runner_ready"] is False
    assert result["summary"]["evidence_issue_count"] == 3


def test_database_drift_audit_reports_malformed_migration(tmp_path: Path) -> None:
    migration_dir = tmp_path / "database/nex-ae-api/migrations"
    migration_dir.mkdir(parents=True)
    overlength = "idx_" + ("x" * 64)
    (migration_dir / "0001_bad.sql").write_text(
        "CREATE TABLE ae_partial (id TEXT);\n"
        f"CREATE INDEX {overlength} ON ae_partial (id);\n",
        encoding="utf-8",
    )

    result = build_ae_database_drift_audit(tmp_path)

    assert result["status"] == "FAIL"
    categories = {item["category"] for item in result["issues"]}
    assert "migration_ledger_missing" in categories
    assert "migration_transaction_missing" in categories
    assert overlength in result["overlength_identifiers"]
    assert result["drift_findings"][0]["risk"] == "MEDIUM"


def test_summary_line_and_runner_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_ae_database_drift_audit()

    assert "database_drift_audit=pass" in runner.summary_line(passing)
    assert "migrations=22" in runner.summary_line(passing)
    assert "alembic=NOT_CONFIGURED" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_ae_database_drift_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "issues=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_ae_database_drift_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
