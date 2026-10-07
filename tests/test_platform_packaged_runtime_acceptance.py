from __future__ import annotations

import subprocess

import pytest

import run_platform_packaged_runtime_acceptance as smoke


def _accepted_projection() -> dict[str, object]:
    return {
        "status": "PACKAGE_CONTEXT_ACCEPTED",
        "artifact_contexts": [{"artifact_id": str(index)} for index in range(6)],
        "migrated_service_ids": [str(index) for index in range(5)],
        "background_check_process_ids": [str(index) for index in range(7)],
        "startup_generations": [["one"], ["two"]],
        "oci_daemon_status": "UNAVAILABLE_PERMISSION_OR_SOCKET",
    }


def test_protected_acceptance_is_opt_in() -> None:
    result = smoke.run_platform_packaged_runtime_acceptance({})

    assert result["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in result["skip_reason"]
    assert smoke.summary_line(result) == (
        "platform_packaged_runtime_acceptance=skip"
    )


def test_protected_acceptance_passes_executor_evidence() -> None:
    result = smoke.run_platform_packaged_runtime_acceptance(
        {smoke.SMOKE_ENV: "1", "NEX_PROFILE": "test"},
        executor=lambda env: _accepted_projection(),
    )

    assert result["status"] == "PASS"
    assert result["decision"] == {
        "package_context_accepted": True,
        "oci_image_execution_deferred": True,
        "production_contact_required": False,
        "production_deployment_approved": False,
        "next_slice": "1421",
    }
    assert smoke.summary_line(result) == (
        "platform_packaged_runtime_acceptance=pass artifacts=6 migrations=5 "
        "background=7 generations=2 "
        "oci=UNAVAILABLE_PERMISSION_OR_SOCKET next=1421"
    )


def test_protected_acceptance_fails_closed() -> None:
    wrong_profile = smoke.run_platform_packaged_runtime_acceptance(
        {smoke.SMOKE_ENV: "1", "NEX_PROFILE": "production"},
        executor=lambda env: _accepted_projection(),
    )
    failed = smoke.run_platform_packaged_runtime_acceptance(
        {smoke.SMOKE_ENV: "1", "NEX_PROFILE": "test"},
        executor=lambda env: (_ for _ in ()).throw(ValueError("bad package")),
    )

    assert wrong_profile["status"] == "FAIL"
    assert failed["status"] == "FAIL"
    assert failed["issues"] == ["bad package"]
    assert smoke.summary_line(failed) == (
        "platform_packaged_runtime_acceptance=fail"
    )


def test_acceptance_environment_is_deterministic_and_uses_no_real_images() -> None:
    ports = iter(range(22001, 22020))
    env = smoke._acceptance_environment(
        {"KEEP": "yes"}, port_allocator=lambda: next(ports)
    )

    assert env["KEEP"] == "yes"
    assert env["NEX_PROFILE"] == "test"
    assert env["NEX_OA_BASE_URL"] == "http://127.0.0.1:22001"
    assert env["NEX_AE_WEB_BASE_URL"].startswith("http://127.0.0.1:")
    assert env["NEX_OA_RUNTIME_IMAGE"].startswith(
        "registry.invalid/nex/nex-oa-runtime@sha256:"
    )


def test_artifact_environment_and_python_command_are_context_scoped(tmp_path) -> None:
    env = smoke._artifact_environment(
        tmp_path, "nex-cx-runtime", {"PYTHONPATH": "host", "KEEP": "yes"}
    )
    web_env = smoke._artifact_environment(
        tmp_path, "nex-ae-web", {"KEEP": "yes"}
    )

    assert env["KEEP"] == "yes"
    assert "services/_shared" in env["PYTHONPATH"]
    assert "services/nex-cx" in env["PYTHONPATH"]
    assert "PYTHONPATH" not in web_env
    assert smoke._host_python_command(("python", "-m", "module"))[0] == str(
        smoke.PYTHON_BIN
    )
    assert smoke._host_python_command(("npm", "start")) == ("npm", "start")
    assert smoke._process_working_directory(tmp_path, "nex-ae-web") == (
        tmp_path / "apps" / "nex-ae-web"
    )
    assert smoke._process_working_directory(tmp_path, "nex-cx-runtime") == tmp_path


def test_oci_daemon_status_covers_available_missing_and_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )
    assert smoke._oci_daemon_status() == "AVAILABLE_NOT_USED"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )
    assert smoke._oci_daemon_status() == "UNAVAILABLE_PERMISSION_OR_SOCKET"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    assert smoke._oci_daemon_status() == "UNAVAILABLE_NOT_INSTALLED"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("docker", 10)
        ),
    )
    assert smoke._oci_daemon_status() == "UNAVAILABLE_PERMISSION_OR_SOCKET"


def test_main_prints_pass_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "acceptance": _accepted_projection(),
    }
    monkeypatch.setattr(
        smoke, "run_platform_packaged_runtime_acceptance", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "acceptance=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_packaged_runtime_acceptance",
        lambda: {"status": "FAIL", "issues": ["bad"]},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


class _Handle:
    def __init__(self, polls, *, timeout: bool = False) -> None:
        self.polls = iter(polls)
        self.timeout = timeout
        self.terminated = False
        self.killed = False

    def poll(self):
        return next(self.polls, None)

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("process", timeout)
        return 0

    def kill(self):
        self.killed = True


def test_stop_process_handles_exited_graceful_and_forced_paths() -> None:
    exited = _Handle([0])
    graceful = _Handle([None])
    forced = _Handle([None], timeout=True)

    smoke._stop_process(exited)
    smoke._stop_process(graceful)
    smoke._stop_process(forced)

    assert exited.terminated is False
    assert graceful.terminated is True
    assert graceful.killed is False
    assert forced.killed is True
