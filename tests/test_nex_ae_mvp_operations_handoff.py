from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nex_ae_api.mvp_acceptance_evaluation import evaluate_ae_mvp_acceptance
from nex_ae_api.mvp_operations_handoff import (
    AE_MVP_ACCEPTANCE_POLICY_ID,
    AeMvpOperationsHandoffError,
    REQUIRED_ASSET_PATHS,
    bind_ae_mvp_operations_handoff,
    build_ae_mvp_operations_handoff_candidate,
    verify_ae_mvp_operations_handoff,
    verify_ae_mvp_operations_handoff_attestation,
)
from test_nex_ae_mvp_acceptance_evaluation import passing_evidence


NOW = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)


def _accepted_report() -> dict:
    return evaluate_ae_mvp_acceptance(passing_evidence(), now=NOW)


def test_candidate_is_sealed_deterministic_and_privacy_safe() -> None:
    first = build_ae_mvp_operations_handoff_candidate(generated_at=NOW)
    second = build_ae_mvp_operations_handoff_candidate(generated_at=NOW)

    assert first == second
    assert verify_ae_mvp_operations_handoff(first)["status"] == "VERIFIED"
    assert first["target_service"] == "nex-ag"
    assert first["acceptance_policy_id"] == AE_MVP_ACCEPTANCE_POLICY_ID
    assert first["manifest_status"] == "SEALED"
    assert len(first["assets"]) == len(REQUIRED_ASSET_PATHS)
    assert first["read_model"]["ag_direct_ae_database_access_allowed"] is False
    assert all(first["privacy"].values()) is False
    serialized = str(first)
    assert "postgresql://" not in serialized
    assert "/home/" not in serialized


def test_candidate_requires_all_assets_and_timezone(tmp_path: Path) -> None:
    with pytest.raises(AeMvpOperationsHandoffError) as missing:
        build_ae_mvp_operations_handoff_candidate(generated_at=NOW, root=tmp_path)
    assert missing.value.error_code == "ae.operations_handoff.required_asset_missing"
    assert "Required operations handoff asset" in str(missing.value)

    with pytest.raises(AeMvpOperationsHandoffError) as naive:
        build_ae_mvp_operations_handoff_candidate(
            generated_at=datetime(2026, 9, 29, 6, 0)
        )
    assert naive.value.error_code == "ae.operations_handoff.timezone_required"


@pytest.mark.parametrize(
    ("package", "failure_code"),
    [
        (None, "package_invalid"),
        ({}, "manifest_hash_invalid"),
        ({"manifest_hash": "z" * 64}, "manifest_hash_invalid"),
    ],
)
def test_candidate_verification_rejects_invalid_shape(package, failure_code: str) -> None:
    result = verify_ae_mvp_operations_handoff(package)
    assert result["status"] == "INVALID"
    assert result["failure_code"] == failure_code


def test_candidate_verification_rejects_hash_and_identity_tampering() -> None:
    candidate = build_ae_mvp_operations_handoff_candidate(generated_at=NOW)
    hash_tampered = deepcopy(candidate)
    hash_tampered["target_service"] = "nex-cx"
    assert verify_ae_mvp_operations_handoff(hash_tampered)["failure_code"] == (
        "manifest_hash_mismatch"
    )

    identity_tampered = deepcopy(candidate)
    identity_tampered["target_service"] = "nex-cx"
    body = {key: value for key, value in identity_tampered.items() if key != "manifest_hash"}
    from nex_ae_api.mvp_operations_handoff import _canonical_json, _sha256

    identity_tampered["manifest_hash"] = _sha256(_canonical_json(body).encode())
    assert verify_ae_mvp_operations_handoff(identity_tampered)["failure_code"] == (
        "manifest_identity_invalid"
    )


def test_acceptance_binds_candidate_and_attestation_verifies() -> None:
    candidate = build_ae_mvp_operations_handoff_candidate(generated_at=NOW)
    report = _accepted_report()
    attestation = bind_ae_mvp_operations_handoff(
        candidate, report, bound_at=NOW
    )

    assert attestation["attestation_status"] == "BOUND"
    assert attestation["operations_status"] == "READY_FOR_OPERATIONS"
    assert attestation["raw_evidence_included"] is False
    assert verify_ae_mvp_operations_handoff_attestation(
        attestation, candidate=candidate, acceptance_report=report
    )["status"] == "VERIFIED"


def test_binding_rejects_invalid_candidate_and_report() -> None:
    candidate = build_ae_mvp_operations_handoff_candidate(generated_at=NOW)
    report = _accepted_report()

    with pytest.raises(AeMvpOperationsHandoffError) as invalid_candidate:
        bind_ae_mvp_operations_handoff(
            {**candidate, "manifest_hash": "a" * 64}, report, bound_at=NOW
        )
    assert invalid_candidate.value.error_code == "ae.operations_handoff.candidate_invalid"

    for updates, code in (
        ({"service_id": "nex-cx"}, "acceptance_service_invalid"),
        ({"status": "BLOCKED"}, "acceptance_not_ready"),
        ({"acceptance_id": "bad"}, "acceptance_id_invalid"),
    ):
        invalid_report = {**report, **updates}
        with pytest.raises(AeMvpOperationsHandoffError) as exc_info:
            bind_ae_mvp_operations_handoff(
                candidate, invalid_report, bound_at=NOW
            )
        assert exc_info.value.error_code.endswith(code)

    with pytest.raises(AeMvpOperationsHandoffError) as naive:
        bind_ae_mvp_operations_handoff(
            candidate, report, bound_at=datetime(2026, 9, 29, 6, 0)
        )
    assert naive.value.error_code == "ae.operations_handoff.timezone_required"


@pytest.mark.parametrize(
    ("attestation", "failure_code"),
    [
        (None, "attestation_invalid"),
        ({}, "attestation_hash_invalid"),
        ({"attestation_hash": "z" * 64}, "attestation_hash_invalid"),
    ],
)
def test_attestation_verification_rejects_invalid_shape(
    attestation, failure_code: str
) -> None:
    candidate = build_ae_mvp_operations_handoff_candidate(generated_at=NOW)
    report = _accepted_report()
    result = verify_ae_mvp_operations_handoff_attestation(
        attestation, candidate=candidate, acceptance_report=report
    )
    assert result["failure_code"] == failure_code


def test_attestation_verification_rejects_hash_and_binding_tampering() -> None:
    from nex_ae_api.mvp_operations_handoff import _canonical_json, _sha256

    candidate = build_ae_mvp_operations_handoff_candidate(generated_at=NOW)
    report = _accepted_report()
    attestation = bind_ae_mvp_operations_handoff(candidate, report, bound_at=NOW)

    hash_tampered = {**attestation, "operations_status": "BLOCKED"}
    assert verify_ae_mvp_operations_handoff_attestation(
        hash_tampered, candidate=candidate, acceptance_report=report
    )["failure_code"] == "attestation_hash_mismatch"

    binding_tampered = {**attestation, "operations_status": "BLOCKED"}
    body = {
        key: value for key, value in binding_tampered.items() if key != "attestation_hash"
    }
    binding_tampered["attestation_hash"] = _sha256(_canonical_json(body).encode())
    assert verify_ae_mvp_operations_handoff_attestation(
        binding_tampered, candidate=candidate, acceptance_report=report
    )["failure_code"] == "attestation_binding_invalid"
