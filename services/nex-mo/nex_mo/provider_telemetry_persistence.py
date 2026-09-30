from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Mapping, Protocol, Sequence

from nex_mo.provider_telemetry import ProviderExecutionConfigView


PROVIDER_TELEMETRY_CAPABILITIES = frozenset(
    {"embedding", "reranking", "generation"}
)
PROVIDER_TELEMETRY_MUTATION_KINDS = frozenset({"success", "failure", "retry"})
PROVIDER_TELEMETRY_COUNTER_FIELDS = (
    "request_count",
    "success_count",
    "failure_count",
    "retryable_failure_count",
    "degraded_count",
    "attempt_count",
    "retry_count",
)


class ProviderTelemetryPersistenceError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderTelemetryIdentity:
    capability: str
    request_shape: str
    deployment_id: str
    model_revision: str

    def __post_init__(self) -> None:
        values = {
            "capability": self.capability,
            "request_shape": self.request_shape,
            "deployment_id": self.deployment_id,
            "model_revision": self.model_revision,
        }
        for field_name, value in values.items():
            _required_string(value, field_name)
        if self.capability not in PROVIDER_TELEMETRY_CAPABILITIES:
            raise ProviderTelemetryPersistenceError("unsupported provider capability")

    @classmethod
    def from_config(
        cls,
        config: ProviderExecutionConfigView,
    ) -> ProviderTelemetryIdentity:
        return cls(
            capability=config.capability,
            request_shape=config.request_shape,
            deployment_id=config.deployment_id,
            model_revision=config.model_revision,
        )

    def to_params(self) -> dict[str, str]:
        return {
            "capability": self.capability,
            "request_shape": self.request_shape,
            "deployment_id": self.deployment_id,
            "model_revision": self.model_revision,
        }

    def storage_key(self) -> str:
        canonical = "\x1f".join(
            (
                self.capability,
                self.request_shape,
                self.deployment_id,
                self.model_revision,
            )
        )
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProviderTelemetryMutation:
    identity: ProviderTelemetryIdentity
    mutation_kind: str
    observed_at: str
    request_increment: int = 0
    success_increment: int = 0
    failure_increment: int = 0
    retryable_failure_increment: int = 0
    degraded_increment: int = 0
    attempt_increment: int = 0
    retry_increment: int = 0
    last_outcome: str | None = None
    last_latency_ms: int | None = None
    last_status_code: int | None = None
    last_error_code: str | None = None
    last_failure_kind: str | None = None
    last_upstream_status_code: int | None = None
    last_retry_delay_ms: int | None = None
    last_retry_failure_kind: str | None = None

    def __post_init__(self) -> None:
        if self.mutation_kind not in PROVIDER_TELEMETRY_MUTATION_KINDS:
            raise ProviderTelemetryPersistenceError("unsupported telemetry mutation")
        _timestamp(self.observed_at, "observed_at")
        increments = self.counter_increments()
        if any(value < 0 for value in increments.values()):
            raise ProviderTelemetryPersistenceError(
                "telemetry increments must not be negative"
            )
        expected = {
            "success": (1, 1, 0, 1, 0),
            "failure": (1, 0, 1, 1, 0),
            "retry": (0, 0, 0, 1, 1),
        }[self.mutation_kind]
        actual = (
            self.request_increment,
            self.success_increment,
            self.failure_increment,
            self.attempt_increment,
            self.retry_increment,
        )
        if actual != expected:
            raise ProviderTelemetryPersistenceError(
                "telemetry mutation increments do not match mutation kind"
            )
        if self.retryable_failure_increment > self.failure_increment:
            raise ProviderTelemetryPersistenceError(
                "retryable failures cannot exceed failures"
            )
        if self.degraded_increment > self.failure_increment:
            raise ProviderTelemetryPersistenceError(
                "degraded failures cannot exceed failures"
            )
        if self.last_latency_ms is not None and self.last_latency_ms < 0:
            raise ProviderTelemetryPersistenceError("latency must not be negative")
        if self.last_retry_delay_ms is not None and self.last_retry_delay_ms < 0:
            raise ProviderTelemetryPersistenceError(
                "retry delay must not be negative"
            )

    def counter_increments(self) -> dict[str, int]:
        return {
            "request_count": self.request_increment,
            "success_count": self.success_increment,
            "failure_count": self.failure_increment,
            "retryable_failure_count": self.retryable_failure_increment,
            "degraded_count": self.degraded_increment,
            "attempt_count": self.attempt_increment,
            "retry_count": self.retry_increment,
        }

    def to_params(self) -> dict[str, Any]:
        return {
            **self.identity.to_params(),
            **self.counter_increments(),
            "mutation_kind": self.mutation_kind,
            "observed_at": self.observed_at,
            "last_outcome": self.last_outcome,
            "last_latency_ms": self.last_latency_ms,
            "last_status_code": self.last_status_code,
            "last_error_code": self.last_error_code,
            "last_failure_kind": self.last_failure_kind,
            "last_upstream_status_code": self.last_upstream_status_code,
            "last_retry_delay_ms": self.last_retry_delay_ms,
            "last_retry_failure_kind": self.last_retry_failure_kind,
        }


