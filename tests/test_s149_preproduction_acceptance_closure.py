from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

import run_s149_preproduction_acceptance_closure as smoke


RC = "rc:s149:0123456789abcdef"
DIGEST = "sha256:" + "a" * 64


def _admission() -> dict[str, object]:
    return {
        "evidence_schema_version": "s149_evidence_admission.v1",
        "requirement": "S149",
        "slice": "1493",
        "status": "PASS",
        "next_slice": "1494",
        "release_binding": {
            "release_candidate_id": RC,
            "release_set_digest": DIGEST,
            "evidence_chain_digest": "sha256:" + "b" * 64,
        },
        "checks": {f"check_{index}": True for index in range(14)},
        "single_host_backlog": [
            {
                "backlog_id": f"backlog_{index}",
                "disposition": "NOT_APPLICABLE_SINGLE_HOST",
            }
            for index in range(5)
        ],
        "s150_admission": {
            "status": "CONDITIONALLY_READY",
            "external_notification_waiver": "REQUIRED_NOT_GRANTED",
            "production_go_eligible": False,
        },
    }


def _full_regression() -> dict[str, object]:
    return {
        "status": "PASS",
        "evidence_digest": "full-regression-digest",
        "metrics": {
            "passed_test_count": 12_345,
            "failed_test_count": 0,
            "skipped_test_count": 30,
            "statement_coverage": 98.5,
            "branch_coverage": 97.2,
        },
    }


def _write_repository(root: Path) -> None:
    runbook = root / smoke.RUNBOOK_PATH.relative_to(smoke.ROOT)
    canonical = root / smoke.CANONICAL_PATH.relative_to(smoke.ROOT)
    quality_gate = root / smoke.QUALITY_GATE_PATH.relative_to(smoke.ROOT)
    runbook.parent.mkdir(parents=True, exist_ok=True)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    quality_gate.parent.mkdir(parents=True, exist_ok=True)
    runbook.write_text("\n".join(smoke.RUNBOOK_TOKENS))
    canonical.write_text(
        "Status: S149 complete; S150 active.\n"
        "Full Gate runs at Slice 1494.\n"
        "Production deployment remains unapproved.\n"
    )
    quality_gate.write_text("\n".join(smoke.S149_RUNNERS))


def _write_quality_files(root: Path) -> tuple[Path, Path]:
    junit = root / "junit.xml"
    coverage = root / "coverage.json"
    junit.write_text(
        '<testsuites tests="12" failures="0" errors="0" skipped="2"></testsuites>'
    )
    coverage.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 98,
                    "num_statements": 100,
                    "covered_branches": 95,
                    "num_branches": 100,
                }
            }
        )
    )
    return junit, coverage


