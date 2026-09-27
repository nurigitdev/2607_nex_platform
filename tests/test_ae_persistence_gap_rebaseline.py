from __future__ import annotations

from pathlib import Path

from nex_ae_api.persistence_audit import (
    PERSISTENCE_SURFACES,
    PersistenceSurface,
    _inspect_surface,
    build_ae_persistence_gap_rebaseline,
)
import run_ae_persistence_gap_rebaseline as runner


def test_repository_persistence_rebaseline_classifies_current_state() -> None:
    result = build_ae_persistence_gap_rebaseline()

    assert result["status"] == "PASS"
    assert result["checkpoint_status"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "surface_count": 15,
        "postgres_ready_count": 6,
        "delegated_count": 2,
        "gap_count": 7,
        "evidence_issue_count": 0,
    }
    assert result["decision"]["schema_decision_required_count"] == 4
    assert result["decision"]["adapter_only_gap_count"] == 2
    assert result["decision"]["runtime_configuration_gap_count"] == 1
    assert result["decision"]["new_table_required_now"] is False


def test_rebaseline_keeps_delegated_oa_and_cx_boundaries_table_free() -> None:
    result = build_ae_persistence_gap_rebaseline()
    delegated = {
        item["surface_id"]: item
        for item in result["surfaces"]
        if item["persistence_status"] == "DELEGATED_SYSTEM_OF_RECORD"
    }

    assert set(delegated) == {"document_library", "browser_auth_sessions"}
    assert {item["owner"] for item in delegated.values()} == {"nex-cx", "nex-oa"}
    assert all(item["target_tables"] == [] for item in delegated.values())


def test_rebaseline_fails_closed_for_missing_runtime_and_migration(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime.py"
    runtime.write_text("wrong token\n", encoding="utf-8")
    surfaces = (
        PersistenceSurface(
            "missing",
            "nex-ae-api",
            "runtime.py",
            "expected token",
            "POSTGRES_ADAPTER_READY",
            None,
            ("ae_missing",),
            "missing.sql",
            "ae_missing",
        ),
    )

    result = build_ae_persistence_gap_rebaseline(tmp_path, surfaces=surfaces)

    assert result["status"] == "FAIL"
    assert result["checkpoint_status"] == "BLOCKED"
    assert result["checks"]["surface_inventory_complete"] is False
    assert result["checks"]["runtime_and_migration_evidence_present"] is False
    assert result["summary"]["evidence_issue_count"] == 1
    assert result["issues"][0]["path"] == "runtime.py"


def test_surface_inspection_covers_runtime_and_migration_failures(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime.py"
    migration = tmp_path / "migration.sql"
    runtime.write_text("runtime token\n", encoding="utf-8")
    migration.write_text("table token\n", encoding="utf-8")
    surface = PersistenceSurface(
        "sample",
        "nex-ae-api",
        "runtime.py",
        "runtime token",
        "POSTGRES_ADAPTER_READY",
        None,
        ("table",),
        "migration.sql",
        "table token",
    )

    assert _inspect_surface(tmp_path, surface)["evidence_present"] is True
    migration.write_text("wrong\n", encoding="utf-8")
    assert _inspect_surface(tmp_path, surface)["failed_path"] == "migration.sql"
    runtime.write_text("wrong\n", encoding="utf-8")
    assert _inspect_surface(tmp_path, surface)["failed_path"] == "runtime.py"


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_ae_persistence_gap_rebaseline()

    assert "rebaseline=pass" in runner.summary_line(passing)
    assert "gaps=7" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_ae_persistence_gap_rebaseline", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "postgres_ready=6" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_ae_persistence_gap_rebaseline", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "rebaseline=fail" in capsys.readouterr().out


def test_surface_inventory_ids_are_unique() -> None:
    ids = [surface.surface_id for surface in PERSISTENCE_SURFACES]
    assert len(ids) == 15
    assert len(ids) == len(set(ids))
