from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import run_platform_test_profile_startup as smoke
from nex_runtime.postgres_targets import POSTGRES_TEST_TARGETS
from nex_runtime.topology import RuntimeProcess
from platform_test_migrations import PlatformMigrationReadinessError


def valid_environment() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        **{
            target.test_database_env: (
                f"postgresql://{target.expected_role_name}:secret@127.0.0.1/"
                f"{target.expected_database_name}"
            )
            for target in POSTGRES_TEST_TARGETS
        },
    }


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class Handle:
    def __init__(self, *, exit_code=None, hang=False) -> None:
        self.exit_code = exit_code
        self.hang = hang
        self.terminated = 0
        self.killed = 0

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated += 1
        if not self.hang:
            self.exit_code = -15

    def wait(self, timeout=None):
        if self.hang and not self.killed:
            raise TimeoutError
        return self.exit_code or 0

    def kill(self):
        self.killed += 1
        self.exit_code = -9


class PopenFactory:
    def __init__(self, *, exit_code=None) -> None:
        self.exit_code = exit_code
        self.calls = []
        self.handles = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        handle = Handle(exit_code=self.exit_code)
        self.handles.append(handle)
        return handle


def migration_result():
    return SimpleNamespace(
        services=tuple(
            SimpleNamespace(migration_count=count)
            for count in (17, 9, 21, 23, 19)
        )
    )


def api_process() -> RuntimeProcess:
    return RuntimeProcess(
        "nex-oa-api",
        "nex-oa",
        "api",
        ("python", "service.py"),
        host="127.0.0.1",
        port=19001,
    )


def background_process() -> RuntimeProcess:
    return RuntimeProcess(
        "nex-cx-ingestion-worker",
        "nex-cx",
        "worker",
        ("python", "worker.py"),
    )


def test_protected_smoke_starts_five_apis_and_seven_backgrounds(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke, "run_platform_test_migration_readiness", lambda env: migration_result()
    )
    popen = PopenFactory()
    clock = Clock()
    ports = iter(range(19001, 19007))

    result = smoke.run_smoke(
        valid_environment(),
        popen=popen,
        readiness_probe=lambda process: {
            "service_id": process.owner,
            "readiness_status": "READY",
        },
        sleeper=clock.sleep,
        clock=clock,
        port_allocator=lambda: next(ports),
    )

    assert result["status"] == "PASS"
    assert result["migration_count"] == 89
    assert result["api_count"] == 5
    assert result["background_count"] == 7
    assert result["ready_process_count"] == 12
    assert result["work_claiming_enabled"] is False
    assert len(popen.calls) == 12
    assert all(handle.terminated == 1 for handle in popen.handles)
    assert all(call[1]["stdout"] is smoke.subprocess.DEVNULL for call in popen.calls)
    assert "secret" not in str(result)


def test_startup_environment_sets_endpoints_and_non_route_tokens() -> None:
    ports = iter(range(20001, 20007))
    result = smoke._startup_environment({}, lambda: next(ports))

    assert result["NEX_PROFILE"] == "test"
    assert result["NEX_OA_BASE_URL"].endswith(":20001")
    assert result["NEX_AE_WEB_BASE_URL"].endswith(":20006")
    assert all(result[name] for name in smoke.SIGNED_TRUST_ENV_NAMES)


def test_smoke_skip_migration_and_unexpected_failures(monkeypatch) -> None:
    assert smoke.run_smoke({})["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "run_platform_test_migration_readiness",
        lambda env: (_ for _ in ()).throw(
            PlatformMigrationReadinessError("migration_failed", "nex-cx")
        ),
    )
    failed = smoke.run_smoke(valid_environment(), port_allocator=lambda: 20001)
    assert failed["failure_code"] == "migration_failed"
    assert failed["process_id"] == "nex-cx"

    monkeypatch.setattr(
        smoke,
        "run_platform_test_migration_readiness",
        lambda env: (_ for _ in ()).throw(RuntimeError("private")),
    )
    unexpected = smoke.run_smoke(
        valid_environment(), port_allocator=lambda: 20001
    )
    assert unexpected["failure_code"] == "test_profile_startup_failed"
    assert unexpected["process_id"] == "RuntimeError"

    monkeypatch.setattr(
        smoke, "run_platform_test_migration_readiness", lambda env: migration_result()
    )
    failure_ports = iter(range(20101, 20107))
    process_failure = smoke.run_smoke(
        valid_environment(),
        popen=PopenFactory(exit_code=2),
        readiness_probe=lambda process: None,
        port_allocator=lambda: next(failure_ports),
    )
    assert process_failure["failure_code"] == "api_exited_before_ready"
    assert process_failure["process_id"] == "nex-oa-api"


