from __future__ import annotations

import pytest

from nex_mo.provider_resilience import compose_provider_resilience
from nex_mo.provider_retry import build_provider_retry_policy
import run_mo_provider_resilience_composition as runner


CAPABILITIES = ("embedding", "reranking", "generation")


def _policies():
    return [build_provider_retry_policy(item, {}) for item in CAPABILITIES]


def _readiness(*, statuses: tuple[str, str, str] = ("READY", "READY", "READY")):
    return {
        "readiness_status": "READY",
        "checked_at": "2026-09-30T00:00:00Z",
        "cache_status": "FRESH",
        "required_capabilities": list(CAPABILITIES),
        "routes": [
            {
                "provider_capability": capability,
                "deployment_id": f"{capability}-deployment",
                "model_revision": f"{capability}-revision",
                "status": status,
            }
            for capability, status in zip(CAPABILITIES, statuses, strict=True)
        ],
    }


def _telemetry(capability: str, *, outcome=None, retries: int = 0):
    return {
        "capability": capability,
        "request_count": 1 if outcome else 0,
        "attempt_count": (1 if outcome else 0) + retries,
        "retry_count": retries,
        "last_outcome": outcome,
        "last_failure_kind": "connection_error" if outcome == "failure" else None,
    }


def test_composition_keeps_successful_retry_separate_from_health() -> None:
    snapshot = compose_provider_resilience(
        _readiness(),
        [_telemetry("embedding", outcome="success", retries=1)],
        _policies(),
    )

    embedding = snapshot["providers"][0]
    assert snapshot["resilience_status"] == "HEALTHY"
    assert snapshot["ok"] is True
    assert embedding["resilience_status"] == "HEALTHY"
    assert embedding["retry_observed"] is True
    assert embedding["retry_policy"]["max_attempts"] == 3
    assert snapshot["summary"]["attempt_count"] == 2


@pytest.mark.parametrize(
    ("route_status", "last_outcome", "expected"),
    [
        ("READY", "failure", "DEGRADED"),
        ("DEGRADED", "success", "DEGRADED"),
        ("UNAVAILABLE", "success", "UNAVAILABLE"),
        ("UNKNOWN", None, "UNKNOWN"),
        ("unexpected", "success", "UNKNOWN"),
    ],
)
def test_composition_status_precedence(
    route_status: str,
    last_outcome: str | None,
    expected: str,
) -> None:
    snapshot = compose_provider_resilience(
        _readiness(statuses=(route_status, "READY", "READY")),
        [_telemetry("embedding", outcome=last_outcome)],
        _policies(),
    )
    assert snapshot["providers"][0]["resilience_status"] == expected
    assert snapshot["resilience_status"] == expected
    assert snapshot["ok"] is (expected == "HEALTHY")


def test_composition_requires_canonical_capabilities_and_policies() -> None:
    readiness = _readiness()
    readiness["required_capabilities"] = ["embedding"]
    with pytest.raises(ValueError, match="canonical capabilities"):
        compose_provider_resilience(readiness, [], _policies())
    with pytest.raises(ValueError, match="one retry policy"):
        compose_provider_resilience(_readiness(), [], _policies()[:2])


@pytest.mark.parametrize("collection", ["routes", "telemetry"])
def test_composition_rejects_duplicate_capabilities(collection: str) -> None:
    readiness = _readiness()
    telemetry = [_telemetry("embedding")]
    if collection == "routes":
        readiness["routes"].append(dict(readiness["routes"][0]))
    else:
        telemetry.append(_telemetry("embedding"))
    with pytest.raises(ValueError, match="duplicate provider capability"):
        compose_provider_resilience(readiness, telemetry, _policies())


@pytest.mark.parametrize("value", [-1, 1.5, True])
def test_composition_rejects_invalid_telemetry_counts(value) -> None:
    telemetry = _telemetry("embedding")
    telemetry["request_count"] = value
    with pytest.raises(ValueError, match="request_count"):
        compose_provider_resilience(_readiness(), [telemetry], _policies())


def test_composition_ignores_unknown_capability_records() -> None:
    snapshot = compose_provider_resilience(
        _readiness(),
        [{"capability": "future", "request_count": -1}],
        _policies(),
    )
    assert snapshot["summary"]["request_count"] == 0


def test_resilience_composition_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_resilience_composition()
    assert passing["status"] == "PASS"
    assert "capabilities=3" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_provider_resilience_composition",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "checks=6/6" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_resilience_composition",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
