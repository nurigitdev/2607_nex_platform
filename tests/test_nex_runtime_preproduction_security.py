from __future__ import annotations

from dataclasses import replace

import pytest

from nex_runtime.preproduction_security import (
    REQUIRED_PROBES,
    SecurityAcceptanceError,
    SecurityProbeResult,
    build_passing_security_probe_results,
    evaluate_security_privacy_acceptance,
)


def _metadata():
    return {
        "release_candidate_id": "rc:s149:test",
        "configuration_digest": "a" * 64,
        "counts": [12, 0],
    }


def test_exact_security_and_privacy_matrix_passes() -> None:
    result = evaluate_security_privacy_acceptance(
        build_passing_security_probe_results(),
        evidence_metadata=_metadata(),
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "required_probe_count": 12,
        "observed_probe_count": 12,
        "matched_probe_count": 12,
        "denial_probe_count": 10,
        "privacy_probe_count": 2,
        "isolation_violation_count": 0,
        "privacy_violation_count": 0,
    }
    assert result["privacy_violation_paths"] == []


def test_decision_mismatch_is_reported_without_input_payload() -> None:
    rows = list(build_passing_security_probe_results())
    rows[0] = replace(rows[0], observed_decision="ALLOW", isolation_violation_count=1)
    result = evaluate_security_privacy_acceptance(
        rows,
        evidence_metadata={"prompt_content": "never-export-this"},
    )

    assert result["status"] == "FAIL"
    assert result["mismatched_probe_ids"] == ["security:cross-tenant-read"]
    assert result["privacy_violation_paths"] == ["$.prompt_content"]
    assert "never-export-this" not in str(result)
    assert result["checks"]["zero_isolation_violations"] is False


def test_each_required_probe_decision_is_blocking() -> None:
    for index, spec in enumerate(REQUIRED_PROBES):
        rows = list(build_passing_security_probe_results())
        opposite = "ALLOW" if spec.expected_decision == "DENY" else "FAIL"
        rows[index] = replace(rows[index], observed_decision=opposite)

        result = evaluate_security_privacy_acceptance(rows, evidence_metadata=_metadata())

        assert result["status"] == "FAIL"
        assert spec.probe_id in result["mismatched_probe_ids"]


def test_inventory_and_metadata_fail_closed() -> None:
    rows = list(build_passing_security_probe_results())
    with pytest.raises(SecurityAcceptanceError):
        evaluate_security_privacy_acceptance([], evidence_metadata=_metadata())
    with pytest.raises(SecurityAcceptanceError):
        evaluate_security_privacy_acceptance(rows[:-1], evidence_metadata=_metadata())
    rows[-1] = rows[0]
    with pytest.raises(SecurityAcceptanceError):
        evaluate_security_privacy_acceptance(rows, evidence_metadata=_metadata())
    with pytest.raises(SecurityAcceptanceError):
        evaluate_security_privacy_acceptance(
            build_passing_security_probe_results(), evidence_metadata="bad"
        )


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-result",
        SecurityProbeResult("bad id", "tenant_isolation", "DENY", "denied"),
        SecurityProbeResult("security:test", "bad id", "DENY", "denied"),
        SecurityProbeResult("security:test", "tenant_isolation", "MAYBE", "denied"),
        SecurityProbeResult("security:test", "tenant_isolation", "DENY", "BAD CODE"),
        SecurityProbeResult("security:test", "tenant_isolation", "DENY", "denied", True),
    ],
)
def test_malformed_probe_result_is_rejected(bad) -> None:
    rows = list(build_passing_security_probe_results())
    rows[0] = bad
    with pytest.raises(SecurityAcceptanceError):
        evaluate_security_privacy_acceptance(rows, evidence_metadata=_metadata())


def test_nested_privacy_paths_are_detected() -> None:
    result = evaluate_security_privacy_acceptance(
        build_passing_security_probe_results(),
        evidence_metadata={"items": [{"vector_value": [1.0]}]},
    )

    assert result["status"] == "FAIL"
    assert result["privacy_violation_paths"] == ["$.items[0].vector_value"]

