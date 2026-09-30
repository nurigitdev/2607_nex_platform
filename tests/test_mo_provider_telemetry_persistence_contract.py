from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from nex_mo.provider_telemetry_persistence import (
    DurableProviderTelemetryRecord,
    ProviderTelemetryIdentity,
    ProviderTelemetryMutation,
    ProviderTelemetryPersistenceError,
)
import run_mo_provider_telemetry_persistence_contract as runner


def _identity() -> ProviderTelemetryIdentity:
    return ProviderTelemetryIdentity(
        capability="embedding",
        request_shape="openai_embeddings",
        deployment_id="deployment-a",
        model_revision="revision-a",
    )


def _record(**overrides: object) -> DurableProviderTelemetryRecord:
    values: dict[str, object] = {
        "identity": _identity(),
        "request_count": 2,
        "success_count": 1,
        "failure_count": 1,
        "retryable_failure_count": 1,
        "degraded_count": 1,
        "attempt_count": 3,
        "retry_count": 1,
        "last_outcome": "failure",
        "last_observed_at": "2026-09-30T01:00:00Z",
        "last_retry_at": "2026-09-30T00:59:59Z",
    }
    values.update(overrides)
    return DurableProviderTelemetryRecord(**values)  # type: ignore[arg-type]


def test_identity_from_config_and_params_are_stable() -> None:
    config = SimpleNamespace(
        capability="reranking",
        request_shape="rerank",
        deployment_id="reranker-a",
        model_revision="qwen-reranker",
    )

    identity = ProviderTelemetryIdentity.from_config(config)

    assert identity.to_params() == {
        "capability": "reranking",
        "request_shape": "rerank",
        "deployment_id": "reranker-a",
        "model_revision": "qwen-reranker",
    }


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"capability": "unknown"}, "unsupported provider capability"),
        ({"request_shape": ""}, "request_shape must be a non-empty string"),
    ],
)
def test_identity_rejects_invalid_fields(values: dict[str, str], message: str) -> None:
    kwargs = _identity().to_params()
    kwargs.update(values)

    with pytest.raises(ProviderTelemetryPersistenceError, match=message):
        ProviderTelemetryIdentity(**kwargs)


def test_mutations_project_atomic_counter_deltas() -> None:
    success = ProviderTelemetryMutation(
        identity=_identity(),
        mutation_kind="success",
        observed_at="2026-09-30T01:00:00Z",
        request_increment=1,
        success_increment=1,
        attempt_increment=1,
        last_outcome="success",
        last_latency_ms=5,
        last_status_code=200,
    )
    failure = ProviderTelemetryMutation(
        identity=_identity(),
        mutation_kind="failure",
        observed_at="2026-09-30T01:00:01+00:00",
        request_increment=1,
        failure_increment=1,
        retryable_failure_increment=1,
        degraded_increment=1,
        attempt_increment=1,
        last_outcome="failure",
        last_latency_ms=10,
        last_status_code=503,
    )
    retry = ProviderTelemetryMutation(
        identity=_identity(),
        mutation_kind="retry",
        observed_at="2026-09-30T01:00:02Z",
        attempt_increment=1,
        retry_increment=1,
        last_retry_delay_ms=100,
        last_retry_failure_kind="upstream_5xx",
    )

    assert success.counter_increments()["success_count"] == 1
    assert failure.to_params()["retryable_failure_count"] == 1
    assert retry.counter_increments() == {
        "request_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "retryable_failure_count": 0,
        "degraded_count": 0,
        "attempt_count": 1,
        "retry_count": 1,
    }


