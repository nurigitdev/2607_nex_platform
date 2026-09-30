from __future__ import annotations

from typing import Any, Protocol


class ModelRuntimeObservationView(Protocol):
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
    failure_code: str | None


class ModelRuntimeSnapshotView(Protocol):
    observation_mode: str
    runtime_status: str
    observed_at: str
    expires_at: str
    cache_status: str
    required_capabilities: tuple[str, ...]
    models: tuple[ModelRuntimeObservationView, ...]
    failure_code: str | None


def project_model_runtime_observation(
    observation: ModelRuntimeObservationView,
) -> dict[str, Any]:
    return {
        "model_runtime_observation_schema_version": "mo_model_runtime_observation.v1",
        "provider_capability": observation.provider_capability,
        "alias": observation.alias,
        "deployment_id": observation.deployment_id,
        "model_revision": observation.model_revision,
        "runtime_status": observation.runtime_status,
        "precision_status": observation.precision_status,
        "requested_dtype": observation.requested_dtype,
        "loaded_dtype": observation.loaded_dtype,
        "process_count": observation.process_count,
        "gpu_count": observation.gpu_count,
        "gpu_memory_used_mib": observation.gpu_memory_used_mib,
        "gpu_memory_total_mib": observation.gpu_memory_total_mib,
        "gpu_utilization_percent": observation.gpu_utilization_percent,
        "gpu_temperature_c": observation.gpu_temperature_c,
        "source": observation.source,
        "observed_at": observation.observed_at,
        "failure_code": observation.failure_code,
    }


def project_model_runtime_snapshot(
    snapshot: ModelRuntimeSnapshotView,
) -> dict[str, Any]:
    status_counts = {
        status: sum(model.runtime_status == status for model in snapshot.models)
        for status in ("HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN")
    }
    return {
        "runtime_observability_schema_version": "mo_runtime_observability.v1",
        "observation_mode": snapshot.observation_mode,
        "runtime_status": snapshot.runtime_status,
        "observed_at": snapshot.observed_at,
        "expires_at": snapshot.expires_at,
        "cache_status": snapshot.cache_status,
        "required_capabilities": list(snapshot.required_capabilities),
        "summary": {
            "required_count": len(snapshot.required_capabilities),
            "model_count": len(snapshot.models),
            "status_counts": status_counts,
        },
        "models": [
            project_model_runtime_observation(model) for model in snapshot.models
        ],
        "failure_code": snapshot.failure_code,
    }
