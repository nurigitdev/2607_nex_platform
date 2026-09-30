from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from nex_mo.runtime_observability import normalize_dtype


GPU_MEMORY_WARN_PERCENT_ENV = "NEX_MO_GPU_MEMORY_WARN_PERCENT"
GPU_TEMPERATURE_WARN_C_ENV = "NEX_MO_GPU_TEMPERATURE_WARN_C"
DEFAULT_GPU_MEMORY_WARN_PERCENT = 90.0
DEFAULT_GPU_TEMPERATURE_WARN_C = 85.0


@dataclass(frozen=True)
class RuntimeObservationThresholds:
    gpu_memory_warn_percent: float = DEFAULT_GPU_MEMORY_WARN_PERCENT
    gpu_temperature_warn_c: float = DEFAULT_GPU_TEMPERATURE_WARN_C

    def __post_init__(self) -> None:
        if not 1 <= self.gpu_memory_warn_percent <= 100:
            raise ValueError("GPU memory warning percent must be between 1 and 100")
        if not 1 <= self.gpu_temperature_warn_c <= 150:
            raise ValueError("GPU temperature warning must be between 1 and 150")


@dataclass(frozen=True)
class RuntimeObservationDecision:
    runtime_status: str
    precision_status: str
    loaded_dtype: str
    failure_code: str | None
    memory_utilization_percent: float | None
    resource_pressure: bool


def runtime_observation_thresholds(
    environ: Mapping[str, str],
) -> RuntimeObservationThresholds:
    return RuntimeObservationThresholds(
        gpu_memory_warn_percent=_float_setting(
            environ,
            GPU_MEMORY_WARN_PERCENT_ENV,
            DEFAULT_GPU_MEMORY_WARN_PERCENT,
        ),
        gpu_temperature_warn_c=_float_setting(
            environ,
            GPU_TEMPERATURE_WARN_C_ENV,
            DEFAULT_GPU_TEMPERATURE_WARN_C,
        ),
    )


def classify_runtime_observation(
    *,
    process_count: int,
    expected_model_seen: bool,
    requested_dtype: str,
    loaded_dtype: str,
    nvidia_available: bool,
    gpu_count: int,
    gpu_memory_used_mib: int | None,
    gpu_memory_total_mib: int | None,
    gpu_utilization_percent: float | None,
    gpu_temperature_c: float | None,
    thresholds: RuntimeObservationThresholds,
) -> RuntimeObservationDecision:
    normalized_loaded = normalize_dtype(loaded_dtype)
    if normalized_loaded == "unknown":
        precision_status = "UNVERIFIED"
    elif normalized_loaded == requested_dtype:
        precision_status = "MATCH"
    else:
        precision_status = "MISMATCH"

    memory_percent = _memory_percent(
        used_mib=gpu_memory_used_mib,
        total_mib=gpu_memory_total_mib,
    )
    metrics_complete = all(
        value is not None
        for value in (
            memory_percent,
            gpu_utilization_percent,
            gpu_temperature_c,
        )
    )
    memory_pressure = (
        memory_percent is not None
        and memory_percent >= thresholds.gpu_memory_warn_percent
    )
    temperature_pressure = (
        gpu_temperature_c is not None
        and gpu_temperature_c >= thresholds.gpu_temperature_warn_c
    )
    resource_pressure = memory_pressure or temperature_pressure

    if process_count == 0:
        status, failure_code = "UNAVAILABLE", "model_runtime_process_missing"
    elif process_count != 1:
        status, failure_code = "DEGRADED", "model_runtime_process_ambiguous"
    elif not expected_model_seen:
        status, failure_code = "DEGRADED", "model_runtime_identity_mismatch"
    elif precision_status == "MISMATCH":
        status, failure_code = "DEGRADED", "model_runtime_precision_mismatch"
    elif precision_status == "UNVERIFIED":
        status, failure_code = "UNKNOWN", "model_runtime_precision_unverified"
    elif not nvidia_available or gpu_count == 0:
        status, failure_code = "UNKNOWN", "gpu_runtime_evidence_missing"
    elif not metrics_complete:
        status, failure_code = "UNKNOWN", "gpu_runtime_metrics_incomplete"
    elif resource_pressure:
        status, failure_code = "DEGRADED", "gpu_runtime_resource_pressure"
    else:
        status, failure_code = "HEALTHY", None

    return RuntimeObservationDecision(
        runtime_status=status,
        precision_status=precision_status,
        loaded_dtype=normalized_loaded,
        failure_code=failure_code,
        memory_utilization_percent=memory_percent,
        resource_pressure=resource_pressure,
    )


def _float_setting(
    environ: Mapping[str, str],
    key: str,
    default: float,
) -> float:
    raw_value = environ.get(key)
    if raw_value is None or raw_value == "":
        return default
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{key} must be numeric") from exc


def _memory_percent(*, used_mib: int | None, total_mib: int | None) -> float | None:
    if used_mib is None or total_mib is None or total_mib <= 0:
        return None
    return round((used_mib / total_mib) * 100, 3)
