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