def test_mutation_parameters_canonicalize_timestamp_to_utc_z() -> None:
    mutation = ProviderTelemetryMutation(
        identity=_identity(),
        mutation_kind="success",
        observed_at="2026-09-30T10:00:00+09:00",
        request_increment=1,
        success_increment=1,
        attempt_increment=1,
    )

    assert mutation.to_params()["observed_at"] == "2026-09-30T01:00:00Z"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mutation_kind": "unknown"}, "unsupported telemetry mutation"),
        ({"observed_at": "bad"}, "observed_at must be ISO 8601"),
        ({"observed_at": "2026-09-30T01:00:00"}, "must include a timezone"),
        ({"request_increment": -1}, "must not be negative"),
        ({"success_increment": 0}, "do not match mutation kind"),
        ({"retryable_failure_increment": 1}, "cannot exceed failures"),
        ({"degraded_increment": 1}, "cannot exceed failures"),
        ({"last_latency_ms": -1}, "latency must not be negative"),
        ({"last_retry_delay_ms": -1}, "retry delay must not be negative"),
    ],
)
def test_mutation_rejects_invalid_contract(
    kwargs: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "identity": _identity(),
        "mutation_kind": "success",
        "observed_at": "2026-09-30T01:00:00Z",
        "request_increment": 1,
        "success_increment": 1,
        "attempt_increment": 1,
    }
    values.update(kwargs)

    with pytest.raises(ProviderTelemetryPersistenceError, match=message):
        ProviderTelemetryMutation(**values)  # type: ignore[arg-type]


def test_record_mapping_round_trip_accepts_database_datetimes() -> None:
    source = _record(last_latency_ms=8, last_status_code=503).to_mapping()
    source["last_observed_at"] = datetime(2026, 9, 30, 1, tzinfo=UTC)

    restored = DurableProviderTelemetryRecord.from_mapping(source)

    assert restored == _record(last_latency_ms=8, last_status_code=503)
    assert "provider_endpoint" not in restored.to_mapping()


def test_record_mapping_canonicalizes_database_timezone_to_utc_z() -> None:
    source = _record().to_mapping()
    source["last_observed_at"] = datetime.fromisoformat(
        "2026-09-30T10:00:00+09:00"
    )
    source["last_retry_at"] = "2026-09-30T09:59:59+09:00"

    restored = DurableProviderTelemetryRecord.from_mapping(source)

    assert restored.last_observed_at == "2026-09-30T01:00:00Z"
    assert restored.last_retry_at == "2026-09-30T00:59:59Z"


def test_record_mapping_accepts_absent_optional_values() -> None:
    row = _record(last_observed_at=None, last_retry_at=None).to_mapping()

    restored = DurableProviderTelemetryRecord.from_mapping(row)

    assert restored.last_observed_at is None
    assert restored.last_retry_at is None
    assert restored.last_latency_ms is None
    assert restored.last_error_code is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"request_count": -1}, "counters must not be negative"),
        ({"request_count": 3}, "request count must equal"),
        ({"attempt_count": 4}, "attempt count must equal"),
        ({"retryable_failure_count": 2}, "cannot exceed failures"),
        ({"degraded_count": 2}, "cannot exceed failures"),
        ({"last_observed_at": "bad"}, "must be ISO 8601"),
    ],
)
def test_record_rejects_broken_aggregate_invariants(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ProviderTelemetryPersistenceError, match=message):
        _record(**overrides)


def test_record_mapping_rejects_naive_database_datetime() -> None:
    row = _record().to_mapping()
    row["last_retry_at"] = datetime(2026, 9, 30, 1)

    with pytest.raises(ProviderTelemetryPersistenceError, match="timezone"):
        DurableProviderTelemetryRecord.from_mapping(row)


def test_mutation_rejects_non_string_observed_timestamp() -> None:
    with pytest.raises(ProviderTelemetryPersistenceError, match="ISO 8601 string"):
        ProviderTelemetryMutation(
            identity=_identity(),
            mutation_kind="success",
            observed_at=None,  # type: ignore[arg-type]
            request_increment=1,
            success_increment=1,
            attempt_increment=1,
        )


def test_persistence_contract_smoke_and_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_telemetry_persistence_contract()
    assert passing["status"] == "PASS"
    assert all(passing["checks"].values())
    assert "attempts=2" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_persistence_contract",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "next=1154" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_persistence_contract",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
