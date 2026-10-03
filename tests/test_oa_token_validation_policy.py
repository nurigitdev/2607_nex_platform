from __future__ import annotations

import pytest

from nex_oa.token_validation_policy import (
    PRODUCTION_TOKEN_VALIDATION_POLICY,
    REVOCATION_SENSITIVE_ROUTE_CLASSES,
    TokenValidationDecision,
    build_token_validation_plan,
    evaluate_token_validation,
)


def test_validation_policy_freezes_cache_introspection_and_privacy() -> None:
    policy = PRODUCTION_TOKEN_VALIDATION_POLICY

    assert policy.jwks_cache_ttl_seconds == 300
    assert policy.unknown_kid_refresh_attempts == 1
    assert policy.introspection_timeout_seconds == 3
    assert set(policy.revocation_sensitive_route_classes) == {
        "WRITE",
        "ADMIN",
        "CREDENTIAL",
        "KEY_MANAGEMENT",
    }
    assert policy.stale_jwks_acceptance_allowed is False
    assert policy.introspection_error_acceptance_allowed is False
    assert policy.raw_token_logging_allowed is False
    assert policy.to_wire()["jwks_cache_ttl_seconds"] == 300


@pytest.mark.parametrize("route_class", sorted(REVOCATION_SENSITIVE_ROUTE_CLASSES))
def test_sensitive_routes_require_live_introspection(route_class: str) -> None:
    plan = build_token_validation_plan(
        route_class=route_class,
        kid_known=True,
        jwks_cache_age_seconds=300,
    )

    assert plan["introspection_required"] is True
    assert plan["jwks_refresh_required"] is False
    assert plan["jwks_refresh_attempts"] == 0
    assert plan["stale_cache_accepted_after_refresh_failure"] is False


@pytest.mark.parametrize(
    ("kid_known", "cache_age", "refresh"),
    [(True, 0, False), (True, 301, True), (False, 0, True)],
)
def test_jwks_refresh_plan_is_bounded(
    kid_known: bool, cache_age: int, refresh: bool
) -> None:
    plan = build_token_validation_plan(
        route_class="READ",
        kid_known=kid_known,
        jwks_cache_age_seconds=cache_age,
    )

    assert plan["jwks_refresh_required"] is refresh
    assert plan["jwks_refresh_attempts"] == (1 if refresh else 0)
    assert plan["introspection_required"] is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"route_class": "UNKNOWN", "kid_known": True, "jwks_cache_age_seconds": 0},
            "unsupported route class",
        ),
        (
            {"route_class": "READ", "kid_known": 1, "jwks_cache_age_seconds": 0},
            "kid_known must be a boolean",
        ),
        (
            {"route_class": "READ", "kid_known": True, "jwks_cache_age_seconds": -1},
            "non-negative integer",
        ),
        (
            {"route_class": "READ", "kid_known": True, "jwks_cache_age_seconds": True},
            "non-negative integer",
        ),
    ],
)
def test_invalid_plan_inputs_fail_closed(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_token_validation_plan(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("local_status", "reason"),
    [
        ("invalid_signature", "token_invalid_signature"),
        ("expired", "token_expired"),
        ("unknown_kid_after_refresh", "token_unknown_kid_after_refresh"),
        ("claim_invalid", "token_claim_invalid"),
    ],
)
def test_local_validation_failure_is_unauthorized(
    local_status: str, reason: str
) -> None:
    decision = evaluate_token_validation(
        route_class="ADMIN",
        local_status=local_status,
        scope_satisfied=True,
        introspection_status="active",
    )

    assert decision == TokenValidationDecision(False, 401, reason, True)


def test_scope_failure_is_forbidden_before_introspection() -> None:
    decision = evaluate_token_validation(
        route_class="WRITE",
        local_status="valid",
        scope_satisfied=False,
        introspection_status="active",
    )

    assert decision.to_wire() == {
        "accepted": False,
        "http_status": 403,
        "reason_code": "token_scope_insufficient",
        "introspection_required": True,
    }


@pytest.mark.parametrize(
    ("status", "http_status", "reason"),
    [
        ("active", 200, "token_accepted"),
        ("inactive", 401, "token_introspection_inactive"),
        ("unavailable", 503, "token_introspection_required_unavailable"),
        ("not_requested", 503, "token_introspection_required_unavailable"),
    ],
)
def test_sensitive_route_introspection_outcomes(
    status: str, http_status: int, reason: str
) -> None:
    decision = evaluate_token_validation(
        route_class="CREDENTIAL",
        local_status="valid",
        scope_satisfied=True,
        introspection_status=status,
    )

    assert decision.http_status == http_status
    assert decision.reason_code == reason
    assert decision.accepted is (status == "active")
    assert decision.introspection_required is True


@pytest.mark.parametrize(
    ("status", "http_status", "accepted"),
    [
        ("not_requested", 200, True),
        ("active", 200, True),
        ("inactive", 401, False),
        ("unavailable", 503, False),
    ],
)
def test_read_route_introspection_outcomes(
    status: str, http_status: int, accepted: bool
) -> None:
    decision = evaluate_token_validation(
        route_class="READ",
        local_status="valid",
        scope_satisfied=True,
        introspection_status=status,
    )

    assert decision.http_status == http_status
    assert decision.accepted is accepted
    assert decision.introspection_required is False


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"route_class": "UNKNOWN"}, "unsupported route class"),
        ({"local_status": "unknown"}, "unsupported local validation status"),
        ({"scope_satisfied": 1}, "scope_satisfied must be a boolean"),
        ({"introspection_status": "unknown"}, "unsupported introspection status"),
    ],
)
def test_invalid_outcome_inputs_fail_closed(
    changes: dict[str, object], message: str
) -> None:
    kwargs: dict[str, object] = {
        "route_class": "READ",
        "local_status": "valid",
        "scope_satisfied": True,
        "introspection_status": "not_requested",
    } | changes
    with pytest.raises(ValueError, match=message):
        evaluate_token_validation(**kwargs)  # type: ignore[arg-type]
