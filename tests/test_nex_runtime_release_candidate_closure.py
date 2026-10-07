from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

import nex_runtime.release_candidate_closure as closure
from nex_runtime.release_candidate import RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION
from nex_runtime.release_candidate_protected_matrix import (
    RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
)
import run_s140_platform_release_candidate_closure as runner


NOW = datetime(2026, 10, 6, 6, 7, 8, tzinfo=UTC)
TIMESTAMP = "2026-10-06T06:07:08Z"


def gate(
    gate_id: str,
    metrics: dict[str, object],
    *,
    protected: bool = False,
    status: str = "PASS",
) -> dict[str, object]:
    return {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "gate_id": gate_id,
        "status": status,
        "execution_mode": "protected" if protected else "deterministic",
        "actual_execution": protected,
        "private_payload_included": False,
        "observed_at": TIMESTAMP,
        "evidence_digest": "a" * 64,
        "metrics": metrics,
    }


def protected_matrix() -> dict[str, object]:
    return {
        "schema_version": RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
        "status": "PASS",
        "readiness": "READY_FOR_FULL_GATE",
        "checks": {"all_sources_passed": True},
        "evidence": [
            gate(
                "golden_scenarios",
                {"scenario_count": 10, "passed_scenario_count": 10},
            ),
            gate(
                "five_database_restart",
                {"database_count": 5, "restored_database_count": 5},
                protected=True,
            ),
            gate(
                "live_provider_matrix",
                {"provider_capability_count": 3, "failed_provider_count": 0},
                protected=True,
            ),
            gate(
                "korean_browser_journey",
                {"viewport_count": 2, "passed_viewport_count": 2},
                protected=True,
            ),
            gate(
                "ag_trace_operations",
                {"trace_stage_count": 8, "audit_export_count": 1},
                protected=True,
            ),
            gate(
                "contract_privacy",
                {"contract_validation_passed": True, "privacy_violation_count": 0},
            ),
            gate(
                "zero_residue",
                {
                    "database_residue_count": 0,
                    "file_residue_count": 0,
                    "running_process_count": 0,
                },
                protected=True,
            ),
            gate(
                "deployment_deferrals",
                {"deferral_count": 9, "production_deployment_approved": False},
            ),
            gate(
                "full_regression",
                {"passed_test_count": 0, "failed_test_count": 0},
                status="SKIPPED",
            ),
        ],
    }


def write_quality_files(
    tmp_path: Path,
    *,
    tests: int = 101,
    failures: int = 0,
    errors: int = 0,
    skipped: int = 1,
    covered_lines: int = 98,
    covered_branches: int = 97,
) -> tuple[Path, Path]:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        (
            f'<testsuites tests="{tests}" failures="{failures}" '
            f'errors="{errors}" skipped="{skipped}"></testsuites>'
        ),
        encoding="utf-8",
    )
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": covered_lines,
                    "num_statements": 100,
                    "covered_branches": covered_branches,
                    "num_branches": 100,
                }
            }
        ),
        encoding="utf-8",
    )
    return junit, coverage


def test_loads_full_gate_and_closes_nine_gate_release_candidate(tmp_path: Path) -> None:
    junit, coverage_path = write_quality_files(tmp_path)
    full_gate = closure.load_full_regression_evidence(
        junit, coverage_path, observed_at=NOW
    )
    result = closure.build_release_candidate_closure(
        protected_matrix(), full_gate, evaluated_at=NOW
    )

    assert full_gate["status"] == "PASS"
    assert full_gate["metrics"] == {
        "passed_test_count": 100,
        "failed_test_count": 0,
        "skipped_test_count": 1,
        "total_test_count": 101,
        "statement_coverage": 98.0,
        "statement_coverage_min": 95.0,
        "branch_coverage": 97.0,
        "branch_coverage_min": 85.0,
    }
    assert result["status"] == "PASS"
    assert result["readiness"] == "RELEASE_CANDIDATE"
    assert result["production_deployment_approved"] is False
    assert all(result["checks"].values())
    assert result["summary"] == {
        "required_gate_count": 9,
        "passed_gate_count": 9,
        "actual_protected_gate_count": 5,
        "privacy_violation_count": 0,
        "passed_test_count": 100,
    }


