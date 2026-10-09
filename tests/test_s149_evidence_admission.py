from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

import run_s149_evidence_admission as smoke


RC = "rc:s149:0123456789abcdef"
RELEASE_DIGEST = "sha256:" + "a" * 64
WORKLOAD_DIGEST = "workload-digest"


def _evidence() -> dict[str, dict[str, object]]:
    s1490: dict[str, object] = {
        "evidence_schema_version": "s149_single_host_live_acceptance.v1",
        "requirement": "S149",
        "slice": "1490",
        "status": "PASS",
        "release_binding": {
            "release_candidate_id": RC,
            "release_set_digest": RELEASE_DIGEST,
        },
        "checks": {"single_host_ready": True},
        "external_notification": {
            "status": "EXTERNAL_NOT_ACTIVATED",
            "s150_requirement": (
                "time_bounded_p1_waiver_and_local_compensating_control"
            ),
        },
        "execution_scope": {
            "production_contacted": False,
            "production_deployment_approved": False,
        },
    }
    s1491: dict[str, object] = {
        "evidence_schema_version": "s149_release_bound_target_workload.v1",
        "requirement": "S149",
        "slice": "1491",
        "status": "PASS",
        "release_binding": {
            "release_candidate_id": RC,
            "release_set_digest": RELEASE_DIGEST,
            "s1490_evidence_digest": smoke._digest(s1490),
            "workload_digest": WORKLOAD_DIGEST,
        },
        "checks": {"target_ready": True},
        "workload": {
            "metrics": {"request_count": 7_200, "success_count": 7_200}
        },
        "cleanup": {"residue_count": 0},
        "execution_scope": {
            "production_contacted": False,
            "production_capacity_claimed": False,
        },
    }
    s1492: dict[str, object] = {
        "evidence_schema_version": (
            "s149_under_load_fault_security_rollback.v1"
        ),
        "requirement": "S149",
        "slice": "1492",
        "status": "PASS",
        "release_binding": {
            "release_candidate_id": RC,
            "release_set_digest": RELEASE_DIGEST,
            "s1491_evidence_digest": smoke._digest(s1491),
            "workload_digest": WORKLOAD_DIGEST,
            "fault_plan_digest": "fault-digest",
        },
        "checks": {"under_load_ready": True},
        "shadow_load": {
            "request_count": 1_440,
            "metrics": {"success_count": 1_440},
            "generation_reasoning_mode": "disabled",
        },
        "faults": {
            "status": "PASS",
            "summary": {"scenario_count": 8, "recovered_count": 8},
        },
        "cleanup": {
            "shadow_residue_count": 0,
            "client_fault_residue_count": 0,
            "provider_residue_count": 0,
            "storage_status": "PASS",
        },
        "execution_scope": {
            "production_contacted": False,
            "production_deployment_approved": False,
            "provider_process_mutation_performed": False,
        },
    }
    return {"1490": s1490, "1491": s1491, "1492": s1492}


def _write_reports(
    tmp_path: Path, evidence: dict[str, dict[str, object]] | None = None
) -> dict[str, tuple[Path, str]]:
    values = evidence or _evidence()
    reports = {}
    for slice_id, value in values.items():
        path = tmp_path / f"{slice_id}.json"
        path.write_text(json.dumps(value))
        reports[slice_id] = (
            path,
            str(value["evidence_schema_version"]),
        )
    return reports


def _run(
    tmp_path: Path,
    evidence: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    return smoke.run_s149_evidence_admission(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "test"},
        execute=True,
        input_reports=_write_reports(tmp_path, evidence),
        report_path=tmp_path / "result.json",
    )


def test_admission_requires_opt_in_and_test_profile() -> None:
    skipped = smoke.run_s149_evidence_admission({})
    wrong = smoke.run_s149_evidence_admission(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "staging"},
        execute=True,
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in skipped["skip_reason"]
    assert wrong["failure_code"] == "profile_not_allowed"


