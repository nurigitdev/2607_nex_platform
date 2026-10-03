from __future__ import annotations

import json

from nex_oa.signed_token_lifecycle_boundary import (
    S127_SIGNED_TOKEN_BOUNDARY,
    implementation_owner_for_table,
    validate_signed_token_boundary,
)
import run_oa_signed_token_lifecycle_boundary as boundary_runner


def test_s127_signed_token_boundary_is_frozen() -> None:
    wire = S127_SIGNED_TOKEN_BOUNDARY.to_wire()

    assert validate_signed_token_boundary(wire) == ()
    assert wire["owned_tables"] == ("oa_signing_keys", "oa_token_revocations")
    assert wire["token_profile"] == "service_access"
    assert wire["algorithm"] == "RS256"
    assert wire["minimum_rsa_bits"] == 3072
    assert wire["maximum_token_ttl_seconds"] == 300
    assert wire["actual_postgres_smoke_slice"] == "1270"


def test_boundary_validation_fails_closed_for_all_drift_classes() -> None:
    wire = S127_SIGNED_TOKEN_BOUNDARY.to_wire()
    wire.pop("owner")
    for name in (
        "requirement",
        "token_profile",
        "grant_type",
        "algorithm",
        "minimum_rsa_bits",
        "maximum_token_ttl_seconds",
        "private_key_custody",
        "revocation_identifier_storage",
        "actual_postgres_smoke_slice",
        "checkpoint_slice",
        "full_gate_slice",
    ):
        wire[name] = "invalid"
    for name in (
        "private_key_database_storage_allowed",
        "raw_token_persistence_allowed",
        "raw_token_logging_allowed",
        "cross_service_database_reads_allowed",
        "remote_model_provider_required",
    ):
        wire[name] = True
    wire["owned_tables"] = ("oa_service_principals",)
    wire["predecessor_tables"] = ("oa_service_principals",)
    wire["slice_order"] = ("1262",)

    errors = validate_signed_token_boundary(wire)

    assert "field_missing:owner" in errors
    assert "owner_invalid" in errors
    assert "algorithm_invalid" in errors
    assert "private_key_database_storage_allowed_must_be_false" in errors
    assert "raw_token_persistence_allowed_must_be_false" in errors
    assert "owned_tables_invalid" in errors
    assert "predecessor_tables_invalid" in errors
    assert "table_ownership_overlap" in errors
    assert "slice_order_invalid" in errors


def test_table_implementation_ownership_is_unambiguous() -> None:
    assert implementation_owner_for_table("oa_service_creds") == "S126"
    assert implementation_owner_for_table("oa_signing_keys") == "S127"
    assert implementation_owner_for_table("unknown") is None


def test_boundary_runner_passes_and_reports_scope() -> None:
    evidence = boundary_runner.run_oa_signed_token_lifecycle_boundary()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert 0 <= evidence["existing_signed_runtime_table_count"] <= 2
    assert boundary_runner.summary_line(evidence) == (
        "oa_signed_token_lifecycle_boundary=pass tables=2 "
        "algorithm=RS256 next=1263"
    )


def test_boundary_runner_detects_premature_runtime_migration(tmp_path) -> None:
    migrations = tmp_path / "database/nex-oa/migrations"
    migrations.mkdir(parents=True)
    (migrations / "future.sql").write_text(
        "CREATE TABLE oa_signing_keys ();",
        encoding="utf-8",
    )

    evidence = boundary_runner.run_oa_signed_token_lifecycle_boundary(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "oa_signed_token_boundary_failed"
    assert evidence["checks"]["signed_runtime_not_preimplemented"] is False


def test_boundary_runner_main_covers_output_modes(monkeypatch, capsys) -> None:
    assert boundary_runner.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary_runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        boundary_runner,
        "run_oa_signed_token_lifecycle_boundary",
        lambda: {"status": "FAIL", "boundary": {}, "next_slice": "1263"},
    )
    assert boundary_runner.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
