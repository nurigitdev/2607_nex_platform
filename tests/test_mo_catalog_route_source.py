from __future__ import annotations

from dataclasses import replace

import pytest

from nex_mo.catalog_lifecycle_repository import InMemoryCatalogLifecycleRepository
from nex_mo.catalog_lifecycle_service import (
    CatalogLifecycleService,
    CatalogLifecycleServiceError,
    RegisterCatalogEntry,
)
from nex_mo.catalog_route_source import CatalogProviderRouteSource
from nex_mo.provider_registry import (
    DEFAULT_PROVIDER_ROUTES,
    ProviderRouteError,
    configure_provider_route_source,
    list_provider_routes,
    resolve_provider_route,
)
import run_mo_catalog_route_resolution as runner


NOW = "2026-10-01T05:00:00Z"


def _service() -> tuple[CatalogLifecycleService, InMemoryCatalogLifecycleRepository]:
    repository = InMemoryCatalogLifecycleRepository()
    identifiers = iter(("candidate", "binding"))
    service = CatalogLifecycleService(
        repository,
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    service.ensure_bootstrap()
    return service, repository


def test_catalog_source_preserves_bootstrap_route_compatibility() -> None:
    service, _ = _service()
    source = CatalogProviderRouteSource(service)

    assert tuple(source()) == DEFAULT_PROVIDER_ROUTES


def test_active_alias_change_is_visible_to_runtime_resolution() -> None:
    service, _ = _service()
    candidate = service.register_catalog_entry(
        RegisterCatalogEntry(
            provider_capability="generation",
            model_name="Generation Candidate",
            model_revision="candidate-v2",
            deployment_id="candidate-deployment",
            runtime_profile="candidate-profile",
            precision="BF16",
            provider_type="openai-compatible",
            supports_response_formats=("text", "json_object"),
            max_input_tokens=16384,
            max_output_tokens=2048,
        )
    )
    candidate = service.transition_catalog_entry(
        candidate.catalog_id,
        expected_revision=1,
        target_state="ACTIVE",
    )
    current = next(
        item
        for item in service.list_alias_bindings(state="ACTIVE")
        if item.provider_capability == "generation"
    )
    service.activate_alias(
        alias=current.alias,
        capability="generation",
        catalog_id=candidate.catalog_id,
        expected_binding_revision=current.binding_revision,
        change_reason="Promote candidate",
        changed_by="service:nex-ag",
    )
    previous = configure_provider_route_source(CatalogProviderRouteSource(service))
    try:
        route = resolve_provider_route(current.alias, "generation")
        assert route.model_revision == "candidate-v2"
        assert route.deployment_id == "candidate-deployment"
        assert route.route_id == "route-binding-binding"
        assert len(list_provider_routes("generation")) == 1
        assert resolve_provider_route(
            "general-llm-default",
            "generation",
            routes=DEFAULT_PROVIDER_ROUTES,
        ).model_revision == "mock-llm-v1"
    finally:
        configure_provider_route_source(previous)


def test_route_source_failures_are_fail_closed_and_private() -> None:
    class FailedService:
        def list_alias_bindings(self, **kwargs):
            raise CatalogLifecycleServiceError(503, "PRIVATE", "database details")

    with pytest.raises(ProviderRouteError) as exc_info:
        CatalogProviderRouteSource(FailedService())()
    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "mo.catalog_runtime_unavailable"
    assert "database details" not in exc_info.value.detail

    previous = configure_provider_route_source(
        lambda: (_ for _ in ()).throw(RuntimeError("private source failure"))
    )
    try:
        with pytest.raises(ProviderRouteError) as source_error:
            list_provider_routes()
        assert source_error.value.error_code == "mo.catalog_runtime_unavailable"
        assert "private source failure" not in source_error.value.detail
    finally:
        configure_provider_route_source(previous)

    expected = ProviderRouteError(503, "mo.explicit_failure", "safe failure")
    previous = configure_provider_route_source(
        lambda: (_ for _ in ()).throw(expected)
    )
    try:
        with pytest.raises(ProviderRouteError) as explicit_error:
            list_provider_routes()
        assert explicit_error.value is expected
    finally:
        configure_provider_route_source(previous)


def test_catalog_source_rejects_inconsistent_active_binding() -> None:
    service, repository = _service()
    binding = service.list_alias_bindings(state="ACTIVE")[0]
    entry = service.get_catalog_entry(binding.catalog_id)
    repository._entries[entry.catalog_id] = replace(entry, catalog_state="RETIRED")

    with pytest.raises(ProviderRouteError) as exc_info:
        CatalogProviderRouteSource(service)()
    assert exc_info.value.error_code == "mo.catalog_runtime_unavailable"


def test_provider_route_source_configuration_guard() -> None:
    with pytest.raises(TypeError, match="callable"):
        configure_provider_route_source("not-callable")  # type: ignore[arg-type]


def test_catalog_route_resolution_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_catalog_route_resolution()
    assert "catalog_route_resolution=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_catalog_route_resolution", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "switched=candidate-v2" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_catalog_route_resolution",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
