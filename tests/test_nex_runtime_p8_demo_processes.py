from __future__ import annotations

import io
import json
from dataclasses import replace

import pytest

from nex_ae_api import demo_runtime as ae_runtime
from nex_eos import demo_runtime as eos_runtime
from nex_runtime.demo_processes import (
    DEMO_APPLICATION_ARTIFACTS,
    DEMO_INSTALLED_PROCESS_IDS,
    DemoProcessManifestError,
    build_demo_process_manifest,
    demo_process_manifest_projection,
    validate_demo_process_manifest,
)
from nex_wc import demo_runtime as wc_runtime


def test_demo_process_manifest_freezes_installed_and_embedded_ownership() -> None:
    manifest = build_demo_process_manifest()
    projection = demo_process_manifest_projection(manifest)

    assert projection["schema_version"] == "p8_demo_process_manifest.v1"
    assert projection["installed_process_count"] == len(DEMO_INSTALLED_PROCESS_IDS)
    assert projection["embedded_component_count"] == 1
    assert projection["application_artifact_count"] == len(DEMO_APPLICATION_ARTIFACTS)
    assert projection["in_test_function_calls_admitted"] is False
    dispatcher = next(
        item
        for item in projection["processes"]
        if item["process_id"] == "nex-ae-agent-runtime-dispatcher"
    )
    assert dispatcher["execution_model"] == "EMBEDDED_COMPONENT"
    assert dispatcher["host_process_id"] == "nex-ae-agent-runtime-worker"
    assert dispatcher["command"] is None


def test_all_installed_background_processes_have_worker_pool_and_lifecycle() -> None:
    background = [
        item
        for item in build_demo_process_manifest()
        if item.kind == "worker"
    ]

    assert {item.process_id for item in background} == {
        "nex-ae-agent-runtime-worker",
        "nex-wc-event-delivery-worker",
        "nex-eos-outbox-publisher",
    }
    assert all(item.pool_workload == "worker" for item in background)
    assert all("HEARTBEAT" in item.health_contract for item in background)
    assert all("STOP" in item.sigterm_contract for item in background)
    assert all(item.command[:2] == ("python", "-m") for item in background)


@pytest.mark.parametrize(
    ("module", "argv", "process_id"),
    (
        (ae_runtime, ["worker", "--check"], "nex-ae-agent-runtime-worker"),
        (wc_runtime, ["events", "--check"], "nex-wc-event-delivery-worker"),
        (eos_runtime, ["outbox", "--check"], "nex-eos-outbox-publisher"),
    ),
)
def test_demo_runtime_commands_admit_check_but_fail_closed_execution(
    module, argv: list[str], process_id: str
) -> None:
    output = io.StringIO()
    assert module.main(argv, stdout=output) == 0
    check = json.loads(output.getvalue())
    assert check["status"] == "PASS"
    assert check["process_id"] == process_id
    assert check["execution_enabled"] is False

    output = io.StringIO()
    assert module.main(argv[:1], stdout=output) == 2
    blocked = json.loads(output.getvalue())
    assert blocked["status"] == "BLOCKED"
    assert blocked["failure_code"].endswith("execution_not_activated")


@pytest.mark.parametrize(
    "mutation",
    (
        lambda items: (*items, items[0]),
        lambda items: (replace(items[0], command=None), *items[1:]),
        lambda items: (
            *items,
            replace(
                next(item for item in items if item.kind == "component"),
                process_id="orphan-component",
                host_process_id="missing-worker",
            ),
        ),
        lambda items: tuple(
            replace(item, pool_workload="api") if item.kind == "worker" else item
            for item in items
        ),
        lambda items: tuple(
            replace(item, source_modules=("missing.module",))
            if item.process_id == "nex-eos-outbox-publisher"
            else item
            for item in items
        ),
        lambda items: tuple(
            item
            for item in items
            if item.process_id != "nex-eos-outbox-publisher"
        ),
        lambda items: tuple(
            replace(item, artifact_id="nex-ae-runtime")
            if item.artifact_id == "nex-eos-runtime"
            else item
            for item in items
        ),
        lambda items: tuple(
            replace(item, execution_model="IN_TEST_FUNCTION")
            if item.process_id == "nex-eos-outbox-publisher"
            else item
            for item in items
        ),
        lambda items: tuple(
            replace(item, health_contract="NONE", sigterm_contract="NONE")
            if item.process_id == "nex-eos-outbox-publisher"
            else item
            for item in items
        ),
        lambda items: tuple(
            replace(item, command=(*item.command, "tests/helper.py"))
            if item.process_id == "nex-eos-outbox-publisher"
            and item.command is not None
            else item
            for item in items
        ),
    ),
)
def test_demo_process_manifest_rejects_incomplete_or_ambiguous_bindings(
    mutation,
) -> None:
    manifest = build_demo_process_manifest()

    with pytest.raises(DemoProcessManifestError):
        validate_demo_process_manifest(
            mutation(manifest),
            module_finder=lambda name: object() if name != "missing.module" else None,
        )


def test_demo_process_manifest_contains_module_finder_failures() -> None:
    def fail(_name: str) -> object:
        raise ImportError("unavailable")

    with pytest.raises(DemoProcessManifestError, match="source module missing"):
        validate_demo_process_manifest(build_demo_process_manifest(), module_finder=fail)
