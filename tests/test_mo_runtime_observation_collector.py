from __future__ import annotations

import json
import subprocess

import pytest

from nex_mo.runtime_observability_collector import (
    RAW_SCHEMA_VERSION,
    RuntimeObservationCollectionError,
    collect_runtime_observations,
    normalize_runtime_observation_payload,
)
from nex_mo.runtime_observability_plan import build_runtime_observation_plan
import run_mo_runtime_observation_collector as runner


OBSERVED_AT = "2026-09-30T00:00:00Z"


def live_plan():
    return build_runtime_observation_plan(
        {
            "NEX_MO_RUNTIME_OBSERVABILITY_MODE": "live",
            "NEX_MO_DGX_SSH_TARGET": "operator@dgx.local",
        }
    )


def raw_item(
    capability: str,
    *,
    process_count: int = 1,
    model_seen: bool = True,
    loaded_dtype: str = "bfloat16",
    gpu_count: int = 1,
) -> dict[str, object]:
    return {
        "capability": capability,
        "process_count": process_count,
        "expected_model_seen": model_seen,
        "loaded_dtype": loaded_dtype,
        "gpu_count": gpu_count,
        "gpu_memory_used_mib": 1024,
        "gpu_memory_total_mib": 8192,
        "gpu_utilization_percent": 25.5,
        "gpu_temperature_c": 48.0,
    }


def raw_payload(*items: dict[str, object], nvidia: str = "available") -> dict[str, object]:
    return {
        "schema_version": RAW_SCHEMA_VERSION,
        "observed_at": OBSERVED_AT,
        "nvidia_smi_status": nvidia,
        "observations": list(items),
    }


