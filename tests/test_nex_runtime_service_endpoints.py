from __future__ import annotations

import pytest

from nex_runtime.service_endpoints import (
    DEFAULT_CX_MO_TIMEOUT_SECONDS,
    RuntimeEndpointPolicyError,
    resolve_cx_mo_timeout_budget,
    resolve_service_endpoint,
)


def test_service_endpoints_resolve_defaults_and_safe_override() -> None:
    default = resolve_service_endpoint("nex-mo", environ={})
    override = resolve_service_endpoint(
        "nex-mo", environ={"NEX_MO_BASE_URL": "https://mo.internal:9443/"}
    )

    assert default.base_url == "http://127.0.0.1:8105"
    assert default.environment_name == "NEX_MO_BASE_URL"
    assert override.base_url == "https://mo.internal:9443"


def test_service_endpoint_uses_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("NEX_CX_BASE_URL", "http://cx.internal:8104")
    assert resolve_service_endpoint("nex-cx").base_url == "http://cx.internal:8104"


@pytest.mark.parametrize(
    "value",
    [
        "ftp://host",
        "http://user:password@host",
        "http://host/path",
        "http://host?token=value",
        "http://host#fragment",
        "http://[invalid",
        "http://host:70000",
    ],
)
def test_service_endpoint_rejects_unsafe_values(value) -> None:
    with pytest.raises(RuntimeEndpointPolicyError, match="invalid service endpoint"):
        resolve_service_endpoint("nex-mo", environ={"NEX_MO_BASE_URL": value})


def test_unknown_service_endpoint_is_rejected() -> None:
    with pytest.raises(RuntimeEndpointPolicyError, match="unsupported service endpoint"):
        resolve_service_endpoint("nex-unknown", environ={})


@pytest.mark.parametrize(
    ("capability", "minimum", "client"),
    [
        ("embedding", 60.0, 60.0),
        ("reranking", 60.0, 60.0),
        ("generation", 130.0, 130.0),
    ],
)
def test_default_timeout_budgets_cover_upstream_retries(capability, minimum, client) -> None:
    result = resolve_cx_mo_timeout_budget(capability, environ={})

    assert result.minimum_client_timeout_seconds == minimum
    assert result.client_timeout_seconds == client
    assert DEFAULT_CX_MO_TIMEOUT_SECONDS[capability] == client


def test_timeout_budget_accepts_larger_explicit_client_value() -> None:
    result = resolve_cx_mo_timeout_budget(
        "embedding",
        environ={"NEX_CX_MO_EMBEDDING_TIMEOUT_SECONDS": "75"},
    )
    assert result.client_timeout_seconds == 75


def test_timeout_budget_uses_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("NEX_CX_MO_GENERATION_TIMEOUT_SECONDS", "140")
    assert resolve_cx_mo_timeout_budget("generation").client_timeout_seconds == 140


def test_timeout_budget_rejects_unsafe_client_timeout() -> None:
    with pytest.raises(RuntimeEndpointPolicyError, match="must be at least 60"):
        resolve_cx_mo_timeout_budget(
            "embedding",
            environ={"NEX_CX_MO_EMBEDDING_TIMEOUT_SECONDS": "59"},
        )


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("NEX_MO_REMOTE_EMBEDDING_TIMEOUT_SECONDS", "abc", "must be numeric"),
        ("NEX_MO_REMOTE_EMBEDDING_TIMEOUT_SECONDS", "0", "must be positive"),
        ("NEX_MO_EMBEDDING_MAX_ATTEMPTS", "1.5", "must be an integer"),
        ("NEX_MO_EMBEDDING_MAX_ATTEMPTS", "0", "must be positive"),
    ],
)
def test_timeout_budget_rejects_invalid_upstream_settings(name, value, message) -> None:
    with pytest.raises(RuntimeEndpointPolicyError, match=message):
        resolve_cx_mo_timeout_budget("embedding", environ={name: value})


def test_timeout_budget_rejects_unknown_capability() -> None:
    with pytest.raises(RuntimeEndpointPolicyError, match="unsupported provider capability"):
        resolve_cx_mo_timeout_budget("speech", environ={})
