"""Admission checks for an explicitly approved MyBee COA source dataset."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nex_runtime.semantic_hashes import (
    hash_ref_from_sha256,
    semantic_sha256_hash_ref,
    sha256_text,
)

from .coa_candidate import (
    CoaCandidateValidationReport,
    verify_coa_candidate_identity,
)

APPROVAL_SCHEMA_VERSION = "nex.mybee.coa.product-accounting-approval.v1"
APPROVED_SOURCE_SCHEMA_VERSION = "nex.mybee.coa.approved-standard-chart.v1"
SEED_MANIFEST_SCHEMA_VERSION = "nex.mybee.account-catalog-seed-manifest.v2"
ADMISSION_STATUS = "PRODUCT_ACCOUNTING_APPROVED_SOURCE_ADMITTED"
APPROVAL_DECISION = "APPROVED_EXACT_DATASET_FOR_SOURCE_ADMISSION"
APPROVAL_PROOF_PATH = (
    "domains/mybee/config/account_catalog/product_accounting_approval.v1.json"
)
APPROVED_SOURCE_PATH = (
    "domains/mybee/config/account_catalog/approved_standard_chart.v1.json"
)
CANDIDATE_PATH = (
    "docs/transition/MyBee_Phase1/NeX_MyBee_COA_Codebook_Candidate_v0.1.json"
)
TERMINOLOGY_CLASSIFICATION = (
    "INTERNAL_MYBEE_PRODUCT_CODE_NOT_OFFICIAL_KIFRS_OR_DART_ID"
)

_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_REVIEWED_ATTRIBUTES = (
    "account_code",
    "standard_account_key",
    "canonical_name_ko",
    "category",
    "normal_balance",
    "is_contra",
    "parent_account_code",
    "is_monetary_default",
    "is_postable_leaf_if_admitted",
    "reporting_mapping_status",
)
_LIMITATIONS = (
    "SOURCE_ADMISSION_ONLY",
    "DOES_NOT_PUBLISH_EOS_RELEASE",
    "DOES_NOT_AUTHORIZE_COMPANY_ADOPTION",
    "DOES_NOT_RESOLVE_REPORTING_TAXONOMY",
    "OA_AUTHORIZED_PUBLICATION_REMAINS_REQUIRED",
)
_RUNTIME_GATES = (
    "COA_02_PERSISTENCE",
    "COA_03_OA_AUTHORIZED_PUBLICATION",
    "COMPANY_ADOPTION_APPROVAL",
    "REPORTING_TAXONOMY_MAPPING_WHERE_REQUIRED",
)


class CoaApprovalAdmissionError(ValueError):
    """Raised when approval evidence or its admitted source binding drifts."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class CoaApprovalAdmission:
    approval_id: str
    approved_on: str
    approver_principal_ref: str
    approval_proof_hash: str
    approved_source_hash: str
    candidate_report: CoaCandidateValidationReport
    runtime_seed_allowed: bool = True
    automatic_publication_allowed: bool = False
    published: bool = False
    company_adoption_allowed: bool = False


