from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


ROLLOUT_UNITS = (
    "shared_verifier_and_oa_issuer",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-ag",
)
ROLLOUT_PROFILE_ORDER = ("TEST_MOCK", "DUAL_READ", "SIGNED_ONLY")


@dataclass(frozen=True)
class TokenRolloutProfile:
    name: str
    environment_scope: str
    issue_signed_tokens: bool
    issue_mock_tokens: bool
    accept_signed_tokens: bool
    accept_mock_tokens: bool
    silent_mock_fallback_allowed: bool
    legacy_mock_allowlist_required: bool
    compatibility_deadline_required: bool

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


TOKEN_ROLLOUT_PROFILES = {
    "TEST_MOCK": TokenRolloutProfile(
        name="TEST_MOCK",
        environment_scope="explicit_test_only",
        issue_signed_tokens=False,
        issue_mock_tokens=True,
        accept_signed_tokens=False,
        accept_mock_tokens=True,
        silent_mock_fallback_allowed=False,
        legacy_mock_allowlist_required=False,
        compatibility_deadline_required=False,
    ),
    "DUAL_READ": TokenRolloutProfile(
        name="DUAL_READ",
        environment_scope="controlled_migration",
        issue_signed_tokens=True,
        issue_mock_tokens=False,
        accept_signed_tokens=True,
        accept_mock_tokens=True,
        silent_mock_fallback_allowed=False,
        legacy_mock_allowlist_required=True,
        compatibility_deadline_required=True,
    ),
    "SIGNED_ONLY": TokenRolloutProfile(
        name="SIGNED_ONLY",
        environment_scope="production_target",
        issue_signed_tokens=True,
        issue_mock_tokens=False,
        accept_signed_tokens=True,
        accept_mock_tokens=False,
        silent_mock_fallback_allowed=False,
        legacy_mock_allowlist_required=False,
        compatibility_deadline_required=False,
    ),
}

_COMMON_SIGNED_CONTROLS = (
    "jwks_ready",
    "introspection_ready",
    "service_principal_ready",
    "outbound_signed_token_ready",
    "audience_scope_mapping_reviewed",
    "negative_auth_tests_passed",
    "telemetry_redacted",
    "mock_fallback_disabled",
)


def allowed_rollout_transition(current: str, target: str) -> bool:
    if current not in ROLLOUT_PROFILE_ORDER or target not in ROLLOUT_PROFILE_ORDER:
        return False
    return ROLLOUT_PROFILE_ORDER.index(target) == ROLLOUT_PROFILE_ORDER.index(current) + 1


def validate_rollout_admission(
    *,
    unit: str,
    profile_name: str,
    controls: Mapping[str, Any],
    completed_units: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    errors: list[str] = []
    if unit not in ROLLOUT_UNITS:
        return ("rollout_unit_unknown",)
    profile = TOKEN_ROLLOUT_PROFILES.get(profile_name)
    if profile is None:
        return ("rollout_profile_unknown",)

    unit_index = ROLLOUT_UNITS.index(unit)
    required_predecessors = ROLLOUT_UNITS[:unit_index]
    missing_predecessors = [
        predecessor
        for predecessor in required_predecessors
        if predecessor not in completed_units
    ]
    errors.extend(
        f"rollout_predecessor_incomplete:{name}" for name in missing_predecessors
    )

    if profile_name == "TEST_MOCK":
        if controls.get("test_environment") is not True:
            errors.append("rollout_test_environment_required")
        if controls.get("production_environment") is True:
            errors.append("rollout_mock_profile_forbidden_in_production")
        return tuple(errors)

    for control in _COMMON_SIGNED_CONTROLS:
        if controls.get(control) is not True:
            errors.append(f"rollout_control_required:{control}")
    if profile_name == "DUAL_READ":
        if controls.get("legacy_mock_callers_allowlisted") is not True:
            errors.append("rollout_legacy_allowlist_required")
        if controls.get("compatibility_deadline_set") is not True:
            errors.append("rollout_compatibility_deadline_required")
        if not _positive_integer(controls.get("legacy_mock_caller_count")):
            errors.append("rollout_legacy_caller_count_invalid")
    else:
        if controls.get("legacy_mock_acceptance_disabled") is not True:
            errors.append("rollout_legacy_acceptance_must_be_disabled")
        if controls.get("legacy_mock_caller_count") != 0:
            errors.append("rollout_legacy_calls_must_be_zero")
    return tuple(errors)


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
