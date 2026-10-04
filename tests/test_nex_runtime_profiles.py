from __future__ import annotations

import pytest

import nex_runtime.runtime_profiles as profiles
from nex_runtime.runtime_profiles import (
    DATABASE_ENV_NAMES,
    LIVE_PROVIDER_ENV_NAMES,
    SERVICE_ENDPOINT_ENV_NAMES,
    SIGNED_TRUST_ENV_NAMES,
    TEST_DATABASE_ENV_NAMES,
    RuntimeProfileError,
    resolve_runtime_profile,
    runtime_profile_environment_overlay,
    runtime_profile_public_projection,
)
from nex_runtime.topology import RuntimeModes


def complete_environment(profile: str) -> dict[str, str]:
    env = runtime_profile_environment_overlay(profile)
    if profile == "local_mock":
        return env
    names = TEST_DATABASE_ENV_NAMES if profile == "test" else DATABASE_ENV_NAMES
    for name in (*names, *SERVICE_ENDPOINT_ENV_NAMES, *SIGNED_TRUST_ENV_NAMES):
        env[name] = "configured"
    if profile != "test":
        for name in LIVE_PROVIDER_ENV_NAMES:
            env[name] = "configured"
    return env


def test_local_mock_is_default_and_requires_no_external_configuration() -> None:
    result = resolve_runtime_profile(environ={})

    assert result.profile == "local_mock"
    assert result.protected is False
    assert result.required_environment_names == ()
    assert result.modes.persistence == "memory"
    assert runtime_profile_environment_overlay("local_mock") == {
        "NEX_PROFILE": "local_mock",
        "NEX_PERSISTENCE_MODE": "memory",
        "NEX_MO_PROVIDER_MODE": "mock",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        "NEX_AG_OPERATIONS_SOURCE_MODE": "memory",
    }


@pytest.mark.parametrize(
    ("profile", "provider", "database_names"),
    [
        ("test", "mock", TEST_DATABASE_ENV_NAMES),
        ("local_live", "live", DATABASE_ENV_NAMES),
        ("staging_live", "live", DATABASE_ENV_NAMES),
        ("production", "live", DATABASE_ENV_NAMES),
    ],
)
def test_protected_profiles_resolve_with_complete_configuration(
    profile, provider, database_names
) -> None:
    result = resolve_runtime_profile(profile, environ=complete_environment(profile))
    projection = runtime_profile_public_projection(result)

    assert result.protected is True
    assert result.modes.provider == provider
    assert result.modes.trust == "signed"
    assert result.modes.ag_projection == "api"
    assert set(database_names).issubset(result.required_environment_names)
    assert projection["required_environment_count"] == len(
        result.required_environment_names
    )
    assert "values" not in projection


def test_environment_profile_selection_and_whitespace() -> None:
    result = resolve_runtime_profile(environ={"NEX_PROFILE": " local_mock "})
    assert result.profile == "local_mock"


def test_process_environment_is_used_when_mapping_is_omitted(monkeypatch) -> None:
    monkeypatch.setenv("NEX_PROFILE", "local_mock")

    assert resolve_runtime_profile().profile == "local_mock"


def test_unknown_profile_is_rejected_by_resolver_and_overlay() -> None:
    with pytest.raises(RuntimeProfileError, match="unsupported runtime profile"):
        resolve_runtime_profile("preview", environ={})
    with pytest.raises(RuntimeProfileError, match="unsupported runtime profile"):
        runtime_profile_environment_overlay("preview")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NEX_PERSISTENCE_MODE", "postgres"),
        ("NEX_MO_PROVIDER_MODE", "live"),
        ("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "SIGNED_ONLY"),
        ("NEX_AG_OPERATIONS_SOURCE_MODE", "postgres"),
    ],
)
def test_local_mock_rejects_mode_conflicts(name, value) -> None:
    with pytest.raises(RuntimeProfileError, match=name):
        resolve_runtime_profile("local_mock", environ={name: value})


@pytest.mark.parametrize("value", [None, "", "  ", "<password>", "CHANGE-ME"])
def test_protected_profiles_reject_missing_and_placeholder_values(value) -> None:
    env = complete_environment("test")
    name = TEST_DATABASE_ENV_NAMES[0]
    if value is None:
        env.pop(name)
    else:
        env[name] = value

    with pytest.raises(RuntimeProfileError) as raised:
        resolve_runtime_profile("test", environ=env)

    assert name in str(raised.value)
    assert value not in raised.value.errors


def test_protected_profile_reports_all_missing_names_without_values() -> None:
    with pytest.raises(RuntimeProfileError) as raised:
        resolve_runtime_profile("production", environ={})

    assert len(raised.value.errors) == (
        len(DATABASE_ENV_NAMES)
        + len(SERVICE_ENDPOINT_ENV_NAMES)
        + len(SIGNED_TRUST_ENV_NAMES)
        + len(LIVE_PROVIDER_ENV_NAMES)
    )
    assert all("required environment" in error for error in raised.value.errors)


def test_protected_profile_defensively_rejects_non_api_projection(monkeypatch) -> None:
    env = complete_environment("production")
    monkeypatch.setitem(
        profiles.PROFILE_MODES,
        "production",
        RuntimeModes("postgres", "live", "signed", "legacy_postgres"),
    )
    env["NEX_AG_OPERATIONS_SOURCE_MODE"] = "legacy_postgres"

    with pytest.raises(RuntimeProfileError, match="service API projections"):
        resolve_runtime_profile("production", environ=env)
