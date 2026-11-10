from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from mybee_ax.domain.coa_approval import (
    CoaApprovalAdmissionError,
    text_file_sha256_hash_ref,
    validate_product_accounting_admission,
)
from mybee_ax.domain.coa_candidate import load_json_object

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "domains/mybee/config/account_catalog"
CANDIDATE_PATH = (
    ROOT
    / "docs/transition/MyBee_Phase1/NeX_MyBee_COA_Codebook_Candidate_v0.1.json"
)
IDENTITY_PATH = CONFIG / "unified_codebook_candidate.identity.v1.json"
APPROVAL_PATH = CONFIG / "product_accounting_approval.v1.json"
SOURCE_PATH = CONFIG / "approved_standard_chart.v1.json"
SEED_PATH = CONFIG / "approved_seed_manifest.json"


@pytest.mark.parametrize(
    ("document", "schema"),
    (
        (APPROVAL_PATH, CONFIG / "product_accounting_approval.schema.json"),
        (SOURCE_PATH, CONFIG / "approved_standard_chart.schema.json"),
        (SEED_PATH, CONFIG / "approved_seed_manifest.schema.json"),
    ),
)
def test_coa_01a_artifacts_match_their_json_schemas(
    document: Path, schema: Path
) -> None:
    jsonschema.Draft202012Validator(load_json_object(schema)).validate(
        load_json_object(document)
    )


def _payloads() -> dict[str, dict[str, Any]]:
    return {
        "candidate": dict(load_json_object(CANDIDATE_PATH)),
        "candidate_identity": dict(load_json_object(IDENTITY_PATH)),
        "approval": dict(load_json_object(APPROVAL_PATH)),
        "approved_source": dict(load_json_object(SOURCE_PATH)),
        "seed_manifest": dict(load_json_object(SEED_PATH)),
    }


def _validate(payloads: dict[str, dict[str, Any]]):
    return validate_product_accounting_admission(
        candidate=payloads["candidate"],
        candidate_file_hash=text_file_sha256_hash_ref(CANDIDATE_PATH),
        candidate_identity=payloads["candidate_identity"],
        approval=payloads["approval"],
        approved_source=payloads["approved_source"],
        seed_manifest=payloads["seed_manifest"],
    )


def test_coa_01a_admits_the_exact_approved_source_without_publication() -> None:
    admission = _validate(_payloads())

    assert admission.approval_id == "COA-01A-2026-11-10-001"
    assert admission.approved_on == "2026-11-10"
    assert admission.approver_principal_ref == "CODEX_SESSION_USER"
    assert admission.approval_proof_hash == (
        "sha256:f16c845b752b8c6a810bc1c75f069c211030e3530996e87bb11f08fb99541d6e"
    )
    assert admission.approved_source_hash == (
        "sha256:7782f96ea7445c6b0c9d82bc4d3c431175e4f32c22a968c1430aea55f736e61c"
    )
    assert admission.candidate_report.total_nodes == 166
    assert admission.runtime_seed_allowed is True
    assert admission.automatic_publication_allowed is False
    assert admission.published is False
    assert admission.company_adoption_allowed is False


