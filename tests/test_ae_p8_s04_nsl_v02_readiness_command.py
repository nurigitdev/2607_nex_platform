from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import check_nsl_v02_readiness as command
import pytest


def _lock() -> dict[str, object]:
    return {
        "wheel_filename": "nex_skill_language-0.2.0-py3-none-any.whl",
    }


def _readiness() -> dict[str, object]:
    return {
        "schema_version": "nsl_installed_package_readiness.v2",
        "status": "PASS",
        "package_version": "0.2.0",
    }


def test_readiness_command_is_protected() -> None:
    assert command.run_nsl_v02_readiness({}, execute=True)["status"] == "SKIPPED"


def test_readiness_command_installs_and_inspects_isolated_wheel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock()), encoding="utf-8")
    wheel_directory = tmp_path / "wheel"
    wheel_directory.mkdir()
    (wheel_directory / _lock()["wheel_filename"]).write_bytes(b"wheel")
    calls: list[tuple[str, ...]] = []

    def fake_run(args, **kwargs):
        calls.append(tuple(args))
        output = "" if "pip" in args else json.dumps(_readiness())
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(command.subprocess, "run", fake_run)
    monkeypatch.setattr(command, "_installed_version", lambda: "0.1.0")
    report = tmp_path / "report.json"
    evidence = command.run_nsl_v02_readiness(
        {command.EXECUTION_ENV: "1"},
        execute=True,
        lock_path=lock_path,
        wheel_directory=wheel_directory,
        report_path=report,
    )

    assert evidence["status"] == "PASS"
    assert evidence["decision"]["v01_host_install_preserved"] is True
    assert evidence["host_environment_mutated"] is False
    assert len(calls) == 2
    assert "--target" in calls[0]
    assert json.loads(report.read_text(encoding="utf-8")) == evidence


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "message"),
    [
        (1, "", "install failed", "install failed"),
        (0, "[]", "", "readiness result is invalid"),
    ],
)
def test_readiness_command_contains_install_and_result_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    returncode: int,
    stdout: str,
    stderr: str,
    message: str,
) -> None:
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock()), encoding="utf-8")
    wheel_directory = tmp_path / "wheel"
    wheel_directory.mkdir()
    (wheel_directory / _lock()["wheel_filename"]).write_bytes(b"wheel")

    if returncode:
        responses = [subprocess.CompletedProcess(("pip",), returncode, stdout, stderr)]
    else:
        responses = [
            subprocess.CompletedProcess(("pip",), 0, "", ""),
            subprocess.CompletedProcess(("python",), 0, stdout, stderr),
        ]
    monkeypatch.setattr(
        command.subprocess, "run", lambda *args, **kwargs: responses.pop(0)
    )
    result = command.run_nsl_v02_readiness(
        {command.EXECUTION_ENV: "1"},
        execute=True,
        lock_path=lock_path,
        wheel_directory=wheel_directory,
        report_path=tmp_path / "report.json",
    )

    assert result["status"] == "FAIL"
    assert message in result["issues"][0]


def test_readiness_command_rejects_missing_wheel_and_writes_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock()), encoding="utf-8")
    monkeypatch.setattr(command, "DEFAULT_LOCK", lock_path)
    monkeypatch.setattr(command, "DEFAULT_WHEEL_DIRECTORY", tmp_path / "missing")
    monkeypatch.setattr(command, "DEFAULT_REPORT", tmp_path / "report.json")
    monkeypatch.setenv(command.EXECUTION_ENV, "1")

    assert command.main(["--execute", "--summary"]) == 1
    assert "p8_s04_nsl_v02_readiness=fail" in capsys.readouterr().out


def test_readiness_command_rejects_non_object_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock.json"
    lock_path.write_text("[]", encoding="utf-8")

    result = command.run_nsl_v02_readiness(
        {command.EXECUTION_ENV: "1"},
        execute=True,
        lock_path=lock_path,
        report_path=tmp_path / "report.json",
    )

    assert result["status"] == "FAIL"
    assert "must be an object" in result["issues"][0]


def test_installed_version_returns_none_when_distribution_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        command.importlib.metadata,
        "version",
        lambda _name: (_ for _ in ()).throw(
            command.importlib.metadata.PackageNotFoundError()
        ),
    )
    assert command._installed_version() is None


def test_main_json_and_script_entrypoint_are_stable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        command,
        "run_nsl_v02_readiness",
        lambda **_kwargs: {"status": "SKIPPED", "isolated_install": False},
    )
    assert command.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"

    monkeypatch.delenv(command.EXECUTION_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", [str(Path(command.__file__))])
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(command.__file__, run_name="__main__")
    assert exited.value.code == 0