def test_admission_passes_with_release_bound_metadata_only_evidence(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["release_binding"]["release_candidate_id"] == RC
    assert result["summary"] == {
        "passed_check_count": 14,
        "check_count": 14,
        "evidence_source_count": 3,
        "backlog_count": 5,
        "target_request_count": 7_200,
        "under_load_request_count": 1_440,
        "recovered_fault_count": 8,
    }
    assert result["s150_admission"] == {
        "status": "CONDITIONALLY_READY",
        "s149_full_gate_complete": False,
        "external_notification_waiver": "REQUIRED_NOT_GRANTED",
        "local_compensating_control_required": True,
        "production_go_eligible": False,
        "open_conditions": [
            "s149_full_gate",
            "external_notification_p1_waiver",
        ],
    }
    assert len(result["single_host_backlog"]) == 5
    assert result["next_slice"] == "1494"
    assert json.loads((tmp_path / "result.json").read_text()) == result


def _refresh_chain(evidence: dict[str, dict[str, object]]) -> None:
    evidence["1491"]["release_binding"]["s1490_evidence_digest"] = smoke._digest(
        evidence["1490"]
    )
    evidence["1492"]["release_binding"]["s1491_evidence_digest"] = smoke._digest(
        evidence["1491"]
    )


@pytest.mark.parametrize(
    ("case", "failed_check"),
    [
        ("source_failed", "all_required_evidence_passed"),
        ("release_id", "release_candidate_identity_consistent"),
        ("release_digest", "immutable_release_digest_consistent"),
        ("chain", "evidence_chain_complete"),
        ("workload", "workload_identity_consistent"),
        ("nested", "all_nested_checks_passed"),
        ("target", "target_workload_exact_and_clean"),
        ("shadow", "under_load_workload_exact_and_clean"),
        ("fault", "fault_recovery_complete"),
        ("reasoning", "generation_reasoning_disabled"),
        ("residue", "all_rehearsal_residue_zero"),
        ("production", "production_and_provider_processes_untouched"),
        ("external", "external_notification_condition_explicit"),
    ],
)
def test_admission_fails_closed_for_evidence_drift(
    tmp_path: Path, case: str, failed_check: str
) -> None:
    evidence = _evidence()
    if case == "source_failed":
        evidence["1490"]["status"] = "FAIL"
        _refresh_chain(evidence)
    elif case == "release_id":
        evidence["1492"]["release_binding"]["release_candidate_id"] = (
            "rc:s149:fedcba9876543210"
        )
    elif case == "release_digest":
        evidence["1492"]["release_binding"]["release_set_digest"] = (
            "sha256:" + "f" * 64
        )
    elif case == "chain":
        evidence["1492"]["release_binding"]["s1491_evidence_digest"] = "bad"
    elif case == "workload":
        evidence["1492"]["release_binding"]["workload_digest"] = "other"
    elif case == "nested":
        evidence["1491"]["checks"] = {"target_ready": False}
        _refresh_chain(evidence)
    elif case == "target":
        evidence["1491"]["workload"]["metrics"]["success_count"] = 7_199
        _refresh_chain(evidence)
    elif case == "shadow":
        evidence["1492"]["shadow_load"]["request_count"] = 1_439
    elif case == "fault":
        evidence["1492"]["faults"]["summary"]["recovered_count"] = 7
    elif case == "reasoning":
        evidence["1492"]["shadow_load"]["generation_reasoning_mode"] = (
            "provider_default"
        )
    elif case == "residue":
        evidence["1492"]["cleanup"]["provider_residue_count"] = 1
    elif case == "production":
        evidence["1492"]["execution_scope"][
            "provider_process_mutation_performed"
        ] = True
    elif case == "external":
        evidence["1490"]["external_notification"]["status"] = "PASS"
        _refresh_chain(evidence)

    result = _run(tmp_path, evidence)

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False
    assert result["s150_admission"]["status"] == "NOT_ADMITTED"
    assert result["next_slice"] == "blocked"


def test_admission_fails_when_backlog_classification_drifts(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(smoke, "_backlog_projection", lambda: [])

    result = _run(tmp_path)

    assert result["checks"]["single_host_backlog_classified"] is False


@pytest.mark.parametrize("case", ("missing", "list", "slice", "schema", "json"))
def test_report_loading_and_evidence_set_fail_closed(
    tmp_path: Path, case: str
) -> None:
    reports = _write_reports(tmp_path)
    if case == "missing":
        reports.pop("1492")
    else:
        path, schema = reports["1492"]
        if case == "list":
            path.write_text("[]")
        elif case == "slice":
            value = json.loads(path.read_text())
            value["slice"] = "wrong"
            path.write_text(json.dumps(value))
        elif case == "schema":
            reports["1492"] = (path, "wrong-schema")
        elif case == "json":
            path.write_text("{")

    result = smoke.run_s149_evidence_admission(
        {smoke.ACTIVATION_ENV: "1"},
        execute=True,
        input_reports=reports,
        report_path=tmp_path / "result.json",
    )

    assert result["failure_code"] == "evidence_admission_execution_failed"
    assert result["diagnostics"] in (
        {"exception_type": "ValueError"},
        {"exception_type": "JSONDecodeError"},
    )


def test_helpers_summary_and_main(monkeypatch, capsys, tmp_path: Path) -> None:
    passing = _run(tmp_path)
    skipped = smoke.run_s149_evidence_admission({})

    assert smoke.summary_line(skipped) == "s149_evidence_admission=skipped"
    assert smoke.summary_line(passing) == (
        "s149_evidence_admission=pass checks=14/14 evidence=3/3 "
        "backlog=5/5 s150=conditionally_ready next=1494"
    )
    assert smoke._mapping([]) == {}
    assert smoke._all_checks_pass({"checks": {}}) is False
    monkeypatch.setattr(smoke, "run_s149_evidence_admission", lambda **_kwargs: passing)
    assert smoke.main(["--execute", "--summary"]) == 0
    assert "s149_evidence_admission=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_s149_evidence_admission",
        lambda **_kwargs: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
