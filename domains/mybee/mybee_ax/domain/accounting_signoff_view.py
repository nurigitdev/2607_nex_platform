"""Redacted MyBee projection for EOS accounting approval evidence."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_id",
        "case_id",
        "company_id",
        "candidate_id",
        "candidate_revision",
        "candidate_hash",
        "document_envelope_hash",
        "fx_rate_set_hash",
        "rule_release_hash",
        "accounting_period_id",
        "approver_subject_id",
        "approval_policy_hash",
        "wc_final_decision_id",
        "oa_authorization_revision_hash",
        "decided_at",
        "proof_hash",
        "observation_state",
    }
)


class AccountingSignoffViewError(ValueError):
    pass


def accounting_signoff_view(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise AccountingSignoffViewError("Accounting evidence fields drifted")
    evidence = dict(value)
    if (
        evidence["schema_version"] != "eos_accounting_approval_evidence.v2"
        or evidence["observation_state"] != "ACCOUNTING_APPROVED_PENDING_POST"
    ):
        raise AccountingSignoffViewError("Accounting evidence state is invalid")
    for field in (
        "evidence_id",
        "case_id",
        "company_id",
        "candidate_id",
        "accounting_period_id",
        "wc_final_decision_id",
    ):
        _uuid(field, evidence[field])
    revision = evidence["candidate_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise AccountingSignoffViewError("Candidate revision is invalid")
    for field in (
        "candidate_hash",
        "document_envelope_hash",
        "fx_rate_set_hash",
        "rule_release_hash",
        "approval_policy_hash",
        "oa_authorization_revision_hash",
        "proof_hash",
    ):
        if not isinstance(evidence[field], str) or not _HASH_REF.fullmatch(
            evidence[field]
        ):
            raise AccountingSignoffViewError(f"{field} is invalid")
    if (
        not isinstance(evidence["approver_subject_id"], str)
        or not evidence["approver_subject_id"]
    ):
        raise AccountingSignoffViewError("Approver subject is invalid")
    if not isinstance(evidence["decided_at"], str) or not evidence["decided_at"]:
        raise AccountingSignoffViewError("Decision timestamp is invalid")
    return MappingProxyType(
        {
            "schema_version": "mybee_accounting_signoff_view.v1",
            "state": evidence["observation_state"],
            "company_id": evidence["company_id"],
            "candidate_id": evidence["candidate_id"],
            "candidate_revision": revision,
            "approver_subject_id": evidence["approver_subject_id"],
            "decided_at": evidence["decided_at"],
            "proof_hash": evidence["proof_hash"],
        }
    )


def _uuid(field: str, value: object) -> None:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AccountingSignoffViewError(f"{field} is invalid") from exc


__all__ = ("AccountingSignoffViewError", "accounting_signoff_view")
