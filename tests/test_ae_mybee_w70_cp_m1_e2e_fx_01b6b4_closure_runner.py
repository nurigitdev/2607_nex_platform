from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke/run_mybee_w70_cp_m1_01b6b4_closure.py"
SPEC = importlib.util.spec_from_file_location("m1_01b6b4_closure", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _environment() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1/nex_ae_test"
        ),
        "NEX_WC_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_wc_user:secret@127.0.0.1/nex_wc_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret@127.0.0.1/nex_oa_test"
        ),
        "NEX_EOS_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_eos_user:secret@127.0.0.1/nex_eos_test"
        ),
    }


def test_01b6b4_runner_requires_every_exact_test_database(tmp_path: Path) -> None:
    environment = _environment()
    environment.pop("NEX_WC_TEST_DATABASE_URL")
    with pytest.raises(runner.M1ProtectedGateError, match="NEX_WC_TEST_DATABASE_URL"):
        runner.run_gate(report_path=tmp_path / "report.json", environ=environment)

    environment = _environment()
    environment["NEX_EOS_TEST_DATABASE_URL"] = environment[
        "NEX_EOS_TEST_DATABASE_URL"
    ].replace("nex_eos_test", "nex_eos_dev")
    with pytest.raises(runner.M1ProtectedGateError, match="nex_eos_user@nex_eos_test"):
        runner.run_gate(report_path=tmp_path / "report.json", environ=environment)


def test_01b6b4_runner_sets_flags_and_records_pass_evidence(tmp_path: Path) -> None:
    observed = {}

    def command_runner(command, *, cwd, env, check):
        observed.update(command=command, cwd=cwd, env=env, check=check)
        return subprocess.CompletedProcess(command, 0)

    report_path = tmp_path / "gate.json"
    report = runner.run_gate(
        report_path=report_path,
        environ=_environment(),
        command_runner=command_runner,
        python_executable="/test/python",
    )

    assert observed["command"] == [
        "/test/python",
        "-m",
        "pytest",
        "-q",
        *runner.PROTECTED_TESTS,
    ]
    assert observed["cwd"] == ROOT
    assert observed["check"] is False
    assert all(observed["env"][name] == "1" for name in runner.PROTECTED_FLAGS)
    assert report["status"] == "PASS"
    assert report["actual_postgresql"] is True
    assert report["approval_wait_restart_points"] == 2
    assert report["exact_replay"]["posted_journal"] is True
    assert report["negative_matrix"]["zero_mutation"] is True
    assert report["remote_provider_required"] is False
    assert report_path.is_file()


def test_01b6b4_runner_rejects_failed_matrix(tmp_path: Path) -> None:
    def command_runner(command, **_values):
        return subprocess.CompletedProcess(command, 7)

    with pytest.raises(runner.M1ProtectedGateError, match="exit code 7"):
        runner.run_gate(
            report_path=tmp_path / "report.json",
            environ=_environment(),
            command_runner=command_runner,
        )
    assert not (tmp_path / "report.json").exists()
