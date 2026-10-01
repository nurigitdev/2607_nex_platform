from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest

from nex_mo.catalog_lifecycle_repository import InMemoryCatalogLifecycleRepository
from nex_mo.catalog_lifecycle_service import CatalogLifecycleService
from nex_mo.operations_service import (
    MOOperationsService,
    _items_by_capability,
    _nonnegative_int,
    _operation_status,
    _readiness_status,
    _runtime_status,
    _safe_failure_code,
    _telemetry_item_status,
    _timestamp_or,
)
from nex_mo.provider_readiness_service import ProviderReadinessService
from nex_mo.runtime_observability_service import RuntimeObservabilityService
import run_mo_operations_integration_service as runner


NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _catalog() -> CatalogLifecycleService:
    service = CatalogLifecycleService(
        InMemoryCatalogLifecycleRepository(),
        clock=lambda: "2026-10-01T00:00:00Z",
    )
    service.ensure_bootstrap()
    return service


def _telemetry(*, failed: str | None = None, configured: bool = True):
    return [
        {
            "capability": capability,
            "configured": configured,
            "request_count": "2",
            "success_count": 1 if capability == failed else 2,
            "failure_count": 1 if capability == failed else 0,
            "degraded_count": 1 if capability == failed else 0,
            "last_outcome": "failure" if capability == failed else "success",
            "last_observed_at": "2026-10-01T00:00:00Z",
            "last_latency_ms": 7,
            "last_error_code": "provider_failed" if capability == failed else None,
        }
        for capability in ("embedding", "reranking", "generation")
    ]


def _service(**overrides) -> MOOperationsService:
    values = {
        "catalog_service": _catalog(),
        "readiness_service": ProviderReadinessService(environ={}, now=lambda: NOW),
        "runtime_service": RuntimeObservabilityService(environ={}, now=lambda: NOW),
        "telemetry_reader": lambda: _telemetry(configured=False),
        "environ": {},
        "now": lambda: NOW,
    }
    values.update(overrides)
    return MOOperationsService(**values)


def test_composes_four_sources_into_three_ready_capabilities() -> None:
    result = _service().snapshot()

    assert result["provider_mode"] == "mock"
    assert result["operations_status"] == "READY"
    assert result["summary"]["source_count"] == 4
    assert result["summary"]["capability_status_counts"]["READY"] == 3
    assert [item["provider_capability"] for item in result["capabilities"]] == [
        "embedding",
        "reranking",
        "generation",
    ]
    assert "provider_api_key" not in json.dumps(result)


def test_force_refresh_is_propagated_to_refreshable_sources() -> None:
    class Readiness:
        def check(self, *, force_refresh: bool):
            assert force_refresh is True
            return ProviderReadinessService(environ={}, now=lambda: NOW).check()

    class Runtime:
        def observe(self, *, force_refresh: bool):
            assert force_refresh is True
            return RuntimeObservabilityService(environ={}, now=lambda: NOW).observe()

    assert _service(readiness_service=Readiness(), runtime_service=Runtime()).snapshot(
        force_refresh=True
    )["operations_status"] == "READY"


def test_telemetry_failure_degrades_only_matching_capability() -> None:
    result = _service(telemetry_reader=lambda: _telemetry(failed="reranking")).snapshot()

    assert result["operations_status"] == "DEGRADED"
    by_capability = {
        item["provider_capability"]: item for item in result["capabilities"]
    }
    assert by_capability["reranking"]["operations_status"] == "DEGRADED"
    assert by_capability["reranking"]["failure_code"] == "provider_failed"


@pytest.mark.parametrize(
    ("override", "source", "expected"),
    [
        (
            {"catalog_service": type("Broken", (), {
                "list_alias_bindings": lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError())
            })()},
            "catalog",
            "UNAVAILABLE",
        ),
        (
            {"readiness_service": type("Broken", (), {
                "check": lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError())
            })()},
            "readiness",
            "UNAVAILABLE",
        ),
        (
            {"telemetry_reader": lambda: (_ for _ in ()).throw(RuntimeError())},
            "telemetry",
            "UNAVAILABLE",
        ),
        (
            {"runtime_service": type("Broken", (), {
                "observe": lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError())
            })()},
            "runtime",
            "UNAVAILABLE",
        ),
    ],
)
def test_source_failures_are_isolated_and_fail_closed(override, source, expected) -> None:
    result = _service(**override).snapshot()
    source_status = {item["source"]: item["status"] for item in result["sources"]}

    assert source_status[source] == expected
    assert result["operations_status"] == "UNAVAILABLE"


def test_live_unconfigured_or_incomplete_telemetry_is_unknown() -> None:
    live = _service(
        environ={"NEX_MO_PROVIDER_MODE": "live"},
        readiness_service=ProviderReadinessService(environ={}, now=lambda: NOW),
        telemetry_reader=lambda: _telemetry(configured=False),
    ).snapshot()
    incomplete = _service(telemetry_reader=lambda: _telemetry()[:1]).snapshot()

    assert {item["source"]: item["status"] for item in live["sources"]}[
        "telemetry"
    ] == "UNKNOWN"
    assert incomplete["operations_status"] == "UNKNOWN"


