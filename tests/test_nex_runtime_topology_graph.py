from __future__ import annotations

from dataclasses import replace

import pytest

from nex_runtime.topology import (
    PlatformRuntimeManifest,
    RuntimeModes,
    RuntimeProbe,
    RuntimeProcess,
)
from nex_runtime.topology_graph import (
    RuntimeDependencyError,
    build_runtime_startup_plan,
    runtime_startup_plan_projection,
)


def process(process_id: str, *, dependencies=(), network=True) -> RuntimeProcess:
    return RuntimeProcess(
        process_id,
        process_id,
        "api" if network else "worker",
        ("run", process_id),
        host="127.0.0.1" if network else None,
        port=(8100 + len(process_id)) if network else None,
        dependencies=dependencies,
        liveness_probe=RuntimeProbe("/health", 1.5) if network else None,
        readiness_probe=RuntimeProbe("/ready", 2.5) if network else None,
    )


def manifest(*processes: RuntimeProcess, profile="local_mock") -> PlatformRuntimeManifest:
    return PlatformRuntimeManifest(
        "platform_runtime_manifest.v1",
        profile,
        RuntimeModes("memory", "mock", "test_mock", "memory"),
        endpoints=(),
        processes=processes,
    )


def test_startup_plan_is_stable_and_uses_local_liveness() -> None:
    value = manifest(
        process("root"),
        process("parallel"),
        process("child", dependencies=("root",)),
        process("last", dependencies=("parallel", "child")),
    )

    plan = build_runtime_startup_plan(value)
    projection = runtime_startup_plan_projection(plan)

    assert plan.layers == (("root", "parallel"), ("child",), ("last",))
    assert plan.ordered_process_ids == ("root", "parallel", "child", "last")
    assert projection["ordered_process_ids"] == list(plan.ordered_process_ids)
    assert len(projection["dependency_probes"]) == 3
    assert all(item["probe_mode"] == "liveness" for item in projection["dependency_probes"])
    assert projection["dependency_probes"][0]["url"].endswith("/health")


def test_protected_plan_uses_readiness_probe_and_timeout() -> None:
    value = manifest(
        process("root"),
        process("child", dependencies=("root",)),
        profile="test",
    )

    plan = build_runtime_startup_plan(value)

    assert plan.dependency_probes[0].probe_mode == "readiness"
    assert plan.dependency_probes[0].url.endswith("/ready")
    assert plan.dependency_probes[0].timeout_seconds == 2.5


def test_empty_unknown_and_cyclic_graphs_are_rejected() -> None:
    with pytest.raises(RuntimeDependencyError, match="must contain a process"):
        build_runtime_startup_plan(manifest())

    with pytest.raises(RuntimeDependencyError, match="unknown dependency"):
        build_runtime_startup_plan(
            manifest(process("child", dependencies=("missing",)))
        )

    first = process("first", dependencies=("second",))
    second = process("second", dependencies=("first",))
    with pytest.raises(RuntimeDependencyError, match="cyclic runtime dependency graph"):
        build_runtime_startup_plan(manifest(first, second))


@pytest.mark.parametrize("profile", ["local_mock", "test"])
def test_dependency_without_required_http_probe_is_rejected(profile) -> None:
    background = process("background", network=False)
    child = process("child", dependencies=("background",))

    with pytest.raises(RuntimeDependencyError, match=f"has no {'liveness' if profile == 'local_mock' else 'readiness'} HTTP probe"):
        build_runtime_startup_plan(manifest(background, child, profile=profile))


def test_dependency_missing_only_selected_probe_is_rejected() -> None:
    root = replace(process("root"), readiness_probe=None)
    child = process("child", dependencies=("root",))

    with pytest.raises(RuntimeDependencyError, match="no readiness HTTP probe"):
        build_runtime_startup_plan(manifest(root, child, profile="production"))
