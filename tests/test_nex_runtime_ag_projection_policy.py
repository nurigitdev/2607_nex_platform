from __future__ import annotations

import pytest

from nex_runtime.ag_projection_policy import (
    AgProjectionPolicyError,
    resolve_ag_projection_policy,
)


def test_unmanaged_runtime_preserves_legacy_postgres_compatibility() -> None:
    policy = resolve_ag_projection_policy("postgres", environ={})

    assert policy.managed_profile is None
    assert policy.expected_mode is None
    assert policy.protected is False
    assert policy.legacy_database_adapter_allowed is True


@pytest.mark.parametrize(
    ("profile", "mode", "protected"),
    [("local_mock", "memory", False), ("test", "api", True)],
)
def test_managed_runtime_requires_profile_projection_mode(
    profile: str, mode: str, protected: bool
) -> None:
    policy = resolve_ag_projection_policy(
        mode,
        environ={"NEX_PROFILE": f" {profile} "},
    )

    assert policy.expected_mode == mode
    assert policy.protected is protected
    assert policy.legacy_database_adapter_allowed is False
    assert policy.to_public_projection()["legacy_database_adapter_allowed"] is False


def test_managed_runtime_rejects_legacy_database_adapter() -> None:
    with pytest.raises(AgProjectionPolicyError, match="requires AG projection mode api"):
        resolve_ag_projection_policy(
            "postgres",
            environ={"NEX_PROFILE": "production"},
        )


def test_unknown_managed_profile_fails_closed() -> None:
    with pytest.raises(AgProjectionPolicyError, match="unsupported managed"):
        resolve_ag_projection_policy("memory", environ={"NEX_PROFILE": "preview"})

