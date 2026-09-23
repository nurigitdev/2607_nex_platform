from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_tiered_quality_gate as gate


def _minimal_root(tmp_path: Path) -> Path:
    for path in (
        "tests/test_nex_cx_alpha.py",
        "tests/test_cx_beta.py",
        "tests/test_focused.py",
        "tests/test_s97_example_closure.py",
        "scripts/smoke/run_current_smoke.py",
        "services/nex-cx/nex_cx/module.py",
        "scripts/smoke/extra.py",
    ):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# fixture\n", encoding="utf-8")
    return tmp_path


def test_slice_plan_includes_service_regression_focused_coverage_and_smoke(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)

    plan = gate.build_slice_plan(
        root=root,
        python_bin="python-test",
        service="nex-cx",
        focused_tests=["tests/test_focused.py", "tests/test_nex_cx_alpha.py"],
        coverage_targets=["scripts/smoke/extra.py"],
        smoke_scripts=["scripts/smoke/run_current_smoke.py"],
    )

    pytest_command = plan.commands[0]
    assert plan.tier == "slice"
    assert plan.service == "nex-cx"
    assert plan.test_count == 3
    assert pytest_command.count("tests/test_nex_cx_alpha.py") == 1
    assert "tests/test_cx_beta.py" in pytest_command
    assert "tests/test_focused.py" in pytest_command
    assert "--cov=services/nex-cx/nex_cx" in pytest_command
    assert "--cov=extra" in pytest_command
    assert "94" in plan.commands[1]
    assert plan.commands[2][-1] == "scripts/smoke/extra.py"
    assert plan.commands[-1] == (
        "python-test",
        "scripts/smoke/run_current_smoke.py",
        "--summary",
    )
    assert plan.full_gate_fallback == "scripts/quality/run_quality_gate.sh"


def test_checkpoint_plan_excludes_historical_closures_and_keeps_full_sources(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)

    plan = gate.build_checkpoint_plan(
        root=root,
        python_bin="python-test",
        focused_tests=["tests/test_focused.py"],
        coverage_targets=["scripts/smoke/extra.py"],
        smoke_scripts=["scripts/smoke/run_current_smoke.py"],
    )

    pytest_command = plan.commands[0]
    assert plan.tier == "checkpoint"
    assert plan.service is None
    assert "tests" in pytest_command
    assert "--ignore-glob=tests/test_s*_closure.py" in pytest_command
    assert "tests/test_focused.py" not in pytest_command
    assert "--cov=services" in pytest_command
    assert "--cov=providers" in pytest_command
    assert "--cov=extra" in pytest_command
    assert plan.commands[-1][-1] == "--summary"


@pytest.mark.parametrize(
    ("builder", "kwargs", "message"),
    [
        (
            gate.build_slice_plan,
            {"service": "unknown"},
            "unsupported service profile",
        ),
        (
            gate.build_slice_plan,
            {"service": "nex-cx", "focused_tests": ["../private.py"]},
            "repository-relative",
        ),
        (
            gate.build_slice_plan,
            {"service": "nex-cx", "smoke_scripts": ["tests/test_focused.py"]},
            "allowed scripts/smoke boundary",
        ),
        (
            gate.build_slice_plan,
            {"service": "nex-cx", "focused_tests": ["tests/missing.py"]},
            "required file does not exist",
        ),
        (
            gate.build_slice_plan,
            {"service": "nex-cx", "coverage_targets": ["--erase"]},
            "invalid coverage target",
        ),
        (
            gate.build_slice_plan,
            {"service": "nex-cx", "coverage_targets": ["nex_cx.module"]},
            "services/, providers/, or scripts/ path",
        ),
        (
            gate.build_slice_plan,
            {
                "service": "nex-cx",
                "coverage_targets": ["scripts/smoke/missing.py"],
            },
            "coverage path does not exist",
        ),
        (
            gate.build_checkpoint_plan,
            {"report_path": "../coverage.json"},
            "reports/quality",
        ),
        (
            gate.build_checkpoint_plan,
            {"focused_tests": ["tests/test_s97_example_closure.py"]},
            "closure tests belong to the full gate",
        ),
    ],
)
def test_gate_plan_rejects_unsafe_or_unsupported_configuration(
    tmp_path: Path,
    builder,
    kwargs,
    message: str,
) -> None:
    root = _minimal_root(tmp_path)

    with pytest.raises(ValueError, match=message):
        builder(root=root, python_bin="python-test", **kwargs)


def test_slice_plan_rejects_profile_without_tests(tmp_path: Path) -> None:
    (tmp_path / "services/nex-cx/nex_cx").mkdir(parents=True)

    with pytest.raises(ValueError, match="selected no regression tests"):
        gate.build_slice_plan(
            root=tmp_path,
            python_bin="python-test",
            service="nex-cx",
        )


