from __future__ import annotations

import io
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from nex_ae_api import demo_runtime as ae_runtime
from nex_eos import demo_runtime as eos_runtime
from nex_runtime.demo_process_runtime import DEMO_RUNTIME_CHECK_MODE_ENV
from nex_runtime.demo_processes import (
    DEMO_APPLICATION_ARTIFACTS,
    DEMO_INSTALLED_PROCESS_IDS,
    DemoProcessManifestError,
    build_demo_process_manifest,
    demo_process_manifest_projection,
    validate_demo_process_manifest,
)
from nex_wc import demo_runtime as wc_runtime


class _Resource:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


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
        item for item in build_demo_process_manifest() if item.kind == "worker"
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
    check_record = {**module.build_source_check(), "database": {"status": "PASS"}}
    output = io.StringIO()
    assert (
        module.main(
            argv,
            stdout=output,
            live_check=lambda _environ: check_record,
        )
        == 0
    )
    check = json.loads(output.getvalue())
    assert check["status"] == "PASS"
    assert check["process_id"] == process_id
    assert check["execution_enabled"] is True
    assert check["domain_claiming_enabled"] is False
    assert check["composition_mode"] == "EXISTING_COMPONENT_COMPOSITION"
    assert check["new_business_behavior_added"] is False

    output = io.StringIO()
    assert (
        module.main(
            [*argv[:1], "--max-cycles", "1"],
            stdout=output,
            live_run=lambda _environ, **_kwargs: {
                "status": "STOPPED",
                "process_id": process_id,
            },
        )
        == 0
    )
    assert json.loads(output.getvalue())["status"] == "STOPPED"

    output = io.StringIO()
    assert (
        module.main(
            argv,
            stdout=output,
            live_check=lambda _environ: (_ for _ in ()).throw(ValueError("private")),
        )
        == 2
    )
    blocked = json.loads(output.getvalue())
    assert blocked["status"] == "BLOCKED"
    assert blocked["secret_included"] is False


@pytest.mark.parametrize(
    ("module", "process", "process_id"),
    (
        (ae_runtime, "worker", "nex-ae-agent-runtime-worker"),
        (wc_runtime, "events", "nex-wc-event-delivery-worker"),
        (eos_runtime, "outbox", "nex-eos-outbox-publisher"),
    ),
)
def test_demo_runtime_offline_package_check_is_explicit_and_non_runtime(
    module, process: str, process_id: str
) -> None:
    output = io.StringIO()

    assert (
        module.main(
            [process, "--check"],
            stdout=output,
            environ={DEMO_RUNTIME_CHECK_MODE_ENV: "PACKAGE"},
            live_check=lambda _environ: (_ for _ in ()).throw(AssertionError),
        )
        == 0
    )

    record = json.loads(output.getvalue())
    assert record["process_id"] == process_id
    assert record["check_scope"] == "PACKAGE"
    assert record["package_ready"] is True
    assert record["runtime_ready"] is False
    assert record["database"] == {"status": "NOT_REQUESTED"}
    assert record["secret_included"] is False


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
            item for item in items if item.process_id != "nex-eos-outbox-publisher"
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
        validate_demo_process_manifest(
            build_demo_process_manifest(), module_finder=fail
        )


@pytest.mark.parametrize("module", (ae_runtime, wc_runtime, eos_runtime))
def test_service_live_check_and_run_close_worker_resource(
    module, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked = _Resource()
    monkeypatch.setattr(
        module,
        "demo_process_database_check",
        lambda _resource, **_kwargs: {"status": "PASS"},
    )

    check = module.build_live_check(
        {}, resource_builder=lambda *_args, **_kwargs: checked
    )

    assert check["status"] == "PASS"
    assert check["database"] == {"status": "PASS"}
    assert checked.closed is True

    running = _Resource()
    monkeypatch.setattr(
        module, "install_demo_process_signal_handlers", lambda _token: {}
    )
    monkeypatch.setattr(
        module, "restore_demo_process_signal_handlers", lambda _old: None
    )
    monkeypatch.setattr(
        module,
        "run_demo_process_loop",
        lambda resource, **_kwargs: {
            "status": "STOPPED",
            "process_id": module.build_source_check()["process_id"],
        },
    )

    result = module.run_live(
        {},
        max_cycles=1,
        resource_builder=lambda *_args, **_kwargs: running,
    )

    assert result["status"] == "STOPPED"
    assert running.closed is True


class _Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one(self):
        return self.value

    def scalar_one(self):
        return self.value


class _Session:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _statement):
        return _Result(self.value)


@pytest.mark.parametrize(
    ("module", "value", "expected"),
    (
        (
            ae_runtime,
            {"queued": 2, "recoverable": 1},
            {"queued_count": 2, "recoverable_lease_count": 1},
        ),
        (
            wc_runtime,
            {"active_jobs": 3, "coordination_events": 2, "approval_events": 1},
            {
                "active_job_count": 3,
                "coordination_event_count": 2,
                "approval_event_count": 1,
            },
        ),
        (eos_runtime, 4, {"pending_outbox_count": 4}),
    ),
)
def test_service_queue_projections_are_safe_and_recovery_aware(
    module, value, expected
) -> None:
    resource = SimpleNamespace(sessions=lambda: _Session(value))

    recovery = module._queue_projection(resource, recovery=True)
    readiness = module._queue_projection(resource, recovery=False)

    assert recovery["probe"] == "RECOVERY"
    assert readiness["probe"] == "READINESS"
    assert recovery["status"] == "IDLE"
    assert recovery["domain_claiming_enabled"] is False
    for key, expected_value in expected.items():
        assert recovery[key] == expected_value


def test_ae_demo_runtime_admits_installed_composition_activation() -> None:
    environment = {
        "NEX_P8_DEMO_DOMAIN_CLAIMING_ENABLED": "true",
        "NEX_PROFILE": "staging_live",
        "NEX_DEPLOYMENT_BOUNDARY": "P8_DEMO",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
        **{name: "configured" for name in ae_runtime.REQUIRED_DOMAIN_SECRETS},
    }

    check = ae_runtime.build_source_check(environment)

    assert check["domain_claiming_enabled"] is True
    assert check["domain_claiming_activation"] == "ACTIVE"
    assert check["installed_execution_composition"] == "P6_P8_EXISTING_COMPONENTS"
    assert check["new_business_behavior_added"] is False
