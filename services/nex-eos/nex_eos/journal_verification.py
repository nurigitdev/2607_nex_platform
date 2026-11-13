from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .journals import (
    JOURNAL_VERIFICATION_SCHEMA,
    JOURNAL_VERIFY_OPERATION,
    EosJournalError,
    SqlAlchemyEosJournalRepository,
    build_journal_hash,
    build_line_hash,
    wire_posted_journal,
)
from .project_authorization import (
    EosProjectAuthorizationError,
    EosProjectAuthorizationGate,
)

FINANCE_JOURNAL_READ_SCOPE = "finance:report:read"
_HASH_REF = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")


class EosJournalQueryService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyEosJournalRepository,
        authorization_source: AuthorizationSource,
        project_authorizer: EosProjectAuthorizationGate,
        clock=None,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source
        self._project_authorizer = project_authorizer
        self._clock = clock or (lambda: datetime.now(UTC))

    def get(
        self,
        *,
        tenant_id: str,
        company_id: str,
        journal_id: str,
        requester_subject_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        authorization = self._authorize_global(
            tenant_id=tenant_id,
            company_id=company_id,
            subject_id=requester,
        )
        journal = self._repository.get(
            tenant_id=tenant_id,
            company_id=company_id,
            journal_id=journal_id,
        )
        if journal is None:
            raise EosJournalError(
                "EOS_JOURNAL_NOT_FOUND",
                "PostedJournal was not found in tenant and company scope",
                status_code=404,
            )
        project_evidence = self._authorize_projects(
            journal,
            tenant_id=tenant_id,
            subject_id=requester,
            correlation_id=correlation_id,
        )
        return {
            **wire_posted_journal(journal),
            "authorization_revision_hash": authorization["revision_hash"],
            "project_authorization": project_evidence,
        }

    def verify(
        self,
        *,
        tenant_id: str,
        company_id: str,
        journal_id: str,
        requester_subject_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        projection = self.get(
            tenant_id=tenant_id,
            company_id=company_id,
            journal_id=journal_id,
            requester_subject_id=requester_subject_id,
            correlation_id=correlation_id,
        )
        header = projection["header"]
        lines = projection["lines"]
        acceptance = projection["accounting_acceptance"]
        failures: list[str] = []
        line_hashes: list[str] = []
        debit = Decimal(0)
        credit = Decimal(0)
        for line in lines:
            stored_hash = line["line_hash"]
            if stored_hash != build_line_hash(line):
                failures.append(f"LINE_HASH_MISMATCH:{line['line_no']}")
            line_hashes.append(stored_hash)
            debit += Decimal(str(line["debit_functional"]))
            credit += Decimal(str(line["credit_functional"]))
        if int(header["line_count"]) != len(lines):
            failures.append("LINE_COUNT_MISMATCH")
        if (
            Decimal(str(header["total_debit_functional"])) != debit
            or Decimal(str(header["total_credit_functional"])) != credit
            or debit != credit
        ):
            failures.append("FUNCTIONAL_BALANCE_MISMATCH")
        if header["journal_hash"] != build_journal_hash(
            header, line_hashes=line_hashes
        ):
            failures.append("JOURNAL_HASH_MISMATCH")
        if (
            acceptance["journal_id"] != header["journal_id"]
            or acceptance["candidate_id"] != header["candidate_id"]
            or acceptance["candidate_revision"] != header["candidate_revision"]
            or acceptance["candidate_hash"] != header["candidate_hash"]
            or acceptance["purpose"] != "ACCOUNTING_POSTING"
        ):
            failures.append("ACCOUNTING_ACCEPTANCE_MISMATCH")
        if failures:
            raise EosJournalError(
                "EOS_JOURNAL_VERIFICATION_FAILED",
                "PostedJournal immutable verification failed: " + ",".join(failures),
                status_code=503,
            )
        verified_at = _aware_datetime(self._clock())
        semantics = {
            "schema_version": JOURNAL_VERIFICATION_SCHEMA,
            "journal_id": header["journal_id"],
            "journal_hash": header["journal_hash"],
            "accounting_acceptance_hash": acceptance["acceptance_hash"],
            "line_hashes": line_hashes,
            "line_count": len(lines),
            "total_debit_functional": format(debit, "f"),
            "total_credit_functional": format(credit, "f"),
            "verified_at": verified_at.isoformat().replace("+00:00", "Z"),
        }
        return {
            **semantics,
            "operation_id": JOURNAL_VERIFY_OPERATION,
            "verification_status": "VERIFIED",
            "verification_hash": semantic_sha256_hash_ref(semantics),
            "authorization_revision_hash": projection["authorization_revision_hash"],
            "project_authorization": projection["project_authorization"],
        }

    def _authorize_global(
        self, *, tenant_id: str, company_id: str, subject_id: str
    ) -> dict[str, str]:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied("OA denied Journal read authority") from exc
        except Exception as exc:
            raise _unavailable("OA Journal authorization is unavailable") from exc
        if not isinstance(value, Mapping):
            raise _denied("OA Journal authorization is malformed")
        scopes = value.get("scopes")
        company_ids = value.get("company_ids")
        revision = value.get("revision_hash")
        if (
            value.get("active") is not True
            or value.get("tenant_id") != tenant_id
            or value.get("subject_id") != subject_id
            or not isinstance(scopes, (list, tuple, set, frozenset))
            or FINANCE_JOURNAL_READ_SCOPE not in scopes
            or (
                company_ids is not None
                and (
                    not isinstance(company_ids, (list, tuple, set, frozenset))
                    or company_id not in company_ids
                )
            )
            or not isinstance(revision, str)
            or _HASH_REF.fullmatch(revision) is None
        ):
            raise _denied("Current OA finance report authority is required")
        return {
            "revision_hash": (
                revision if revision.startswith("sha256:") else f"sha256:{revision}"
            )
        }

    def _authorize_projects(
        self,
        journal: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str,
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        project_pairs = sorted(
            {
                (str(line["project_id"]), str(line["project_code"]))
                for line in journal["lines"]
            }
        )
        evidence: list[dict[str, Any]] = []
        for project_id, project_code in project_pairs:
            try:
                admitted = self._project_authorizer.authorize(
                    tenant_id=tenant_id,
                    subject_id=subject_id,
                    project_id=project_id,
                    action=FINANCE_JOURNAL_READ_SCOPE,
                    correlation_id=_scoped_id("correlation_id", correlation_id),
                    expected_project_code=project_code,
                )
            except EosProjectAuthorizationError as exc:
                if exc.status_code == 403:
                    raise _denied("OA denied Project Journal read authority") from exc
                raise _unavailable(
                    "Project Journal authorization is unavailable"
                ) from exc
            evidence.append(
                {
                    "decision_ref": admitted.decision_ref,
                    "project_code": admitted.project_code,
                    "project_role": admitted.project_role,
                    "project_status": admitted.project_status,
                    "source_version": admitted.source_version,
                    "authorization_revision_hash": admitted.authorization_revision_hash,
                }
            )
        if not evidence:
            raise EosJournalError(
                "EOS_JOURNAL_STATE_INVALID",
                "PostedJournal has no Project-attributed lines",
                status_code=503,
            )
        return evidence


def _scoped_id(field_name: str, value: object) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise EosJournalError(
            "EOS_JOURNAL_QUERY_INVALID",
            f"{field_name} has invalid stable-reference syntax",
            status_code=422,
        )
    return normalized


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EosJournalError(
            "EOS_JOURNAL_VERIFICATION_FAILED",
            "Journal verification clock must be timezone-aware",
            status_code=503,
        )
    return value.astimezone(UTC)


def _denied(detail: str) -> EosJournalError:
    return EosJournalError("EOS_JOURNAL_READ_DENIED", detail, status_code=403)


def _unavailable(detail: str) -> EosJournalError:
    return EosJournalError(
        "EOS_JOURNAL_AUTHORIZATION_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )
