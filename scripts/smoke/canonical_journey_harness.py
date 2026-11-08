from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def approval_scenario_matches(
    scenario: Mapping[str, Any], validation: str, status: str, gate_passed: bool
) -> bool:
    resume = _mapping(scenario.get("resume"))
    return (
        resume.get("approval_validation") == validation
        and resume.get("approval_status") == status
        and resume.get("approval_gate_passed") is gate_passed
        and resume.get("claim_consumed") is True
        and resume.get("checkpoint_consumed") is True
        and resume.get("runtime_job_state") == "DONE"
    )


def approval_resume_checks(
    *,
    release: Mapping[str, Any],
    lock: Mapping[str, Any],
    scenarios: Mapping[str, Any],
    expected_ae_database: str,
    expected_ae_role: str,
    expected_wc_database: str,
    expected_wc_role: str,
) -> dict[str, bool]:
    required_names = ("approve", "reject", "expiry")
    cases = tuple(_mapping(scenarios.get(name)) for name in required_names)
    release_digest = release.get("wheel_sha256")
    lock_digest = lock.get("wheel_sha256")
    return {
        "release_identity_exact": isinstance(release_digest, str)
        and bool(release_digest)
        and release_digest == lock_digest,
        "actual_ae_postgres": len(scenarios) == len(required_names)
        and all(
            case.get("database") == expected_ae_database
            and case.get("role") == expected_ae_role
            for case in cases
        ),
        "actual_wc_postgres": len(scenarios) == len(required_names)
        and all(
            case.get("wc_database") == expected_wc_database
            and case.get("wc_role") == expected_wc_role
            for case in cases
        ),
        "approve_resume_valid": approval_scenario_matches(
            cases[0], "VALID", "APPROVED", True
        ),
        "reject_resume_blocked": approval_scenario_matches(
            cases[1], "VALID", "REJECTED", False
        ),
        "expired_resume_blocked": approval_scenario_matches(
            cases[2], "EXPIRED", "EXPIRED", False
        ),
        "mismatch_rejected_before_job": all(
            _mapping(case.get("mismatch_event")).get("inbox_state") == "REJECTED"
            and _mapping(case.get("mismatch_event")).get("resume_runtime_job_id")
            is None
            for case in cases
        ),
        "exact_resume_lineage": all(
            case.get("lineage_exact") is True for case in cases
        ),
        "zero_eos_mutation": all(
            _mapping(case.get("resume")).get("write_execution") == "not_started"
            and _mapping(case.get("resume")).get("eos_mutation_count") == 0
            and _mapping(case.get("prefix_audit")).get("write_requested_count") == 0
            for case in cases
        ),
        "cleanup_complete": all(case.get("cleanup_remaining") == 0 for case in cases),
    }


def finalize_cleanup_evidence(
    evidence: Mapping[str, Any],
    *,
    cleanup: Mapping[str, int],
    oa_residue_count: int,
    storage_residue_count: int,
    failure_code: str,
) -> dict[str, Any]:
    result = dict(evidence)
    checks = dict(_mapping(result.get("checks")))
    result["checks"] = checks
    result["cleanup"] = {
        **cleanup,
        "oa_residue_count": oa_residue_count,
        "storage_residue_count": storage_residue_count,
    }
    checks["cleanup_residue_free"] = all(
        value == 0 for value in result["cleanup"].values()
    )
    result["status"] = "PASS" if checks and all(checks.values()) else "FAIL"
    if result["status"] == "FAIL":
        result["failure_code"] = failure_code
    else:
        result.pop("failure_code", None)
    return result


def nvt_acceptance_checks(
    *, backend: Mapping[str, Any], browser: Mapping[str, Any]
) -> dict[str, bool]:
    projection = _mapping(backend.get("project_membership_batch_result"))
    source_smokes = _mapping(browser.get("source_smokes"))
    node = _mapping(source_smokes.get("node_playwright"))
    return {
        "actual_oa_ae_wc_eos_postgres": backend.get("actual_postgres") is True,
        "live_nvt_and_membership_intent": backend.get("live_generation_stages")
        == ["INTENT", "INTENT"],
        "nvt_crud_verified": backend.get("nvt_crud_verified") is True,
        "oa_batch_resolution_verified": backend.get("oa_batch_resolution_verified")
        is True,
        "wc_approval_verified": backend.get("wc_approval_verified") is True,
        "eos_exact_replay_verified": backend.get("eos_exact_replay_verified") is True,
        "partial_result_projected": projection.get("overall_status")
        == "PARTIALLY_APPLIED",
        "authenticated_playwright": browser.get("status") == "PASS",
        "playwright_batch_surface": node.get("status") == "PASS",
        "backend_zero_residue": backend.get("residue_count") == 0,
    }


def strict_gate_exit_code(evidence: Mapping[str, Any]) -> int:
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


def fail_only_exit_code(evidence: Mapping[str, Any]) -> int:
    return 1 if evidence.get("status") == "FAIL" else 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
