from __future__ import annotations

import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
import run_parallel_quality_gate as gate


def _root(tmp_path: Path) -> Path:
    paths = (
        "tests/test_nex_ae_alpha.py",
        "tests/test_nex_eos_alpha.py",
        "tests/test_nex_wc_alpha.py",
        "tests/test_ae_wc_cross_service.py",
        "tests/test_repository_policy.py",
        "tests/test_s100_example_closure.py",
        "tests/nested/test_nested_policy.py",
    )
    for raw in paths:
        path = tmp_path / raw
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test fixture\n", encoding="utf-8")
    return tmp_path


def test_inventory_assigns_every_checkpoint_test_exactly_once(tmp_path: Path) -> None:
    root = _root(tmp_path)

    evidence = gate.build_test_ownership_inventory(
        root=root,
        tier="checkpoint",
        revision="a" * 40,
        generated_at="2026-11-27T00:00:00+00:00",
    )

    assignments = {item["path"]: item for item in evidence["assignments"]}
    assert evidence["test_file_count"] == 6
    assert evidence["resolved_missing_count"] == 0
    assert evidence["resolved_duplicate_count"] == 0
    assert assignments["tests/test_nex_ae_alpha.py"]["lane"] == "nex-ae-api"
    assert assignments["tests/test_nex_eos_alpha.py"]["lane"] == "nex-eos"
    assert assignments["tests/test_ae_wc_cross_service.py"]["lane"] == (
        gate.SERIAL_INTEGRATION_LANE
    )
    assert assignments["tests/test_repository_policy.py"]["lane"] == (
        gate.SERIAL_REPOSITORY_LANE
    )
    assert assignments["tests/nested/test_nested_policy.py"]["lane"] == (
        gate.SERIAL_REPOSITORY_LANE
    )
    assert "tests/test_s100_example_closure.py" not in assignments
    assert evidence["source_multi_owned_count"] == 1
    assert evidence["source_unowned_count"] == 2
    assert str(evidence["inventory_digest"]).startswith("sha256:")