def test_live_collector_executes_fixed_ssh_shape_and_projects_safe_snapshot() -> None:
    captured: dict[str, object] = {}
    payload = raw_payload(
        raw_item("embedding"), raw_item("reranking"), raw_item("generation")
    )

    def command_runner(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    snapshot = collect_runtime_observations(live_plan(), command_runner=command_runner)
    wire = snapshot.to_wire()
    serialized = json.dumps(wire)

    assert captured["command"][:5] == [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"
    ]
    assert captured["command"][-2:] == ["python3", "-"]
    assert "nvidia-smi" in str(captured["input"])
    assert wire["runtime_status"] == "HEALTHY"
    assert wire["summary"]["status_counts"]["HEALTHY"] == 3
    for private in ("operator@dgx.local", "process_id", "gpu_uuid", "model_path"):
        assert private not in serialized


def test_mock_collection_never_calls_command_runner() -> None:
    snapshot = collect_runtime_observations(
        build_runtime_observation_plan({}),
        command_runner=lambda *args, **kwargs: pytest.fail("must remain offline"),
        observed_at=OBSERVED_AT,
    )
    assert snapshot.runtime_status == "HEALTHY"


@pytest.mark.parametrize(
    ("item", "expected_status", "failure_code", "precision"),
    [
        (raw_item("embedding", process_count=0), "UNAVAILABLE", "model_runtime_process_missing", "MATCH"),
        (raw_item("embedding", process_count=2), "DEGRADED", "model_runtime_process_ambiguous", "MATCH"),
        (raw_item("embedding", model_seen=False), "DEGRADED", "model_runtime_identity_mismatch", "MATCH"),
        (raw_item("embedding", loaded_dtype="float32"), "DEGRADED", "model_runtime_precision_mismatch", "MISMATCH"),
        (raw_item("embedding", loaded_dtype="invalid"), "UNKNOWN", "model_runtime_precision_unverified", "UNVERIFIED"),
        (raw_item("embedding", gpu_count=0), "UNKNOWN", "gpu_runtime_evidence_missing", "MATCH"),
    ],
)
def test_normalization_classifies_runtime_failures(
    item: dict[str, object],
    expected_status: str,
    failure_code: str,
    precision: str,
) -> None:
    snapshot = normalize_runtime_observation_payload(
        raw_payload(item, raw_item("reranking"), raw_item("generation")),
        live_plan(),
        ttl_seconds=30,
    )
    observation = snapshot.models[0]
    assert observation.runtime_status == expected_status
    assert observation.failure_code == failure_code
    assert observation.precision_status == precision


def test_normalization_classifies_missing_duplicate_and_nvidia_evidence() -> None:
    missing = normalize_runtime_observation_payload(
        raw_payload(raw_item("reranking"), raw_item("generation")),
        live_plan(), ttl_seconds=30,
    )
    duplicate = normalize_runtime_observation_payload(
        raw_payload(
            raw_item("embedding"), raw_item("embedding"),
            raw_item("reranking"), raw_item("generation"),
        ),
        live_plan(), ttl_seconds=30,
    )
    no_nvidia = normalize_runtime_observation_payload(
        raw_payload(
            raw_item("embedding"), raw_item("reranking"), raw_item("generation"),
            nvidia="unavailable",
        ),
        live_plan(), ttl_seconds=30,
    )

    assert missing.models[0].failure_code == "model_runtime_observation_missing"
    assert duplicate.models[0].failure_code == "model_runtime_observation_ambiguous"
    assert duplicate.models[0].process_count == 2
    assert all(model.failure_code == "gpu_runtime_evidence_missing" for model in no_nvidia.models)


def test_normalization_sanitizes_invalid_optional_metric_types() -> None:
    item = raw_item("embedding")
    item.update(
        process_count=True,
        gpu_count=True,
        gpu_memory_used_mib="bad",
        gpu_memory_total_mib=False,
        gpu_utilization_percent="bad",
        gpu_temperature_c=None,
    )
    snapshot = normalize_runtime_observation_payload(
        raw_payload(item, raw_item("reranking"), raw_item("generation")),
        live_plan(), ttl_seconds=30,
    )
    observation = snapshot.models[0]
    assert observation.process_count == 0
    assert observation.gpu_count == 0
    assert observation.gpu_memory_used_mib is None
    assert observation.gpu_utilization_percent is None


def test_normalization_ignores_non_observation_entries() -> None:
    payload = raw_payload(
        raw_item("embedding"), raw_item("reranking"), raw_item("generation")
    )
    payload["observations"] = [None, {}, *payload["observations"]]  # type: ignore[list-item]

    snapshot = normalize_runtime_observation_payload(
        payload,
        live_plan(),
        ttl_seconds=30,
    )

    assert snapshot.runtime_status == "HEALTHY"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"schema_version": RAW_SCHEMA_VERSION},
        {"schema_version": RAW_SCHEMA_VERSION, "observed_at": 1, "observations": []},
    ],
)
def test_normalization_rejects_invalid_payload(payload) -> None:
    with pytest.raises(ValueError):
        normalize_runtime_observation_payload(payload, live_plan(), ttl_seconds=30)


@pytest.mark.parametrize(
    ("runner", "error_code"),
    [
        (lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("ssh", 1)), "collector_timeout"),
        (lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing")), "collector_unavailable"),
        (lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="failed"), "collector_command_failed"),
        (lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="not-json", stderr=""), "collector_output_invalid"),
        (lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="{}", stderr=""), "collector_payload_invalid"),
    ],
)
def test_live_collection_maps_failures_to_safe_codes(runner, error_code: str) -> None:
    with pytest.raises(RuntimeObservationCollectionError) as caught:
        collect_runtime_observations(live_plan(), command_runner=runner)
    assert caught.value.error_code == error_code


def test_unconfigured_live_plan_fails_before_command() -> None:
    plan = live_plan().__class__(**{**live_plan().__dict__, "configured": False})
    with pytest.raises(RuntimeObservationCollectionError, match="not_configured"):
        collect_runtime_observations(plan)


def test_collector_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_observation_collector()
    assert "runtime_observation_collector=pass" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner, "run_mo_runtime_observation_collector", lambda: passing
    )
    assert runner.main(["--summary"]) == 0
    assert "models=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_runtime_observation_collector",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
