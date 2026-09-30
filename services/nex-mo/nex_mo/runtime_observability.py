from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from nex_mo.provider_catalog import build_model_profile_catalog
from nex_mo.provider_registry import DEFAULT_PROVIDER_ROUTES
from nex_mo.runtime_observability_projection import project_model_runtime_snapshot


REQUIRED_RUNTIME_CAPABILITIES = ("embedding", "reranking", "generation")
RUNTIME_STATUSES = {"HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"}
PRECISION_STATUSES = {"MATCH", "MISMATCH", "UNVERIFIED"}
OBSERVATION_SOURCES = {"mock_fixture", "protected_ssh"}
RUNTIME_CACHE_STATUSES = {"FRESH", "REFRESHED", "STALE"}


@dataclass(frozen=True)
class ModelRuntimeObservation:
    provider_capability: str
    alias: str
    deployment_id: str
    model_revision: str
    runtime_status: str
    precision_status: str
    requested_dtype: str
    loaded_dtype: str
    process_count: int
    gpu_count: int
    gpu_memory_used_mib: int | None
    gpu_memory_total_mib: int | None
    gpu_utilization_percent: float | None
    gpu_temperature_c: float | None
    source: str
    observed_at: str
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.provider_capability not in REQUIRED_RUNTIME_CAPABILITIES:
            raise ValueError("unsupported runtime capability")
        if not all(
            value.strip()
            for value in (self.alias, self.deployment_id, self.model_revision)
        ):
            raise ValueError("runtime identity fields must not be empty")
        if self.runtime_status not in RUNTIME_STATUSES:
            raise ValueError("unsupported runtime status")
        if self.precision_status not in PRECISION_STATUSES:
            raise ValueError("unsupported precision status")
        if self.source not in OBSERVATION_SOURCES:
            raise ValueError("unsupported observation source")
        if self.process_count < 0 or self.gpu_count < 0:
            raise ValueError("runtime counts must not be negative")
        _validate_resource_values(self)
        _parse_timestamp(self.observed_at)


@dataclass(frozen=True)
class ModelRuntimeSnapshot:
    observation_mode: str
    runtime_status: str
    observed_at: str
    expires_at: str
    cache_status: str
    required_capabilities: tuple[str, ...]
    models: tuple[ModelRuntimeObservation, ...]
    failure_code: str | None

    def to_wire(self) -> dict[str, Any]:
        return project_model_runtime_snapshot(self)


def build_mock_model_runtime_snapshot(
    *,
    observed_at: str = "2026-09-30T00:00:00Z",
    ttl_seconds: int = 30,
) -> ModelRuntimeSnapshot:
    selected_profiles = {
        profile.provider_capability: profile
        for profile in build_model_profile_catalog({})
        if profile.selected
    }
    models = []
    for route in DEFAULT_PROVIDER_ROUTES:
        capability = route.provider_capability
        profile = selected_profiles[capability]
        dtype = normalize_dtype(profile.precision)
        models.append(
            ModelRuntimeObservation(
                provider_capability=capability,
                alias=route.alias,
                deployment_id=route.deployment_id,
                model_revision=profile.model_name,
                runtime_status="HEALTHY",
                precision_status="MATCH",
                requested_dtype=dtype,
                loaded_dtype=dtype,
                process_count=0,
                gpu_count=0,
                gpu_memory_used_mib=None,
                gpu_memory_total_mib=None,
                gpu_utilization_percent=None,
                gpu_temperature_c=None,
                source="mock_fixture",
                observed_at=observed_at,
            )
        )
    return build_model_runtime_snapshot(
        observation_mode="mock",
        models=models,
        observed_at=observed_at,
        ttl_seconds=ttl_seconds,
        cache_status="FRESH",
    )


def build_model_runtime_snapshot(
    *,
    observation_mode: str,
    models: Sequence[ModelRuntimeObservation],
    observed_at: str,
    ttl_seconds: int,
    cache_status: str,
    required_capabilities: tuple[str, ...] = REQUIRED_RUNTIME_CAPABILITIES,
) -> ModelRuntimeSnapshot:
    if observation_mode not in {"mock", "live"}:
        raise ValueError("observation_mode must be mock or live")
    if not required_capabilities or len(set(required_capabilities)) != len(
        required_capabilities
    ):
        raise ValueError("required capabilities must be unique and non-empty")
    if not 1 <= ttl_seconds <= 300:
        raise ValueError("ttl_seconds must be between 1 and 300")
    if cache_status not in RUNTIME_CACHE_STATUSES:
        raise ValueError("unsupported runtime cache status")
    observed = _parse_timestamp(observed_at)
    by_capability: dict[str, ModelRuntimeObservation] = {}
    for model in models:
        if model.provider_capability not in required_capabilities:
            raise ValueError("model capability is not required")
        if model.provider_capability in by_capability:
            raise ValueError("duplicate model runtime capability")
        by_capability[model.provider_capability] = model

    missing = set(required_capabilities) - set(by_capability)
    statuses = {model.runtime_status for model in models}
    if cache_status == "STALE" or missing or "UNKNOWN" in statuses:
        runtime_status = "UNKNOWN"
        failure_code = "runtime_observation_incomplete"
    elif "UNAVAILABLE" in statuses:
        runtime_status = "UNAVAILABLE"
        failure_code = "model_runtime_unavailable"
    elif "DEGRADED" in statuses:
        runtime_status = "DEGRADED"
        failure_code = "model_runtime_degraded"
    else:
        runtime_status = "HEALTHY"
        failure_code = None

    return ModelRuntimeSnapshot(
        observation_mode=observation_mode,
        runtime_status=runtime_status,
        observed_at=observed_at,
        expires_at=(observed + timedelta(seconds=ttl_seconds))
        .isoformat()
        .replace("+00:00", "Z"),
        cache_status=cache_status,
        required_capabilities=required_capabilities,
        models=tuple(models),
        failure_code=failure_code,
    )


def normalize_dtype(value: str) -> str:
    normalized = value.strip().lower().replace("_", "")
    aliases = {
        "bf16": "bfloat16",
        "bfloat16": "bfloat16",
        "fp16": "float16",
        "float16": "float16",
        "fp32": "float32",
        "float32": "float32",
        "nvfp4": "nvfp4",
        "auto": "auto",
        "unknown": "unknown",
    }
    return aliases.get(normalized, "unknown")


def _validate_resource_values(observation: ModelRuntimeObservation) -> None:
    used = observation.gpu_memory_used_mib
    total = observation.gpu_memory_total_mib
    if used is not None and used < 0:
        raise ValueError("GPU memory used must not be negative")
    if total is not None and total <= 0:
        raise ValueError("GPU memory total must be positive")
    if used is not None and total is not None and used > total:
        raise ValueError("GPU memory used must not exceed total")
    utilization = observation.gpu_utilization_percent
    if utilization is not None and not 0 <= utilization <= 100:
        raise ValueError("GPU utilization must be between 0 and 100")
    temperature = observation.gpu_temperature_c
    if temperature is not None and not 0 <= temperature <= 150:
        raise ValueError("GPU temperature must be between 0 and 150")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)
