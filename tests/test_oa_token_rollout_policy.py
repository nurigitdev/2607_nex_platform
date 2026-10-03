from __future__ import annotations

from nex_oa.token_rollout_policy import (
    ROLLOUT_UNITS,
    TOKEN_ROLLOUT_PROFILES,
    allowed_rollout_transition,
    validate_rollout_admission,
)


def _signed_controls(**changes: object) -> dict[str, object]:
    return {
        "jwks_ready": True,
        "introspection_ready": True,
        "service_principal_ready": True,
        "outbound_signed_token_ready": True,
        "audience_scope_mapping_reviewed": True,
        "negative_auth_tests_passed": True,
        "telemetry_redacted": True,
        "mock_fallback_disabled": True,
    } | changes


def test_rollout_profiles_freeze_explicit_compatibility_boundaries() -> None:
    assert set(TOKEN_ROLLOUT_PROFILES) == {
        "TEST_MOCK",
        "DUAL_READ",
        "SIGNED_ONLY",
    }
    test_mock = TOKEN_ROLLOUT_PROFILES["TEST_MOCK"]
    dual = TOKEN_ROLLOUT_PROFILES["DUAL_READ"]
    signed = TOKEN_ROLLOUT_PROFILES["SIGNED_ONLY"]

    assert test_mock.environment_scope == "explicit_test_only"
    assert dual.issue_mock_tokens is False
    assert dual.accept_mock_tokens is True
    assert dual.legacy_mock_allowlist_required is True
    assert dual.compatibility_deadline_required is True
    assert signed.accept_mock_tokens is False
    assert all(
        not profile.silent_mock_fallback_allowed
        for profile in TOKEN_ROLLOUT_PROFILES.values()
    )
    assert signed.to_wire()["environment_scope"] == "production_target"


def test_rollout_transitions_are_forward_only() -> None:
    assert allowed_rollout_transition("TEST_MOCK", "DUAL_READ") is True
    assert allowed_rollout_transition("DUAL_READ", "SIGNED_ONLY") is True
    assert allowed_rollout_transition("SIGNED_ONLY", "DUAL_READ") is False
    assert allowed_rollout_transition("TEST_MOCK", "SIGNED_ONLY") is False
    assert allowed_rollout_transition("UNKNOWN", "DUAL_READ") is False
    assert allowed_rollout_transition("DUAL_READ", "UNKNOWN") is False


def test_explicit_test_mock_profile_is_admitted_only_outside_production() -> None:
    assert validate_rollout_admission(
        unit=ROLLOUT_UNITS[0],
        profile_name="TEST_MOCK",
        controls={"test_environment": True, "production_environment": False},
        completed_units=(),
    ) == ()
    errors = validate_rollout_admission(
        unit=ROLLOUT_UNITS[0],
        profile_name="TEST_MOCK",
        controls={"test_environment": False, "production_environment": True},
        completed_units=(),
    )
    assert errors == (
        "rollout_test_environment_required",
        "rollout_mock_profile_forbidden_in_production",
    )


def test_dual_read_requires_controls_allowlist_deadline_and_legacy_callers() -> None:
    controls = _signed_controls(
        legacy_mock_callers_allowlisted=True,
        compatibility_deadline_set=True,
        legacy_mock_caller_count=20,
    )
    assert validate_rollout_admission(
        unit="nex-ae-api",
        profile_name="DUAL_READ",
        controls=controls,
        completed_units=(ROLLOUT_UNITS[0],),
    ) == ()

    errors = validate_rollout_admission(
        unit="nex-ae-api",
        profile_name="DUAL_READ",
        controls=_signed_controls(legacy_mock_caller_count=True),
        completed_units=(ROLLOUT_UNITS[0],),
    )
    assert "rollout_legacy_allowlist_required" in errors
    assert "rollout_compatibility_deadline_required" in errors
    assert "rollout_legacy_caller_count_invalid" in errors


def test_signed_only_requires_zero_legacy_calls_and_disabled_acceptance() -> None:
    controls = _signed_controls(
        legacy_mock_acceptance_disabled=True,
        legacy_mock_caller_count=0,
    )
    assert validate_rollout_admission(
        unit="nex-cx",
        profile_name="SIGNED_ONLY",
        controls=controls,
        completed_units=ROLLOUT_UNITS[:2],
    ) == ()

    errors = validate_rollout_admission(
        unit="nex-cx",
        profile_name="SIGNED_ONLY",
        controls=_signed_controls(legacy_mock_caller_count=1),
        completed_units=ROLLOUT_UNITS[:2],
    )
    assert "rollout_legacy_acceptance_must_be_disabled" in errors
    assert "rollout_legacy_calls_must_be_zero" in errors


def test_unknown_unit_profile_predecessor_and_common_controls_fail_closed() -> None:
    assert validate_rollout_admission(
        unit="unknown",
        profile_name="SIGNED_ONLY",
        controls={},
        completed_units=(),
    ) == ("rollout_unit_unknown",)
    assert validate_rollout_admission(
        unit=ROLLOUT_UNITS[0],
        profile_name="unknown",
        controls={},
        completed_units=(),
    ) == ("rollout_profile_unknown",)

    errors = validate_rollout_admission(
        unit="nex-ag",
        profile_name="SIGNED_ONLY",
        controls={},
        completed_units=(ROLLOUT_UNITS[0],),
    )
    assert "rollout_predecessor_incomplete:nex-ae-api" in errors
    assert "rollout_predecessor_incomplete:nex-mo" in errors
    assert "rollout_control_required:jwks_ready" in errors
    assert "rollout_control_required:mock_fallback_disabled" in errors
