from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from nex_mo import provider_telemetry, remote_provider
from nex_mo.providers import ProviderRouteError
import run_mo_provider_telemetry_extraction as runner


def config(capability: str = "embedding", deployment: str = "deployment"):
    return SimpleNamespace(
        capability=capability,
        endpoint_env=f"NEX_MO_{capability.upper()}_URL",
        configured=True,
        request_shape="shape",
        model_name="model",
        model_revision="revision",
        deployment_id=deployment,
        api_key_env="PRIVATE_KEY_ENV",
        api_key="private-value",
    )


def test_memory_store_records_filters_sorts_and_resets() -> None:
    store = provider_telemetry.InMemoryProviderTelemetryStore()
    generation = config("generation", "z")
    embedding = config("embedding", "a")
    store.record_success(generation, latency_ms=7, observed_at="now")
    store.record_success(generation, latency_ms=8, observed_at="later")
    store.record_failure(
        embedding,
        route_error=ProviderRouteError(
            503,
            "mo.unavailable",
            "private",
            retryable=True,
            degraded=True,
            failure_kind=None,
        ),
        latency_ms=9,
        observed_at="now",
    )

    snapshot = store.snapshot([generation, embedding])
    filtered = store.snapshot([generation, embedding], capability="generation")

    assert [item["capability"] for item in snapshot] == ["embedding", "generation"]
    assert filtered[0]["request_count"] == 2
    assert snapshot[0]["last_failure_kind"] == "provider_route_error"
    assert snapshot[0]["retryable_failure_count"] == 1
    assert "private-value" not in str(snapshot)
    store.reset()
    assert all(item["request_count"] == 0 for item in store.snapshot([generation, embedding]))


def test_recorded_call_supports_success_failure_and_injected_time() -> None:
    store = provider_telemetry.InMemoryProviderTelemetryStore()
    selected = config()
    ticks = iter((1.0, 1.005, 2.0, 1.5))

    result = provider_telemetry.recorded_provider_call(
        selected,
        lambda: {"ok": True},
        store=store,
        clock=lambda: next(ticks),
        observed_at=lambda: "observed",
    )
    assert result == {"ok": True}
    assert store.snapshot([selected])[0]["last_latency_ms"] == 5

    def fail():
        raise ProviderRouteError(400, "mo.invalid", "detail")

    with pytest.raises(ProviderRouteError):
        provider_telemetry.recorded_provider_call(
            selected,
            fail,
            store=store,
            clock=lambda: next(ticks),
            observed_at=lambda: "failed",
        )
    snapshot = store.snapshot([selected])[0]
    assert snapshot["failure_count"] == 1
    assert snapshot["last_latency_ms"] == 0


def test_module_helpers_and_compatibility_exports() -> None:
    selected = config()
    store = provider_telemetry.InMemoryProviderTelemetryStore()
    assert provider_telemetry.telemetry_key(selected) == (
        "embedding|shape|deployment|revision"
    )
    assert provider_telemetry.elapsed_ms(2.0, clock=lambda: 1.0) == 0
    assert provider_telemetry.utc_now().endswith("Z")
    assert provider_telemetry.list_provider_telemetry([selected], store=store)[0][
        "capability"
    ] == "embedding"
    provider_telemetry.reset_provider_telemetry(store)
    assert remote_provider.RemoteProviderTelemetryBucket is (
        provider_telemetry.RemoteProviderTelemetryBucket
    )


def test_telemetry_extraction_evidence_and_runner(tmp_path: Path, monkeypatch, capsys) -> None:
    missing = runner.run_mo_provider_telemetry_extraction(tmp_path)
    assert missing["status"] == "FAIL"
    assert missing["summary"]["failed_check_count"] == 3

    passing = runner.run_mo_provider_telemetry_extraction()
    assert passing["status"] == "PASS"
    assert passing["persistence_status"] == "PROCESS_LOCAL_ADAPTER_READY_FOR_S116"
    monkeypatch.setattr(runner, "run_mo_provider_telemetry_extraction", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "stores=1" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_provider_telemetry_extraction", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "telemetry_extraction=fail" in capsys.readouterr().out