def test_api_success_invalid_exit_and_timeout_paths() -> None:
    process = api_process()
    clock = Clock()
    ready_handle = Handle()
    result = smoke._start_api(
        process,
        environment={},
        popen=lambda *args, **kwargs: ready_handle,
        readiness_probe=lambda item: {
            "service_id": "nex-oa",
            "readiness_status": "READY",
        },
        sleeper=clock.sleep,
        clock=clock,
    )
    assert result["state"] == "READY"
    assert ready_handle.terminated == 1

    invalid_handle = Handle()
    with pytest.raises(
        smoke.PlatformTestProfileStartupError, match="api_readiness_invalid"
    ):
        smoke._start_api(
            process,
            environment={},
            popen=lambda *args, **kwargs: invalid_handle,
            readiness_probe=lambda item: {"service_id": "wrong"},
            sleeper=clock.sleep,
            clock=clock,
        )
    assert invalid_handle.terminated == 1

    exited = Handle(exit_code=3)
    with pytest.raises(
        smoke.PlatformTestProfileStartupError, match="api_exited_before_ready"
    ):
        smoke._start_api(
            process,
            environment={},
            popen=lambda *args, **kwargs: exited,
            readiness_probe=lambda item: None,
            sleeper=clock.sleep,
            clock=clock,
        )

    timeout_clock = Clock()
    with pytest.raises(
        smoke.PlatformTestProfileStartupError, match="api_readiness_timeout"
    ):
        smoke._start_api(
            process,
            environment={},
            popen=lambda *args, **kwargs: Handle(),
            readiness_probe=lambda item: None,
            sleeper=timeout_clock.sleep,
            clock=timeout_clock,
        )


def test_background_success_and_early_exit() -> None:
    process = background_process()
    clock = Clock()
    handle = Handle()
    assert smoke._start_background(
        process,
        environment={},
        popen=lambda *args, **kwargs: handle,
        sleeper=clock.sleep,
        clock=clock,
    )["state"] == "READY"
    assert handle.terminated == 1

    with pytest.raises(
        smoke.PlatformTestProfileStartupError,
        match="background_exited_before_ready",
    ):
        smoke._start_background(
            process,
            environment={},
            popen=lambda *args, **kwargs: Handle(exit_code=2),
            sleeper=clock.sleep,
            clock=clock,
        )


def test_spawn_and_stop_defensive_paths() -> None:
    with pytest.raises(
        smoke.PlatformTestProfileStartupError, match="process_launch_failed"
    ):
        smoke._spawn(
            api_process(),
            environment={},
            popen=lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
        )

    stopped = Handle(exit_code=0)
    smoke._stop_process(stopped)
    assert stopped.terminated == 0

    hanging = Handle(hang=True)
    smoke._stop_process(hanging)
    assert hanging.terminated == 1
    assert hanging.killed == 1


def test_http_probe_and_free_port(monkeypatch) -> None:
    class Response:
        def __init__(self, status=200, payload=None):
            self.status = status
            self.payload = payload or {
                "service_id": "nex-oa",
                "readiness_status": "READY",
            }

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(self.payload).encode()

    monkeypatch.setattr(smoke, "urlopen", lambda *args, **kwargs: Response())
    assert smoke._http_readiness_probe(api_process())["service_id"] == "nex-oa"
    monkeypatch.setattr(
        smoke, "urlopen", lambda *args, **kwargs: Response(status=204)
    )
    assert smoke._http_readiness_probe(api_process()) is None
    monkeypatch.setattr(
        smoke, "urlopen", lambda *args, **kwargs: Response(payload=["bad"])
    )
    assert smoke._http_readiness_probe(api_process()) is None
    monkeypatch.setattr(
        smoke,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )
    assert smoke._http_readiness_probe(api_process()) is None
    assert smoke._http_readiness_probe(background_process()) is None
    assert smoke._free_port() > 0


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "api_count": 5,
        "background_count": 7,
        "ready_process_count": 12,
        "next_slice": "1328",
    }
    assert smoke.summary_line(passing) == (
        "platform_test_profile_startup=pass apis=5 background=7 "
        "ready=12 next=1328"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skip")
    failed = smoke._failure("failed", "worker")
    assert "code=failed" in smoke.summary_line(failed)

    monkeypatch.setattr(smoke, "run_smoke", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "apis=5" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(smoke, "run_smoke", lambda: failed)
    assert smoke.main([]) == 1


@pytest.mark.skipif(
    smoke.os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required",
)
def test_actual_platform_test_profile_startup() -> None:
    result = smoke.run_smoke()

    assert result["status"] == "PASS", result
    assert result["migration_count"] == 89
    assert result["ready_process_count"] == 12
