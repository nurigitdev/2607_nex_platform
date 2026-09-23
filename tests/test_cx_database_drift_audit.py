from __future__ import annotations

from pathlib import Path

from nex_cx.database_drift_audit import (
    _declared_table_names,
    _sql_identifiers,
    build_cx_database_drift_audit,
)
import run_cx_database_drift_audit as runner


def test_repository_database_drift_audit_passes_static_chain() -> None:
    result = build_cx_database_drift_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"]["migration_count"] == 21
    assert result["summary"]["core_table_count"] == 19
    assert result["summary"]["longest_identifier_length"] <= 63
    assert result["migration_strategy"] == {
        "canonical": "versioned_sql_schema_migrations_runner",
        "alembic_status": "NOT_CONFIGURED",
        "alembic_config_builder_present": True,
        "decision_required_before_next_schema_change": True,
        "policy": "keep_exactly_one_canonical_migration_history",
    }
    assert result["actual_database_comparison"]["status"] == (
        "DEFERRED_TO_SLICE_0909"
    )


def test_sql_identifier_parser_handles_tables_indexes_constraints_and_rename() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS cx_old (id TEXT CONSTRAINT ck_short CHECK (id <> ''));
    CREATE UNIQUE INDEX IF NOT EXISTS ux_cx_old_id ON cx_old (id);
    ALTER TABLE cx_old RENAME TO cx_new;
    """

    assert _sql_identifiers(sql) == {"cx_old", "ck_short", "ux_cx_old_id"}
    assert _declared_table_names(sql) == {"cx_old", "cx_new"}


def test_database_drift_audit_fails_closed_without_repository(tmp_path: Path) -> None:
    result = build_cx_database_drift_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "cx_database_drift_audit_failed"
    assert result["checks"]["migration_count_expected"] is False
    assert result["checks"]["core_tables_declared"] is False
    assert result["checks"]["repository_core_table_refs_complete"] is False
    assert result["checks"]["migration_runner_ready"] is False
    assert result["summary"]["issue_count"] == 3


def test_database_drift_audit_reports_malformed_migration(tmp_path: Path) -> None:
    migration_dir = tmp_path / "database/nex-cx/migrations"
    migration_dir.mkdir(parents=True)
    overlength = "idx_" + ("x" * 64)
    (migration_dir / "0001_bad.sql").write_text(
        "CREATE TABLE cx_partial (id TEXT);\n"
        f"CREATE INDEX {overlength} ON cx_partial (id);\n",
        encoding="utf-8",
    )

    result = build_cx_database_drift_audit(tmp_path)

    assert result["status"] == "FAIL"
    categories = {item["category"] for item in result["issues"]}
    assert "migration_ledger_missing" in categories
    assert "migration_transaction_missing" in categories
    assert "identifier_too_long" in categories
    assert overlength in result["overlength_identifiers"]


def test_summary_line_and_runner_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_cx_database_drift_audit()

    assert "drift_audit=pass" in runner.summary_line(passing)
    assert "migrations=21" in runner.summary_line(passing)
    assert "alembic=NOT_CONFIGURED" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_cx_database_drift_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "issues=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_cx_database_drift_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