def test_execute_plan_stops_on_failure_and_writes_safe_evidence(
    tmp_path: Path,
) -> None:
    plan = gate.GatePlan(
        tier="slice",
        service="nex-cx",
        test_count=2,
        report_path="reports/quality/slice.json",
        full_gate_fallback=gate.FULL_GATE_PATH,
        commands=(("first",), ("second",), ("never",)),
    )
    calls: list[tuple[str, ...]] = []
    times = iter((10.0, 12.5))

    def runner(command, _root, _env):
        calls.append(tuple(command))
        return 7 if command[0] == "second" else 0

    result = gate.execute_plan(
        plan,
        root=tmp_path,
        environ={"PRIVATE": "not-persisted"},
        runner=runner,
        clock=lambda: next(times),
    )

    assert calls == [("first",), ("second",)]
    assert result["status"] == "FAIL"
    assert result["failed_command"] == 2
    assert result["completed_command_count"] == 1
    assert result["exit_code"] == 7
    assert result["duration_seconds"] == 2.5
    persisted = json.loads(
        (tmp_path / "reports/quality/slice-latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted == result
    assert "PRIVATE" not in str(persisted)


def test_execute_plan_success_and_helpers(tmp_path: Path) -> None:
    plan = gate.GatePlan(
        tier="checkpoint",
        service=None,
        test_count=None,
        report_path="reports/quality/checkpoint.json",
        full_gate_fallback=gate.FULL_GATE_PATH,
        commands=(("first",), ("second",)),
    )
    times = iter((1.0, 1.25))

    result = gate.execute_plan(
        plan,
        root=tmp_path,
        environ={},
        runner=lambda *_args: 0,
        clock=lambda: next(times),
    )

    assert result["status"] == "PASS"
    assert result["completed_command_count"] == 2
    assert result["failed_command"] is None
    assert gate._deduplicated(("a", "b", "a")) == ["a", "b"]
    assert gate._format_threshold(95.0) == "95"
    assert gate._format_threshold(94.5) == "94.5"
    assert gate._plan_payload(plan)["commands"] == [["first"], ["second"]]
    assert gate._coverage_source_argument(
        "services/nex-cx/nex_cx/generation.py"
    ) == "nex_cx.generation"
    assert gate._coverage_source_argument(
        "providers/nex-compatible-provider/nex_compatible_provider/app.py"
    ) == "nex_compatible_provider.app"
    assert gate._coverage_source_argument("services/nex-cx/nex_cx") == (
        "services/nex-cx/nex_cx"
    )
    with pytest.raises(ValueError, match="outside an import root"):
        gate._coverage_source_argument("scripts/nested/path/module.py")


def test_subprocess_adapter_returns_child_exit_code(
    monkeypatch, tmp_path: Path
) -> None:
    observed = {}

    class Completed:
        returncode = 6

    def fake_run(command, *, cwd, env, check):
        observed.update(
            {"command": command, "cwd": cwd, "env": env, "check": check}
        )
        return Completed()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    assert gate._run_command(("command", "arg"), tmp_path, {"SAFE": "1"}) == 6
    assert observed == {
        "command": ("command", "arg"),
        "cwd": tmp_path,
        "env": {"SAFE": "1"},
        "check": False,
    }


def test_main_dry_run_and_configuration_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(gate, "ROOT", Path(__file__).resolve().parents[1])

    assert gate.main(["slice", "--service", "nex-cx", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tier"] == "slice"
    assert payload["full_gate_fallback"] == gate.FULL_GATE_PATH

    assert gate.main(["slice"]) == 2
    assert "requires --service" in capsys.readouterr().err
    assert gate.main(["checkpoint", "--service", "nex-cx"]) == 2
    assert "does not accept --service" in capsys.readouterr().err


def test_main_executes_plan_and_propagates_exit_code(monkeypatch, capsys) -> None:
    plan = gate.GatePlan(
        tier="checkpoint",
        service=None,
        test_count=None,
        report_path="reports/quality/checkpoint.json",
        full_gate_fallback=gate.FULL_GATE_PATH,
        commands=(("pytest",),),
    )
    monkeypatch.setattr(gate, "build_checkpoint_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(
        gate,
        "execute_plan",
        lambda _plan: {
            "status": "FAIL",
            "tier": "checkpoint",
            "service": None,
            "completed_command_count": 0,
            "command_count": 1,
            "duration_seconds": 0.1,
            "full_gate_fallback": gate.FULL_GATE_PATH,
            "exit_code": 9,
        },
    )

    assert gate.main(["checkpoint"]) == 9
    assert "tiered_quality_gate=fail" in capsys.readouterr().out


def test_original_full_gate_remains_the_independent_fallback() -> None:
    root = Path(__file__).resolve().parents[1]
    full_gate = (root / gate.FULL_GATE_PATH).read_text(encoding="utf-8")
    slice_wrapper = (root / "scripts/quality/run_slice_gate.sh").read_text(
        encoding="utf-8"
    )
    checkpoint_wrapper = (
        root / "scripts/quality/run_checkpoint_gate.sh"
    ).read_text(encoding="utf-8")

    assert "--cov=services" in full_gate
    assert "--cov=scripts" in full_gate
    assert "--cov=providers" in full_gate
    assert "scripts/quality/validate_contracts.py" in full_gate
    assert "run_s97_cx_grounded_generation_runtime_closure.py" in full_gate
    assert "run_tiered_quality_gate.py" not in full_gate
    assert "run_tiered_quality_gate.py slice" in slice_wrapper
    assert "run_tiered_quality_gate.py checkpoint" in checkpoint_wrapper
