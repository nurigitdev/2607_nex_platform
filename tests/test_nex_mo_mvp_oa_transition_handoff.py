from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nex_mo.mvp_acceptance_evaluation import evaluate_mo_mvp_acceptance
from nex_mo.mvp_oa_transition_handoff import (
    MO_MVP_ACCEPTANCE_POLICY_ID,
    PRIVACY_FLAGS,
    REQUIRED_ASSET_PATHS,
    MoMvpOaTransitionHandoffError,
    _canonical_json,
    _sha256,
    bind_mo_mvp_oa_transition_handoff,
    build_mo_mvp_oa_transition_candidate,
    verify_mo_mvp_oa_transition_attestation,
    verify_mo_mvp_oa_transition_handoff,
)
from run_mo_mvp_acceptance_evaluator import build_passing_evidence


NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _accepted_report() -> dict:
    return evaluate_mo_mvp_acceptance(build_passing_evidence(), now=NOW)


def _rehash(document: dict, hash_field: str) -> None:
    body = {key: value for key, value in document.items() if key != hash_field}
    document[hash_field] = _sha256(_canonical_json(body).encode())


def test_candidate_is_sealed_deterministic_and_privacy_safe() -> None:
    first = build_mo_mvp_oa_transition_candidate(generated_at=NOW)
    second = build_mo_mvp_oa_transition_candidate(generated_at=NOW)

    assert first == second
    assert verify_mo_mvp_oa_transition_handoff(first)["status"] == "VERIFIED"
    assert first["target_service"] == "nex-oa"
    assert first["acceptance_policy_id"] == MO_MVP_ACCEPTANCE_POLICY_ID
    assert first["manifest_status"] == "SEALED"
    assert first["privacy"] == PRIVACY_FLAGS
    assert len(first["assets"]) == len(REQUIRED_ASSET_PATHS)
    assert first["read_model"]["oa_direct_mo_database_access_allowed"] is False
    assert first["oa_entrypoint"] == {
        "requirement": "S121",
        "capability": "oa_current_state_reaudit_and_refactoring_checkpoint",
    }
    assert first["model_aliases"] == {
        "embedding": "Qwen3-Embedding-4B",
        "reranking": "Qwen3-Reranker-4B",
        "generation": "Qwen3.5-4B",
    }
    serialized = str(first)
    assert "postgresql://" not in serialized
    assert "http://" not in serialized
    assert "/home/" not in serialized


def test_candidate_requires_all_assets_and_timezone(tmp_path: Path) -> None:
    with pytest.raises(MoMvpOaTransitionHandoffError) as missing:
        build_mo_mvp_oa_transition_candidate(generated_at=NOW, root=tmp_path)
    assert missing.value.error_code.endswith("required_asset_missing")
    assert "Required OA transition asset" in str(missing.value)

    with pytest.raises(MoMvpOaTransitionHandoffError) as naive:
        build_mo_mvp_oa_transition_candidate(
            generated_at=datetime(2026, 10, 1, 9, 0)
        )
    assert naive.value.error_code.endswith("timezone_required")


@pytest.mark.parametrize(
    ("package", "failure_code"),
    [
        (None, "package_invalid"),
        ({}, "manifest_hash_invalid"),
        ({"manifest_hash": "a" * 63}, "manifest_hash_invalid"),
        ({"manifest_hash": "z" * 64}, "manifest_hash_invalid"),
    ],
)
def test_candidate_verification_rejects_invalid_shape(
    package, failure_code: str
) -> None:
    assert verify_mo_mvp_oa_transition_handoff(package)["failure_code"] == failure_code


def test_candidate_verification_rejects_hash_tampering() -> None:
    candidate = build_mo_mvp_oa_transition_candidate(generated_at=NOW)
    candidate["target_service"] = "nex-cx"

    assert verify_mo_mvp_oa_transition_handoff(candidate)["failure_code"] == (
        "manifest_hash_mismatch"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("handoff_schema_version", "bad"),
        ("source_service", "nex-cx"),
        ("target_service", "nex-ag"),
        ("manifest_status", "OPEN"),
        ("acceptance_policy_id", "bad"),
        ("acceptance_binding_status", "BOUND"),
        ("read_model", "bad"),
        ("privacy", {}),
    ],
)
def test_candidate_verification_rejects_identity_tampering(
    field: str,
    value,
) -> None:
    candidate = build_mo_mvp_oa_transition_candidate(generated_at=NOW)
    candidate[field] = value
    _rehash(candidate, "manifest_hash")

    assert verify_mo_mvp_oa_transition_handoff(candidate)["failure_code"] == (
        "manifest_identity_invalid"
    )


