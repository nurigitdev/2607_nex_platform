from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import httpx
import pytest

from nex_mo.provider_readiness_service import (
    ProviderReadinessService,
    failed_provider_readiness_check,
    provider_readiness_ttl_seconds,
)
import run_mo_provider_readiness_service as runner


NOW = datetime(2026, 9, 30, tzinfo=UTC)


def live_env() -> dict[str, str]:
    return {
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9113/v1/rerank",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.local:9111",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "provider-secret",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "provider-secret",
        "NEX_MO_VLLM_API_KEY": "provider-secret",
    }


def passing_requester(
    method: str,
    url: str,
    **kwargs: object,
) -> httpx.Response:
    if url.endswith("/v1/embeddings"):
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
    if url.endswith("/v1/rerank"):
        return httpx.Response(200, json={"results": [{"score": 0.9}]})
    return httpx.Response(200, json={"data": [{"id": "Qwen3.5-4B"}]})


def test_mock_service_check_is_ready_and_network_free() -> None:
    service = ProviderReadinessService(
        environ={},
        requester=lambda *args, **kwargs: pytest.fail("network access is forbidden"),
        now=lambda: NOW,
    )

    check = service.check()

    assert check["name"] == "provider_routes"
    assert check["ok"] is True
    assert check["readiness_status"] == "READY"
    assert check["error_code"] is None
    assert check["summary"]["status_counts"]["READY"] == 3


def test_live_service_uses_cache_and_force_refresh() -> None:
    calls: list[str] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        return passing_requester(method, url, **kwargs)

    service = ProviderReadinessService(
        environ=live_env(), requester=requester, now=lambda: NOW
    )
    first = service.check()
    cached = service.check()
    refreshed = service.check(force_refresh=True)

    assert first["ok"] is True
    assert cached["checked_at"] == first["checked_at"]
    assert refreshed["cache_status"] == "REFRESHED"
    assert len(calls) == 6


def test_environment_change_invalidates_cached_snapshot() -> None:
    env = live_env()
    calls: list[str] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        return passing_requester(method, url, **kwargs)

    service = ProviderReadinessService(environ=env, requester=requester, now=lambda: NOW)
    service.check()
    env["NEX_MO_REMOTE_EMBEDDING_URL"] = "http://new-dgx.local/v1/embeddings"
    service.check()

    assert len(calls) == 6
    assert calls[-3] == "http://new-dgx.local/v1/embeddings"


def test_clear_forces_next_check_to_refresh() -> None:
    calls = 0

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        return passing_requester(method, url, **kwargs)

    service = ProviderReadinessService(
        environ=live_env(), requester=requester, now=lambda: NOW
    )
    service.check()
    service.clear()
    service.check()

    assert calls == 6


@pytest.mark.parametrize(
    "environ",
    [
        {"NEX_MO_PROVIDER_MODE": "invalid"},
        {"NEX_MO_PROVIDER_READINESS_TTL_SECONDS": "bad"},
        {"NEX_MO_PROVIDER_READINESS_TTL_SECONDS": "0"},
    ],
)
def test_configuration_failure_returns_safe_not_ready_check(
    environ: dict[str, str],
) -> None:
    check = ProviderReadinessService(environ=environ, now=lambda: NOW).check()
    serialized = json.dumps(check)

    assert check["ok"] is False
    assert check["cache_status"] == "MISS"
    assert check["routes"] == []
    assert check["error_code"] == "PROVIDER_READINESS_EVALUATION_FAILED"
    assert "invalid" not in serialized


def test_live_provider_failure_projects_route_health_without_private_values() -> None:
    env = live_env()
    check = ProviderReadinessService(
        environ=env,
        requester=lambda *args, **kwargs: httpx.Response(503),
        now=lambda: NOW,
    ).check()
    serialized = json.dumps(check)

    assert check["ok"] is False
    assert check["error_code"] == "PROVIDER_ROUTE_NOT_READY"
    assert all(route["status"] == "DEGRADED" for route in check["routes"])
    assert "dgx.local" not in serialized
    assert "provider-secret" not in serialized


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [(None, 30), ("", 30), ("1", 1), ("300", 300)],
)
def test_provider_readiness_ttl_values(raw_value: str | None, expected: int) -> None:
    environ = {}
    if raw_value is not None:
        environ["NEX_MO_PROVIDER_READINESS_TTL_SECONDS"] = raw_value
    assert provider_readiness_ttl_seconds(environ) == expected


@pytest.mark.parametrize("raw_value", ["bad", "0", "301"])
def test_provider_readiness_ttl_rejects_invalid_values(raw_value: str) -> None:
    with pytest.raises(ValueError, match="TTL"):
        provider_readiness_ttl_seconds(
            {"NEX_MO_PROVIDER_READINESS_TTL_SECONDS": raw_value}
        )


def test_failed_check_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone"):
        failed_provider_readiness_check(checked_at=datetime(2026, 9, 30))


@pytest.mark.parametrize(
    "now",
    [
        lambda: datetime(2026, 9, 30),
        lambda: (_ for _ in ()).throw(RuntimeError("clock failed")),
    ],
)
def test_service_clock_failure_returns_safe_not_ready_check(now) -> None:
    check = ProviderReadinessService(environ={}, now=now).check()

    assert check["ok"] is False
    assert check["error_code"] == "PROVIDER_READINESS_EVALUATION_FAILED"
    assert check["checked_at"].endswith("Z")


def test_service_cache_expires_using_injected_time() -> None:
    current = NOW
    calls = 0

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        return passing_requester(method, url, **kwargs)

    service = ProviderReadinessService(
        environ={**live_env(), "NEX_MO_PROVIDER_READINESS_TTL_SECONDS": "1"},
        requester=requester,
        now=lambda: current,
    )
    service.check()
    current += timedelta(seconds=1)
    refreshed = service.check()

    assert calls == 6
    assert refreshed["cache_status"] == "REFRESHED"


def test_service_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_readiness_service()
    assert "readiness_service=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_provider_readiness_service", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "probes=6" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_readiness_service",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
