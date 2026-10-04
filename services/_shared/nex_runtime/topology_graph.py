from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .topology import PlatformRuntimeManifest, RuntimeManifestError, RuntimeProcess


class RuntimeDependencyError(RuntimeManifestError):
    pass


@dataclass(frozen=True)
class DependencyProbeTarget:
    process_id: str
    dependency_id: str
    probe_mode: str
    url: str
    timeout_seconds: float


@dataclass(frozen=True)
class RuntimeStartupPlan:
    profile: str
    layers: tuple[tuple[str, ...], ...]
    dependency_probes: tuple[DependencyProbeTarget, ...]

    @property
    def ordered_process_ids(self) -> tuple[str, ...]:
        return tuple(item for layer in self.layers for item in layer)


def build_runtime_startup_plan(
    manifest: PlatformRuntimeManifest,
) -> RuntimeStartupPlan:
    processes = {item.process_id: item for item in manifest.processes}
    if not processes:
        raise RuntimeDependencyError("runtime manifest must contain a process")
    dependencies = {
        process_id: set(process.dependencies)
        for process_id, process in processes.items()
    }
    unknown = sorted(
        (process_id, dependency)
        for process_id, values in dependencies.items()
        for dependency in values
        if dependency not in processes
    )
    if unknown:
        process_id, dependency = unknown[0]
        raise RuntimeDependencyError(
            f"unknown dependency for {process_id}: {dependency}"
        )

    layers: list[tuple[str, ...]] = []
    remaining = set(processes)
    completed: set[str] = set()
    manifest_order = tuple(processes)
    while remaining:
        ready = tuple(
            process_id
            for process_id in manifest_order
            if process_id in remaining
            and dependencies[process_id].issubset(completed)
        )
        if not ready:
            cycle = ",".join(
                process_id for process_id in manifest_order if process_id in remaining
            )
            raise RuntimeDependencyError(f"cyclic runtime dependency graph: {cycle}")
        layers.append(ready)
        completed.update(ready)
        remaining.difference_update(ready)

    probe_mode = "liveness" if manifest.profile == "local_mock" else "readiness"
    probes = tuple(
        _dependency_probe_target(
            process,
            processes[dependency_id],
            probe_mode=probe_mode,
        )
        for process in manifest.processes
        for dependency_id in process.dependencies
    )
    return RuntimeStartupPlan(
        profile=manifest.profile,
        layers=tuple(layers),
        dependency_probes=probes,
    )


def runtime_startup_plan_projection(plan: RuntimeStartupPlan) -> dict[str, Any]:
    return {
        "schema_version": "platform_runtime_startup_plan.v1",
        "profile": plan.profile,
        "layers": [list(layer) for layer in plan.layers],
        "ordered_process_ids": list(plan.ordered_process_ids),
        "dependency_probes": [
            {
                "process_id": item.process_id,
                "dependency_id": item.dependency_id,
                "probe_mode": item.probe_mode,
                "url": item.url,
                "timeout_seconds": item.timeout_seconds,
            }
            for item in plan.dependency_probes
        ],
    }


def _dependency_probe_target(
    process: RuntimeProcess,
    dependency: RuntimeProcess,
    *,
    probe_mode: str,
) -> DependencyProbeTarget:
    probe = (
        dependency.liveness_probe
        if probe_mode == "liveness"
        else dependency.readiness_probe
    )
    if dependency.host is None or dependency.port is None or probe is None:
        raise RuntimeDependencyError(
            f"{process.process_id} dependency {dependency.process_id} "
            f"has no {probe_mode} HTTP probe"
        )
    return DependencyProbeTarget(
        process_id=process.process_id,
        dependency_id=dependency.process_id,
        probe_mode=probe_mode,
        url=f"http://{dependency.host}:{dependency.port}{probe.path}",
        timeout_seconds=probe.timeout_seconds,
    )
