from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
import run_parallel_quality_gate as gate


def _root(tmp_path: Path) -> Path:
    paths = (
        "tests/test_nex_ae_alpha.py",
        "tests/test_nex_eos_alpha.py",
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
    assert evidence["test_file_count"] == 5
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
    assert first["test_file_count"] == 6
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
    assert printed["test_file_count"] == 6


def test_main_fails_closed_for_unsafe_output(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(gate, "ROOT", _root(tmp_path))

    assert gate.main(
        ["inventory", "--tier", "full", "--output", "reports/quality/out.json"]
    ) == 1
    assert "parallel_quality_inventory=fail error=ValueError" in capsys.readouterr().out


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