def test_loads_pytest_junit_testsuites_child_counts(tmp_path: Path) -> None:
    junit, coverage_path = write_quality_files(tmp_path)
    junit.write_text(
        (
            '<testsuites name="pytest tests">'
            '<testsuite tests="61" failures="0" errors="0" skipped="1"/>'
            '<testsuite tests="40" failures="0" errors="0" skipped="0"/>'
            "</testsuites>"
        ),
        encoding="utf-8",
    )

    evidence = closure.load_full_regression_evidence(
        junit, coverage_path, observed_at=NOW
    )

    assert evidence["status"] == "PASS"
    assert evidence["metrics"]["total_test_count"] == 101
    assert evidence["metrics"]["passed_test_count"] == 100
    assert evidence["metrics"]["skipped_test_count"] == 1


@pytest.mark.parametrize(
    ("quality_kwargs", "expected_failed"),
    (
        ({"failures": 1}, 1),
        ({"errors": 1}, 1),
        ({"covered_lines": 94}, 0),
        ({"covered_branches": 84}, 0),
    ),
)
def test_full_gate_evidence_fails_closed(
    tmp_path: Path,
    quality_kwargs: dict[str, int],
    expected_failed: int,
) -> None:
    junit, coverage_path = write_quality_files(tmp_path, **quality_kwargs)
    evidence = closure.load_full_regression_evidence(
        junit, coverage_path, observed_at=NOW
    )
    assert evidence["status"] == "FAIL"
    assert evidence["metrics"]["failed_test_count"] == expected_failed


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(schema_version="wrong"),
        lambda value: value.update(status="FAIL"),
        lambda value: value.update(readiness="BLOCKED"),
        lambda value: value.update(checks={"source": False}),
        lambda value: value.update(checks={}),
        lambda value: value.update(evidence=value["evidence"][:-1]),
        lambda value: value["evidence"][0].update(status="FAIL"),
        lambda value: value["evidence"][1].update(actual_execution=False),
    ),
)
def test_closure_rejects_incomplete_or_failed_protected_evidence(
    tmp_path: Path, mutation
) -> None:
    junit, coverage_path = write_quality_files(tmp_path)
    source = protected_matrix()
    mutation(source)
    result = closure.build_release_candidate_closure(
        source,
        closure.load_full_regression_evidence(
            junit, coverage_path, observed_at=NOW
        ),
        evaluated_at=NOW,
    )
    assert result["status"] == "FAIL"
    assert result["readiness"] == "BLOCKED"
    assert result["failed_checks"]


def test_quality_input_parsers_reject_invalid_shapes(tmp_path: Path) -> None:
    junit, coverage_path = write_quality_files(tmp_path)
    junit.write_text('<not-junit tests="1"/>', encoding="utf-8")
    with pytest.raises(ValueError, match="JUnit root"):
        closure.load_full_regression_evidence(junit, coverage_path)

    for attributes in (
        'tests="0" failures="0" errors="0" skipped="0"',
        'tests="1" failures="x" errors="0" skipped="0"',
        'tests="1" failures="1" errors="1" skipped="0"',
        'tests="1" failures="0" errors="0" skipped="true"',
    ):
        junit.write_text(f"<testsuite {attributes}/>", encoding="utf-8")
        with pytest.raises(ValueError):
            closure.load_full_regression_evidence(junit, coverage_path)

    junit.write_text(
        '<testsuite tests="1" failures="0" errors="0"/>', encoding="utf-8"
    )
    for totals in (
        {},
        {
            "covered_lines": 1,
            "num_statements": 0,
            "covered_branches": 1,
            "num_branches": 0,
        },
        {
            "covered_lines": 2,
            "num_statements": 1,
            "covered_branches": 2,
            "num_branches": 1,
        },
        {
            "covered_lines": True,
            "num_statements": 1,
            "covered_branches": 1,
            "num_branches": 1,
        },
        {
            "covered_lines": -1,
            "num_statements": 1,
            "covered_branches": 1,
            "num_branches": 1,
        },
    ):
        coverage_path.write_text(json.dumps({"totals": totals}), encoding="utf-8")
        with pytest.raises(ValueError):
            closure.load_full_regression_evidence(junit, coverage_path)


