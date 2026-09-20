from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from nex_ag.cx_transition_handoff import (
    REQUIRED_CHECKPOINT_PATHS,
    REQUIRED_CONTRACT_PATHS,
    AgCxTransitionHandoffError,
    bind_ag_cx_transition_handoff,
    build_ag_cx_transition_handoff_candidate,
    verify_ag_cx_transition_handoff,
    verify_ag_cx_transition_handoff_attestation,
)


GENERATED_AT = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)


def _accepted_report(**updates: object) -> dict[str, object]:
    report: dict[str, object] = {
        "service_id": "nex-ag",
        "status": "ACCEPTED",
        "transition_status": "READY_FOR_CX",
        "acceptance_id": "a" * 64,
    }
    report.update(updates)
    return report


def test_handoff_is_deterministic_sealed_and_verifiable() -> None:
    first = build_ag_cx_transition_handoff_candidate(generated_at=GENERATED_AT)
    second = build_ag_cx_transition_handoff_candidate(generated_at=GENERATED_AT)

    assert first == second
    assert first["manifest_status"] == "SEALED"
    assert first["source_service"] == "nex-ag"
    assert first["target_service"] == "nex-cx"
    assert first["next_requirement"] == "S91"
    assert first["acceptance_policy_id"] == "ag-mvp-acceptance-v1"
    assert first["acceptance_binding_status"] == "PENDING"
    assert "acceptance_id" not in first
    assert len(first["assets"]) == len(REQUIRED_CONTRACT_PATHS) == 11
    assert len(first["checkpoints"]) == len(REQUIRED_CHECKPOINT_PATHS) == 4
    assert all(len(item["sha256"]) == 64 for item in first["assets"])
    assert verify_ag_cx_transition_handoff(first) == {
        "verification_schema_version": (
            "ag_cx_transition_handoff_verification.v1"
        ),
        "status": "VERIFIED",
        "failure_code": None,
    }
    serialized = str(first)
    assert "postgresql://" not in serialized
    assert "nuri1004" not in serialized
    assert "/home/" not in serialized


def test_verifier_rejects_invalid_package_hash_and_identity() -> None:
    package = build_ag_cx_transition_handoff_candidate(generated_at=GENERATED_AT)
    tampered = deepcopy(package)
    tampered["target_service"] = "nex-ae-api"
    invalid_identity = deepcopy(package)
    invalid_identity["target_service"] = "nex-ae-api"
    invalid_identity.pop("manifest_hash")
    rebuilt = build_ag_cx_transition_handoff_candidate(generated_at=GENERATED_AT)
    body = {key: value for key, value in invalid_identity.items()}
    from nex_ag import cx_transition_handoff as handoff

    invalid_identity["manifest_hash"] = handoff._sha256(
        handoff._canonical_json(body).encode("utf-8")
    )

    assert verify_ag_cx_transition_handoff(None)["failure_code"] == (
        "package_invalid"
    )
    assert verify_ag_cx_transition_handoff({})["failure_code"] == (
        "manifest_hash_invalid"
    )
    assert verify_ag_cx_transition_handoff(tampered)["failure_code"] == (
        "manifest_hash_mismatch"
    )
    assert verify_ag_cx_transition_handoff(invalid_identity)["failure_code"] == (
        "manifest_identity_invalid"
    )
    assert verify_ag_cx_transition_handoff(rebuilt)["status"] == "VERIFIED"


def test_accepted_report_binds_candidate_and_verifies_attestation() -> None:
    candidate = build_ag_cx_transition_handoff_candidate(
        generated_at=GENERATED_AT
    )
    report = _accepted_report()

    attestation = bind_ag_cx_transition_handoff(
        candidate,
        report,
        bound_at=GENERATED_AT,
    )

    assert attestation["attestation_status"] == "BOUND"
    assert attestation["manifest_hash"] == candidate["manifest_hash"]
    assert attestation["acceptance_id"] == report["acceptance_id"]
    assert len(attestation["attestation_hash"]) == 64
    assert verify_ag_cx_transition_handoff_attestation(
        attestation,
        candidate=candidate,
        acceptance_report=report,
    )["status"] == "VERIFIED"


