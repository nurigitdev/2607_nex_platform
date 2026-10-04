from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_mo import provider_registry, providers, remote_provider
import run_mo_provider_registry_decoupling as runner


def test_registry_filters_and_resolves_routes() -> None:
    routes = provider_registry.list_provider_routes()

    assert len(routes) == 3
    assert [item.provider_capability for item in provider_registry.list_provider_routes("generation")] == [
        "generation"
    ]
    assert provider_registry.resolve_provider_route(
        "general-llm-default",
        "generation",
    ).route_id == "route-general-llm-default"
    assert provider_registry.resolve_provider_route(
        "embedding-default", "embedding"
    ).alias == "mock-embedding-default"
    assert provider_registry.resolve_provider_route(
        "reranker-default", "reranking"
    ).alias == "mock-reranker-default"


def test_registry_fails_closed_for_unknown_mismatched_and_unready_routes() -> None:
    with pytest.raises(provider_registry.ProviderRouteError) as missing:
        provider_registry.resolve_provider_route("missing", "embedding")
    assert missing.value.status_code == 404

    with pytest.raises(provider_registry.ProviderRouteError) as mismatch:
        provider_registry.resolve_provider_route(
            "mock-embedding-default",
            "generation",
        )
    assert mismatch.value.status_code == 422

    unavailable = replace(provider_registry.DEFAULT_PROVIDER_ROUTES[0], status="DEGRADED")
    with pytest.raises(provider_registry.ProviderRouteError) as degraded:
        provider_registry.resolve_provider_route(
            unavailable.alias,
            unavailable.provider_capability,
            (unavailable,),
        )
    assert degraded.value.status_code == 503
    assert degraded.value.retryable is True


def test_compatibility_exports_and_remote_dependency_direction() -> None:
    assert providers.ProviderRoute is provider_registry.ProviderRoute
    assert providers.ProviderRouteError is provider_registry.ProviderRouteError
    assert providers.DEFAULT_PROVIDER_ROUTES is provider_registry.DEFAULT_PROVIDER_ROUTES
    assert providers.resolve_provider_route is provider_registry.resolve_provider_route
    assert remote_provider.ProviderRouteError is provider_registry.ProviderRouteError


def test_registry_decoupling_evidence_and_runner(tmp_path: Path, monkeypatch, capsys) -> None:
    missing = runner.run_mo_provider_registry_decoupling(tmp_path)
    assert missing["status"] == "FAIL"
    assert missing["summary"]["failed_check_count"] == 3

    passing = runner.run_mo_provider_registry_decoupling()
    assert passing["status"] == "PASS"
    assert passing["summary"]["direct_remote_api_import_count"] == 0
    monkeypatch.setattr(runner, "run_mo_provider_registry_decoupling", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "remote_api_imports=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_provider_registry_decoupling", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "registry_decoupling=fail" in capsys.readouterr().out
