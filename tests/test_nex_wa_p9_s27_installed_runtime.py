from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from nex_runtime import DEFAULT_SERVICE_SCOPE
from nex_runtime.deployment_artifacts import build_current_deployment_artifact_catalog
from nex_runtime.deployment_entrypoints import (
    build_current_packaged_runtime_manifest,
    build_packaged_entrypoint_definitions,
)
from nex_wa import (
    OA_SUBJECT_VERIFY_SCOPE,
    WaInstalledConsumerProcess,
    WaSettings,
    build_installed_consumer_process,
    build_installed_source_registry,
)
from nex_wa.agent_result_source import EOS_PROJECT_VERIFY_SCOPE, WORK_SOURCE_READ_SCOPE
from nex_wa.consumer_main import main, run_installed_consumer
from nex_wa.installed_consumer import _wire_now

ROOT = Path(__file__).resolve().parents[1]


class _Persistence:
    def __init__(self) -> None:
        self.evidence_admission_service = object()
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Runtime:
    def __init__(self, *, executions=None) -> None:
        self.config = SimpleNamespace(
            worker_id="wa-installed-worker",
            worker_type="wa.evidence_consumer",
        )
        self.executions = list(executions or [])
        self.ready_calls = 0
        self.recovery_calls = []
        self.stop_calls = []

    def require_ready(self) -> None:
        self.ready_calls += 1

    def recover_stale(self, **kwargs):
        self.recovery_calls.append(kwargs)
        return ({"job_id": "job-stale"},)

    def run_once(self):
        status = self.executions.pop(0) if self.executions else "IDLE"
        return SimpleNamespace(to_summary=lambda: {"status": status})

    def stop(self, **kwargs):
        self.stop_calls.append(kwargs)
        return ()


class _Process:
    def __init__(self, statuses=("IDLE", "SUCCEEDED")) -> None:
        self.statuses = list(statuses)
        self.closed = False

    def metadata(self):
        return {
            "service_id": "nex-wa",
            "process_id": "nex-wa-evidence-consumer",
            "work_claiming_enabled": True,
        }

    def startup(self):
        return {"readiness_status": "READY", "recovered_job_count": 0}

    def run_once(self):
        return {"status": self.statuses.pop(0)}

    def close(self):
        self.closed = True


def test_installed_registry_resolves_exact_service_edges_and_minimum_scopes() -> None:
    persistence = _Persistence()
    endpoint_calls = []
    token_calls = []

    def endpoint(service_id, *, environ):
        endpoint_calls.append((service_id, environ["NEX_PROFILE"]))
        return SimpleNamespace(base_url=f"https://{service_id}.example")

    def token(configured, *, audience, scopes, environ):
        token_calls.append((configured, audience, scopes, environ["NEX_PROFILE"]))
        return f"signed-{audience}"

    registry = build_installed_source_registry(
        environ={"NEX_PROFILE": "staging_live"},
        persistence=persistence,  # type: ignore[arg-type]
        endpoint_resolver=endpoint,
        token_resolver=token,
    )

    assert registry.readiness()["ok"] is True
    assert [item[0] for item in endpoint_calls] == [
        "nex-ae-api",
        "nex-wc",
        "nex-oa",
        "nex-eos",
    ]
    assert {(audience, scopes) for _, audience, scopes, _ in token_calls} == {
        ("nex-ae-api", (DEFAULT_SERVICE_SCOPE, WORK_SOURCE_READ_SCOPE)),
        ("nex-wc", (DEFAULT_SERVICE_SCOPE, WORK_SOURCE_READ_SCOPE)),
        ("nex-oa", (DEFAULT_SERVICE_SCOPE, OA_SUBJECT_VERIFY_SCOPE)),
        ("nex-eos", (DEFAULT_SERVICE_SCOPE, EOS_PROJECT_VERIFY_SCOPE)),
    }


def test_installed_process_builder_disposes_persistence_on_composition_failure() -> None:
    persistence = _Persistence()

    with pytest.raises(RuntimeError, match="composition failed"):
        build_installed_consumer_process(
            environ={"NEX_PROFILE": "test"},
            persistence_builder=lambda **_: persistence,
            registry_builder=lambda **_: (_ for _ in ()).throw(
                RuntimeError("composition failed")
            ),
        )

    assert persistence.disposed is True


def test_installed_process_builder_uses_default_worker_identity() -> None:
    persistence = _Persistence()
    runtime = _Runtime()
    observed = {}

    def build_runtime(**kwargs):
        observed.update(kwargs)
        return runtime

    process = build_installed_consumer_process(
        environ={"NEX_PROFILE": "test"},
        persistence_builder=lambda **_: persistence,
        registry_builder=lambda **_: object(),
        runtime_builder=build_runtime,
    )

    assert process.runtime is runtime
    assert observed["worker_id"] == "nex-wa-evidence-consumer-001"
    assert persistence.disposed is False
    process.close()