def test_attestation_verifier_rejects_invalid_hash_and_binding() -> None:
    candidate = build_ag_cx_transition_handoff_candidate(
        generated_at=GENERATED_AT
    )
    report = _accepted_report()
    attestation = bind_ag_cx_transition_handoff(
        candidate,
        report,
        bound_at=GENERATED_AT,
    )
    tampered = deepcopy(attestation)
    tampered["acceptance_id"] = "b" * 64
    invalid_binding = deepcopy(attestation)
    invalid_binding["acceptance_id"] = "b" * 64
    invalid_binding.pop("attestation_hash")
    from nex_ag import cx_transition_handoff as handoff

    invalid_binding["attestation_hash"] = handoff._sha256(
        handoff._canonical_json(invalid_binding).encode("utf-8")
    )

    assert verify_ag_cx_transition_handoff_attestation(
        None, candidate=candidate, acceptance_report=report
    )["failure_code"] == "attestation_invalid"
    assert verify_ag_cx_transition_handoff_attestation(
        {}, candidate=candidate, acceptance_report=report
    )["failure_code"] == "attestation_hash_invalid"
    assert verify_ag_cx_transition_handoff_attestation(
        tampered, candidate=candidate, acceptance_report=report
    )["failure_code"] == "attestation_hash_mismatch"
    assert verify_ag_cx_transition_handoff_attestation(
        invalid_binding, candidate=candidate, acceptance_report=report
    )["failure_code"] == "attestation_binding_invalid"


def test_binding_rejects_invalid_candidate() -> None:
    with pytest.raises(AgCxTransitionHandoffError) as exc_info:
        bind_ag_cx_transition_handoff(
            {},
            _accepted_report(),
            bound_at=GENERATED_AT,
        )

    assert exc_info.value.error_code == "ag.cx_handoff.candidate_invalid"


@pytest.mark.parametrize(
    ("updates", "error_code"),
    [
        (
            {"service_id": "nex-cx"},
            "ag.cx_handoff.acceptance_service_invalid",
        ),
        ({"status": "BLOCKED"}, "ag.cx_handoff.acceptance_not_ready"),
        (
            {"transition_status": "BLOCKED"},
            "ag.cx_handoff.acceptance_not_ready",
        ),
        ({"acceptance_id": "short"}, "ag.cx_handoff.acceptance_id_invalid"),
        ({"acceptance_id": "z" * 64}, "ag.cx_handoff.acceptance_id_invalid"),
        ({"acceptance_id": None}, "ag.cx_handoff.acceptance_id_invalid"),
    ],
)
def test_handoff_rejects_invalid_acceptance(updates, error_code: str) -> None:
    candidate = build_ag_cx_transition_handoff_candidate(
        generated_at=GENERATED_AT
    )
    with pytest.raises(AgCxTransitionHandoffError) as exc_info:
        bind_ag_cx_transition_handoff(
            candidate,
            _accepted_report(**updates),
            bound_at=GENERATED_AT,
        )

    assert exc_info.value.error_code == error_code
    assert str(exc_info.value)


def test_handoff_rejects_naive_time_and_missing_assets(tmp_path) -> None:
    with pytest.raises(AgCxTransitionHandoffError) as naive:
        build_ag_cx_transition_handoff_candidate(
            generated_at=datetime(2026, 9, 20, 4, 0),
        )
    with pytest.raises(AgCxTransitionHandoffError) as missing:
        build_ag_cx_transition_handoff_candidate(
            generated_at=GENERATED_AT,
            root=tmp_path,
        )

    assert naive.value.error_code == (
        "ag.cx_handoff.generated_at_timezone_required"
    )
    assert missing.value.error_code == "ag.cx_handoff.required_asset_missing"