def test_malformed_source_collections_are_unavailable() -> None:
    class BadReadiness:
        def check(self, **kwargs):
            return {"routes": "bad", "checked_at": "bad"}

    class BadRuntime:
        def observe(self, **kwargs):
            return {"models": ["bad"], "observed_at": "bad"}

    result = _service(
        readiness_service=BadReadiness(),
        runtime_service=BadRuntime(),
        telemetry_reader=lambda: [
            {"capability": "embedding"},
            {"capability": "embedding"},
        ],
    ).snapshot()
    statuses = {item["source"]: item["status"] for item in result["sources"]}
    assert statuses["readiness"] == "UNAVAILABLE"
    assert statuses["telemetry"] == "UNAVAILABLE"
    assert statuses["runtime"] == "UNAVAILABLE"


@pytest.mark.parametrize("inactive", [False, True])
def test_duplicate_or_inactive_catalog_is_unavailable(inactive: bool) -> None:
    binding = SimpleNamespace(
        provider_capability="embedding",
        catalog_id="catalog-embedding",
        alias="embedding-default",
    )
    entry = SimpleNamespace(
        catalog_state="DRAFT" if inactive else "ACTIVE",
        catalog_id="catalog-embedding",
        model_revision="embedding-v1",
        deployment_id="embedding-live",
    )

    class Catalog:
        def list_alias_bindings(self, **kwargs):
            return [binding] if inactive else [binding, binding]

        def get_catalog_entry(self, catalog_id):
            return entry

    result = _service(catalog_service=Catalog()).snapshot()
    source = {item["source"]: item for item in result["sources"]}["catalog"]
    assert source["status"] == "UNAVAILABLE"


def test_incomplete_catalog_and_unsupported_source_items_are_safe() -> None:
    binding = SimpleNamespace(
        provider_capability="embedding",
        catalog_id="catalog-embedding",
        alias="embedding-default",
    )
    entry = SimpleNamespace(
        catalog_state="ACTIVE",
        catalog_id="catalog-embedding",
        model_revision="embedding-v1",
        deployment_id="embedding-live",
    )

    class Catalog:
        def list_alias_bindings(self, **kwargs):
            return [binding]

        def get_catalog_entry(self, catalog_id):
            return entry

    result = _service(catalog_service=Catalog()).snapshot()
    source = {item["source"]: item for item in result["sources"]}["catalog"]
    assert source["status"] == "UNKNOWN"
    assert _items_by_capability(
        [{"capability": "other"}, {"capability": "embedding"}],
        "capability",
    ) == {"embedding": {"capability": "embedding"}}


@pytest.mark.parametrize(
    ("payload", "stale", "expected"),
    [
        ({"readiness_status": "READY", "ok": True}, True, "UNKNOWN"),
        ({"readiness_status": "READY", "ok": True}, False, "READY"),
        ({"routes": [{"status": "UNAVAILABLE"}]}, False, "UNAVAILABLE"),
        ({"routes": [{"status": "DEGRADED"}]}, False, "DEGRADED"),
        ({"routes": [{"status": "OTHER"}, "bad"]}, False, "UNKNOWN"),
    ],
)
def test_readiness_status_mapping(payload, stale: bool, expected: str) -> None:
    assert _readiness_status(payload, stale=stale) == expected


@pytest.mark.parametrize(
    ("value", "stale", "expected"),
    [
        ("HEALTHY", False, "READY"),
        ("READY", False, "READY"),
        ("DEGRADED", False, "DEGRADED"),
        ("UNAVAILABLE", False, "UNAVAILABLE"),
        ("UNKNOWN", False, "UNKNOWN"),
        ("OTHER", False, "UNKNOWN"),
        ("HEALTHY", True, "UNKNOWN"),
    ],
)
def test_runtime_status_mapping(value: str, stale: bool, expected: str) -> None:
    assert _runtime_status(value, stale=stale) == expected


def test_safe_helper_fallbacks_cover_malformed_operational_values() -> None:
    assert _operation_status("DEGRADED") == "DEGRADED"
    assert _operation_status("OTHER") == "UNKNOWN"
    assert _telemetry_item_status({}) == "UNKNOWN"
    assert _telemetry_item_status({"configured": False}, provider_mode="live") == (
        "UNKNOWN"
    )
    assert _telemetry_item_status({"degraded_count": 1}) == "DEGRADED"
    assert _safe_failure_code({}, "READY", "fallback") is None
    assert _safe_failure_code({"error_code": "SAFE"}, "UNKNOWN", "fallback") == (
        "SAFE"
    )
    assert _safe_failure_code({}, "UNKNOWN", "fallback") == "fallback"
    assert _timestamp_or(None, "fallback") == "fallback"
    assert _timestamp_or("bad", "fallback") == "fallback"
    assert _nonnegative_int("bad") == 0
    assert _nonnegative_int([]) == 0
    assert _nonnegative_int(-1) == 0


def test_invalid_mode_and_naive_clock_are_safe_or_rejected() -> None:
    result = _service(environ={"NEX_MO_PROVIDER_MODE": "invalid"}).snapshot()
    assert result["provider_mode"] == "unknown"
    with pytest.raises(ValueError, match="timezone"):
        _service(now=lambda: datetime(2026, 10, 1)).snapshot()


def test_service_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    evidence = runner.run_mo_operations_integration_service()
    assert evidence["status"] == "PASS"
    assert "ready=3" in runner.summary_line(evidence)
    monkeypatch.setattr(runner, "run_mo_operations_integration_service", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1185" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_operations_integration_service",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
