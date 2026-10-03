from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_runtime.signed_token_adoption_boundary import (
    S128_CONSUMER_SERVICES,
    S128_ROLLOUT_PROFILES,
    S128_ROLLOUT_UNITS,
    S128_SIGNED_TOKEN_ADOPTION_BOUNDARY,
    adoption_owner_for_service,
    validate_signed_token_adoption_boundary,
)
import run_platform_signed_token_adoption_boundary as runner


def test_s128_boundary_freezes_platform_adoption() -> None:
    boundary = S128_SIGNED_TOKEN_ADOPTION_BOUNDARY

    assert validate_signed_token_adoption_boundary(boundary.to_wire()) == ()
    assert boundary.consumer_services == S128_CONSUMER_SERVICES
    assert boundary.rollout_units == S128_ROLLOUT_UNITS
    assert boundary.rollout_profiles == S128_ROLLOUT_PROFILES
    assert boundary.primary_verification == "local_jwks_signature_and_claim_validation"
    assert boundary.sensitive_route_check == "oa_introspection"
    assert boundary.deferred_token_profiles == ("delegated_user_access",)
    assert boundary.actual_postgres_smoke_slice == "1280"
    assert boundary.checkpoint_slice == "1276"
    assert boundary.full_gate_slice == "1281"
    assert boundary.slice_order == tuple(str(number) for number in range(1272, 1282))


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("owner", "nex-oa", "owner_invalid"),
        ("issuer_service", "nex-cx", "issuer_service_invalid"),
        ("algorithm", "HS256", "algorithm_invalid"),
        ("silent_mock_fallback_allowed", True, "silent_mock_fallback_allowed_must_be_false"),
        ("cross_service_database_reads_allowed", True, "cross_service_database_reads_allowed_must_be_false"),
        ("new_database_tables_required", True, "new_database_tables_required_must_be_false"),
        ("remote_model_provider_required", True, "remote_model_provider_required_must_be_false"),
        ("consumer_services", ("nex-cx",), "consumer_services_invalid"),
        ("rollout_units", ("nex-cx",), "rollout_units_invalid"),
        ("rollout_profiles", ("SIGNED_ONLY",), "rollout_profiles_invalid"),
        ("deferred_token_profiles", (), "deferred_token_profiles_invalid"),
        ("slice_order", ("1272",), "slice_order_invalid"),
    ),
)
def test_boundary_rejects_drift(field: str, value: object, error: str) -> None:
    payload = replace(S128_SIGNED_TOKEN_ADOPTION_BOUNDARY, **{field: value}).to_wire()

    assert error in validate_signed_token_adoption_boundary(payload)


def test_boundary_reports_missing_fields_and_adoption_ownership() -> None:
    errors = validate_signed_token_adoption_boundary({})

    assert "field_missing:owner" in errors
    assert adoption_owner_for_service("nex-oa") == "issuer"
    assert adoption_owner_for_service("nex-cx") == "consumer"
    assert adoption_owner_for_service("unknown") is None


def test_repository_boundary_audit_passes() -> None:
    evidence = runner.run_platform_signed_token_adoption_boundary()

    assert evidence["status"] == "PASS"
    assert evidence["issues"] == []
    assert all(evidence["checks"].values())
    assert set(evidence["consumer_apps"]) == set(S128_CONSUMER_SERVICES)
    assert all(evidence["consumer_apps"].values())
    assert evidence["mock_fallback_file_count"] > 0
    assert evidence["next_slice"] == "1273"


def test_boundary_audit_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    evidence = runner.run_platform_signed_token_adoption_boundary(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "platform_signed_token_adoption_boundary_failed"
    assert evidence["checks"]["required_evidence_present"] is False
    assert evidence["checks"]["all_consumer_app_shells_present"] is False
    assert evidence["checks"]["mock_fallback_debt_explicit"] is False
    assert len(evidence["issues"]) == len(runner.REQUIRED_EVIDENCE) + len(S128_CONSUMER_SERVICES)


def test_boundary_runner_helpers_and_cli(monkeypatch, capsys, tmp_path: Path) -> None:
    assert runner._read_text(tmp_path / "missing") == ""
    assert runner._mock_fallback_files(tmp_path) == ()
    passing = runner.run_platform_signed_token_adoption_boundary()
    assert runner.summary_line(passing).startswith("platform_signed_token_adoption_boundary=pass")
    monkeypatch.setattr(runner, "run_platform_signed_token_adoption_boundary", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "next=1273" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_platform_signed_token_adoption_boundary",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
