from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from nex_runtime.production_release import RELEASE_GATE_NAMES
import run_s150_production_release_closure as runner


RELEASE_ID = "rc:s149:0123456789abcdef"
RELEASE_DIGEST = "sha256:" + "a" * 64


def _gates(*, go: bool = False) -> dict[str, bool]:
    result = {name: True for name in RELEASE_GATE_NAMES}
    if not go:
        result["p1_waivers_valid"] = False
        result["approval_roles_complete"] = False
    return result


def _decision(*, go: bool = False) -> dict:
    gates = _gates(go=go)
    failed = [name for name in RELEASE_GATE_NAMES if not gates[name]]
    return {
        "status": "PASS",
        "decision": "GO" if go else "NO_GO",
        "release_candidate_id": RELEASE_ID,
        "release_set_digest": RELEASE_DIGEST,
        "gate_order": list(RELEASE_GATE_NAMES),
        "gate_results": gates,
        "failed_gates": failed,
        "go_authorized": go,
        "implicit_deployment_performed": False,
        "production_deployment_approved": False,
    }


def _protected(*, go: bool = False) -> dict:
    decision = _decision(go=go)
    return {
        "evidence_schema_version": "s150_protected_acceptance.v1",
        "slice": "1503",
        "status": "PASS",
        "next_slice": "1504",
        "release_candidate_id": RELEASE_ID,
        "release_set_digest": RELEASE_DIGEST,
        "release_decision": decision["decision"],
        "gate_results": decision["gate_results"],
        "failed_gates": decision["failed_gates"],
        "checks": {f"check_{index}": True for index in range(10)},
        "summary": {"distributed_backlog_count": 5},
        "go_live_authorized": go,
        "implicit_deployment_performed": False,
        "production_deployment_approved": False,
    }


def _regression() -> dict:
    return {
        "status": "PASS",
        "evidence_digest": "sha256:" + "b" * 64,
        "metrics": {
            "passed_test_count": 13_700,
            "failed_test_count": 0,
            "skipped_test_count": 33,
            "statement_coverage": 97.9,
            "branch_coverage": 96.9,
        },
    }


def _write_repository(root: Path, *, decision: str = "NO_GO") -> None:
    runbook = root / runner.RUNBOOK_PATH.relative_to(runner.ROOT)
    canonical = root / runner.CANONICAL_PATH.relative_to(runner.ROOT)
    quality_gate = root / runner.QUALITY_GATE_PATH.relative_to(runner.ROOT)
    runbook.parent.mkdir(parents=True, exist_ok=True)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    quality_gate.parent.mkdir(parents=True, exist_ok=True)
    runbook.write_text("\n".join(runner.RUNBOOK_TOKENS), encoding="utf-8")
    canonical.write_text(
        "Status: S150 complete.\n"
        f"Current release decision: `{decision}`.\n"
        "Production deployment remains unapproved.\n"
        "NOT_APPLICABLE_SINGLE_HOST\n",
        encoding="utf-8",
    )
    quality_gate.write_text("\n".join(runner.S150_RUNNERS), encoding="utf-8")


def _write_quality_files(root: Path) -> tuple[Path, Path]:
    junit = root / "junit.xml"
    coverage = root / "coverage.json"
    junit.write_text(
        '<testsuites tests="100" failures="0" errors="0" skipped="2"></testsuites>',
        encoding="utf-8",
    )
    coverage.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 98,
                    "num_statements": 100,
                    "covered_branches": 97,
                    "num_branches": 100,
                }
            }
        ),
        encoding="utf-8",
    )
    return junit, coverage


@pytest.mark.parametrize("go", (False, True))
def test_closure_accepts_complete_go_or_no_go_implementation(
    tmp_path: Path, go: bool
) -> None:
    _write_repository(tmp_path, decision="GO" if go else "NO_GO")
    result = runner._evaluate(
        _protected(go=go),
        _decision(go=go),
        _regression(),
        protected_mtime=1,
        junit_mtime=2,
        coverage_mtime=2,
        root=tmp_path,
    )

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["closure_status"] == "S150_COMPLETE"
    assert result["release_decision"] == ("GO" if go else "NO_GO")
    assert result["go_live_authorized"] is go
    assert result["production_deployment_approved"] is False