def text_file_sha256_hash_ref(path: Path) -> str:
    """Hash a UTF-8 source file through the shared SHA-256 helpers."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CoaApprovalAdmissionError(
            "APPROVED_SOURCE_UNREADABLE", str(path)
        ) from error
    return hash_ref_from_sha256(sha256_text(text))


def validate_product_accounting_admission(
    *,
    candidate: Mapping[str, Any],
    candidate_file_hash: str,
    candidate_identity: Mapping[str, Any],
    approval: Mapping[str, Any],
    approved_source: Mapping[str, Any],
    seed_manifest: Mapping[str, Any],
) -> CoaApprovalAdmission:
    """Verify exact-data approval without treating it as EOS publication."""

    report = verify_coa_candidate_identity(candidate, candidate_identity)
    approval_id, approved_on, principal_ref = _validate_approval(
        approval=approval,
        report=report,
        candidate_file_hash=candidate_file_hash,
        candidate=candidate,
    )
    approval_hash = semantic_sha256_hash_ref(approval)
    _validate_approved_source(
        approved_source=approved_source,
        report=report,
        candidate_file_hash=candidate_file_hash,
        approval_hash=approval_hash,
        candidate=candidate,
    )
    source_hash = semantic_sha256_hash_ref(approved_source)
    _validate_seed_manifest(
        seed_manifest=seed_manifest,
        report=report,
        approval_hash=approval_hash,
        source_hash=source_hash,
        candidate=candidate,
    )
    return CoaApprovalAdmission(
        approval_id=approval_id,
        approved_on=approved_on,
        approver_principal_ref=principal_ref,
        approval_proof_hash=approval_hash,
        approved_source_hash=source_hash,
        candidate_report=report,
    )


def _validate_approval(
    *,
    approval: Mapping[str, Any],
    report: CoaCandidateValidationReport,
    candidate_file_hash: str,
    candidate: Mapping[str, Any],
) -> tuple[str, str, str]:
    _require_exact_keys(
        approval,
        {
            "schema_version",
            "approval_id",
            "decision",
            "approved_on",
            "approver",
            "approved_scope",
            "terminology_classification",
            "limitations",
        },
        "APPROVAL_FIELDS_INVALID",
    )
    _expect(
        approval,
        "schema_version",
        APPROVAL_SCHEMA_VERSION,
        "APPROVAL_SCHEMA_INVALID",
    )
    _expect(approval, "decision", APPROVAL_DECISION, "APPROVAL_DECISION_INVALID")
    approval_id = _required_text(approval, "approval_id", "APPROVAL_ID_INVALID")
    approved_on = _required_text(approval, "approved_on", "APPROVAL_DATE_INVALID")
    if _ISO_DATE.fullmatch(approved_on) is None:
        raise CoaApprovalAdmissionError("APPROVAL_DATE_INVALID", approved_on)

    approver = _object(approval, "approver", "APPROVER_INVALID")
    _require_exact_keys(
        approver,
        {
            "principal_ref",
            "asserted_role",
            "identity_assurance",
            "approval_channel",
            "signature_status",
        },
        "APPROVER_FIELDS_INVALID",
    )
    principal_ref = _required_text(approver, "principal_ref", "APPROVER_INVALID")
    _expect(
        approver,
        "asserted_role",
        "PRODUCT_ACCOUNTING_OWNER",
        "APPROVER_ROLE_INVALID",
    )
    _expect(
        approver,
        "identity_assurance",
        "SELF_ATTESTED_BY_EXPLICIT_USER_INSTRUCTION",
        "APPROVER_ASSURANCE_INVALID",
    )
    _expect(
        approver,
        "approval_channel",
        "CODEX_CONVERSATION",
        "APPROVAL_CHANNEL_INVALID",
    )
    _expect(
        approver,
        "signature_status",
        "NOT_CRYPTOGRAPHICALLY_SIGNED",
        "APPROVAL_SIGNATURE_CLAIM_INVALID",
    )

    scope = _object(approval, "approved_scope", "APPROVED_SCOPE_INVALID")
    expected_scope = _source_dataset_contract(
        report=report,
        candidate_file_hash=candidate_file_hash,
        candidate=candidate,
    )
    expected_scope["candidate_path"] = expected_scope.pop("path")
    expected_scope["candidate_file_sha256"] = expected_scope.pop("file_sha256")
    expected_scope["candidate_semantic_hash"] = expected_scope.pop("semantic_hash")
    expected_scope["reviewed_attributes"] = list(_REVIEWED_ATTRIBUTES)
    if scope != expected_scope:
        raise CoaApprovalAdmissionError(
            "APPROVED_SCOPE_MISMATCH", "approval is not bound to the exact dataset"
        )
    _expect(
        approval,
        "terminology_classification",
        TERMINOLOGY_CLASSIFICATION,
        "TERMINOLOGY_CLASSIFICATION_INVALID",
    )
    if approval.get("limitations") != list(_LIMITATIONS):
        raise CoaApprovalAdmissionError(
            "APPROVAL_LIMITATIONS_INVALID", "boundary drift"
        )
    return approval_id, approved_on, principal_ref


def _validate_approved_source(
    *,
    approved_source: Mapping[str, Any],
    report: CoaCandidateValidationReport,
    candidate_file_hash: str,
    approval_hash: str,
    candidate: Mapping[str, Any],
) -> None:
    expected = {
        "schema_version": APPROVED_SOURCE_SCHEMA_VERSION,
        "catalog_id": "mybee.finance.k-ifrs-adopted-chart",
        "catalog_profile": "MYBEE-KIFRS-NFI",
        "catalog_version": "MYBEE-KIFRS-NFI-v1.0",
        "status": ADMISSION_STATUS,
        "source_approved_on": "2026-11-10",
        "runtime_seed_allowed": True,
        "automatic_publication_allowed": False,
        "published": False,
        "company_adoption_allowed": False,
        "source_dataset": _source_dataset_contract(
            report=report,
            candidate_file_hash=candidate_file_hash,
            candidate=candidate,
        ),
        "approved_proof_ref": APPROVAL_PROOF_PATH,
        "approved_proof_hash": approval_hash,
        "terminology_classification": TERMINOLOGY_CLASSIFICATION,
        "next_gate": "COA_02_PERSISTENCE_AND_COA_03_OA_AUTHORIZED_PUBLICATION",
    }
    if approved_source != expected:
        raise CoaApprovalAdmissionError(
            "APPROVED_SOURCE_MISMATCH", "approved source contract drifted"
        )


def _validate_seed_manifest(
    *,
    seed_manifest: Mapping[str, Any],
    report: CoaCandidateValidationReport,
    approval_hash: str,
    source_hash: str,
    candidate: Mapping[str, Any],
) -> None:
    expected_fields = {
        "schema_version": SEED_MANIFEST_SCHEMA_VERSION,
        "catalog_id": "mybee.finance.k-ifrs-adopted-chart",
        "admission_status": ADMISSION_STATUS,
        "runtime_seed_allowed": True,
        "automatic_publication_allowed": False,
        "published": False,
        "company_adoption_allowed": False,
        "source_reference": APPROVED_SOURCE_PATH,
        "source_version": "MYBEE-KIFRS-NFI-v1.0",
        "source_hash": source_hash,
        "source_dataset_hash": report.candidate_semantic_hash,
        "identity_set_hash": report.identity_set_hash,
        "node_contract_hash": report.node_contract_hash,
        "approved_proof_ref": APPROVAL_PROOF_PATH,
        "approved_proof_hash": approval_hash,
        "accounts_source": {
            "path": CANDIDATE_PATH,
            "total_nodes": report.total_nodes,
            "leaf_accounts": _leaf_count(candidate),
        },
        "blocking_reason": None,
        "remaining_runtime_gates": list(_RUNTIME_GATES),
    }
    _require_exact_keys(
        seed_manifest,
        set(expected_fields) | {"decision_evidence"},
        "SEED_MANIFEST_FIELDS_INVALID",
    )
    for field, expected in expected_fields.items():
        if seed_manifest.get(field) != expected:
            raise CoaApprovalAdmissionError(
                "SEED_MANIFEST_MISMATCH",
                f"{field}: expected {expected!r}, got {seed_manifest.get(field)!r}",
            )


def _source_dataset_contract(
    *,
    report: CoaCandidateValidationReport,
    candidate_file_hash: str,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "path": CANDIDATE_PATH,
        "file_sha256": candidate_file_hash,
        "semantic_hash": report.candidate_semantic_hash,
        "identity_set_hash": report.identity_set_hash,
        "node_contract_hash": report.node_contract_hash,
        "total_nodes": report.total_nodes,
        "leaf_accounts": _leaf_count(candidate),
    }


def _leaf_count(candidate: Mapping[str, Any]) -> int:
    accounts = candidate.get("accounts")
    if not isinstance(accounts, list):
        return 0
    return sum(
        isinstance(account, dict) and account.get("hierarchy_level") == 4
        for account in accounts
    )


def _expect(
    value: Mapping[str, Any], field: str, expected: object, error_code: str
) -> None:
    if value.get(field) != expected:
        raise CoaApprovalAdmissionError(error_code, field)


def _required_text(value: Mapping[str, Any], field: str, error_code: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise CoaApprovalAdmissionError(error_code, field)
    return item


def _object(
    value: Mapping[str, Any], field: str, error_code: str
) -> Mapping[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise CoaApprovalAdmissionError(error_code, field)
    return item


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], error_code: str
) -> None:
    if set(value) != expected:
        raise CoaApprovalAdmissionError(error_code, "field set drift")
