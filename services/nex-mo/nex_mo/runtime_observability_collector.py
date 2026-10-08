from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from typing import Any

from nex_mo.runtime_observability import (
    ModelRuntimeObservation,
    ModelRuntimeSnapshot,
    build_mock_model_runtime_snapshot,
    build_model_runtime_snapshot,
)
from nex_mo.runtime_observability_plan import RuntimeObservationPlan
from nex_mo.runtime_observability_policy import (
    RuntimeObservationThresholds,
    classify_runtime_observation,
)

RAW_SCHEMA_VERSION = "mo_runtime_observability_collector.raw.v1"
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class RuntimeObservationCollectionError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


REMOTE_COLLECTOR = r'''import json
import os
import subprocess
from datetime import datetime, timezone

TARGETS = json.loads(__TARGETS_JSON__)


def option_value(arguments, name):
    for index, argument in enumerate(arguments):
        if argument == name and index + 1 < len(arguments):
            return arguments[index + 1]
        prefix = name + "="
        if argument.startswith(prefix):
            return argument[len(prefix):]
    return ""


def model_reference(arguments):
    configured = option_value(arguments, "--model")
    if configured:
        return configured
    for index, argument in enumerate(arguments):
        if argument == "serve" and index + 1 < len(arguments):
            return arguments[index + 1]
    return ""


def configured_dtype(arguments, process_id):
    reference = model_reference(arguments)
    if not reference:
        return "unknown"
    if not os.path.isabs(reference):
        try:
            reference = os.path.join(os.readlink(f"/proc/{process_id}/cwd"), reference)
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            return "unknown"
    try:
        with open(os.path.join(reference, "config.json"), encoding="utf-8") as stream:
            config = json.load(stream)
    except (FileNotFoundError, NotADirectoryError, PermissionError, json.JSONDecodeError):
        return "unknown"
    value = config.get("torch_dtype", config.get("dtype", "unknown"))
    return value.strip().lower() if isinstance(value, str) else "unknown"


def csv_rows(arguments):
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return [
        [field.strip() for field in line.split(",")]
        for line in completed.stdout.splitlines()
        if line.strip()
    ]


def number(value, cast):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def unified_memory_total_mib():
    try:
        with open("/proc/meminfo", encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except (FileNotFoundError, PermissionError, ValueError, IndexError):
        return None
    return None


gpu_rows = csv_rows([
    "nvidia-smi",
    "--query-gpu=uuid,index,memory.total,memory.used,utilization.gpu,temperature.gpu",
    "--format=csv,noheader,nounits",
])
app_rows = csv_rows([
    "nvidia-smi",
    "--query-compute-apps=pid,gpu_uuid,used_memory",
    "--format=csv,noheader,nounits",
])
nvidia_status = "available" if gpu_rows is not None and app_rows is not None else "unavailable"

gpus = {}
unified_total = unified_memory_total_mib()
for row in gpu_rows or []:
    if len(row) != 6:
        continue
    total = number(row[2], int) or unified_total
    utilization = number(row[4], float)
    temperature = number(row[5], float)
    if None not in (total, utilization, temperature):
        gpus[row[0]] = {
            "total": total,
            "utilization": utilization,
            "temperature": temperature,
        }

apps = []
for row in app_rows or []:
    if len(row) != 3:
        continue
    pid = number(row[0], int)
    used = number(row[2], int)
    if pid is not None and used is not None and row[1] in gpus:
        apps.append({"pid": pid, "gpu_uuid": row[1], "used": used})

processes = {}
parents = {}
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    pid = int(entry)
    try:
        raw = open(f"/proc/{entry}/cmdline", "rb").read()
        stat = open(f"/proc/{entry}/stat", encoding="utf-8").read()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    arguments = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    if arguments:
        processes[pid] = arguments
    try:
        parents[pid] = int(stat.rsplit(")", 1)[1].split()[1])
    except (IndexError, ValueError):
        pass


def descendants(root_pids):
    result = set(root_pids)
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in result and pid not in result:
                result.add(pid)
                changed = True
    return result


observations = []
for target in TARGETS:
    roots = []
    for pid, arguments in processes.items():
        if not any("vllm" in argument.lower() for argument in arguments):
            continue
        try:
            port = int(option_value(arguments, "--port"))
        except ValueError:
            continue
        if port == target["process_port"]:
            roots.append((pid, arguments))

    tree = descendants([pid for pid, unused in roots])
    matched_apps = [app for app in apps if app["pid"] in tree]
    gpu_uuids = sorted({app["gpu_uuid"] for app in matched_apps})
    gpu_metrics = [gpus[gpu_uuid] for gpu_uuid in gpu_uuids]
    dtype = "unknown"
    expected_model_seen = False
    if len(roots) == 1:
        pid, arguments = roots[0]
        launch_dtype = option_value(arguments, "--dtype").strip().lower() or "auto"
        dtype = configured_dtype(arguments, pid) if launch_dtype == "auto" else launch_dtype
        expected_model = target["model_revision"]
        expected_model_seen = any(
            expected_model == argument or expected_model in argument
            for argument in arguments
        )

    observations.append({
        "capability": target["capability"],
        "process_count": len(roots),
        "expected_model_seen": expected_model_seen,
        "loaded_dtype": dtype,
        "gpu_count": len(gpu_uuids),
        "gpu_memory_used_mib": sum(app["used"] for app in matched_apps) if matched_apps else None,
        "gpu_memory_total_mib": sum(item["total"] for item in gpu_metrics) if gpu_metrics else None,
        "gpu_utilization_percent": max((item["utilization"] for item in gpu_metrics), default=None),
        "gpu_temperature_c": max((item["temperature"] for item in gpu_metrics), default=None),
    })

print(json.dumps({
    "schema_version": "mo_runtime_observability_collector.raw.v1",
    "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "nvidia_smi_status": nvidia_status,
    "observations": observations,
}))
'''


