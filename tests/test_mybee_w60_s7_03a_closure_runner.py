from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_mybee_w60_s7_03a_closure as runner


def _performance(**overrides):
    value = {
        "schema_version": "mybee.w60_s7_03a_performance.v1",
        "status": "PASS",
        "rebuild_p95_ms": 120.0,
        "rebuild_p95_budget_ms": 30_000.0,
        "read_p95_ms": 80.0,
        "read_p95_budget_ms": 2_000.0,
        "projection_index_names": ["ix_eos_project_pnl_lookup"],
        "restart_rebuild_exact_replay": True,
        "actual_population_evidence": True,
    }
    value.update(overrides)
    return value


def _environment():
    return {
        "NEX_EOS_TEST_DATABASE_URL": (
            "postgresql+psycopg://eos@127.0.0.1:5432/nex_eos_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://oa@127.0.0.1:5432/nex_oa_test"
        ),
    }


def test_runner_executes_full_protected_matrix_and_writes_closure(tmp_path) -> None:
    report_path = tmp_path / "closure.json"
    performance_path = tmp_path / "performance.json"
    performance_path.write_text(json.dumps(_performance()), encoding="utf-8")
    observed = {}

    def command_runner(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0)

    report = runner.run_closure(
        report_path=report_path,
        performance_report_path=performance_path,
        environ=_environment(),
        command_runner=command_runner,
        python_executable="python-test",
    )

    assert report["status"] == "PASS"
    assert report["protected_test_count"] == 8
    assert report["query_plan_recorded"] is True
    assert report["zero_residue"] is True
    assert report["remote_provider_required"] is False
    assert observed["command"] == runner._pytest_command("python-test")
    assert observed["cwd"] == ROOT
    assert observed["check"] is False
    assert all(observed["env"][name] == "1" for name in runner.PROTECTED_FLAGS)
    assert observed["env"]["NEX_MYBEE_W60_PERFORMANCE_REPORT"] == str(performance_path)
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_runner_rejects_missing_database_and_failed_matrix(tmp_path) -> None:
    with pytest.raises(runner.W60ClosureError, match="NEX_EOS_TEST_DATABASE_URL"):
        runner.run_closure(environ={})

    environment = _environment()
    environment["NEX_EOS_TEST_DATABASE_URL"] = environment[
        "NEX_EOS_TEST_DATABASE_URL"
    ].replace("nex_eos_test", "nex_eos_dev")
    with pytest.raises(runner.W60ClosureError, match="nex_eos_test"):
        runner.run_closure(environ=environment)

    with pytest.raises(runner.W60ClosureError, match="exit code 3"):
        runner.run_closure(
            report_path=tmp_path / "closure.json",
            performance_report_path=tmp_path / "performance.json",
            environ=_environment(),
            command_runner=lambda *args, **kwargs: subprocess.CompletedProcess(
                args[0], 3
            ),
        )


@pytest.mark.parametrize(
    ("performance", "message"),
    [
        ({"status": "FAIL"}, "did not pass"),
        (_performance(read_p95_ms=2_001.0), "read p95"),
        (_performance(rebuild_p95_ms=30_001.0), "rebuild p95"),
        (_performance(restart_rebuild_exact_replay=False), "did not converge"),
        (_performance(actual_population_evidence=False), "not source-backed"),
        (_performance(projection_index_names=[]), "index was not observed"),
    ],
)
def test_performance_evidence_fail_closed(tmp_path, performance, message) -> None:
    path = tmp_path / "performance.json"
    path.write_text(json.dumps(performance), encoding="utf-8")
    with pytest.raises(runner.W60ClosureError, match=message):
        runner._load_performance_report(path)


def test_performance_evidence_missing_malformed_and_incomplete(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(runner.W60ClosureError, match="not produced"):
        runner._load_performance_report(missing)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(runner.W60ClosureError, match="malformed"):
        runner._load_performance_report(malformed)

    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    with pytest.raises(runner.W60ClosureError, match="incomplete"):
        runner._load_performance_report(incomplete)


def test_main_reports_pass_and_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runner,
        "run_closure",
        lambda **_kwargs: {
            "protected_test_count": 8,
            "performance": {"rebuild_p95_ms": 100.0, "read_p95_ms": 50.0},
        },
    )
    monkeypatch.setattr(sys, "argv", ["runner"])
    assert runner.main() == 0
    assert "w60_closure=pass" in capsys.readouterr().out

    def fail(**_kwargs):
        raise runner.W60ClosureError("bounded failure")

    monkeypatch.setattr(runner, "run_closure", fail)
    assert runner.main() == 1
    assert "w60_closure=fail" in capsys.readouterr().err