@dataclass(frozen=True)
class DurableProviderTelemetryRecord:
    identity: ProviderTelemetryIdentity
    request_count: int
    success_count: int
    failure_count: int
    retryable_failure_count: int
    degraded_count: int
    attempt_count: int
    retry_count: int
    last_outcome: str | None = None
    last_observed_at: str | None = None
    last_latency_ms: int | None = None
    last_status_code: int | None = None
    last_error_code: str | None = None
    last_failure_kind: str | None = None
    last_upstream_status_code: int | None = None
    last_retry_at: str | None = None
    last_retry_delay_ms: int | None = None
    last_retry_failure_kind: str | None = None

    def __post_init__(self) -> None:
        counters = {
            field_name: getattr(self, field_name)
            for field_name in PROVIDER_TELEMETRY_COUNTER_FIELDS
        }
        if any(value < 0 for value in counters.values()):
            raise ProviderTelemetryPersistenceError(
                "telemetry counters must not be negative"
            )
        if self.request_count != self.success_count + self.failure_count:
            raise ProviderTelemetryPersistenceError(
                "request count must equal success plus failure counts"
            )
        if self.attempt_count != self.request_count + self.retry_count:
            raise ProviderTelemetryPersistenceError(
                "attempt count must equal request plus retry counts"
            )
        if self.retryable_failure_count > self.failure_count:
            raise ProviderTelemetryPersistenceError(
                "retryable failures cannot exceed failures"
            )
        if self.degraded_count > self.failure_count:
            raise ProviderTelemetryPersistenceError(
                "degraded failures cannot exceed failures"
            )
        for field_name in ("last_observed_at", "last_retry_at"):
            value = getattr(self, field_name)
            if value is not None:
                _timestamp(value, field_name)

    @classmethod
    def from_mapping(
        cls,
        row: Mapping[str, Any],
    ) -> DurableProviderTelemetryRecord:
        return cls(
            identity=ProviderTelemetryIdentity(
                capability=str(row["capability"]),
                request_shape=str(row["request_shape"]),
                deployment_id=str(row["deployment_id"]),
                model_revision=str(row["model_revision"]),
            ),
            request_count=int(row["request_count"]),
            success_count=int(row["success_count"]),
            failure_count=int(row["failure_count"]),
            retryable_failure_count=int(row["retryable_failure_count"]),
            degraded_count=int(row["degraded_count"]),
            attempt_count=int(row["attempt_count"]),
            retry_count=int(row["retry_count"]),
            last_outcome=_optional_string(row.get("last_outcome")),
            last_observed_at=_optional_timestamp(row.get("last_observed_at")),
            last_latency_ms=_optional_int(row.get("last_latency_ms")),
            last_status_code=_optional_int(row.get("last_status_code")),
            last_error_code=_optional_string(row.get("last_error_code")),
            last_failure_kind=_optional_string(row.get("last_failure_kind")),
            last_upstream_status_code=_optional_int(
                row.get("last_upstream_status_code")
            ),
            last_retry_at=_optional_timestamp(row.get("last_retry_at")),
            last_retry_delay_ms=_optional_int(row.get("last_retry_delay_ms")),
            last_retry_failure_kind=_optional_string(
                row.get("last_retry_failure_kind")
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            **self.identity.to_params(),
            **{
                field_name: getattr(self, field_name)
                for field_name in PROVIDER_TELEMETRY_COUNTER_FIELDS
            },
            "last_outcome": self.last_outcome,
            "last_observed_at": self.last_observed_at,
            "last_latency_ms": self.last_latency_ms,
            "last_status_code": self.last_status_code,
            "last_error_code": self.last_error_code,
            "last_failure_kind": self.last_failure_kind,
            "last_upstream_status_code": self.last_upstream_status_code,
            "last_retry_at": self.last_retry_at,
            "last_retry_delay_ms": self.last_retry_delay_ms,
            "last_retry_failure_kind": self.last_retry_failure_kind,
        }


class DurableProviderTelemetryRepository(Protocol):
    def apply(
        self,
        mutation: ProviderTelemetryMutation,
    ) -> DurableProviderTelemetryRecord: ...

    def list_records(
        self,
        *,
        capability: str | None = None,
    ) -> Sequence[DurableProviderTelemetryRecord]: ...

    def clear(self) -> int: ...


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderTelemetryPersistenceError(
            f"{field_name} must be a non-empty string"
        )
    return value.strip()


def _timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ProviderTelemetryPersistenceError(
            f"{field_name} must be an ISO 8601 string"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderTelemetryPersistenceError(
            f"{field_name} must be ISO 8601"
        ) from exc
    if parsed.tzinfo is None:
        raise ProviderTelemetryPersistenceError(
            f"{field_name} must include a timezone"
        )
    return parsed


def _optional_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ProviderTelemetryPersistenceError(
                "persisted timestamp must include a timezone"
            )
        return value.isoformat().replace("+00:00", "Z")
    resolved = str(value)
    _timestamp(resolved, "persisted timestamp")
    return resolved


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)
