from __future__ import annotations

import pytest

from nex_mo.runtime_observability_policy import (
    RuntimeObservationThresholds,
    classify_runtime_observation,
    runtime_observation_thresholds,
)
import run_mo_runtime_observability_policy as runner


def decision(**overrides: object):
    values: dict[str, object] = {
        "process_count": 1,
        "expected_model_seen": True,
        "requested_dtype": "bfloat16",
        "loaded_dtype": "bfloat16",
        "nvidia_available": True,
        "gpu_count": 1,
        "gpu_memory_used_mib": 4096,
        "gpu_memory_total_mib": 8192,
        "gpu_utilization_percent": 99.0,
        "gpu_temperature_c": 55.0,
        "thresholds": RuntimeObservationThresholds(),
    }
    values.update(overrides)
    return classify_runtime_observation(**values)  # type: ignore[arg-type]


def test_healthy_runtime_allows_high_compute_utilization() -> None:
    result = decision(gpu_utilization_percent=100.0)
    assert result.runtime_status == "HEALTHY"
    assert result.failure_code is None
    assert result.memory_utilization_percent == 50.0
    assert result.resource_pressure is False


@pytest.mark.parametrize(
    ("overrides", "status", "failure_code", "precision"),
    [
        ({"process_count": 0}, "UNAVAILABLE", "model_runtime_process_missing", "MATCH"),
        ({"process_count": 2}, "DEGRADED", "model_runtime_process_ambiguous", "MATCH"),
        ({"expected_model_seen": False}, "DEGRADED", "model_runtime_identity_mismatch", "MATCH"),
        ({"loaded_dtype": "float32"}, "DEGRADED", "model_runtime_precision_mismatch", "MISMATCH"),
        ({"loaded_dtype": "bad"}, "UNKNOWN", "model_runtime_precision_unverified", "UNVERIFIED"),
        ({"nvidia_available": False}, "UNKNOWN", "gpu_runtime_evidence_missing", "MATCH"),
        ({"gpu_count": 0}, "UNKNOWN", "gpu_runtime_evidence_missing", "MATCH"),
        ({"gpu_utilization_percent": None}, "UNKNOWN", "gpu_runtime_metrics_incomplete", "MATCH"),
        ({"gpu_memory_used_mib": 900, "gpu_memory_total_mib": 1000}, "DEGRADED", "gpu_runtime_resource_pressure", "MATCH"),
        ({"gpu_temperature_c": 85.0}, "DEGRADED", "gpu_runtime_resource_pressure", "MATCH"),
    ],
)
def test_policy_failure_precedence(
    overrides: dict[str, object],
    status: str,
    failure_code: str,
    precision: str,
) -> None:
    result = decision(**overrides)
    assert result.runtime_status == status
    assert result.failure_code == failure_code
    assert result.precision_status == precision


def test_missing_or_invalid_memory_capacity_is_incomplete() -> None:
    missing = decision(gpu_memory_total_mib=None)
    zero = decision(gpu_memory_total_mib=0)
    assert missing.failure_code == "gpu_runtime_metrics_incomplete"
    assert zero.failure_code == "gpu_runtime_metrics_incomplete"


def test_threshold_environment_defaults_and_overrides() -> None:
    defaults = runtime_observation_thresholds({})
    empty = runtime_observation_thresholds(
        {
            "NEX_MO_GPU_MEMORY_WARN_PERCENT": "",
            "NEX_MO_GPU_TEMPERATURE_WARN_C": "",
        }
    )
    custom = runtime_observation_thresholds(
        {
            "NEX_MO_GPU_MEMORY_WARN_PERCENT": "80.5",
            "NEX_MO_GPU_TEMPERATURE_WARN_C": "75",
        }
    )
    assert defaults == empty == RuntimeObservationThresholds()
    assert custom.gpu_memory_warn_percent == 80.5
    assert custom.gpu_temperature_warn_c == 75.0


@pytest.mark.parametrize(
    "environ",
    [
        {"NEX_MO_GPU_MEMORY_WARN_PERCENT": "bad"},
        {"NEX_MO_GPU_MEMORY_WARN_PERCENT": "0"},
        {"NEX_MO_GPU_MEMORY_WARN_PERCENT": "101"},
        {"NEX_MO_GPU_TEMPERATURE_WARN_C": "0"},
        {"NEX_MO_GPU_TEMPERATURE_WARN_C": "151"},
    ],
)
def test_threshold_environment_rejects_invalid_values(
    environ: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        runtime_observation_thresholds(environ)


def test_threshold_change_invalidates_service_cache() -> None:
    from datetime import UTC, datetime

    from nex_mo.runtime_observability_collector import collect_runtime_observations
    from nex_mo.runtime_observability_service import RuntimeObservabilityService

    env: dict[str, str] = {}
    calls = 0

    def collector(plan, **kwargs):
        nonlocal calls
        calls += 1
        return collect_runtime_observations(plan, **kwargs)

    service = RuntimeObservabilityService(
        environ=env,
        collector=collector,
        now=lambda: datetime(2026, 9, 30, tzinfo=UTC),
    )
    service.observe()
    env["NEX_MO_GPU_MEMORY_WARN_PERCENT"] = "80"
    service.observe()
    assert calls == 2


def test_policy_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_observability_policy()
    assert "runtime_observability_policy=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_runtime_observability_policy", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "memory_warn=90.0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_runtime_observability_policy",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
