from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence


REQUIRED_OPERATION_SOURCES = ("catalog", "readiness", "telemetry", "runtime")
REQUIRED_OPERATION_CAPABILITIES = ("embedding", "reranking", "generation")
OPERATION_STATUSES = ("READY", "UNKNOWN", "DEGRADED", "UNAVAILABLE")
ACCEPTANCE_STATUSES = ("NOT_RUN", "PASS", "FAIL")
_STATUS_RANK = {status: index for index, status in enumerate(OPERATION_STATUSES)}


@dataclass(frozen=True)
class OperationsSourceAssessment:
    source: str
    status: str
    fresh: bool
    observed_at: str
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.source not in REQUIRED_OPERATION_SOURCES:
            raise ValueError("unsupported operations source")
        _validate_status(self.status)
        _parse_timestamp(self.observed_at)
        if self.status == "READY" and (not self.fresh or self.failure_code):
            raise ValueError("ready operations source must be fresh and successful")

    def to_wire(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "fresh": self.fresh,
            "observed_at": self.observed_at,
            "failure_code": self.failure_code,
        }


@dataclass(frozen=True)
class CapabilityOperationsStatus:
    provider_capability: str
    alias: str
    catalog_id: str
    model_revision: str
    deployment_id: str
    catalog_status: str
    route_status: str
    telemetry_status: str
    runtime_status: str
    operations_status: str
    request_count: int
    success_count: int
    failure_count: int
    last_latency_ms: int | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.provider_capability not in REQUIRED_OPERATION_CAPABILITIES:
            raise ValueError("unsupported provider capability")
        if not all(
            value.strip()
            for value in (
                self.alias,
                self.catalog_id,
                self.model_revision,
                self.deployment_id,
            )
        ):
            raise ValueError("capability operations identity must not be empty")
        for status in (
            self.catalog_status,
            self.route_status,
            self.telemetry_status,
            self.runtime_status,
            self.operations_status,
        ):
            _validate_status(status)
        if min(self.request_count, self.success_count, self.failure_count) < 0:
            raise ValueError("capability operations counters must not be negative")
        if self.success_count + self.failure_count > self.request_count:
            raise ValueError("provider outcomes must not exceed request count")
        if self.last_latency_ms is not None and self.last_latency_ms < 0:
            raise ValueError("last_latency_ms must not be negative")

    def to_wire(self) -> dict[str, Any]:
        return {
            "provider_capability": self.provider_capability,
            "alias": self.alias,
            "catalog_id": self.catalog_id,
            "model_revision": self.model_revision,
            "deployment_id": self.deployment_id,
            "catalog_status": self.catalog_status,
            "route_status": self.route_status,
            "telemetry_status": self.telemetry_status,
            "runtime_status": self.runtime_status,
            "operations_status": self.operations_status,
            "request_count": self.request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_latency_ms": self.last_latency_ms,
            "failure_code": self.failure_code,
        }


@dataclass(frozen=True)
class MOOperationsSnapshot:
    provider_mode: str
    operations_status: str
    generated_at: str
    acceptance_status: str
    sources: tuple[OperationsSourceAssessment, ...]
    capabilities: tuple[CapabilityOperationsStatus, ...]
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.provider_mode not in {"mock", "live"}:
            raise ValueError("provider_mode must be mock or live")
        _validate_status(self.operations_status)
        _parse_timestamp(self.generated_at)
        if self.acceptance_status not in ACCEPTANCE_STATUSES:
            raise ValueError("unsupported acceptance status")

    def to_wire(self) -> dict[str, Any]:
        status_counts = {
            status: sum(
                item.operations_status == status for item in self.capabilities
            )
            for status in OPERATION_STATUSES
        }
        return {
            "operations_schema_version": "mo_operations_snapshot.v1",
            "provider_mode": self.provider_mode,
            "operations_status": self.operations_status,
            "generated_at": self.generated_at,
            "acceptance_status": self.acceptance_status,
            "failure_code": self.failure_code,
            "sources": [source.to_wire() for source in self.sources],
            "capabilities": [item.to_wire() for item in self.capabilities],
            "summary": {
                "source_count": len(self.sources),
                "capability_count": len(self.capabilities),
                "capability_status_counts": status_counts,
            },
        }