@pytest.mark.parametrize(
    ("case", "failed_check"),
    [
        ("protected", "protected_acceptance_passed"),
        ("release", "release_identity_valid"),
        ("gates", "ten_gate_decision_exact"),
        ("regression", "full_regression_passed"),
        ("freshness", "full_regression_evidence_fresh"),
        ("runbook", "operator_runbook_complete"),
        ("registration", "all_s150_runners_registered_once"),
        ("canonical", "canonical_closure_recorded"),
        ("backlog", "distributed_backlog_preserved"),
        ("deployment", "production_deployment_separate"),
    ],
)
def test_closure_fails_closed_for_every_check(
    tmp_path: Path, case: str, failed_check: str
) -> None:
    _write_repository(tmp_path)
    protected = deepcopy(_protected())
    decision = deepcopy(_decision())
    regression = _regression()
    protected_mtime = 1.0
    junit_mtime = 2.0
    coverage_mtime = 2.0
    if case == "protected":
        protected["status"] = "FAIL"
    elif case == "release":
        decision["release_set_digest"] = "bad"
    elif case == "gates":
        protected["failed_gates"] = []
    elif case == "regression":
        regression["metrics"]["branch_coverage"] = 93.9
    elif case == "freshness":
        junit_mtime = 0.0
    elif case == "runbook":
        (tmp_path / runner.RUNBOOK_PATH.relative_to(runner.ROOT)).write_text("")
    elif case == "registration":
        gate = tmp_path / runner.QUALITY_GATE_PATH.relative_to(runner.ROOT)
        gate.write_text(gate.read_text() + "\n" + runner.S150_RUNNERS[0])
    elif case == "canonical":
        (tmp_path / runner.CANONICAL_PATH.relative_to(runner.ROOT)).write_text("")
    elif case == "backlog":
        protected["summary"]["distributed_backlog_count"] = 4
    elif case == "deployment":
        decision["production_deployment_approved"] = True

    result = runner._evaluate(
        protected,
        decision,
        regression,
        protected_mtime=protected_mtime,
        junit_mtime=junit_mtime,
        coverage_mtime=coverage_mtime,
        root=tmp_path,
    )

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False
    assert result["go_live_authorized"] is False
    assert result["next_action"] == "BLOCKED"


def test_closure_runs_from_files_and_writes_atomic_evidence(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    protected = tmp_path / "protected.json"
    decision = tmp_path / "decision.json"
    protected.write_text(json.dumps(_protected()), encoding="utf-8")
    decision.write_text(json.dumps(_decision()), encoding="utf-8")
    junit, coverage = _write_quality_files(tmp_path)
    output = tmp_path / "nested/closure.json"

    result = runner.run_production_release_closure(
        {runner.ACTIVATION_ENV: "1"},
        protected_path=protected,
        decision_path=decision,
        junit_path=junit,
        coverage_path=coverage,
        output_path=output,
        root=tmp_path,
    )

    assert result["status"] == "PASS", result
    assert json.loads(output.read_text()) == result
    assert not output.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("case", ("missing", "list", "json", "junit", "coverage"))
def test_closure_inputs_fail_closed(tmp_path: Path, case: str) -> None:
    _write_repository(tmp_path)
    protected = tmp_path / "protected.json"
    decision = tmp_path / "decision.json"
    protected.write_text(json.dumps(_protected()), encoding="utf-8")
    decision.write_text(json.dumps(_decision()), encoding="utf-8")
    junit, coverage = _write_quality_files(tmp_path)
    if case == "missing":
        protected = tmp_path / "missing.json"
    elif case == "list":
        protected.write_text("[]")
    elif case == "json":
        decision.write_text("{")
    elif case == "junit":
        junit.write_text("<testsuites>")
    elif case == "coverage":
        coverage.write_text("{")

    result = runner.run_production_release_closure(
        {runner.ACTIVATION_ENV: "1"},
        protected_path=protected,
        decision_path=decision,
        junit_path=junit,
        coverage_path=coverage,
        output_path=tmp_path / "closure.json",
        root=tmp_path,
    )

    assert result["failure_code"] == "s150_closure_input_failed"
    assert result["production_deployment_approved"] is False


def test_closure_skip_helpers_summary_and_cli(monkeypatch, tmp_path: Path, capsys) -> None:
    assert runner.run_production_release_closure({})["status"] == "SKIPPED"
    assert "diagnostics" not in runner._failure("direct_failure")
    _write_repository(tmp_path)
    result = runner._evaluate(
        _protected(),
        _decision(),
        _regression(),
        protected_mtime=1,
        junit_mtime=2,
        coverage_mtime=2,
        root=tmp_path,
    )
    assert runner._mapping([]) == {}
    assert runner._read_text(tmp_path / "missing") == ""
    assert runner.summary_line({"status": "SKIPPED"}).endswith("skipped")
    assert "decision=NO_GO" in runner.summary_line(result)
    monkeypatch.setattr(runner, "run_production_release_closure", lambda **_kw: result)
    assert runner.main(["--summary"]) == 0
    assert "checks=10/10" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_production_release_closure",
        lambda **_kw: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
