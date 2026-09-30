from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import pytest

from nex_mo.runtime_observability_collector import collect_runtime_observations
from nex_mo.runtime_observability_service import (
    RuntimeObservabilityService,
    failed_runtime_observation,
    runtime_observation_ttl_seconds,
)
import run_mo_runtime_observability_service as runner


NOW = datetime(2026, 9, 30, tzinfo=UTC)


def test_service_uses_cache_force_refresh_and_clear() -> None:
    calls = 0

    def collector(plan, **kwargs):
        nonlocal calls
        calls += 1
        return collect_runtime_observations(plan, **kwargs)

    service = RuntimeObservabilityService(
        environ={}, collector=collector, now=lambda: NOW
    )
    first = service.observe()
    cached = service.observe()
    refreshed = service.observe(force_refresh=True)
    service.clear()
    after_clear = service.observe()

    assert first["runtime_status"] == "HEALTHY"
    assert cached["observed_at"] == first["observed_at"]
    assert refreshed["cache_status"] == "REFRESHED"
    assert after_clear["cache_status"] == "FRESH"
    assert calls == 3


def test_environment_change_invalidates_cache() -> None:
    env: dict[str, str] = {}
    calls = 0

    def collector(plan, **kwargs):
        nonlocal calls
        calls += 1
        return collect_runtime_observations(plan, **kwargs)

    service = RuntimeObservabilityService(
        environ=env, collector=collector, now=lambda: NOW
    )
    service.observe()
    env["NEX_MO_RUNTIME_GENERATION_PORT"] = "12011"
    service.observe()
    assert calls == 2


def test_expired_refresh_failure_returns_safe_stale_snapshot() -> None:
    current = NOW
    calls = 0

    def collector(plan, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("private failure")
        return collect_runtime_observations(plan, **kwargs)

    service = RuntimeObservabilityService(
        environ={"NEX_MO_RUNTIME_OBSERVABILITY_TTL_SECONDS": "1"},
        collector=collector,
        now=lambda: current,
    )
    assert service.observe()["runtime_status"] == "HEALTHY"
    current += timedelta(seconds=1)
    stale = service.observe()

    assert stale["runtime_status"] == "UNKNOWN"
    assert stale["cache_status"] == "STALE"
    assert stale["failure_code"] == "runtime_observation_stale"


@pytest.mark.parametrize(
    "environ",
    [
        {"NEX_MO_RUNTIME_OBSERVABILITY_MODE": "bad"},
        {"NEX_MO_RUNTIME_OBSERVABILITY_TTL_SECONDS": "bad"},
        {"NEX_MO_RUNTIME_OBSERVABILITY_TTL_SECONDS": "0"},
    ],
)
def test_configuration_failure_returns_private_safe_unknown(
    environ: dict[str, str],
) -> None:
    result = RuntimeObservabilityService(environ=environ, now=lambda: NOW).observe()
    serialized = json.dumps(result)
    assert result["runtime_status"] == "UNKNOWN"
    assert result["cache_status"] == "MISS"
    assert result["models"] == []
    assert "private failure" not in serialized


def test_initial_collector_failure_returns_safe_unknown() -> None:
    service = RuntimeObservabilityService(
        environ={},
        collector=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret")),
        now=lambda: NOW,
    )
    result = service.observe()
    assert result["failure_code"] == "runtime_observation_failed"
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [(None, 30), ("", 30), ("1", 1), ("300", 300)],
)
def test_runtime_observation_ttl_values(raw_value: str | None, expected: int) -> None:
    environ = {}
    if raw_value is not None:
        environ["NEX_MO_RUNTIME_OBSERVABILITY_TTL_SECONDS"] = raw_value
    assert runtime_observation_ttl_seconds(environ) == expected


@pytest.mark.parametrize("raw_value", ["bad", "0", "301"])
def test_runtime_observation_ttl_rejects_invalid_values(raw_value: str) -> None:
    with pytest.raises(ValueError, match="TTL"):
        runtime_observation_ttl_seconds(
            {"NEX_MO_RUNTIME_OBSERVABILITY_TTL_SECONDS": raw_value}
        )


def test_failed_observation_and_clock_reject_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        failed_runtime_observation(observed_at=datetime(2026, 9, 30))
    result = RuntimeObservabilityService(
        environ={}, now=lambda: datetime(2026, 9, 30)
    ).observe()
    assert result["runtime_status"] == "UNKNOWN"


def test_clock_failure_returns_safe_unknown() -> None:
    result = RuntimeObservabilityService(
        environ={},
        now=lambda: (_ for _ in ()).throw(RuntimeError("clock failed")),
    ).observe()
    assert result["failure_code"] == "runtime_observation_failed"
    assert result["observed_at"].endswith("Z")


def test_service_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_observability_service()
    assert "runtime_observability_service=pass" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner, "run_mo_runtime_observability_service", lambda: passing
    )
    assert runner.main(["--summary"]) == 0
    assert "ttl=30" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_runtime_observability_service",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
