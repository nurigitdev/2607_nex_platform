from __future__ import annotations

import json

import pytest

from nex_mo.runtime_observability import (
    ModelRuntimeObservation,
    build_mock_model_runtime_snapshot,
    build_model_runtime_snapshot,
    normalize_dtype,
)
import run_mo_runtime_observability_domain as runner


OBSERVED_AT = "2026-09-30T00:00:00Z"


def model(capability: str, *, status: str = "HEALTHY") -> ModelRuntimeObservation:
    return ModelRuntimeObservation(
        provider_capability=capability,
        alias=f"{capability}-default",
        deployment_id=f"deployment-{capability}",
        model_revision=f"model-{capability}",
        runtime_status=status,
        precision_status="MATCH",
        requested_dtype="bfloat16",
        loaded_dtype="bfloat16",
        process_count=1,
        gpu_count=1,
        gpu_memory_used_mib=1024,
        gpu_memory_total_mib=8192,
        gpu_utilization_percent=25.5,
        gpu_temperature_c=48.0,
        source="protected_ssh",
        observed_at=OBSERVED_AT,
        failure_code=None if status == "HEALTHY" else "runtime_issue",
    )


def test_mock_snapshot_is_deterministic_healthy_and_privacy_safe() -> None:
    snapshot = build_mock_model_runtime_snapshot().to_wire()
    serialized = json.dumps(snapshot)

    assert snapshot["runtime_status"] == "HEALTHY"
    assert snapshot["expires_at"] == "2026-09-30T00:00:30Z"
    assert snapshot["summary"]["status_counts"]["HEALTHY"] == 3
    assert [item["provider_capability"] for item in snapshot["models"]] == [
        "embedding",
        "reranking",
        "generation",
    ]
    assert all(item["precision_status"] == "MATCH" for item in snapshot["models"])
    for private in (
        "ssh_target",
        "provider_api_key",
        "process_id",
        "process_command_line",
        "model_path",
        "gpu_uuid",
    ):
        assert private not in serialized


@pytest.mark.parametrize(
    ("statuses", "cache_status", "expected", "failure_code"),
    [
        (("HEALTHY", "HEALTHY", "UNAVAILABLE"), "FRESH", "UNAVAILABLE", "model_runtime_unavailable"),
        (("HEALTHY", "DEGRADED", "HEALTHY"), "FRESH", "DEGRADED", "model_runtime_degraded"),
        (("HEALTHY", "UNKNOWN", "HEALTHY"), "FRESH", "UNKNOWN", "runtime_observation_incomplete"),
        (("HEALTHY", "HEALTHY", "HEALTHY"), "STALE", "UNKNOWN", "runtime_observation_incomplete"),
    ],
)
def test_snapshot_aggregate_status_fails_closed(
    statuses: tuple[str, str, str],
    cache_status: str,
    expected: str,
    failure_code: str,
) -> None:
    snapshot = build_model_runtime_snapshot(
        observation_mode="live",
        models=[
            model(capability, status=status)
            for capability, status in zip(
                ("embedding", "reranking", "generation"), statuses
            )
        ],
        observed_at=OBSERVED_AT,
        ttl_seconds=30,
        cache_status=cache_status,
    )

    assert snapshot.runtime_status == expected
    assert snapshot.failure_code == failure_code


def test_missing_model_is_unknown() -> None:
    snapshot = build_model_runtime_snapshot(
        observation_mode="live",
        models=[model("embedding"), model("reranking")],
        observed_at=OBSERVED_AT,
        ttl_seconds=30,
        cache_status="FRESH",
    )
    assert snapshot.runtime_status == "UNKNOWN"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"observation_mode": "other"}, "observation_mode"),
        ({"ttl_seconds": 0}, "ttl_seconds"),
        ({"ttl_seconds": 301}, "ttl_seconds"),
        ({"cache_status": "OLD"}, "cache status"),
        ({"required_capabilities": ()}, "required capabilities"),
        ({"required_capabilities": ("embedding", "embedding")}, "required capabilities"),
    ],
)
def test_snapshot_rejects_invalid_configuration(
    kwargs: dict[str, object],
    message: str,
) -> None:
    arguments: dict[str, object] = {
        "observation_mode": "live",
        "models": [],
        "observed_at": OBSERVED_AT,
        "ttl_seconds": 30,
        "cache_status": "FRESH",
    }
    arguments.update(kwargs)
    with pytest.raises(ValueError, match=message):
        build_model_runtime_snapshot(**arguments)  # type: ignore[arg-type]


def test_snapshot_rejects_duplicate_and_unexpected_model() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        build_model_runtime_snapshot(
            observation_mode="live",
            models=[model("embedding"), model("embedding")],
            observed_at=OBSERVED_AT,
            ttl_seconds=30,
            cache_status="FRESH",
        )
    with pytest.raises(ValueError, match="not required"):
        build_model_runtime_snapshot(
            observation_mode="live",
            models=[model("reranking")],
            observed_at=OBSERVED_AT,
            ttl_seconds=30,
            cache_status="FRESH",
            required_capabilities=("embedding",),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("provider_capability", "invalid", "capability"),
        ("alias", "", "identity"),
        ("runtime_status", "BROKEN", "runtime status"),
        ("precision_status", "BAD", "precision status"),
        ("source", "other", "source"),
        ("process_count", -1, "counts"),
        ("gpu_count", -1, "counts"),
        ("gpu_memory_used_mib", -1, "memory used"),
        ("gpu_memory_total_mib", 0, "memory total"),
        ("gpu_utilization_percent", 101.0, "utilization"),
        ("gpu_temperature_c", 151.0, "temperature"),
        ("observed_at", "bad", "ISO 8601"),
        ("observed_at", "2026-09-30T00:00:00", "timezone"),
    ],
)
def test_observation_rejects_invalid_values(
    field: str,
    value: object,
    message: str,
) -> None:
    values = dict(model("embedding").__dict__)
    values[field] = value
    with pytest.raises(ValueError, match=message):
        ModelRuntimeObservation(**values)


def test_observation_rejects_used_memory_above_total() -> None:
    values = dict(model("embedding").__dict__)
    values.update(gpu_memory_used_mib=8193, gpu_memory_total_mib=8192)
    with pytest.raises(ValueError, match="exceed"):
        ModelRuntimeObservation(**values)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("BF16", "bfloat16"),
        ("bfloat16", "bfloat16"),
        ("FP16", "float16"),
        ("float32", "float32"),
        ("NVFP4", "nvfp4"),
        ("auto", "auto"),
        ("other", "unknown"),
    ],
)
def test_dtype_normalization(value: str, expected: str) -> None:
    assert normalize_dtype(value) == expected


def test_domain_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_observability_domain()
    assert "runtime_observability_domain=pass" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner, "run_mo_runtime_observability_domain", lambda: passing
    )
    assert runner.main(["--summary"]) == 0
    assert "models=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_runtime_observability_domain",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
