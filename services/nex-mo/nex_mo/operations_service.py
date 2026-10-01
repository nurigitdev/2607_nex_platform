from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
import os
from typing import Any

from nex_mo.catalog_lifecycle_service import CatalogLifecycleService
from nex_mo.operations_snapshot import (
    REQUIRED_OPERATION_CAPABILITIES,
    CapabilityOperationsStatus,
    OperationsSourceAssessment,
    build_capability_operations_status,
    build_mo_operations_snapshot,
)
from nex_mo.provider_readiness_service import ProviderReadinessService
from nex_mo.runtime_observability_service import RuntimeObservabilityService


TelemetryReader = Callable[[], Sequence[Mapping[str, Any]]]


class MOOperationsService:
    def __init__(
        self,
        *,
        catalog_service: CatalogLifecycleService,
        readiness_service: ProviderReadinessService,
        runtime_service: RuntimeObservabilityService,
        telemetry_reader: TelemetryReader,
        environ: Mapping[str, str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog_service = catalog_service
        self._readiness_service = readiness_service
        self._runtime_service = runtime_service
        self._telemetry_reader = telemetry_reader
        self._environ = environ
        self._now = now or (lambda: datetime.now(UTC))

    def snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        generated_at = _iso_timestamp(self._now())
        provider_mode = _provider_mode(self._environ)

        catalog, catalog_source = self._read_catalog(generated_at)
        readiness, readiness_source = self._read_readiness(
            generated_at,
            force_refresh=force_refresh,
        )
        telemetry, telemetry_source = self._read_telemetry(generated_at)
        runtime, runtime_source = self._read_runtime(
            generated_at,
            force_refresh=force_refresh,
        )
        capabilities = _compose_capabilities(
            catalog=catalog,
            readiness=readiness,
            telemetry=telemetry,
            runtime=runtime,
            provider_mode=provider_mode,
        )
        return build_mo_operations_snapshot(
            provider_mode=provider_mode,
            generated_at=generated_at,
            sources=(
                catalog_source,
                readiness_source,
                telemetry_source,
                runtime_source,
            ),
            capabilities=capabilities,
        ).to_wire()

    def _read_catalog(
        self,
        generated_at: str,
    ) -> tuple[dict[str, tuple[Any, Any]], OperationsSourceAssessment]:
        try:
            bindings = self._catalog_service.list_alias_bindings(state="ACTIVE")
            catalog: dict[str, tuple[Any, Any]] = {}
            for binding in bindings:
                if binding.provider_capability in catalog:
                    raise ValueError("duplicate active capability binding")
                entry = self._catalog_service.get_catalog_entry(binding.catalog_id)
                if entry.catalog_state != "ACTIVE":
                    raise ValueError("active binding references inactive catalog")
                catalog[binding.provider_capability] = (binding, entry)
            missing = set(REQUIRED_OPERATION_CAPABILITIES) - set(catalog)
            status = "UNKNOWN" if missing else "READY"
            return catalog, OperationsSourceAssessment(
                "catalog",
                status,
                not missing,
                generated_at,
                "catalog_capability_missing" if missing else None,
            )
        except Exception:
            return {}, OperationsSourceAssessment(
                "catalog",
                "UNAVAILABLE",
                False,
                generated_at,
                "catalog_source_unavailable",
            )

    def _read_readiness(
        self,
        generated_at: str,
        *,
        force_refresh: bool,
    ) -> tuple[dict[str, Mapping[str, Any]], OperationsSourceAssessment]:
        try:
            payload = self._readiness_service.check(force_refresh=force_refresh)
            routes = _items_by_capability(payload.get("routes"), "provider_capability")
            stale = payload.get("cache_status") in {"STALE", "MISS"}
            status = _readiness_status(payload, stale=stale)
            return routes, OperationsSourceAssessment(
                "readiness",
                status,
                not stale,
                _timestamp_or(payload.get("checked_at"), generated_at),
                _safe_failure_code(payload, status, "provider_route_not_ready"),
            )
        except Exception:
            return {}, OperationsSourceAssessment(
                "readiness",
                "UNAVAILABLE",
                False,
                generated_at,
                "readiness_source_unavailable",
            )

    def _read_telemetry(
        self,
        generated_at: str,
    ) -> tuple[dict[str, Mapping[str, Any]], OperationsSourceAssessment]:
        try:
            items = _items_by_capability(
                self._telemetry_reader(),
                "capability",
            )
            missing = set(REQUIRED_OPERATION_CAPABILITIES) - set(items)
            failures = any(_telemetry_item_status(item) == "DEGRADED" for item in items.values())
            unconfigured = _provider_mode(self._environ) == "live" and any(
                not item.get("configured") for item in items.values()
            )
            if missing or unconfigured:
                status = "UNKNOWN"
            elif failures:
                status = "DEGRADED"
            else:
                status = "READY"
            observed = max(
                (
                    str(item["last_observed_at"])
                    for item in items.values()
                    if item.get("last_observed_at")
                ),
                default=generated_at,
            )
            return items, OperationsSourceAssessment(
                "telemetry",
                status,
                not missing and not unconfigured,
                _timestamp_or(observed, generated_at),
                None if status == "READY" else "provider_telemetry_incomplete",
            )
        except Exception:
            return {}, OperationsSourceAssessment(
                "telemetry",
                "UNAVAILABLE",
                False,
                generated_at,
                "telemetry_source_unavailable",
            )

    def _read_runtime(
        self,
        generated_at: str,
        *,
        force_refresh: bool,
    ) -> tuple[dict[str, Mapping[str, Any]], OperationsSourceAssessment]:
        try:
            payload = self._runtime_service.observe(force_refresh=force_refresh)
            models = _items_by_capability(payload.get("models"), "provider_capability")
            stale = payload.get("cache_status") in {"STALE", "MISS"}
            status = _runtime_status(payload.get("runtime_status"), stale=stale)
            return models, OperationsSourceAssessment(
                "runtime",
                status,
                not stale,
                _timestamp_or(payload.get("observed_at"), generated_at),
                _safe_failure_code(payload, status, "runtime_observation_incomplete"),
            )
        except Exception:
            return {}, OperationsSourceAssessment(
                "runtime",
                "UNAVAILABLE",
                False,
                generated_at,
                "runtime_source_unavailable",
            )


def _compose_capabilities(
    *,
    catalog: Mapping[str, tuple[Any, Any]],
    readiness: Mapping[str, Mapping[str, Any]],
    telemetry: Mapping[str, Mapping[str, Any]],
    runtime: Mapping[str, Mapping[str, Any]],
    provider_mode: str,
) -> tuple[CapabilityOperationsStatus, ...]:
    capabilities = []
    for capability in REQUIRED_OPERATION_CAPABILITIES:
        catalog_item = catalog.get(capability)
        if catalog_item is None:
            continue
        binding, entry = catalog_item
        route = readiness.get(capability, {})
        telemetry_item = telemetry.get(capability, {})
        runtime_item = runtime.get(capability, {})
        catalog_status = "READY" if entry.catalog_state == "ACTIVE" else "UNAVAILABLE"
        route_status = _operation_status(route.get("status"))
        telemetry_status = _telemetry_item_status(
            telemetry_item,
            provider_mode=provider_mode,
        )
        runtime_status = _runtime_status(runtime_item.get("runtime_status"))
        status_failure = next(
            (
                str(code)
                for code in (
                    route.get("failure_code"),
                    telemetry_item.get("last_error_code"),
                    runtime_item.get("failure_code"),
                )
                if code
            ),
            None,
        )
        capabilities.append(
            build_capability_operations_status(
                provider_capability=capability,
                alias=binding.alias,
                catalog_id=entry.catalog_id,
                model_revision=entry.model_revision,
                deployment_id=entry.deployment_id,
                catalog_status=catalog_status,
                route_status=route_status,
                telemetry_status=telemetry_status,
                runtime_status=runtime_status,
                request_count=_nonnegative_int(telemetry_item.get("request_count")),
                success_count=_nonnegative_int(telemetry_item.get("success_count")),
                failure_count=_nonnegative_int(telemetry_item.get("failure_count")),
                last_latency_ms=_optional_nonnegative_int(
                    telemetry_item.get("last_latency_ms")
                ),
                failure_code=status_failure,
            )
        )
    return tuple(capabilities)


def _items_by_capability(value: Any, key: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("operations source collection is invalid")
    items: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("operations source item is invalid")
        capability = str(item.get(key) or "")
        if capability not in REQUIRED_OPERATION_CAPABILITIES:
            continue
        if capability in items:
            raise ValueError("duplicate operations source capability")
        items[capability] = item
    return items


def _provider_mode(environ: Mapping[str, str] | None) -> str:
    env = os.environ if environ is None else environ
    mode = str(env.get("NEX_MO_PROVIDER_MODE", "mock"))
    return mode if mode in {"mock", "live"} else "unknown"


def _readiness_status(payload: Mapping[str, Any], *, stale: bool) -> str:
    if stale:
        return "UNKNOWN"
    if payload.get("readiness_status") == "READY" and payload.get("ok") is True:
        return "READY"
    statuses = {
        str(item.get("status"))
        for item in payload.get("routes", [])
        if isinstance(item, Mapping)
    }
    if "UNAVAILABLE" in statuses:
        return "UNAVAILABLE"
    if "DEGRADED" in statuses:
        return "DEGRADED"
    return "UNKNOWN"


def _runtime_status(value: Any, *, stale: bool = False) -> str:
    if stale:
        return "UNKNOWN"
    return {
        "HEALTHY": "READY",
        "READY": "READY",
        "DEGRADED": "DEGRADED",
        "UNAVAILABLE": "UNAVAILABLE",
        "UNKNOWN": "UNKNOWN",
    }.get(str(value), "UNKNOWN")


def _operation_status(value: Any) -> str:
    return str(value) if value in {"READY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"} else "UNKNOWN"


def _telemetry_item_status(
    item: Mapping[str, Any],
    *,
    provider_mode: str = "mock",
) -> str:
    if not item:
        return "UNKNOWN"
    if provider_mode == "live" and not item.get("configured"):
        return "UNKNOWN"
    if item.get("last_outcome") == "failure" or _nonnegative_int(
        item.get("degraded_count")
    ) > 0:
        return "DEGRADED"
    return "READY"


def _safe_failure_code(
    payload: Mapping[str, Any],
    status: str,
    fallback: str,
) -> str | None:
    if status == "READY":
        return None
    code = payload.get("failure_code") or payload.get("error_code")
    return str(code) if code else fallback


def _timestamp_or(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    try:
        _iso_timestamp(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, AttributeError):
        return fallback
    return value


def _nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value)


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("operations time must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