def test_closure_is_explicitly_protected() -> None:
    result = smoke.run_s149_preproduction_acceptance_closure({})

    assert result["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in result["skip_reason"]


def test_closure_passes_and_writes_atomic_metadata_evidence(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    admission = tmp_path / "admission.json"
    admission.write_text(json.dumps(_admission()))
    junit, coverage = _write_quality_files(tmp_path)
    output = tmp_path / "nested" / "closure.json"

    result = smoke.run_s149_preproduction_acceptance_closure(
        {smoke.ACTIVATION_ENV: "1"},
        admission_path=admission,
        junit_path=junit,
        coverage_path=coverage,
        output_path=output,
        root=tmp_path,
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["closure_readiness"] == "S149_COMPLETE_S150_ACTIVE"
    assert result["s150_handoff"]["production_go_eligible"] is False
    assert result["summary"]["registered_runner_count"] == 12
    assert result["next_requirement"] == "S150"
    assert json.loads(output.read_text()) == result
    assert not output.with_name(f".{output.name}.tmp").exists()


@pytest.mark.parametrize(
    ("case", "failed_check"),
    [
        ("admission", "admission_schema_and_status_valid"),
        ("release", "release_binding_valid"),
        ("checks", "all_admission_checks_passed"),
        ("backlog", "single_host_backlog_preserved"),
        ("regression", "fresh_full_regression_passed"),
        ("freshness", "full_regression_evidence_is_fresh"),
        ("runbook", "operator_runbook_complete"),
        ("registration", "all_s149_runners_registered_once"),
        ("canonical", "canonical_closure_and_handoff_recorded"),
        ("go_guard", "production_go_guard_preserved"),
    ],
)
def test_closure_fails_closed_for_gate_drift(
    tmp_path: Path, case: str, failed_check: str
) -> None:
    _write_repository(tmp_path)
    admission = _admission()
    regression = _full_regression()
    admission_mtime = 1.0
    junit_mtime = 2.0
    coverage_mtime = 2.0
    if case == "admission":
        admission["status"] = "FAIL"
    elif case == "release":
        admission["release_binding"]["release_set_digest"] = "bad"
    elif case == "checks":
        admission["checks"]["check_0"] = False
    elif case == "backlog":
        admission["single_host_backlog"][0]["disposition"] = "PASS"
    elif case == "regression":
        regression["metrics"]["branch_coverage"] = 93.99
    elif case == "freshness":
        junit_mtime = 0.0
    elif case == "runbook":
        (tmp_path / smoke.RUNBOOK_PATH.relative_to(smoke.ROOT)).write_text("")
    elif case == "registration":
        gate = tmp_path / smoke.QUALITY_GATE_PATH.relative_to(smoke.ROOT)
        gate.write_text(gate.read_text() + "\n" + smoke.S149_RUNNERS[0])
    elif case == "canonical":
        (tmp_path / smoke.CANONICAL_PATH.relative_to(smoke.ROOT)).write_text("")
    elif case == "go_guard":
        admission["s150_admission"]["production_go_eligible"] = True

    result = smoke._evaluate(
        admission,
        regression,
        admission_mtime=admission_mtime,
        junit_mtime=junit_mtime,
        coverage_mtime=coverage_mtime,
        root=tmp_path,
    )

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False
    assert failed_check in result["failed_checks"]
    assert result["next_requirement"] == "blocked"


@pytest.mark.parametrize("case", ("missing", "list", "json", "junit", "coverage"))
def test_closure_inputs_fail_closed(tmp_path: Path, case: str) -> None:
    _write_repository(tmp_path)
    admission = tmp_path / "admission.json"
    admission.write_text(json.dumps(_admission()))
    junit, coverage = _write_quality_files(tmp_path)
    if case == "missing":
        admission = tmp_path / "missing.json"
    elif case == "list":
        admission.write_text("[]")
    elif case == "json":
        admission.write_text("{")
    elif case == "junit":
        junit.write_text("<testsuites>")
    elif case == "coverage":
        coverage.write_text("{")

    result = smoke.run_s149_preproduction_acceptance_closure(
        {smoke.ACTIVATION_ENV: "1"},
        admission_path=admission,
        junit_path=junit,
        coverage_path=coverage,
        output_path=tmp_path / "output.json",
        root=tmp_path,
    )

    assert result["failure_code"] == "s149_closure_input_failed"
    assert result["production_deployment_approved"] is False


def test_helpers_summary_and_main(monkeypatch, capsys, tmp_path: Path) -> None:
    _write_repository(tmp_path)
    result = smoke._evaluate(
        _admission(),
        _full_regression(),
        admission_mtime=1,
        junit_mtime=2,
        coverage_mtime=2,
        root=tmp_path,
    )

    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert smoke.summary_line(result) == (
        "s149_preproduction_acceptance_closure=pass checks=10/10 "
        "runners=12/12 tests=12345 coverage=98.5/97.2 next=S150"
    )
    assert smoke._mapping([]) == {}
    assert smoke._read_text(tmp_path / "missing") == ""
    output = tmp_path / "direct.json"
    smoke._write_evidence(output, result)
    assert json.loads(output.read_text())["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_s149_preproduction_acceptance_closure",
        lambda **_kwargs: result,
    )
    assert smoke.main(["--summary", "--output", str(tmp_path / "main.json")]) == 0
    assert "closure=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_s149_preproduction_acceptance_closure",
        lambda **_kwargs: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1


def test_default_paths_can_be_supplied_by_environment(
    monkeypatch, tmp_path: Path
) -> None:
    _write_repository(tmp_path)
    admission = tmp_path / "admission.json"
    admission.write_text(json.dumps(_admission()))
    junit, coverage = _write_quality_files(tmp_path)
    output = tmp_path / "output.json"
    env = {
        smoke.ACTIVATION_ENV: "1",
        smoke.ADMISSION_PATH_ENV: str(admission),
        smoke.JUNIT_PATH_ENV: str(junit),
        smoke.COVERAGE_PATH_ENV: str(coverage),
        smoke.OUTPUT_PATH_ENV: str(output),
    }
    monkeypatch.setattr(os.path, "getmtime", os.path.getmtime)

    result = smoke.run_s149_preproduction_acceptance_closure(env, root=tmp_path)

    assert result["status"] == "PASS"
    assert output.is_file()
