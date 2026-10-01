from __future__ import annotations

import pytest

from nex_mo.operations_snapshot import (
    CapabilityOperationsStatus,
    MOOperationsSnapshot,
    OperationsSourceAssessment,
    build_capability_operations_status,
    build_mo_operations_snapshot,
    worst_operations_status,
)
import run_mo_operations_snapshot_domain as runner


NOW = "2026-10-01T00:00:00Z"


def _source(name: str, status: str = "READY") -> OperationsSourceAssessment:
    return OperationsSourceAssessment(
        name,
        status,
        status == "READY",
        NOW,
        None if status == "READY" else f"{name}_failed",
    )


def _capability(
    name: str,
    *,
    route_status: str = "READY",
    runtime_status: str = "READY",
) -> CapabilityOperationsStatus:
    return build_capability_operations_status(
        provider_capability=name,
        alias=f"{name}-default",
        catalog_id=f"catalog-{name}",
        model_revision=f"model-{name}",
        deployment_id=f"deployment-{name}",
        catalog_status="READY",
        route_status=route_status,
        telemetry_status="READY",
        runtime_status=runtime_status,
        request_count=3,
        success_count=2,
        failure_count=1,
        last_latency_ms=12,
        failure_code=None if route_status == "READY" else "route_degraded",
    )


def test_builds_complete_privacy_safe_ready_snapshot() -> None:
    snapshot = build_mo_operations_snapshot(
        provider_mode="mock",
        generated_at=NOW,
        sources=tuple(_source(name) for name in (
            "catalog", "readiness", "telemetry", "runtime"
        )),
        capabilities=tuple(_capability(name) for name in (
            "embedding", "reranking", "generation"
        )),
    )

    wire = snapshot.to_wire()
    assert snapshot.operations_status == "READY"
    assert snapshot.failure_code is None
    assert wire["summary"] == {
        "source_count": 4,
        "capability_count": 3,
        "capability_status_counts": {
            "READY": 3,
            "UNKNOWN": 0,
            "DEGRADED": 0,
            "UNAVAILABLE": 0,
        },
    }
    assert "provider_api_key" not in str(wire)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "UNKNOWN"),
        (["READY", "UNKNOWN"], "UNKNOWN"),
        (["READY", "DEGRADED"], "DEGRADED"),
        (["DEGRADED", "UNAVAILABLE"], "UNAVAILABLE"),
    ],
)
def test_status_precedence(statuses: list[str], expected: str) -> None:
    assert worst_operations_status(statuses) == expected


def test_snapshot_is_unknown_when_sources_or_capabilities_are_missing() -> None:
    snapshot = build_mo_operations_snapshot(
        provider_mode="live",
        generated_at=NOW,
        sources=(_source("catalog"),),
        capabilities=(_capability("embedding"),),
        acceptance_status="PASS",
    )

    assert snapshot.operations_status == "UNKNOWN"
    assert snapshot.failure_code == "operations_snapshot_incomplete"


def test_snapshot_uses_worst_complete_status_and_failure_code() -> None:
    sources = tuple(_source(name) for name in (
        "catalog", "readiness", "telemetry", "runtime"
    ))
    capabilities = (
        _capability("embedding"),
        _capability("reranking", route_status="DEGRADED"),
        _capability("generation", runtime_status="UNAVAILABLE"),
    )
    snapshot = build_mo_operations_snapshot(
        provider_mode="live",
        generated_at=NOW,
        sources=sources,
        capabilities=capabilities,
    )

    assert snapshot.operations_status == "UNAVAILABLE"
    assert snapshot.failure_code == "operations_unavailable"
    degraded = build_mo_operations_snapshot(
        provider_mode="live",
        generated_at=NOW,
        sources=sources,
        capabilities=(
            _capability("embedding"),
            _capability("reranking", route_status="DEGRADED"),
            _capability("generation"),
        ),
    )
    assert degraded.failure_code == "operations_degraded"


def test_rejects_duplicate_sources_capabilities_and_invalid_status() -> None:
    with pytest.raises(ValueError, match="duplicate operations source"):
        build_mo_operations_snapshot(
            provider_mode="mock",
            generated_at=NOW,
            sources=(_source("catalog"), _source("catalog")),
            capabilities=(),
        )
    with pytest.raises(ValueError, match="duplicate operations capability"):
        build_mo_operations_snapshot(
            provider_mode="mock",
            generated_at=NOW,
            sources=(),
            capabilities=(_capability("embedding"), _capability("embedding")),
        )
    with pytest.raises(ValueError, match="unsupported operations status"):
        worst_operations_status(["BROKEN"])


@pytest.mark.parametrize(
    "factory, message",
    [
        (lambda: OperationsSourceAssessment("other", "READY", True, NOW), "source"),
        (lambda: OperationsSourceAssessment("catalog", "READY", False, NOW), "fresh"),
        (lambda: OperationsSourceAssessment("catalog", "READY", True, "bad"), "timestamp"),
        (
            lambda: OperationsSourceAssessment(
                "catalog", "READY", True, "2026-10-01T00:00:00"
            ),
            "timezone",
        ),
        (lambda: _capability("other"), "capability"),
        (
            lambda: CapabilityOperationsStatus(
                "embedding", "", "c", "m", "d", *(["READY"] * 5), 0, 0, 0
            ),
            "identity",
        ),
        (
            lambda: CapabilityOperationsStatus(
                "embedding", "a", "c", "m", "d", *(["READY"] * 5), -1, 0, 0
            ),
            "negative",
        ),
        (
            lambda: CapabilityOperationsStatus(
                "embedding", "a", "c", "m", "d", *(["READY"] * 5), 1, 1, 1
            ),
            "outcomes",
        ),
        (
            lambda: CapabilityOperationsStatus(
                "embedding", "a", "c", "m", "d", *(["READY"] * 5), 1, 1, 0, -1
            ),
            "latency",
        ),
        (
            lambda: MOOperationsSnapshot("other", "READY", NOW, "NOT_RUN", (), ()),
            "provider_mode",
        ),
        (
            lambda: MOOperationsSnapshot("mock", "READY", NOW, "OTHER", (), ()),
            "acceptance",
        ),
    ],
)
def test_domain_validation_rejects_invalid_values(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_domain_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    evidence = runner.run_mo_operations_snapshot_domain()
    assert evidence["status"] == "PASS"
    assert evidence["summary"]["private_field_count"] == 0
    assert "ready=3" in runner.summary_line(evidence)

    monkeypatch.setattr(runner, "run_mo_operations_snapshot_domain", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1184" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_operations_snapshot_domain",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
