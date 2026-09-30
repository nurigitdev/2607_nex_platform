from __future__ import annotations

from types import SimpleNamespace

from nex_mo.provider_retry import ProviderRetryEvent
from nex_mo.provider_telemetry import (
    InMemoryProviderTelemetryStore,
    record_provider_retry,
)
import run_mo_provider_retry_telemetry as runner


def _config():
    return SimpleNamespace(
        capability="embedding",
        endpoint_env="NEX_MO_REMOTE_EMBEDDING_URL",
        configured=True,
        request_shape="openai_embeddings",
        model_name="model",
        model_revision="revision",
        deployment_id="deployment",
        api_key_env="NEX_MO_REMOTE_EMBEDDING_API_KEY",
        api_key="private",
    )


def _event(delay: float = 0.25) -> ProviderRetryEvent:
    return ProviderRetryEvent(
        capability="embedding",
        attempt_number=1,
        next_attempt_number=2,
        delay_seconds=delay,
        failure_kind="connection_error",
        reason="transient_failure_within_budget",
    )


def test_store_records_retry_attempt_without_incrementing_logical_request() -> None:
    store = InMemoryProviderTelemetryStore()
    config = _config()

    store.record_retry(config, event=_event(), observed_at="2026-09-30T00:00:00Z")
    snapshot = store.snapshot([config])[0]

    assert snapshot["request_count"] == 0
    assert snapshot["attempt_count"] == 1
    assert snapshot["retry_count"] == 1
    assert snapshot["last_retry_at"] == "2026-09-30T00:00:00Z"
    assert snapshot["last_retry_delay_ms"] == 250
    assert snapshot["last_retry_failure_kind"] == "connection_error"
    assert "private" not in str(snapshot)


def test_success_and_failure_each_count_the_final_attempt() -> None:
    store = InMemoryProviderTelemetryStore()
    config = _config()
    store.record_retry(config, event=_event(-1.0), observed_at="retry")
    store.record_success(config, latency_ms=2, observed_at="success")
    store.record_failure(
        config,
        route_error=SimpleNamespace(
            retryable=False,
            degraded=False,
            status_code=400,
            error_code="mo.invalid",
            failure_kind="upstream_4xx",
            upstream_status_code=400,
        ),
        latency_ms=3,
        observed_at="failure",
    )

    snapshot = store.snapshot([config])[0]
    assert snapshot["request_count"] == 2
    assert snapshot["attempt_count"] == 3
    assert snapshot["retry_count"] == 1
    assert snapshot["last_retry_delay_ms"] == 0


def test_module_retry_helper_accepts_injected_store_and_time() -> None:
    store = InMemoryProviderTelemetryStore()
    config = _config()

    record_provider_retry(
        config,
        _event(),
        store=store,
        observed_at=lambda: "observed",
    )

    assert store.snapshot([config])[0]["last_retry_at"] == "observed"


def test_retry_telemetry_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_retry_telemetry()
    assert passing["status"] == "PASS"
    assert "attempts=2" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_retry_telemetry", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "checks=6/6" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_retry_telemetry",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
