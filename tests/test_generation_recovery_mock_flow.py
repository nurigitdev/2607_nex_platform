from __future__ import annotations

import json

import pytest

import run_generation_recovery_mock_flow as recovery_smoke


def test_run_generation_recovery_mock_flow_links_failure_recovery_and_audit() -> None:
    evidence = recovery_smoke.run_generation_recovery_mock_flow()

    assert all(evidence["assertions"].values())
    assert evidence["cx_problem"]["error_code"] == "mo.provider_timeout"
    assert evidence["cx"]["status"] == "FAILED"
    assert evidence["cx"]["failure"]["recovery_policy_id"] == (
        "recovery-mo-provider-timeout-retry-v1"
    )
    assert evidence["ae_recovery"]["requested_action"] == "retry"
    assert evidence["ae_recovery"]["dispatch"]["attempt_no"] == 2
    assert evidence["ag"]["recovery_request_summary"]["requested_action"] == "retry"
    assert evidence["ag"]["audit_event"]["details"]["policy_hash_status"] == "MATCHED"


def test_assert_recovery_evidence_reports_mismatch() -> None:
    evidence = recovery_smoke.run_generation_recovery_mock_flow()
    evidence["ae_recovery"]["requested_action"] = "cancel"

    with pytest.raises(AssertionError):
        recovery_smoke.assert_recovery_evidence(evidence)


def test_recovery_main_prints_summary(capsys) -> None:
    assert recovery_smoke.main(["--summary"]) == 0

    output = capsys.readouterr().out
    assert "generation_recovery_mock_flow=pass" in output
    assert "action=retry" in output


def test_recovery_main_writes_evidence_file(tmp_path) -> None:
    output = tmp_path / "recovery-smoke.json"

    assert recovery_smoke.main(["--output", str(output)]) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["trace_id"] == recovery_smoke.TRACE_ID
    assert evidence["assertions"]["ag_recovery_lineage"] is True
