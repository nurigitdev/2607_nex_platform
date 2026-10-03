from __future__ import annotations

import json

from nex_oa.service_principal_lifecycle_boundary import (
    S126_LIFECYCLE_BOUNDARY,
    implementation_owner_for_table,
    validate_lifecycle_boundary,
)
import run_oa_service_principal_lifecycle_boundary as boundary_runner


def test_s126_lifecycle_boundary_is_frozen() -> None:
    wire = S126_LIFECYCLE_BOUNDARY.to_wire()

    assert validate_lifecycle_boundary(wire) == ()
    assert wire["lifecycle_tables"] == (
        "oa_service_principals",
        "oa_service_creds",
    )
    assert wire["deferred_requirement"] == "S127"
    assert wire["actual_postgres_smoke_slice"] == "1260"


def test_boundary_validation_fails_closed_for_drift_and_missing_fields() -> None:
    wire = S126_LIFECYCLE_BOUNDARY.to_wire()
    wire.pop("owner")
    wire.update(
        requirement="S999",
        lifecycle_tables=("oa_signing_keys",),
        deferred_requirement="S126",
        deferred_tables=("oa_signing_keys",),
        slice_order=("1252",),
        actual_postgres_smoke_slice="1259",
        checkpoint_slice="1255",
        full_gate_slice="1260",
    )

    errors = validate_lifecycle_boundary(wire)

    assert "field_missing:owner" in errors
    assert "owner_invalid" in errors
    assert "requirement_invalid" in errors
    assert "lifecycle_tables_invalid" in errors
    assert "deferred_requirement_invalid" in errors
    assert "deferred_tables_invalid" in errors
    assert "table_ownership_overlap" in errors
    assert "slice_order_invalid" in errors
    assert "postgres_smoke_slice_invalid" in errors
    assert "checkpoint_slice_invalid" in errors
    assert "full_gate_slice_invalid" in errors


def test_table_implementation_ownership_is_unambiguous() -> None:
    assert implementation_owner_for_table("oa_service_principals") == "S126"
    assert implementation_owner_for_table("oa_signing_keys") == "S127"
    assert implementation_owner_for_table("oa_users") is None


def test_boundary_runner_passes_and_reports_refined_scope() -> None:
    evidence = boundary_runner.run_oa_service_principal_lifecycle_boundary()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert 0 <= evidence["existing_lifecycle_table_count"] <= 2
    assert boundary_runner.summary_line(evidence) == (
        "oa_service_principal_lifecycle_boundary=pass "
        "owned_tables=2 deferred=S127 next=1253"
    )


def test_boundary_runner_detects_deferred_runtime_migration(tmp_path) -> None:
    migrations = tmp_path / "database/nex-oa/migrations"
    migrations.mkdir(parents=True)
    (migrations / "future.sql").write_text(
        "CREATE TABLE oa_signing_keys ();",
        encoding="utf-8",
    )

    evidence = boundary_runner.run_oa_service_principal_lifecycle_boundary(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "oa_service_principal_boundary_failed"
    assert evidence["checks"]["deferred_runtime_not_implemented_in_s126"] is False


def test_boundary_runner_main_covers_output_modes(monkeypatch, capsys) -> None:
    assert boundary_runner.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary_runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        boundary_runner,
        "run_oa_service_principal_lifecycle_boundary",
        lambda: {"status": "FAIL", "boundary": {}, "next_slice": "1253"},
    )
    assert boundary_runner.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
