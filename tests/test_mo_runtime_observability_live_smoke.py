from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_mo_runtime_observability_live_smoke as smoke
from nex_mo.runtime_observability import (
    ModelRuntimeObservation,
    build_model_runtime_snapshot,
)
from nex_mo.runtime_observability_collector import RuntimeObservationCollectionError


OBSERVED_AT = "2026-09-30T04:00:00Z"


def live_env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        smoke.SSH_TARGET_ENV: "operator@dgx.internal",
        "NEX_MO_VLLM_API_KEY": "private-api-key",
    }


def healthy_snapshot(plan: object):
    models = []
    for target in plan.targets:
        models.append(
            ModelRuntimeObservation(
                provider_capability=target.provider_capability,
                alias=target.alias,
                deployment_id=target.deployment_id,
                model_revision=target.model_revision,
                runtime_status="HEALTHY",
                precision_status="MATCH",
                requested_dtype=target.requested_dtype,
                loaded_dtype=target.requested_dtype,
                process_count=1,
                gpu_count=1,
                gpu_memory_used_mib=4096,
                gpu_memory_total_mib=12288,
                gpu_utilization_percent=37.0,
                gpu_temperature_c=55.0,
                source="protected_ssh",
                observed_at=OBSERVED_AT,
            )
        )
    return build_model_runtime_snapshot(
        observation_mode="live",
        models=models,
        observed_at=OBSERVED_AT,
        ttl_seconds=30,
        cache_status="FRESH",
    )


def test_live_smoke_skips_by_default_and_rejects_invalid_configuration() -> None:
    skipped = smoke.run_mo_runtime_observability_live_smoke({})
    invalid = smoke.run_mo_runtime_observability_live_smoke(
        {smoke.ACTIVATION_ENV: "1", smoke.SSH_TARGET_ENV: "-oProxyCommand=unsafe"}
    )

    assert skipped["status"] == "SKIPPED"
    assert skipped["issues"][0]["error_code"] == "live_smoke_not_enabled"
    assert invalid["status"] == "FAIL"
    assert invalid["issues"][0]["error_code"] == "live_configuration_invalid"


def test_live_smoke_collects_three_healthy_redacted_models() -> None:
    calls: list[dict[str, object]] = []

    def collector(plan: object, **kwargs: object):
        calls.append({"plan": plan, **kwargs})
        return healthy_snapshot(plan)

    evidence = smoke.run_mo_runtime_observability_live_smoke(
        live_env(),
        collector=collector,
    )
    serialized = json.dumps(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["stage_status"]["assertions"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "model_count": 3,
        "healthy_count": 3,
        "precision_match_count": 3,
        "gpu_observed_count": 3,
    }
    assert calls[0]["plan"].mode == "live"
    assert calls[0]["ttl_seconds"] == 30
    assert calls[0]["thresholds"].gpu_memory_warn_percent == 90.0
    assert "operator@dgx.internal" not in serialized
    assert "private-api-key" not in serialized


def test_live_smoke_fails_closed_for_degraded_or_private_snapshot() -> None:
    class WireSnapshot:
        def to_wire(self) -> dict[str, object]:
            return {
                "observation_mode": "live",
                "runtime_status": "DEGRADED",
                "models": [
                    {
                        "provider_capability": "embedding",
                        "model_revision": "operator@dgx.internal",
                        "runtime_status": "DEGRADED",
                        "precision_status": "MISMATCH",
                        "process_count": 2,
                        "gpu_count": 0,
                    }
                ],
            }

    evidence = smoke.run_mo_runtime_observability_live_smoke(
        live_env(),
        collector=lambda *args, **kwargs: WireSnapshot(),
    )

    assert evidence["status"] == "FAIL"
    assert evidence["stage_status"]["assertions"] == "FAIL"
    assert evidence["checks"]["private_runtime_values_absent"] is False
    assert evidence["snapshot"] is None
    assert "operator@dgx.internal" not in json.dumps(evidence)


def test_live_smoke_reports_safe_collection_failures() -> None:
    def expected_failure(*args: object, **kwargs: object):
        raise RuntimeObservationCollectionError("collector_timeout")

    def unexpected_failure(*args: object, **kwargs: object):
        raise RuntimeError("private diagnostic")

    class InvalidSnapshot:
        def to_wire(self) -> list[object]:
            return []

    expected = smoke.run_mo_runtime_observability_live_smoke(
        live_env(), collector=expected_failure
    )
    unexpected = smoke.run_mo_runtime_observability_live_smoke(
        live_env(), collector=unexpected_failure
    )
    invalid = smoke.run_mo_runtime_observability_live_smoke(
        live_env(), collector=lambda *args, **kwargs: InvalidSnapshot()
    )

    assert expected["issues"] == [
        {"stage": "collection", "error_code": "collector_timeout"}
    ]
    assert unexpected["issues"] == [
        {"stage": "collection", "error_code": "collector_unexpected_failure"}
    ]
    assert invalid["issues"] == [
        {"stage": "collection", "error_code": "collector_payload_invalid"}
    ]
    assert "private diagnostic" not in json.dumps(unexpected)


def test_live_smoke_summary_output_and_protected_evidence_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passed = smoke.run_mo_runtime_observability_live_smoke(
        live_env(), collector=lambda plan, **kwargs: healthy_snapshot(plan)
    )
    assert smoke.summary_line(passed) == (
        "mo_runtime_observability_live_smoke=pass models=3/3 healthy=3/3 "
        "precision=3/3 gpu=3/3 next=1171"
    )
    skipped = smoke.run_mo_runtime_observability_live_smoke({})
    assert smoke.summary_line(skipped) == (
        "mo_runtime_observability_live_smoke=skipped "
        f"reason={smoke.ACTIVATION_ENV}"
    )

    output = Path("/tmp/nex-mo-runtime-observability-test/evidence.json")
    smoke.write_evidence(output, passed)
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    with pytest.raises(ValueError, match="below /tmp"):
        smoke.write_evidence(Path.cwd() / "protected-evidence.json", passed)

    monkeypatch.delenv(smoke.ACTIVATION_ENV, raising=False)
    assert smoke.main(["--summary"]) == 0
    assert "skipped" in capsys.readouterr().out
    cli_output = Path("/tmp/nex-mo-runtime-observability-test/cli-evidence.json")
    assert smoke.main(["--output", str(cli_output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"
    assert json.loads(cli_output.read_text(encoding="utf-8"))["status"] == "SKIPPED"