def collect_runtime_observations(
    plan: RuntimeObservationPlan,
    *,
    command_runner: CommandRunner = subprocess.run,
    observed_at: str | None = None,
    ttl_seconds: int = 30,
    thresholds: RuntimeObservationThresholds | None = None,
) -> ModelRuntimeSnapshot:
    if plan.mode == "mock":
        return build_mock_model_runtime_snapshot(
            observed_at=observed_at or "2026-09-30T00:00:00Z",
            ttl_seconds=ttl_seconds,
        )
    if not plan.configured or plan.ssh_target is None:
        raise RuntimeObservationCollectionError("collector_plan_not_configured")

    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={plan.connect_timeout_seconds}",
        "-o",
        f"PubkeyAuthentication={plan.ssh_pubkey_mode}",
        plan.ssh_target,
        "python3",
        "-",
    ]
    source = _remote_collector_source(plan)
    try:
        completed = command_runner(
            command,
            input=source,
            capture_output=True,
            text=True,
            timeout=plan.command_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeObservationCollectionError("collector_timeout") from exc
    except OSError as exc:
        raise RuntimeObservationCollectionError("collector_unavailable") from exc
    if completed.returncode != 0:
        raise RuntimeObservationCollectionError("collector_command_failed")
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeObservationCollectionError("collector_output_invalid") from exc
    try:
        return normalize_runtime_observation_payload(
            payload,
            plan,
            ttl_seconds=ttl_seconds,
            thresholds=thresholds,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeObservationCollectionError("collector_payload_invalid") from exc


def normalize_runtime_observation_payload(
    payload: Any,
    plan: RuntimeObservationPlan,
    *,
    ttl_seconds: int,
    thresholds: RuntimeObservationThresholds | None = None,
) -> ModelRuntimeSnapshot:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != RAW_SCHEMA_VERSION:
        raise ValueError("unsupported collector payload")
    observed_at = payload.get("observed_at")
    raw_observations = payload.get("observations")
    nvidia_status = payload.get("nvidia_smi_status")
    if not isinstance(observed_at, str) or not isinstance(raw_observations, list):
        raise ValueError("collector payload fields are invalid")
    by_capability: dict[str, list[Mapping[str, Any]]] = {}
    for item in raw_observations:
        if isinstance(item, Mapping) and isinstance(item.get("capability"), str):
            by_capability.setdefault(str(item["capability"]), []).append(item)

    models = [
        _normalize_model_observation(
            target=target,
            matches=by_capability.get(target.provider_capability, []),
            nvidia_available=nvidia_status == "available",
            observed_at=observed_at,
            thresholds=thresholds or RuntimeObservationThresholds(),
        )
        for target in plan.targets
    ]
    return build_model_runtime_snapshot(
        observation_mode="live",
        models=models,
        observed_at=observed_at,
        ttl_seconds=ttl_seconds,
        cache_status="FRESH",
    )


def _normalize_model_observation(
    *,
    target: Any,
    matches: list[Mapping[str, Any]],
    nvidia_available: bool,
    observed_at: str,
    thresholds: RuntimeObservationThresholds,
) -> ModelRuntimeObservation:
    if len(matches) != 1:
        process_count = 0 if not matches else sum(
            _integer(item.get("process_count"), default=0) for item in matches
        )
        return _unknown_observation(
            target,
            observed_at=observed_at,
            process_count=process_count,
            failure_code=(
                "model_runtime_observation_missing"
                if not matches
                else "model_runtime_observation_ambiguous"
            ),
        )

    item = matches[0]
    process_count = _integer(item.get("process_count"), default=-1)
    gpu_count = _integer(item.get("gpu_count"), default=0)
    metrics = {
        "gpu_memory_used_mib": _optional_integer(item.get("gpu_memory_used_mib")),
        "gpu_memory_total_mib": _optional_integer(item.get("gpu_memory_total_mib")),
        "gpu_utilization_percent": _optional_float(item.get("gpu_utilization_percent")),
        "gpu_temperature_c": _optional_float(item.get("gpu_temperature_c")),
    }
    expected_model_seen = item.get("expected_model_seen") is True
    decision = classify_runtime_observation(
        process_count=process_count,
        expected_model_seen=expected_model_seen,
        requested_dtype=target.requested_dtype,
        loaded_dtype=str(item.get("loaded_dtype") or "unknown"),
        nvidia_available=nvidia_available,
        gpu_count=gpu_count,
        thresholds=thresholds,
        **metrics,
    )

    return ModelRuntimeObservation(
        provider_capability=target.provider_capability,
        alias=target.alias,
        deployment_id=target.deployment_id,
        model_revision=target.model_revision,
        runtime_status=decision.runtime_status,
        precision_status=decision.precision_status,
        requested_dtype=target.requested_dtype,
        loaded_dtype=decision.loaded_dtype,
        process_count=max(process_count, 0),
        gpu_count=max(gpu_count, 0),
        source="protected_ssh",
        observed_at=observed_at,
        failure_code=decision.failure_code,
        **metrics,
    )


def _unknown_observation(
    target: Any,
    *,
    observed_at: str,
    process_count: int,
    failure_code: str,
) -> ModelRuntimeObservation:
    return ModelRuntimeObservation(
        provider_capability=target.provider_capability,
        alias=target.alias,
        deployment_id=target.deployment_id,
        model_revision=target.model_revision,
        runtime_status="UNKNOWN",
        precision_status="UNVERIFIED",
        requested_dtype=target.requested_dtype,
        loaded_dtype="unknown",
        process_count=max(process_count, 0),
        gpu_count=0,
        gpu_memory_used_mib=None,
        gpu_memory_total_mib=None,
        gpu_utilization_percent=None,
        gpu_temperature_c=None,
        source="protected_ssh",
        observed_at=observed_at,
        failure_code=failure_code,
    )


def _remote_collector_source(plan: RuntimeObservationPlan) -> str:
    targets = [
        {
            "capability": target.provider_capability,
            "process_port": target.process_port,
            "model_revision": target.model_revision,
        }
        for target in plan.targets
    ]
    return REMOTE_COLLECTOR.replace(
        "__TARGETS_JSON__",
        repr(json.dumps(targets, ensure_ascii=True, separators=(",", ":"))),
        1,
    )


def _integer(value: Any, *, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _optional_integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
