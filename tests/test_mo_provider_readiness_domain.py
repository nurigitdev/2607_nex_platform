from __future__ import annotations

import json

import pytest

from nex_mo.provider_readiness import (
    ProviderRouteHealth,
    build_mock_provider_readiness_snapshot,
    build_provider_readiness_snapshot,
)
from nex_mo.provider_registry import ProviderRoute
import run_mo_provider_readiness_domain as runner


CHECKED_AT = "2026-09-30T00:00:00Z"


def route_health(
    capability: str,
    *,
    status: str = "READY",
) -> ProviderRouteHealth:
    return ProviderRouteHealth(
        provider_capability=capability,
        alias=f"{capability}-default",
        route_id=f"route-{capability}",
        deployment_id=f"deployment-{capability}",
        model_revision=f"model-{capability}",
        status=status,
        source="active_preflight",
        checked_at=CHECKED_AT,
        latency_ms=5,
        failure_code=None if status == "READY" else "provider_unavailable",
        retryable=status == "DEGRADED",
        degraded=status == "DEGRADED",
    )


def test_mock_snapshot_is_deterministic_ready_and_privacy_safe() -> None:
    snapshot = build_mock_provider_readiness_snapshot(checked_at=CHECKED_AT)
    projected = snapshot.to_wire()
    serialized = json.dumps(projected)

    assert snapshot.readiness_status == "READY"
    assert snapshot.expires_at == "2026-09-30T00:00:30Z"
    assert projected["provider_readiness_schema_version"] == "mo_provider_readiness.v1"
    assert projected["summary"]["status_counts"] == {
        "READY": 3,
        "DEGRADED": 0,
        "UNAVAILABLE": 0,
        "UNKNOWN": 0,
    }
    assert all(item["ok"] for item in projected["routes"])
    assert all(
        forbidden not in serialized
        for forbidden in (
            "provider_endpoint",
            "provider_api_key",
            "model_path",
            "process_command",
            "request_payload",
            "response_payload",
        )
    )


def test_snapshot_fails_closed_for_degraded_missing_or_stale_routes() -> None:
    complete = [
        route_health("embedding"),
        route_health("reranking"),
        route_health("generation", status="DEGRADED"),
    ]
    degraded = build_provider_readiness_snapshot(
        provider_mode="live",
        routes=complete,
        checked_at=CHECKED_AT,
        ttl_seconds=15,
        cache_status="REFRESHED",
    )
    missing = build_provider_readiness_snapshot(
        provider_mode="live",
        routes=complete[:2],
        checked_at=CHECKED_AT,
        ttl_seconds=15,
        cache_status="FRESH",
    )
    stale = build_provider_readiness_snapshot(
        provider_mode="live",
        routes=[
            route_health("embedding"),
            route_health("reranking"),
            route_health("generation"),
        ],
        checked_at=CHECKED_AT,
        ttl_seconds=15,
        cache_status="STALE",
    )

    assert degraded.readiness_status == "NOT_READY"
    assert degraded.routes[-1].to_wire()["degraded"] is True
    assert missing.failure_code == "provider_route_not_ready"
    assert stale.readiness_status == "NOT_READY"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"provider_mode": "other"}, "provider_mode"),
        ({"ttl_seconds": 0}, "ttl_seconds"),
        ({"ttl_seconds": 301}, "ttl_seconds"),
        ({"cache_status": "OLD"}, "cache status"),
        ({"required_capabilities": ()}, "required capabilities"),
        (
            {"required_capabilities": ("embedding", "embedding")},
            "required capabilities",
        ),
    ],
)
def test_snapshot_rejects_invalid_configuration(
    kwargs: dict[str, object],
    message: str,
) -> None:
    arguments: dict[str, object] = {
        "provider_mode": "live",
        "routes": [],
        "checked_at": CHECKED_AT,
        "ttl_seconds": 30,
        "cache_status": "FRESH",
    }
    arguments.update(kwargs)

    with pytest.raises(ValueError, match=message):
        build_provider_readiness_snapshot(**arguments)  # type: ignore[arg-type]


def test_snapshot_rejects_duplicate_unexpected_and_bad_route_health() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        build_provider_readiness_snapshot(
            provider_mode="live",
            routes=[route_health("embedding"), route_health("embedding")],
            checked_at=CHECKED_AT,
            ttl_seconds=30,
            cache_status="FRESH",
        )
    with pytest.raises(ValueError, match="not required"):
        build_provider_readiness_snapshot(
            provider_mode="live",
            routes=[route_health("reranking")],
            checked_at=CHECKED_AT,
            ttl_seconds=30,
            cache_status="FRESH",
            required_capabilities=("embedding",),
        )
    with pytest.raises(ValueError, match="capability"):
        route_health("invalid")
    with pytest.raises(ValueError, match="health status"):
        ProviderRouteHealth(
            provider_capability="embedding",
            alias="a",
            route_id="r",
            deployment_id="d",
            model_revision="m",
            status="BROKEN",
            source="active_preflight",
            checked_at=CHECKED_AT,
        )
    with pytest.raises(ValueError, match="source"):
        ProviderRouteHealth(
            provider_capability="embedding",
            alias="a",
            route_id="r",
            deployment_id="d",
            model_revision="m",
            status="READY",
            source="other",
            checked_at=CHECKED_AT,
        )
    with pytest.raises(ValueError, match="negative"):
        route_health("embedding").__class__(
            **{
                **route_health("embedding").__dict__,
                "latency_ms": -1,
            }
        )
    with pytest.raises(ValueError, match="ISO 8601"):
        ProviderRouteHealth(
            provider_capability="embedding",
            alias="a",
            route_id="r",
            deployment_id="d",
            model_revision="m",
            status="READY",
            source="active_preflight",
            checked_at="bad",
        )
    with pytest.raises(ValueError, match="timezone"):
        ProviderRouteHealth(
            provider_capability="embedding",
            alias="a",
            route_id="r",
            deployment_id="d",
            model_revision="m",
            status="READY",
            source="active_preflight",
            checked_at="2026-09-30T00:00:00",
        )


def test_mock_snapshot_reports_unavailable_registry_route() -> None:
    routes = (
        ProviderRoute(
            alias="embedding-default",
            provider_capability="embedding",
            provider_type="mock",
            model_revision="embedding-v1",
            deployment_id="embedding-local",
            route_id="route-embedding",
            supports_response_formats=("vector",),
            max_input_tokens=100,
            max_output_tokens=0,
            status="NOT_READY",
        ),
    )

    snapshot = build_mock_provider_readiness_snapshot(
        routes=routes,
        checked_at=CHECKED_AT,
    )

    assert snapshot.readiness_status == "NOT_READY"
    assert snapshot.routes[0].failure_code == "mock_route_not_ready"


def test_mock_snapshot_uses_current_utc_time_when_not_injected() -> None:
    snapshot = build_mock_provider_readiness_snapshot()

    assert snapshot.checked_at.endswith("Z")
    assert snapshot.expires_at.endswith("Z")


def test_domain_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_readiness_domain()
    assert "readiness_domain=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_provider_readiness_domain", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "ready=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_readiness_domain",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
