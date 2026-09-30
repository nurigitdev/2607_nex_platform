from __future__ import annotations

from dataclasses import fields
from typing import Sequence

from nex_mo.provider_registry import ProviderRouteError
from nex_mo.provider_retry import ProviderRetryEvent
from nex_mo.provider_telemetry import (
    ProviderExecutionConfigView,
    RemoteProviderTelemetryBucket,
)
from nex_mo.provider_telemetry_persistence import (
    DurableProviderTelemetryRecord,
    DurableProviderTelemetryRepository,
    ProviderTelemetryIdentity,
    ProviderTelemetryMutation,
)


_DURABLE_BUCKET_FIELDS = tuple(
    field.name
    for field in fields(DurableProviderTelemetryRecord)
    if field.name != "identity"
)


class DurableProviderTelemetryStore:
    def __init__(self, repository: DurableProviderTelemetryRepository) -> None:
        self._repository = repository

    def snapshot(
        self,
        configs: Sequence[ProviderExecutionConfigView],
        *,
        capability: str | None = None,
    ) -> list[dict[str, object]]:
        selected_configs = [
            config
            for config in configs
            if capability is None or config.capability == capability
        ]
        if not selected_configs:
            return []
        records = {
            record.identity.storage_key(): record
            for record in self._repository.list_records(capability=capability)
        }
        buckets = []
        for config in selected_configs:
            bucket = RemoteProviderTelemetryBucket.from_config(config)
            record = records.get(ProviderTelemetryIdentity.from_config(config).storage_key())
            if record is not None:
                _merge_record(bucket, record)
            buckets.append(bucket.to_wire())
        return sorted(
            buckets,
            key=lambda item: (str(item["capability"]), str(item["deployment_id"])),
        )

    def reset(self) -> None:
        self._repository.clear()

    def record_success(
        self,
        config: ProviderExecutionConfigView,
        *,
        latency_ms: int,
        observed_at: str,
    ) -> None:
        self._repository.apply(
            ProviderTelemetryMutation(
                identity=ProviderTelemetryIdentity.from_config(config),
                mutation_kind="success",
                observed_at=observed_at,
                request_increment=1,
                success_increment=1,
                attempt_increment=1,
                last_outcome="success",
                last_latency_ms=latency_ms,
                last_status_code=200,
            )
        )

    def record_failure(
        self,
        config: ProviderExecutionConfigView,
        *,
        route_error: ProviderRouteError,
        latency_ms: int,
        observed_at: str,
    ) -> None:
        self._repository.apply(
            ProviderTelemetryMutation(
                identity=ProviderTelemetryIdentity.from_config(config),
                mutation_kind="failure",
                observed_at=observed_at,
                request_increment=1,
                failure_increment=1,
                retryable_failure_increment=int(route_error.retryable),
                degraded_increment=int(route_error.degraded),
                attempt_increment=1,
                last_outcome="failure",
                last_latency_ms=latency_ms,
                last_status_code=route_error.status_code,
                last_error_code=route_error.error_code,
                last_failure_kind=(
                    route_error.failure_kind or "provider_route_error"
                ),
                last_upstream_status_code=route_error.upstream_status_code,
            )
        )

    def record_retry(
        self,
        config: ProviderExecutionConfigView,
        *,
        event: ProviderRetryEvent,
        observed_at: str,
    ) -> None:
        self._repository.apply(
            ProviderTelemetryMutation(
                identity=ProviderTelemetryIdentity.from_config(config),
                mutation_kind="retry",
                observed_at=observed_at,
                attempt_increment=1,
                retry_increment=1,
                last_retry_delay_ms=max(
                    0,
                    int(round(event.delay_seconds * 1000)),
                ),
                last_retry_failure_kind=event.failure_kind,
            )
        )


def _merge_record(
    bucket: RemoteProviderTelemetryBucket,
    record: DurableProviderTelemetryRecord,
) -> None:
    for field_name in _DURABLE_BUCKET_FIELDS:
        setattr(bucket, field_name, getattr(record, field_name))