@pytest.mark.parametrize("worker_id", ["", " worker", "x" * 129])
def test_installed_process_builder_rejects_invalid_worker_identity(worker_id) -> None:
    persistence = _Persistence()

    with pytest.raises(ValueError, match="NEX_WA_WORKER_ID"):
        build_installed_consumer_process(
            environ={"NEX_PROFILE": "test", "NEX_WA_WORKER_ID": worker_id},
            persistence_builder=lambda **_: persistence,
            registry_builder=lambda **_: object(),
            runtime_builder=lambda **_: (_ for _ in ()).throw(
                AssertionError("runtime must not be built")
            ),
        )

    assert persistence.disposed is True


def test_installed_process_recovers_runs_stops_and_disposes() -> None:
    persistence = _Persistence()
    runtime = _Runtime(executions=["SUCCEEDED"])
    process = WaInstalledConsumerProcess(
        WaSettings(
            service_id="nex-wa",
            profile="test",
            version="2.1.0-p9-s27",
            build_sha="p9s27",
            stale_job_seconds=300,
        ),
        persistence,  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
    )

    assert process.metadata()["work_claiming_enabled"] is True
    assert process.startup()["recovered_job_count"] == 1
    assert process.run_once()["status"] == "SUCCEEDED"
    process.close()

    assert runtime.ready_calls == 1
    assert runtime.recovery_calls[0]["stale_after_seconds"] == 300
    assert len(runtime.stop_calls) == 1
    assert persistence.disposed is True


def test_installed_loop_emits_lifecycle_and_sleeps_only_between_cycles() -> None:
    process = _Process()
    output = io.StringIO()
    sleeps = []

    result = run_installed_consumer(
        process,  # type: ignore[arg-type]
        poll_interval_seconds=0.5,
        max_cycles=2,
        sleeper=sleeps.append,
        out=output,
    )

    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert result == 0
    assert [event["state"] for event in events] == [
        "STARTED",
        "RECOVERED",
        "WORK",
        "STOPPED",
    ]
    assert events[-1]["completed_cycles"] == 2
    assert sleeps == [0.5]
    assert process.closed is True


def test_installed_loop_honors_external_supervisor_stop_before_polling() -> None:
    process = _Process(())
    output = io.StringIO()

    assert run_installed_consumer(
        process,  # type: ignore[arg-type]
        should_stop=lambda: True,
        sleeper=lambda _: (_ for _ in ()).throw(AssertionError("must not sleep")),
        out=output,
    ) == 0

    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["state"] for event in events] == [
        "STARTED",
        "RECOVERED",
        "STOPPED",
    ]
    assert events[-1]["completed_cycles"] == 0
    assert process.closed is True


@pytest.mark.parametrize(
    ("poll", "cycles", "message"),
    [(0, 1, "poll interval"), (0.1, 0, "max cycles")],
)
def test_installed_loop_rejects_invalid_bounds(poll, cycles, message) -> None:
    with pytest.raises(ValueError, match=message):
        run_installed_consumer(
            _Process(("IDLE",)),  # type: ignore[arg-type]
            poll_interval_seconds=poll,
            max_cycles=cycles,
        )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--poll-interval-seconds", "0"],
        ["--max-cycles", "0"],
    ],
)
def test_main_rejects_invalid_installed_loop_bounds(arguments) -> None:
    with pytest.raises(SystemExit):
        main(arguments, environ={})


def test_installed_clock_rejects_timezone_naive_values() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _wire_now(lambda: datetime(2026, 10, 28, 12, 0))


def test_main_sanitizes_installed_startup_failure(capsys) -> None:
    assert main(
        ["--max-cycles", "1"],
        environ={},
        process_builder=lambda **_: (_ for _ in ()).throw(
            RuntimeError("private database and token detail")
        ),
    ) == 2

    result = json.loads(capsys.readouterr().out)
    assert result["error_code"] == "WA_INSTALLED_CONSUMER_STARTUP_FAILED"
    assert "private" not in str(result)


def test_packaged_manifest_and_compose_activate_the_same_job_claiming_entrypoint() -> None:
    manifest = build_current_packaged_runtime_manifest(environ={})
    definitions = build_packaged_entrypoint_definitions(
        manifest,
        catalog=build_current_deployment_artifact_catalog(),
    )
    entry = next(
        item for item in definitions if item.process_id == "nex-wa-evidence-consumer"
    )
    compose = yaml.safe_load(
        (ROOT / "deployment/compose/p9-wa.override.yaml").read_text(encoding="utf-8")
    )
    consumer = compose["services"]["nex-wa-evidence-consumer"]

    assert entry.command == ("python", "-m", "nex_wa.consumer_main")
    assert entry.capability == "job_claiming"
    assert consumer["command"] == list(entry.command)
    assert consumer["restart"] == "unless-stopped"
    assert "profiles" not in consumer
    assert set(consumer["depends_on"]) == {
        "nex-wa",
        "nex-oa",
        "nex-ae-api",
        "nex-wc",
        "nex-eos",
    }
    assert consumer["read_only"] is True
    assert consumer["cap_drop"] == ["ALL"]
    assert consumer["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in consumer
    assert "nuri1004" not in str(consumer)