def test_full_inventory_includes_historical_closure_and_is_stable(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    kwargs = {
        "root": root,
        "tier": "full",
        "revision": "b" * 40,
        "generated_at": "2026-11-27T00:00:00+00:00",
    }

    first = gate.build_test_ownership_inventory(**kwargs)
    second = gate.build_test_ownership_inventory(**kwargs)

    assert first == second
    assert first["test_file_count"] == 7
    assert any(
        item["path"] == "tests/test_s100_example_closure.py"
        for item in first["assignments"]
    )


def test_inventory_write_and_output_validation(tmp_path: Path) -> None:
    evidence = {"status": "PASS"}
    output = tmp_path / "reports/quality/parallel/run/inventory.json"

    gate.write_inventory(output, evidence)

    assert json.loads(output.read_text(encoding="utf-8")) == evidence
    assert gate._validated_output(
        tmp_path, "reports/quality/parallel/run/inventory.json"
    ) == output
    with pytest.raises(ValueError, match="reports/quality/parallel"):
        gate._validated_output(tmp_path, "reports/quality/inventory.json")
    with pytest.raises(ValueError, match="repository-relative"):
        gate._validated_output(tmp_path, "../inventory.json")


def test_inventory_rejects_unknown_tier(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="checkpoint or full"):
        gate.discover_test_files(_root(tmp_path), tier="slice")


def test_git_revision_uses_repository_head_and_rejects_empty(tmp_path: Path) -> None:
    observed = {}

    def runner(command, **kwargs):
        observed.update({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")

    assert gate._git_revision(tmp_path, runner=runner) == "abc123"
    assert observed == {
        "command": ("git", "rev-parse", "HEAD"),
        "cwd": tmp_path,
        "check": True,
        "capture_output": True,
        "text": True,
    }

    def empty_runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="\n", stderr="")

    with pytest.raises(ValueError, match="revision is empty"):
        gate._git_revision(tmp_path, runner=empty_runner)


def test_main_writes_summary_and_full_payload(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(gate, "ROOT", root)
    monkeypatch.setattr(gate, "_git_revision", lambda _root: "c" * 40)
    summary_path = "reports/quality/parallel/run/checkpoint.json"

    assert gate.main(
        ["inventory", "--tier", "checkpoint", "--output", summary_path, "--summary"]
    ) == 0
    assert "parallel_quality_inventory=pass" in capsys.readouterr().out
    assert (root / summary_path).is_file()

    full_path = "reports/quality/parallel/run/full.json"
    assert gate.main(
        ["inventory", "--tier", "full", "--output", full_path]
    ) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["tier"] == "full"
    assert printed["test_file_count"] == 7


def test_main_fails_closed_for_unsafe_output(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(gate, "ROOT", _root(tmp_path))

    assert gate.main(
        ["inventory", "--tier", "full", "--output", "reports/quality/out.json"]
    ) == 1
    assert "parallel_quality_gate=fail error=ValueError" in capsys.readouterr().out


def test_output_validation_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        gate._validated_output(tmp_path, str(tmp_path / "inventory.json"))


def test_lane_artifacts_are_run_and_service_scoped(tmp_path: Path) -> None:
    paths = gate.build_lane_artifact_paths(
        root=tmp_path, run_id="w80-ca00i2-test", lane="nex-ae-api"
    )

    assert paths.relative_payload(tmp_path) == {
        "run_id": "w80-ca00i2-test",
        "lane": "nex-ae-api",
        "base_dir": (
            "reports/quality/parallel/w80-ca00i2-test/nex-ae-api"
        ),
        "raw_coverage": (
            "reports/quality/parallel/w80-ca00i2-test/nex-ae-api/.coverage"
        ),
        "coverage_json": (
            "reports/quality/parallel/w80-ca00i2-test/nex-ae-api/coverage.json"
        ),
        "junit_xml": (
            "reports/quality/parallel/w80-ca00i2-test/nex-ae-api/junit.xml"
        ),
        "stdout_log": (
            "reports/quality/parallel/w80-ca00i2-test/nex-ae-api/stdout.log"
        ),
        "stderr_log": (
            "reports/quality/parallel/w80-ca00i2-test/nex-ae-api/stderr.log"
        ),
        "evidence_json": (
            "reports/quality/parallel/w80-ca00i2-test/nex-ae-api/evidence.json"
        ),
    }
    env = gate.lane_environment(paths, {"SAFE": "1"})
    assert env == {
        "SAFE": "1",
        "COVERAGE_FILE": str(paths.raw_coverage),
        "NEX_QUALITY_GATE_RUN_ID": "w80-ca00i2-test",
        "NEX_QUALITY_GATE_LANE": "nex-ae-api",
    }


def test_lane_artifact_layout_rejects_unsafe_or_unknown_identity(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="safe lowercase"):
        gate.build_lane_artifact_paths(
            root=tmp_path, run_id="../unsafe", lane="nex-ae-api"
        )
    with pytest.raises(ValueError, match="unsupported quality gate lane"):
        gate.build_lane_artifact_paths(
            root=tmp_path, run_id="safe", lane="unknown-service"
        )


def test_artifact_isolation_rejects_duplicate_lane(tmp_path: Path) -> None:
    ae = gate.build_lane_artifact_paths(
        root=tmp_path, run_id="same-run", lane="nex-ae-api"
    )
    eos = gate.build_lane_artifact_paths(
        root=tmp_path, run_id="same-run", lane="nex-eos"
    )

    gate.validate_artifact_isolation((ae, eos))
    with pytest.raises(ValueError, match="duplicate run/lane"):
        gate.validate_artifact_isolation((ae, ae))
    colliding = replace(eos, coverage_json=ae.coverage_json)
    with pytest.raises(ValueError, match="artifact path collision"):
        gate.validate_artifact_isolation((ae, colliding))


def test_concurrent_lane_workspace_claim_is_fail_closed(tmp_path: Path) -> None:
    paths = gate.build_lane_artifact_paths(
        root=tmp_path, run_id="concurrent-run", lane="nex-ae-api"
    )

    def claim() -> str:
        try:
            gate.prepare_lane_artifacts(paths)
        except FileExistsError:
            return "DENIED"
        return "CLAIMED"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _index: claim(), range(2)))

    assert results == ["CLAIMED", "DENIED"]
    assert paths.base_dir.is_dir()


def test_owner_lane_plan_uses_only_owned_tests_and_isolated_reports(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    inventory = gate.build_test_ownership_inventory(
        root=root,
        tier="checkpoint",
        revision="d" * 40,
    )

    plan = gate.build_owner_lane_plan(
        root=root,
        inventory=inventory,
        run_id="owner-plan",
        lane="nex-ae-api",
        python_bin="python-test",
    )

    assert plan.tests == ("tests/test_nex_ae_alpha.py",)
    assert plan.command[:5] == (
        "python-test",
        "-m",
        "pytest",
        "-q",
        "tests/test_nex_ae_alpha.py",
    )
    assert "--cov=services" in plan.command
    assert "--cov=providers" in plan.command
    assert "--cov=scripts" not in plan.command
    assert f"--cov-report=json:{plan.artifacts.coverage_json}" in plan.command
    assert f"--junitxml={plan.artifacts.junit_xml}" in plan.command

    with pytest.raises(ValueError, match="serial lane"):
        gate.build_owner_lane_plan(
            root=root,
            inventory=inventory,
            run_id="owner-plan",
            lane=gate.SERIAL_REPOSITORY_LANE,
            python_bin="python-test",
        )
    with pytest.raises(ValueError, match="no assigned tests"):
        gate.build_owner_lane_plan(
            root=root,
            inventory=inventory,
            run_id="owner-plan",
            lane="nex-ag",
            python_bin="python-test",
        )


def test_owner_lane_order_places_ae_first_and_rejects_invalid() -> None:
    assert gate._ordered_owner_lanes(("nex-eos", "nex-ae-api", "nex-eos")) == (
        "nex-ae-api",
        "nex-eos",
    )
    assert gate._ordered_owner_lanes(("nex-eos",)) == ("nex-eos",)
    with pytest.raises(ValueError, match="at least one"):
        gate._ordered_owner_lanes(())
    with pytest.raises(ValueError, match="serial lanes"):
        gate._ordered_owner_lanes((gate.SERIAL_INTEGRATION_LANE,))


def test_platform_profile_is_classified_as_serial_integration(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = root / "tests/test_platform_alpha.py"
    path.write_text("# platform fixture\n", encoding="utf-8")

    evidence = gate.build_test_ownership_inventory(
        root=root,
        tier="checkpoint",
        revision="1" * 40,
    )
    item = next(
        item
        for item in evidence["assignments"]
        if item["path"] == "tests/test_platform_alpha.py"
    )

    assert item["lane"] == gate.SERIAL_INTEGRATION_LANE
    assert item["reason"] == "PLATFORM_CROSS_SERVICE"


def test_parallel_owner_orchestrator_starts_ae_first_and_collects_failures(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    started: list[str] = []
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def runner(command, **kwargs):
        nonlocal active, maximum_active
        lane = kwargs["env"]["NEX_QUALITY_GATE_LANE"]
        with lock:
            started.append(lane)
            active += 1
            maximum_active = max(maximum_active, active)
        kwargs["stdout"].write(f"lane={lane}\n")
        time.sleep(0.02)
        with lock:
            active -= 1
        code = 7 if lane == "nex-wc" else 0
        return subprocess.CompletedProcess(command, code)

    evidence = gate.execute_owner_service_lanes(
        root=root,
        tier="checkpoint",
        run_id="parallel-owner-test",
        lanes=("nex-eos", "nex-wc", "nex-ae-api"),
        max_parallel=2,
        python_bin="python-test",
        revision="e" * 40,
        environ={"SAFE": "1"},
        runner=runner,
    )

    assert started[0] == "nex-ae-api"
    assert maximum_active == 2
    assert evidence["status"] == "FAIL"
    assert evidence["lane_start_order"] == ["nex-ae-api", "nex-eos", "nex-wc"]
    lanes = {item["lane"]: item for item in evidence["lanes"]}
    assert lanes["nex-wc"]["exit_code"] == 7
    assert lanes["nex-eos"]["status"] == "PASS"
    assert (root / "reports/quality/parallel/parallel-owner-test/owner-lanes.json").is_file()
    assert "lane=nex-ae-api" in (
        root
        / "reports/quality/parallel/parallel-owner-test/nex-ae-api/stdout.log"
    ).read_text(encoding="utf-8")


def test_parallel_owner_orchestrator_validates_parallel_budget(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 1 and 8"):
        gate.execute_owner_service_lanes(
            root=_root(tmp_path),
            tier="checkpoint",
            run_id="bad-budget",
            max_parallel=0,
            revision="f" * 40,
        )


def test_main_owner_lane_summary_and_failure(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    monkeypatch.setattr(gate, "ROOT", _root(tmp_path))
    observed = {}

    def execute(**kwargs):
        observed.update(kwargs)
        return {
            "status": "PASS",
            "lanes": [{"lane": "nex-ae-api"}],
            "duration_seconds": 1.25,
        }

    monkeypatch.setattr(gate, "execute_owner_service_lanes", execute)
    assert gate.main(
        [
            "run-owner-lanes",
            "--tier",
            "checkpoint",
            "--run-id",
            "cli-test",
            "--lane",
            "nex-ae-api",
            "--summary",
        ]
    ) == 0
    assert observed["lanes"] == ("nex-ae-api",)
    assert "parallel_owner_lanes=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        gate,
        "execute_owner_service_lanes",
        lambda **_kwargs: {"status": "FAIL", "lanes": [], "duration_seconds": 0.1},
    )
    assert gate.main(
        [
            "run-owner-lanes",
            "--tier",
            "full",
            "--run-id",
            "cli-fail",
            "--summary",
        ]
    ) == 1
    assert "parallel_owner_lanes=fail" in capsys.readouterr().out


def test_checkpoint_closure_commands_preserve_thresholds_and_audits(
    tmp_path: Path,
) -> None:
    commands = gate._checkpoint_closure_commands(
        python_bin="python-test",
        combined_raw=tmp_path / "combined/.coverage",
        combined_json=tmp_path / "combined/coverage.json",
        raw_coverage_paths=(tmp_path / "ae/.coverage", tmp_path / "eos/.coverage"),
    )

    assert len(commands) == 6
    assert commands[0][:5] == (
        "python-test",
        "-m",
        "coverage",
        "combine",
        "--keep",
    )
    assert str(tmp_path / "ae/.coverage") in commands[0]
    assert commands[2][-2:] == ("95", "94")
    assert commands[3][-1] == "scripts/quality/validate_contracts.py"
    assert commands[-1][-1] == "--summary"


def test_logged_commands_stop_on_failure_and_record_timings(tmp_path: Path) -> None:
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 9 if command[0] == "bad" else 0)

    times = iter((1.0, 1.2, 1.3, 1.8))
    results = gate._execute_logged_commands(
        commands=(("good",), ("bad",), ("never",)),
        root=tmp_path,
        environ={},
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        runner=runner,
        clock=lambda: next(times),
    )

    assert calls == [("good",), ("bad",)]
    assert results == [
        {"index": 1, "label": "good", "duration_seconds": 0.2, "exit_code": 0},
        {"index": 2, "label": "bad", "duration_seconds": 0.5, "exit_code": 9},
    ]


def test_parallel_checkpoint_executes_owner_then_serial_and_closure(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)

    def runner(command, **kwargs):
        kwargs["stdout"].write(f"command={command[0]}\n")
        return subprocess.CompletedProcess(command, 0)

    evidence = gate.execute_parallel_checkpoint_gate(
        root=root,
        run_id="checkpoint-test",
        max_parallel=2,
        python_bin="python-test",
        revision="2" * 40,
        environ={"SAFE": "1"},
        runner=runner,
    )

    assert evidence["status"] == "PASS"
    assert evidence["test_file_count"] == 6
    assert len(evidence["owner_lanes"]["lanes"]) == 3
    assert [item["lane"] for item in evidence["serial_lanes"]] == [
        gate.SERIAL_INTEGRATION_LANE,
        gate.SERIAL_REPOSITORY_LANE,
    ]
    assert len(evidence["closure_commands"]) == 6
    assert evidence["combined_coverage"].endswith("closure/coverage.json")
    assert (root / "reports/quality/checkpoint-parallel-latest.json").is_file()


def test_parallel_checkpoint_stops_before_serial_when_owner_fails(
    monkeypatch, tmp_path: Path
) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(
        gate,
        "execute_owner_service_lanes",
        lambda **_kwargs: {"status": "FAIL", "lanes": []},
    )

    evidence = gate.execute_parallel_checkpoint_gate(
        root=root,
        run_id="owner-failure",
        revision="4" * 40,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["serial_lanes"] == []
    assert evidence["closure_commands"] == []


def test_parallel_checkpoint_stops_on_serial_lane_failure(tmp_path: Path) -> None:
    root = _root(tmp_path)

    def runner(command, **kwargs):
        lane = kwargs["env"].get("NEX_QUALITY_GATE_LANE")
        code = 8 if lane == gate.SERIAL_INTEGRATION_LANE else 0
        return subprocess.CompletedProcess(command, code)

    evidence = gate.execute_parallel_checkpoint_gate(
        root=root,
        run_id="serial-failure",
        max_parallel=2,
        revision="5" * 40,
        runner=runner,
    )

    assert evidence["status"] == "FAIL"
    assert len(evidence["serial_lanes"]) == 1
    assert evidence["serial_lanes"][0]["lane"] == gate.SERIAL_INTEGRATION_LANE
    assert evidence["closure_commands"] == []


def test_checkpoint_result_fails_without_complete_serial_closure(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "reports/quality/parallel/incomplete"
    run_root.mkdir(parents=True)
    times = iter((5.0,))
    evidence = gate._write_checkpoint_result(
        root=tmp_path,
        run_root=run_root,
        run_id="incomplete",
        revision="3" * 40,
        inventory={"inventory_digest": "sha256:" + "0" * 64, "test_file_count": 1},
        owner_evidence={"status": "FAIL"},
        serial_results=[],
        closure_results=[],
        combined_coverage=None,
        started=4.0,
        clock=lambda: next(times),
    )

    assert evidence["status"] == "FAIL"
    assert evidence["duration_seconds"] == 1.0


def test_default_run_id_is_safe() -> None:
    value = gate._default_run_id("checkpoint", "ABCDEF123456")
    assert value.startswith("checkpoint-")
    assert value.endswith("-abcdef12")
    assert gate.RUN_ID_PATTERN.fullmatch(value)


def test_main_parallel_checkpoint_summary(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(gate, "ROOT", _root(tmp_path))
    monkeypatch.setattr(gate, "_git_revision", lambda _root: "6" * 40)
    observed = {}

    def execute(**kwargs):
        observed.update(kwargs)
        return {"status": "PASS", "test_file_count": 6, "duration_seconds": 2.5}

    monkeypatch.setattr(gate, "execute_parallel_checkpoint_gate", execute)

    assert gate.main(["checkpoint", "--summary"]) == 0
    assert observed["run_id"].startswith("checkpoint-")
    assert observed["revision"] == "6" * 40
    assert "parallel_checkpoint_gate=pass tests=6 duration=2.5s" in (
        capsys.readouterr().out
    )