def test_candidate_rejects_direct_database_access_after_rehash() -> None:
    candidate = build_mo_mvp_oa_transition_candidate(generated_at=NOW)
    candidate["read_model"]["oa_direct_mo_database_access_allowed"] = True
    _rehash(candidate, "manifest_hash")

    assert verify_mo_mvp_oa_transition_handoff(candidate)["failure_code"] == (
        "manifest_identity_invalid"
    )


def test_acceptance_binds_candidate_and_attestation_verifies() -> None:
    candidate = build_mo_mvp_oa_transition_candidate(generated_at=NOW)
    report = _accepted_report()
    attestation = bind_mo_mvp_oa_transition_handoff(
        candidate,
        report,
        bound_at=NOW,
    )

    assert attestation["attestation_status"] == "BOUND"
    assert attestation["transition_status"] == "READY_FOR_OA"
    assert attestation["raw_evidence_included"] is False
    assert verify_mo_mvp_oa_transition_attestation(
        attestation,
        candidate=candidate,
        acceptance_report=report,
    )["status"] == "VERIFIED"


def test_binding_rejects_invalid_candidate() -> None:
    candidate = build_mo_mvp_oa_transition_candidate(generated_at=NOW)
    candidate["manifest_hash"] = "a" * 64

    with pytest.raises(MoMvpOaTransitionHandoffError) as exc_info:
        bind_mo_mvp_oa_transition_handoff(
            candidate,
            _accepted_report(),
            bound_at=NOW,
        )
    assert exc_info.value.error_code.endswith("candidate_invalid")


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"service_id": "nex-cx"}, "acceptance_service_invalid"),
        ({"status": "BLOCKED"}, "acceptance_not_ready"),
        ({"transition_status": "BLOCKED"}, "acceptance_not_ready"),
        ({"transition_target": "nex-ag"}, "acceptance_not_ready"),
        ({"acceptance_id": "bad"}, "acceptance_id_invalid"),
    ],
)
def test_binding_rejects_invalid_acceptance_report(
    updates: dict,
    code: str,
) -> None:
    report = {**_accepted_report(), **updates}

    with pytest.raises(MoMvpOaTransitionHandoffError) as exc_info:
        bind_mo_mvp_oa_transition_handoff(
            build_mo_mvp_oa_transition_candidate(generated_at=NOW),
            report,
            bound_at=NOW,
        )
    assert exc_info.value.error_code.endswith(code)


def test_binding_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(MoMvpOaTransitionHandoffError) as exc_info:
        bind_mo_mvp_oa_transition_handoff(
            build_mo_mvp_oa_transition_candidate(generated_at=NOW),
            _accepted_report(),
            bound_at=datetime(2026, 10, 1, 9, 0),
        )
    assert exc_info.value.error_code.endswith("timezone_required")


@pytest.mark.parametrize(
    ("attestation", "failure_code"),
    [
        (None, "attestation_invalid"),
        ({}, "attestation_hash_invalid"),
        ({"attestation_hash": "z" * 64}, "attestation_hash_invalid"),
    ],
)
def test_attestation_verification_rejects_invalid_shape(
    attestation,
    failure_code: str,
) -> None:
    result = verify_mo_mvp_oa_transition_attestation(
        attestation,
        candidate=build_mo_mvp_oa_transition_candidate(generated_at=NOW),
        acceptance_report=_accepted_report(),
    )
    assert result["failure_code"] == failure_code


def test_attestation_verification_rejects_hash_tampering() -> None:
    candidate = build_mo_mvp_oa_transition_candidate(generated_at=NOW)
    report = _accepted_report()
    attestation = bind_mo_mvp_oa_transition_handoff(candidate, report, bound_at=NOW)
    attestation["transition_status"] = "BLOCKED"

    assert verify_mo_mvp_oa_transition_attestation(
        attestation,
        candidate=candidate,
        acceptance_report=report,
    )["failure_code"] == "attestation_hash_mismatch"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attestation_schema_version", "bad"),
        ("attestation_status", "OPEN"),
        ("source_service", "nex-cx"),
        ("target_service", "nex-ag"),
        ("manifest_hash", "c" * 64),
        ("acceptance_id", "d" * 64),
        ("transition_status", "BLOCKED"),
        ("raw_evidence_included", True),
    ],
)
def test_attestation_verification_rejects_binding_tampering(
    field: str,
    value,
) -> None:
    candidate = build_mo_mvp_oa_transition_candidate(generated_at=NOW)
    report = _accepted_report()
    attestation = bind_mo_mvp_oa_transition_handoff(candidate, report, bound_at=NOW)
    attestation[field] = value
    _rehash(attestation, "attestation_hash")

    assert verify_mo_mvp_oa_transition_attestation(
        attestation,
        candidate=candidate,
        acceptance_report=report,
    )["failure_code"] == "attestation_binding_invalid"