def test_coa_01a_approval_is_self_attested_and_does_not_claim_a_signature() -> None:
    approval = _payloads()["approval"]

    assert approval["approver"] == {
        "principal_ref": "CODEX_SESSION_USER",
        "asserted_role": "PRODUCT_ACCOUNTING_OWNER",
        "identity_assurance": "SELF_ATTESTED_BY_EXPLICIT_USER_INSTRUCTION",
        "approval_channel": "CODEX_CONVERSATION",
        "signature_status": "NOT_CRYPTOGRAPHICALLY_SIGNED",
    }
    assert approval["terminology_classification"] == (
        "INTERNAL_MYBEE_PRODUCT_CODE_NOT_OFFICIAL_KIFRS_OR_DART_ID"
    )
    assert "DOES_NOT_PUBLISH_EOS_RELEASE" in approval["limitations"]
    assert "OA_AUTHORIZED_PUBLICATION_REMAINS_REQUIRED" in approval["limitations"]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("extra_approval_field", "APPROVAL_FIELDS_INVALID"),
        ("approval_schema", "APPROVAL_SCHEMA_INVALID"),
        ("approval_decision", "APPROVAL_DECISION_INVALID"),
        ("blank_approval_id", "APPROVAL_ID_INVALID"),
        ("bad_date", "APPROVAL_DATE_INVALID"),
        ("approver_not_object", "APPROVER_INVALID"),
        ("extra_approver_field", "APPROVER_FIELDS_INVALID"),
        ("blank_principal", "APPROVER_INVALID"),
        ("wrong_role", "APPROVER_ROLE_INVALID"),
        ("wrong_assurance", "APPROVER_ASSURANCE_INVALID"),
        ("wrong_channel", "APPROVAL_CHANNEL_INVALID"),
        ("fake_signature", "APPROVAL_SIGNATURE_CLAIM_INVALID"),
        ("scope_drift", "APPROVED_SCOPE_MISMATCH"),
        ("terminology_drift", "TERMINOLOGY_CLASSIFICATION_INVALID"),
        ("limitations_drift", "APPROVAL_LIMITATIONS_INVALID"),
    ),
)
def test_coa_01a_approval_contract_drift_fails_closed(
    mutation: str, expected_code: str
) -> None:
    payloads = copy.deepcopy(_payloads())
    approval = payloads["approval"]
    approver = approval["approver"]
    if mutation == "extra_approval_field":
        approval["unexpected"] = True
    elif mutation == "approval_schema":
        approval["schema_version"] = "future"
    elif mutation == "approval_decision":
        approval["decision"] = "PUBLISH"
    elif mutation == "blank_approval_id":
        approval["approval_id"] = " "
    elif mutation == "bad_date":
        approval["approved_on"] = "today"
    elif mutation == "approver_not_object":
        approval["approver"] = []
    elif mutation == "extra_approver_field":
        approver["unexpected"] = True
    elif mutation == "blank_principal":
        approver["principal_ref"] = ""
    elif mutation == "wrong_role":
        approver["asserted_role"] = "CATALOG_PUBLISHER"
    elif mutation == "wrong_assurance":
        approver["identity_assurance"] = "UNKNOWN"
    elif mutation == "wrong_channel":
        approver["approval_channel"] = "UNRECORDED"
    elif mutation == "fake_signature":
        approver["signature_status"] = "SIGNED"
    elif mutation == "scope_drift":
        approval["approved_scope"]["total_nodes"] = 165
    elif mutation == "terminology_drift":
        approval["terminology_classification"] = "OFFICIAL_KIFRS_CODE"
    elif mutation == "limitations_drift":
        approval["limitations"] = []

    with pytest.raises(CoaApprovalAdmissionError) as raised:
        _validate(payloads)
    assert raised.value.code == expected_code


@pytest.mark.parametrize(
    ("section", "field", "value", "expected_code"),
    (
        ("approved_source", "published", True, "APPROVED_SOURCE_MISMATCH"),
        (
            "approved_source",
            "automatic_publication_allowed",
            True,
            "APPROVED_SOURCE_MISMATCH",
        ),
        (
            "approved_source",
            "approved_proof_hash",
            "sha256:" + "0" * 64,
            "APPROVED_SOURCE_MISMATCH",
        ),
        (
            "seed_manifest",
            "source_hash",
            "sha256:" + "0" * 64,
            "SEED_MANIFEST_MISMATCH",
        ),
        ("seed_manifest", "published", True, "SEED_MANIFEST_MISMATCH"),
        (
            "seed_manifest",
            "company_adoption_allowed",
            True,
            "SEED_MANIFEST_MISMATCH",
        ),
    ),
)
def test_coa_01a_source_and_seed_drift_fail_closed(
    section: str, field: str, value: object, expected_code: str
) -> None:
    payloads = copy.deepcopy(_payloads())
    payloads[section][field] = value

    with pytest.raises(CoaApprovalAdmissionError) as raised:
        _validate(payloads)
    assert raised.value.code == expected_code


def test_coa_01a_seed_manifest_rejects_unknown_fields() -> None:
    payloads = _payloads()
    payloads["seed_manifest"]["implicit_publish"] = True

    with pytest.raises(CoaApprovalAdmissionError) as raised:
        _validate(payloads)
    assert raised.value.code == "SEED_MANIFEST_FIELDS_INVALID"


def test_coa_01a_candidate_file_hash_drift_is_rejected() -> None:
    payloads = _payloads()

    with pytest.raises(CoaApprovalAdmissionError) as raised:
        validate_product_accounting_admission(
            candidate=payloads["candidate"],
            candidate_file_hash="sha256:" + "0" * 64,
            candidate_identity=payloads["candidate_identity"],
            approval=payloads["approval"],
            approved_source=payloads["approved_source"],
            seed_manifest=payloads["seed_manifest"],
        )
    assert raised.value.code == "APPROVED_SCOPE_MISMATCH"


def test_coa_01a_text_file_hash_reports_missing_source(tmp_path: Path) -> None:
    with pytest.raises(CoaApprovalAdmissionError) as raised:
        text_file_sha256_hash_ref(tmp_path / "missing.json")
    assert raised.value.code == "APPROVED_SOURCE_UNREADABLE"