def test_naive_timestamp_and_nonsequence_evidence_are_bounded(tmp_path: Path) -> None:
    junit, coverage_path = write_quality_files(tmp_path)
    evidence = closure.load_full_regression_evidence(
        junit,
        coverage_path,
        observed_at=datetime(2026, 10, 6, 6, 7, 8),
    )
    source = protected_matrix()
    source["evidence"] = "invalid"
    result = closure.build_release_candidate_closure(
        source, evidence, evaluated_at=NOW
    )
    assert evidence["observed_at"].endswith("Z")
    assert result["status"] == "FAIL"


def test_runner_is_opt_in_writes_safe_evidence_and_handles_inputs(
    tmp_path: Path,
) -> None:
    assert runner.run_s140_platform_release_candidate_closure({})["status"] == "SKIPPED"
    assert runner.summary_line({"status": "SKIPPED"}).endswith("=skip")

    protected_path = tmp_path / "protected.json"
    protected_path.write_text(json.dumps(protected_matrix()), encoding="utf-8")
    junit, coverage_path = write_quality_files(tmp_path)
    result = runner.run_s140_platform_release_candidate_closure(
        {
            runner.ENABLE_ENV: "1",
            runner.PROTECTED_EVIDENCE_ENV: str(protected_path),
        },
        junit_path=junit,
        coverage_path=coverage_path,
        observed_at=NOW,
    )
    assert result["status"] == "PASS"
    assert "gates=9/9" in runner.summary_line(result)

    output = tmp_path / "nested" / "closure.json"
    runner.write_evidence(output, result)
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert not output.with_name(f".{output.name}.tmp").exists()

    missing = runner.run_s140_platform_release_candidate_closure(
        {runner.ENABLE_ENV: "1"}
    )
    assert missing["failure_code"] == "platform_release_candidate_closure_input_failed"
    protected_path.write_text("[]", encoding="utf-8")
    invalid = runner.run_s140_platform_release_candidate_closure(
        {runner.ENABLE_ENV: "1"},
        protected_evidence_path=protected_path,
        junit_path=junit,
        coverage_path=coverage_path,
    )
    assert invalid["status"] == "FAIL"

    protected_path.write_text(json.dumps(protected_matrix()), encoding="utf-8")
    junit.write_text("<testsuites>", encoding="utf-8")
    malformed_xml = runner.run_s140_platform_release_candidate_closure(
        {runner.ENABLE_ENV: "1"},
        protected_evidence_path=protected_path,
        junit_path=junit,
        coverage_path=coverage_path,
    )
    assert malformed_xml["status"] == "FAIL"


def test_runner_main_and_repository_registration(monkeypatch, tmp_path: Path, capsys) -> None:
    passing = {
        "status": "PASS",
        "readiness": "RELEASE_CANDIDATE",
        "summary": {
            "passed_gate_count": 9,
            "actual_protected_gate_count": 5,
            "passed_test_count": 100,
            "privacy_violation_count": 0,
        },
    }
    monkeypatch.setattr(
        runner, "run_s140_platform_release_candidate_closure", lambda **kwargs: passing
    )
    output = tmp_path / "evidence.json"
    assert runner.main(["--summary", "--output", str(output)]) == 0
    assert "decision=RELEASE_CANDIDATE" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        runner,
        "run_s140_platform_release_candidate_closure",
        lambda **kwargs: {"status": "FAIL", "readiness": "BLOCKED", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out

    quality_gate = (runner.ROOT / "scripts/quality/run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    for script in (
        "run_platform_release_candidate_live_providers.py",
        "run_platform_release_candidate_browser_ag_operations.py",
        "run_platform_release_candidate_assurance.py",
        "run_platform_release_candidate_protected_matrix.py",
        "run_s140_platform_release_candidate_closure.py",
    ):
        assert quality_gate.count(script) == 1
    assert '--junitxml="$REPORT_DIR/junit.xml"' in quality_gate
