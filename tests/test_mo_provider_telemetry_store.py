from __future__ import annotations

from types import SimpleNamespace

from nex_mo.provider_registry import ProviderRouteError
from nex_mo.provider_retry import ProviderRetryEvent
from nex_mo.provider_telemetry_persistence import (
    DurableProviderTelemetryRecord,
    ProviderTelemetryIdentity,
    ProviderTelemetryMutation,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore


def _config(capability: str = "embedding") -> SimpleNamespace:
    return SimpleNamespace(
        capability=capability,
        endpoint_env=f"NEX_MO_{capability.upper()}_URL",
        configured=True,
        request_shape="openai_embeddings" if capability == "embedding" else "rerank",
        model_name=f"{capability}-model",
        model_revision=f"{capability}-revision",
        deployment_id=f"{capability}-deployment",
        api_key_env=f"NEX_MO_{capability.upper()}_API_KEY",
        api_key="private-key",
    )


def _record(config: SimpleNamespace) -> DurableProviderTelemetryRecord:
    return DurableProviderTelemetryRecord(
        identity=ProviderTelemetryIdentity.from_config(config),
        request_count=2,
        success_count=1,
        failure_count=1,
        retryable_failure_count=1,
        degraded_count=1,
        attempt_count=3,
        retry_count=1,
        last_outcome="failure",
        last_observed_at="2026-09-30T01:00:02Z",
        last_latency_ms=18,
        last_status_code=503,
        last_error_code="mo.remote_embedding.http_error",
        last_failure_kind="upstream_5xx",
        last_upstream_status_code=503,
        last_retry_at="2026-09-30T01:00:01Z",
        last_retry_delay_ms=250,
        last_retry_failure_kind="upstream_5xx",
    )


class RepositoryStub:
    def __init__(self, records: list[DurableProviderTelemetryRecord] | None = None) -> None:
        self.records = list(records or [])
        self.mutations: list[ProviderTelemetryMutation] = []
        self.filters: list[str | None] = []
        self.clear_count = 0

    def apply(
        self,
        mutation: ProviderTelemetryMutation,
    ) -> DurableProviderTelemetryRecord:
        self.mutations.append(mutation)
        return self.records[0] if self.records else _empty_record(mutation.identity)

    def list_records(
        self,
        *,
        capability: str | None = None,
    ) -> list[DurableProviderTelemetryRecord]:
        self.filters.append(capability)
        return [
            record
            for record in self.records
            if capability is None or record.identity.capability == capability
        ]

    def clear(self) -> int:
        deleted = len(self.records)
        self.records.clear()
        self.clear_count += 1
        return deleted


def _empty_record(identity: ProviderTelemetryIdentity) -> DurableProviderTelemetryRecord:
    return DurableProviderTelemetryRecord(
        identity=identity,
        request_count=0,
        success_count=0,
        failure_count=0,
        retryable_failure_count=0,
        degraded_count=0,
        attempt_count=0,
        retry_count=0,
    )


def test_snapshot_merges_durable_counters_with_current_runtime_config() -> None:
    embedding = _config()
    reranking = _config("reranking")
    repository = RepositoryStub([_record(embedding)])
    store = DurableProviderTelemetryStore(repository)

    snapshot = store.snapshot([reranking, embedding])

    assert [item["capability"] for item in snapshot] == ["embedding", "reranking"]
    assert snapshot[0]["request_count"] == 2
    assert snapshot[0]["attempt_count"] == 3
    assert snapshot[0]["endpoint_env"] == "NEX_MO_EMBEDDING_URL"
    assert snapshot[0]["authorization_configured"] is True
    assert "private-key" not in str(snapshot)
    assert snapshot[1]["request_count"] == 0
    assert repository.filters == [None]


def test_snapshot_filters_current_capability_and_ignores_historical_rows() -> None:
    embedding = _config()
    historical = _config()
    historical.deployment_id = "old-deployment"
    repository = RepositoryStub([_record(embedding), _record(historical)])
    store = DurableProviderTelemetryStore(repository)

    snapshot = store.snapshot([embedding], capability="embedding")

    assert len(snapshot) == 1
    assert snapshot[0]["deployment_id"] == "embedding-deployment"
    assert repository.filters == ["embedding"]


def test_snapshot_returns_empty_without_query_for_unknown_capability() -> None:
    repository = RepositoryStub()
    store = DurableProviderTelemetryStore(repository)

    assert store.snapshot([_config()], capability="unknown") == []
    assert repository.filters == []


def test_store_projects_success_failure_and_retry_mutations() -> None:
    config = _config()
    repository = RepositoryStub()
    store = DurableProviderTelemetryStore(repository)

    store.record_success(config, latency_ms=4, observed_at="2026-09-30T01:00:00Z")
    store.record_failure(
        config,
        route_error=ProviderRouteError(
            status_code=503,
            error_code="mo.remote_embedding.http_error",
            detail="private detail",
            retryable=True,
            degraded=True,
            failure_kind=None,
            upstream_status_code=503,
        ),
        latency_ms=8,
        observed_at="2026-09-30T01:00:01Z",
    )
    store.record_retry(
        config,
        event=ProviderRetryEvent(
            capability="embedding",
            attempt_number=1,
            next_attempt_number=2,
            delay_seconds=0.1256,
            failure_kind="upstream_5xx",
            reason="transient_failure_within_budget",
        ),
        observed_at="2026-09-30T01:00:02Z",
    )

    success, failure, retry = repository.mutations
    assert success.mutation_kind == "success"
    assert success.last_status_code == 200
    assert failure.mutation_kind == "failure"
    assert failure.retryable_failure_increment == 1
    assert failure.degraded_increment == 1
    assert failure.last_failure_kind == "provider_route_error"
    assert "private detail" not in str(failure.to_params())
    assert retry.mutation_kind == "retry"
    assert retry.last_retry_delay_ms == 126


def test_retry_delay_is_clamped_and_failure_kind_is_preserved() -> None:
    repository = RepositoryStub()
    store = DurableProviderTelemetryStore(repository)

    store.record_retry(
        _config(),
        event=ProviderRetryEvent(
            capability="embedding",
            attempt_number=1,
            next_attempt_number=2,
            delay_seconds=-0.1,
            failure_kind="connect_timeout",
            reason="transient_failure_within_budget",
        ),
        observed_at="2026-09-30T01:00:00Z",
    )

    assert repository.mutations[0].last_retry_delay_ms == 0


def test_reset_delegates_to_repository_clear() -> None:
    repository = RepositoryStub([_record(_config())])
    store = DurableProviderTelemetryStore(repository)

    store.reset()

    assert repository.clear_count == 1
    assert repository.records == []