def build_capability_operations_status(
    *,
    provider_capability: str,
    alias: str,
    catalog_id: str,
    model_revision: str,
    deployment_id: str,
    catalog_status: str,
    route_status: str,
    telemetry_status: str,
    runtime_status: str,
    request_count: int,
    success_count: int,
    failure_count: int,
    last_latency_ms: int | None = None,
    failure_code: str | None = None,
) -> CapabilityOperationsStatus:
    statuses = (catalog_status, route_status, telemetry_status, runtime_status)
    return CapabilityOperationsStatus(
        provider_capability=provider_capability,
        alias=alias,
        catalog_id=catalog_id,
        model_revision=model_revision,
        deployment_id=deployment_id,
        catalog_status=catalog_status,
        route_status=route_status,
        telemetry_status=telemetry_status,
        runtime_status=runtime_status,
        operations_status=worst_operations_status(statuses),
        request_count=request_count,
        success_count=success_count,
        failure_count=failure_count,
        last_latency_ms=last_latency_ms,
        failure_code=failure_code,
    )


def build_mo_operations_snapshot(
    *,
    provider_mode: str,
    generated_at: str,
    sources: Sequence[OperationsSourceAssessment],
    capabilities: Sequence[CapabilityOperationsStatus],
    acceptance_status: str = "NOT_RUN",
) -> MOOperationsSnapshot:
    source_by_name = _unique_by(
        sources,
        key=lambda item: item.source,
        duplicate_message="duplicate operations source",
    )
    capability_by_name = _unique_by(
        capabilities,
        key=lambda item: item.provider_capability,
        duplicate_message="duplicate operations capability",
    )
    missing_sources = set(REQUIRED_OPERATION_SOURCES) - set(source_by_name)
    missing_capabilities = set(REQUIRED_OPERATION_CAPABILITIES) - set(
        capability_by_name
    )
    statuses = [item.status for item in sources]
    statuses.extend(item.operations_status for item in capabilities)
    if missing_sources or missing_capabilities:
        statuses.append("UNKNOWN")
    operations_status = worst_operations_status(statuses)
    failure_code = (
        None
        if operations_status == "READY"
        else _snapshot_failure_code(
            operations_status,
            missing_sources=missing_sources,
            missing_capabilities=missing_capabilities,
        )
    )
    return MOOperationsSnapshot(
        provider_mode=provider_mode,
        operations_status=operations_status,
        generated_at=generated_at,
        acceptance_status=acceptance_status,
        sources=tuple(sources),
        capabilities=tuple(capabilities),
        failure_code=failure_code,
    )


def worst_operations_status(statuses: Sequence[str]) -> str:
    if not statuses:
        return "UNKNOWN"
    for status in statuses:
        _validate_status(status)
    return max(statuses, key=_STATUS_RANK.__getitem__)


def _snapshot_failure_code(
    status: str,
    *,
    missing_sources: set[str],
    missing_capabilities: set[str],
) -> str:
    if missing_sources or missing_capabilities:
        return "operations_snapshot_incomplete"
    return {
        "UNKNOWN": "operations_status_unknown",
        "DEGRADED": "operations_degraded",
        "UNAVAILABLE": "operations_unavailable",
    }[status]


def _unique_by(items, *, key, duplicate_message: str) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for item in items:
        identity = key(item)
        if identity in selected:
            raise ValueError(duplicate_message)
        selected[identity] = item
    return selected


def _validate_status(status: str) -> None:
    if status not in OPERATION_STATUSES:
        raise ValueError("unsupported operations status")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)
