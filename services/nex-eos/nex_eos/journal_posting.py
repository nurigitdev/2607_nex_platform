from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import (
    nsl_write_payload_hash_ref,
    semantic_sha256_hash_ref,
)
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .account_catalog import (
    EOS_COMPANY_ACCOUNT_POLICY_TABLE,
    EOS_POSTING_RULE_RELEASE_TABLE,
)
from .accounting_approval import EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE
from .accounting_periods import EOS_ACCOUNTING_PERIOD_TABLE
from .accounting_posting_admission import (
    ACCOUNTING_POSTING_ADMISSION_REQUEST_SCHEMA,
    EosAccountingPostingAdmissionError,
    EosAccountingPostingAdmissionService,
)
from .accounts import EOS_ACCOUNT_TABLE
from .approved_document_consumption import (
    ApprovedDocumentConsumptionInput,
    EosApprovedDocumentConsumptionAdapter,
    EosApprovedDocumentConsumptionError,
)
from .approved_documents import EOS_APPROVED_DOCUMENT_TABLE
from .business_transactions import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .candidate_validation import (
    EosCandidateValidationError,
    EosCandidateValidationService,
)
from .fx_rates import EOS_FX_RATE_SNAPSHOT_TABLE
from .journals import (
    EOS_JOURNAL_SEQUENCE_TABLE,
    EosJournalError,
    SqlAlchemyEosJournalRepository,
    build_acceptance_hash,
    build_journal_hash,
    build_line_hash,
)
from .voucher_candidates import (
    EOS_VOUCHER_CANDIDATE_LINE_TABLE,
    EOS_VOUCHER_CANDIDATE_REVISION_TABLE,
    EOS_VOUCHER_CANDIDATE_TABLE,
)

JOURNAL_POST_OPERATION = "FINANCE.VOUCHER.APPROVE_AND_POST"
JOURNAL_POST_EVENT_TYPE = "FINANCE.JOURNAL_POSTED.v1"
JOURNAL_POST_COMMAND_SCHEMA = "eos_journal_post_command.v1"
JOURNAL_POST_RESULT_SCHEMA = "eos_journal_post_result.v1"

_COMMAND_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "company_id",
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "expected_candidate_version",
        "expected_candidate_revision",
        "expected_candidate_hash",
        "accounting_approval_evidence_id",
        "correlation_id",
    }
)
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


class EosJournalPostingError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class JournalPostCommand:
    tenant_id: str
    company_id: str
    candidate_id: str
    business_operation_id: str
    idempotency_key: str
    payload_hash: str
    expected_candidate_version: int
    expected_candidate_revision: int
    expected_candidate_hash: str
    accounting_approval_evidence_id: str
    correlation_id: str

    def business_payload(self) -> dict[str, Any]:
        return {
            "schema_version": JOURNAL_POST_COMMAND_SCHEMA,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "candidate_id": self.candidate_id,
            "expected_candidate_version": self.expected_candidate_version,
            "expected_candidate_revision": self.expected_candidate_revision,
            "expected_candidate_hash": self.expected_candidate_hash,
            "accounting_approval_evidence_id": (self.accounting_approval_evidence_id),
        }


FaultInjector = Callable[[str], None]


class EosJournalPostingService:
    """Posts one approved Candidate without crossing the EOS transaction boundary."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        coordinator: EosBusinessTransactionCoordinator,
        validation_service: EosCandidateValidationService,
        admission_service: EosAccountingPostingAdmissionService,
        journals: SqlAlchemyEosJournalRepository,
        consumption: EosApprovedDocumentConsumptionAdapter | None = None,
        clock: Callable[[], datetime] | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._coordinator = coordinator
        self._validation = validation_service
        self._admission = admission_service
        self._journals = journals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._consumption = consumption or EosApprovedDocumentConsumptionAdapter(
            clock=self._clock
        )
        self._fault_injector = fault_injector

    def execute(self, candidate_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        command = parse_journal_post_command(candidate_id, payload)
        if journal_post_payload_hash(command) != command.payload_hash:
            raise _invalid("Canonical Posting payload hash does not match")
        operation_request = EosBusinessOperationRequest(
            tenant_id=command.tenant_id,
            business_operation_id=command.business_operation_id,
            idempotency_key=command.idempotency_key,
            operation=JOURNAL_POST_OPERATION,
            payload_hash=command.payload_hash,
            event_type=JOURNAL_POST_EVENT_TYPE,
        )
        replay = self._existing_replay(operation_request)
        if replay is not None:
            return _result_projection(replay)
        observed_at = _aware_datetime("clock", self._clock())
        try:
            validation = self._validation.validate(
                command.candidate_id,
                {
                    "schema_version": "eos_voucher_candidate_validate.v1",
                    "tenant_id": command.tenant_id,
                    "expected_revision_no": command.expected_candidate_revision,
                    "expected_candidate_hash": command.expected_candidate_hash,
                    "as_of": observed_at.isoformat(),
                },
            )
            receipt = self._admission.admit(
                command.candidate_id,
                {
                    "schema_version": ACCOUNTING_POSTING_ADMISSION_REQUEST_SCHEMA,
                    "tenant_id": command.tenant_id,
                    "company_id": command.company_id,
                    "expected_candidate_version": (command.expected_candidate_version),
                    "expected_candidate_revision": (
                        command.expected_candidate_revision
                    ),
                    "expected_candidate_hash": command.expected_candidate_hash,
                    "accounting_approval_evidence_id": (
                        command.accounting_approval_evidence_id
                    ),
                    "correlation_id": command.correlation_id,
                },
            )
            _require_validation_matches(command, validation, receipt)
        except (EosCandidateValidationError, EosAccountingPostingAdmissionError) as exc:
            replay = self._existing_replay(operation_request)
            if replay is not None:
                return _result_projection(replay)
            raise EosJournalPostingError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise EosBusinessOperationError(
                    "EOS_JOURNAL_POST_TRANSACTION_REQUIRED",
                    "Posting requires an active EOS database transaction",
                    status_code=500,
                )
            return self._post_in_session(
                session,
                command=command,
                validation=validation,
                receipt=receipt,
            )

        try:
            transaction = self._coordinator.execute(operation_request, mutation)
        except EosBusinessOperationError as exc:
            raise EosJournalPostingError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return _result_projection(transaction)

    def _existing_replay(self, request: EosBusinessOperationRequest):
        try:
            with self._session_factory() as session:
                operation_exists = session.execute(
                    select(EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id).where(
                        EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == request.tenant_id,
                        EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                        == request.business_operation_id,
                    )
                ).scalar_one_or_none()
                idempotency_exists = session.execute(
                    select(EOS_IDEMPOTENCY_TABLE.c.idempotency_key).where(
                        EOS_IDEMPOTENCY_TABLE.c.tenant_id == request.tenant_id,
                        EOS_IDEMPOTENCY_TABLE.c.idempotency_key
                        == request.idempotency_key,
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise EosJournalPostingError(
                "EOS_JOURNAL_POST_PERSISTENCE_UNAVAILABLE",
                "Atomic Posting replay admission is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        if operation_exists is None and idempotency_exists is None:
            return None

        def must_not_mutate(_session):
            raise EosBusinessOperationError(
                "EOS_JOURNAL_POST_REPLAY_INCOMPLETE",
                "Posting identity exists without a committed replay result",
                status_code=409,
            )

        try:
            return self._coordinator.execute(request, must_not_mutate)
        except EosBusinessOperationError as exc:
            raise EosJournalPostingError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc

    def _post_in_session(
        self,
        session: Session,
        *,
        command: JournalPostCommand,
        validation: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            self._admission.require_current_in_session(session, receipt)
            candidate, revision, candidate_lines = _load_candidate(
                session, command=command
            )
            period = _lock_open_period(session, command=command, validation=validation)
            policies = _load_effective_policies(
                session,
                command=command,
                candidate_lines=candidate_lines,
                recognition_date=candidate["recognition_date"],
                validation=validation,
            )
            document = _load_document(session, command=command, candidate=candidate)
            accounting_evidence = _load_accounting_evidence(
                session, command=command, receipt=receipt
            )
            fx_snapshot = _load_fx_snapshot(
                session, command=command, validation=validation
            )
            posted_at = _aware_datetime("clock", self._clock())
            sequence = _allocate_sequence(
                session,
                command=command,
                period=period,
                updated_at=posted_at,
            )
            staged = _build_posted_journal(
                command=command,
                validation=validation,
                receipt=receipt,
                candidate=candidate,
                revision=revision,
                candidate_lines=candidate_lines,
                policies=policies,
                document=document,
                accounting_evidence=accounting_evidence,
                fx_snapshot=fx_snapshot,
                period=period,
                posting_sequence=sequence,
                posted_at=posted_at,
            )
            self._journals.stage_in_session(session, **staged)
            self._fault("JOURNAL_STAGED")
            consumed, _ = self._consumption.consume_in_session(
                session,
                ApprovedDocumentConsumptionInput(
                    tenant_id=command.tenant_id,
                    consumption_id=_derived_uuid(command, "consumption"),
                    company_id=command.company_id,
                    envelope_id=str(candidate["document_envelope_id"]),
                    source_document_line_ref=str(candidate["source_record_ref"]),
                    candidate_revision_id=str(revision["revision_id"]),
                    posted_journal_id=staged["header"]["journal_id"],
                    consumed_amount=Decimal(
                        str(validation["totals"]["debit_original"])
                    ),
                    currency=str(validation["transaction_currency"]),
                    operation_id=command.business_operation_id,
                ),
            )
            self._fault("DOCUMENT_CONSUMED")
            changed = session.execute(
                update(EOS_VOUCHER_CANDIDATE_TABLE)
                .where(
                    EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id == command.tenant_id,
                    EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == command.candidate_id,
                    EOS_VOUCHER_CANDIDATE_TABLE.c.company_id == command.company_id,
                    EOS_VOUCHER_CANDIDATE_TABLE.c.state == "READY_FOR_REVIEW",
                    EOS_VOUCHER_CANDIDATE_TABLE.c.version
                    == command.expected_candidate_version,
                    EOS_VOUCHER_CANDIDATE_TABLE.c.current_revision_no
                    == command.expected_candidate_revision,
                )
                .values(
                    state="POSTED",
                    version=command.expected_candidate_version + 1,
                    updated_at=posted_at,
                )
            )
            if changed.rowcount != 1:
                raise _business_error(
                    "EOS_JOURNAL_POST_CANDIDATE_STALE",
                    "VoucherCandidate changed before the atomic Posting CAS",
                    status_code=409,
                )
            self._fault("CANDIDATE_POSTED")
        except EosBusinessOperationError:
            raise
        except (
            EosAccountingPostingAdmissionError,
            EosApprovedDocumentConsumptionError,
            EosJournalError,
        ) as exc:
            raise _business_error(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        except SQLAlchemyError as exc:
            raise _business_error(
                "EOS_JOURNAL_POST_PERSISTENCE_UNAVAILABLE",
                "Atomic Posting persistence is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        return {
            "business_result_ref": (
                f"eos.posted_journal:{staged['header']['journal_id']}"
            ),
            "journal_id": staged["header"]["journal_id"],
            "journal_no": staged["header"]["journal_no"],
            "candidate_id": command.candidate_id,
            "candidate_revision": command.expected_candidate_revision,
            "candidate_version": command.expected_candidate_version + 1,
            "candidate_state": "POSTED",
            "accounting_acceptance_id": staged["acceptance"]["acceptance_id"],
            "consumption_id": consumed["consumption_id"],
            "journal_hash": staged["header"]["journal_hash"],
            "posted_at": posted_at.isoformat(),
        }

    def _fault(self, stage: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(stage)


def parse_journal_post_command(
    candidate_id: object, value: Mapping[str, Any]
) -> JournalPostCommand:
    if not isinstance(value, Mapping) or set(value) != _COMMAND_FIELDS:
        raise _invalid("Posting command fields do not match the canonical contract")
    if value.get("schema_version") != JOURNAL_POST_COMMAND_SCHEMA:
        raise _invalid("Posting command schema_version is invalid")
    return JournalPostCommand(
        tenant_id=_scoped_id("tenant_id", value.get("tenant_id")),
        company_id=_uuid("company_id", value.get("company_id")),
        candidate_id=_uuid("candidate_id", candidate_id),
        business_operation_id=_uuid(
            "business_operation_id", value.get("business_operation_id")
        ),
        idempotency_key=_scoped_id("idempotency_key", value.get("idempotency_key")),
        payload_hash=_hash_ref("payload_hash", value.get("payload_hash")),
        expected_candidate_version=_positive_int(
            "expected_candidate_version", value.get("expected_candidate_version")
        ),
        expected_candidate_revision=_positive_int(
            "expected_candidate_revision", value.get("expected_candidate_revision")
        ),
        expected_candidate_hash=_hash_ref(
            "expected_candidate_hash", value.get("expected_candidate_hash")
        ),
        accounting_approval_evidence_id=_uuid(
            "accounting_approval_evidence_id",
            value.get("accounting_approval_evidence_id"),
        ),
        correlation_id=_scoped_id("correlation_id", value.get("correlation_id")),
    )


def journal_post_payload_hash(command: JournalPostCommand) -> str:
    return nsl_write_payload_hash_ref(command.business_payload())


def _result_projection(transaction) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_POST_RESULT_SCHEMA,
        "operation": JOURNAL_POST_OPERATION,
        "idempotency_disposition": "CREATED" if transaction.created else "REPLAYED",
        **transaction.to_public_projection(),
    }


def _require_validation_matches(
    command: JournalPostCommand,
    validation: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    expected = (
        command.tenant_id,
        command.company_id,
        command.candidate_id,
        command.expected_candidate_version,
        command.expected_candidate_revision,
        command.expected_candidate_hash,
    )
    actual = (
        validation.get("tenant_id"),
        validation.get("company_id"),
        validation.get("candidate_ref", {}).get("id"),
        validation.get("candidate_version"),
        validation.get("revision_ref", {}).get("revision_no"),
        validation.get("revision_ref", {}).get("hash"),
    )
    if actual != expected or validation.get("status") != "PASS":
        raise _stale("Current Candidate validation does not match the Posting command")
    if (
        receipt.get("validation_hash")
        != _review_bound_validation_hash(command, validation)
        or receipt.get("accounting_approval_evidence_id")
        != command.accounting_approval_evidence_id
    ):
        raise _stale("Accounting approval does not bind the current validation")


def _review_bound_validation_hash(
    command: JournalPostCommand, validation: Mapping[str, Any]
) -> str:
    evidence = {
        "candidate_id": command.candidate_id,
        "candidate_version": command.expected_candidate_version - 1,
        "candidate_hash": command.expected_candidate_hash,
        "revision_no": command.expected_candidate_revision,
        "company_id": command.company_id,
        "project_id": validation["project_ref"]["id"],
        "document_envelope_id": validation["document_ref"]["id"],
        "approved_document_hash": validation["document_ref"]["hash"],
        "preparer_subject_id": validation["preparer_subject_id"],
        "accounting_period_id": validation["accounting_period_id"],
        "posting_rule_release_hash": validation["posting_rule_release_hash"],
        "account_policy_set_hash": validation["account_policy_set_hash"],
        "fx_rate_set_hash": validation["fx_rate_set_hash"],
        "accounting_rule_profile_hash": validation["accounting_rule_profile_hash"],
        "lines": list(validation["lines"]),
    }
    return semantic_sha256_hash_ref(
        {"domain": "EOS-VOUCHER-CANDIDATE-VALIDATION-V1", **evidence}
    )


def _load_candidate(
    session: Session, *, command: JournalPostCommand
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    candidate = (
        session.execute(
            select(EOS_VOUCHER_CANDIDATE_TABLE)
            .where(
                EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id == command.tenant_id,
                EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == command.candidate_id,
                EOS_VOUCHER_CANDIDATE_TABLE.c.company_id == command.company_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if candidate is None:
        raise _business_error(
            "EOS_JOURNAL_POST_CANDIDATE_NOT_FOUND",
            "VoucherCandidate was not found in the exact company scope",
            status_code=404,
        )
    revision = (
        session.execute(
            select(EOS_VOUCHER_CANDIDATE_REVISION_TABLE).where(
                EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.tenant_id == command.tenant_id,
                EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.candidate_id
                == command.candidate_id,
                EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.revision_no
                == command.expected_candidate_revision,
            )
        )
        .mappings()
        .one_or_none()
    )
    lines = (
        session.execute(
            select(EOS_VOUCHER_CANDIDATE_LINE_TABLE)
            .where(
                EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.tenant_id == command.tenant_id,
                EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.candidate_id == command.candidate_id,
                EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.revision_no
                == command.expected_candidate_revision,
            )
            .order_by(EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.line_no)
        )
        .mappings()
        .all()
    )
    if revision is None or not lines:
        raise _business_error(
            "EOS_JOURNAL_POST_CANDIDATE_STALE",
            "Current VoucherCandidate revision or lines are unavailable",
            status_code=409,
        )
    return dict(candidate), dict(revision), [dict(line) for line in lines]


def _lock_open_period(
    session: Session,
    *,
    command: JournalPostCommand,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    period = (
        session.execute(
            select(EOS_ACCOUNTING_PERIOD_TABLE)
            .where(
                EOS_ACCOUNTING_PERIOD_TABLE.c.tenant_id == command.tenant_id,
                EOS_ACCOUNTING_PERIOD_TABLE.c.company_id == command.company_id,
                EOS_ACCOUNTING_PERIOD_TABLE.c.period_id
                == validation["accounting_period_id"],
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    recognition_date = date.fromisoformat(str(validation["recognition_date"]))
    if (
        period is None
        or period["state"] != "OPEN"
        or not period["start_date"] <= recognition_date <= period["end_date"]
    ):
        raise _business_error(
            "EOS_JOURNAL_POST_PERIOD_NOT_OPEN",
            "The admitted AccountingPeriod is not OPEN at commit time",
            status_code=409,
        )
    return dict(period)


def _load_effective_policies(
    session: Session,
    *,
    command: JournalPostCommand,
    candidate_lines: list[dict[str, Any]],
    recognition_date: date,
    validation: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    account_ids = sorted({str(line["account_id"]) for line in candidate_lines})
    rows = (
        session.execute(
            select(
                EOS_COMPANY_ACCOUNT_POLICY_TABLE,
                EOS_ACCOUNT_TABLE.c.account_code,
                EOS_ACCOUNT_TABLE.c.name.label("account_name"),
                EOS_POSTING_RULE_RELEASE_TABLE.c.rule_hash,
            )
            .join(
                EOS_ACCOUNT_TABLE,
                (
                    EOS_ACCOUNT_TABLE.c.tenant_id
                    == EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.tenant_id
                )
                & (
                    EOS_ACCOUNT_TABLE.c.account_id
                    == EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.account_id
                ),
            )
            .join(
                EOS_POSTING_RULE_RELEASE_TABLE,
                (
                    EOS_POSTING_RULE_RELEASE_TABLE.c.tenant_id
                    == EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.tenant_id
                )
                & (
                    EOS_POSTING_RULE_RELEASE_TABLE.c.posting_rule_id
                    == EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.posting_rule_id
                ),
            )
            .where(
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.tenant_id == command.tenant_id,
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.company_id == command.company_id,
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.account_id.in_(account_ids),
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.state == "APPROVED",
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.is_postable_leaf.is_(True),
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.valid_from <= recognition_date,
                (
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.valid_until.is_(None)
                    | (
                        EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.valid_until
                        > recognition_date
                    )
                ),
                EOS_POSTING_RULE_RELEASE_TABLE.c.status == "PUBLISHED",
                EOS_POSTING_RULE_RELEASE_TABLE.c.effective_date <= recognition_date,
            )
            .with_for_update()
        )
        .mappings()
        .all()
    )
    by_account = {str(row["account_id"]): dict(row) for row in rows}
    if set(by_account) != set(account_ids):
        raise _business_error(
            "EOS_JOURNAL_POST_ACCOUNT_POLICY_STALE",
            "An admitted account policy is no longer effective or postable",
            status_code=409,
        )
    transaction_currency = str(validation["transaction_currency"])
    if any(transaction_currency not in row["allowed_currencies"] for row in rows):
        raise _business_error(
            "EOS_JOURNAL_POST_ACCOUNT_CURRENCY_DENIED",
            "An admitted account policy no longer accepts the transaction currency",
            status_code=409,
        )
    policy_semantics = [
        {
            "policy_id": str(row["policy_id"]),
            "account_id": str(row["account_id"]),
            "catalog_release_id": str(row["catalog_release_id"]),
            "posting_rule_id": str(row["posting_rule_id"]),
            "rule_revision": int(row["rule_revision"]),
            "approved_proof_ref": str(row["approved_proof_ref"]),
            "allowed_currencies": sorted(
                str(item) for item in row["allowed_currencies"]
            ),
        }
        for row in sorted(rows, key=lambda item: str(item["policy_id"]))
    ]
    policy_hash = semantic_sha256_hash_ref(
        {"domain": "EOS-CANDIDATE-ACCOUNT-POLICY-SET-V1", "policies": policy_semantics}
    )
    if policy_hash != validation["account_policy_set_hash"] or any(
        row["rule_hash"] != validation["posting_rule_release_hash"] for row in rows
    ):
        raise _business_error(
            "EOS_JOURNAL_POST_ACCOUNT_POLICY_STALE",
            "Account or PostingRule policy changed after validation",
            status_code=409,
        )
    return by_account


def _load_document(
    session: Session,
    *,
    command: JournalPostCommand,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    row = (
        session.execute(
            select(EOS_APPROVED_DOCUMENT_TABLE).where(
                EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id == command.tenant_id,
                EOS_APPROVED_DOCUMENT_TABLE.c.envelope_id
                == candidate["document_envelope_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _business_error(
            "EOS_JOURNAL_POST_DOCUMENT_NOT_FOUND",
            "ApprovedDocumentEnvelope is unavailable",
            status_code=409,
        )
    return dict(row)


def _load_accounting_evidence(
    session: Session,
    *,
    command: JournalPostCommand,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    row = (
        session.execute(
            select(EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE).where(
                EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.tenant_id == command.tenant_id,
                EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.evidence_id
                == command.accounting_approval_evidence_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["proof_hash"] != receipt["accounting_proof_hash"]:
        raise _business_error(
            "EOS_JOURNAL_POST_ACCOUNTING_PROOF_STALE",
            "Accounting approval evidence changed before Posting",
            status_code=409,
        )
    return dict(row)


def _load_fx_snapshot(
    session: Session,
    *,
    command: JournalPostCommand,
    validation: Mapping[str, Any],
) -> dict[str, Any] | None:
    snapshot_hash = validation["fx_evidence"].get("snapshot_hash")
    if snapshot_hash is None:
        return None
    row = (
        session.execute(
            select(EOS_FX_RATE_SNAPSHOT_TABLE).where(
                EOS_FX_RATE_SNAPSHOT_TABLE.c.tenant_id == command.tenant_id,
                EOS_FX_RATE_SNAPSHOT_TABLE.c.company_id == command.company_id,
                EOS_FX_RATE_SNAPSHOT_TABLE.c.snapshot_hash == snapshot_hash,
                EOS_FX_RATE_SNAPSHOT_TABLE.c.approved_state == "APPROVED",
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _business_error(
            "EOS_JOURNAL_POST_FX_STALE",
            "The admitted FX RateSnapshot is unavailable",
            status_code=409,
        )
    return dict(row)


def _allocate_sequence(
    session: Session,
    *,
    command: JournalPostCommand,
    period: Mapping[str, Any],
    updated_at: datetime,
) -> int:
    key = (
        (EOS_JOURNAL_SEQUENCE_TABLE.c.tenant_id == command.tenant_id)
        & (EOS_JOURNAL_SEQUENCE_TABLE.c.company_id == command.company_id)
        & (EOS_JOURNAL_SEQUENCE_TABLE.c.period_id == period["period_id"])
    )
    current = session.execute(
        select(EOS_JOURNAL_SEQUENCE_TABLE.c.last_sequence).where(key).with_for_update()
    ).scalar_one_or_none()
    if current is None:
        sequence = 1
        session.execute(
            EOS_JOURNAL_SEQUENCE_TABLE.insert().values(
                tenant_id=command.tenant_id,
                company_id=command.company_id,
                period_id=period["period_id"],
                last_sequence=sequence,
                updated_at=updated_at,
            )
        )
    else:
        sequence = int(current) + 1
        session.execute(
            update(EOS_JOURNAL_SEQUENCE_TABLE)
            .where(key)
            .values(last_sequence=sequence, updated_at=updated_at)
        )
    return sequence


def _build_posted_journal(
    *,
    command: JournalPostCommand,
    validation: Mapping[str, Any],
    receipt: Mapping[str, Any],
    candidate: Mapping[str, Any],
    revision: Mapping[str, Any],
    candidate_lines: list[dict[str, Any]],
    policies: Mapping[str, Mapping[str, Any]],
    document: Mapping[str, Any],
    accounting_evidence: Mapping[str, Any],
    fx_snapshot: Mapping[str, Any] | None,
    period: Mapping[str, Any],
    posting_sequence: int,
    posted_at: datetime,
) -> dict[str, Any]:
    journal_id = _derived_uuid(command, "journal")
    acceptance_id = _derived_uuid(command, "accounting-acceptance")
    acceptance = {
        "tenant_id": command.tenant_id,
        "company_id": command.company_id,
        "acceptance_id": acceptance_id,
        "candidate_id": command.candidate_id,
        "candidate_revision": command.expected_candidate_revision,
        "candidate_hash": command.expected_candidate_hash,
        "accounting_evidence_id": command.accounting_approval_evidence_id,
        "approval_case_id": str(receipt["approval_case_id"]),
        "purpose": "ACCOUNTING_POSTING",
        "proof_hash": str(receipt["accounting_proof_hash"]),
        "wc_decision_id": str(accounting_evidence["wc_final_decision_id"]),
        "oa_decision_ref": str(receipt["fresh_oa_decision_ref"]),
        "oa_decision_revision_hash": str(receipt["fresh_oa_revision_hash"]),
        "accepted_by": str(receipt["approver_subject_id"]),
        "accepted_at": posted_at,
        "journal_id": journal_id,
        "acceptance_hash": "",
    }
    acceptance["acceptance_hash"] = build_acceptance_hash(acceptance)
    functional_lines = {int(row["line_no"]): row for row in validation["lines"]}
    lines: list[dict[str, Any]] = []
    for source in candidate_lines:
        line_no = int(source["line_no"])
        converted = functional_lines[line_no]
        policy = policies[str(source["account_id"])]
        line = {
            "tenant_id": command.tenant_id,
            "company_id": command.company_id,
            "journal_id": journal_id,
            "line_no": line_no,
            "candidate_id": command.candidate_id,
            "candidate_revision": command.expected_candidate_revision,
            "candidate_source_line_no": line_no,
            "account_id": str(source["account_id"]),
            "account_code_snapshot": str(policy["account_code"]),
            "account_name_snapshot": str(policy["account_name"]),
            "account_policy_id": str(policy["policy_id"]),
            "account_policy_release_hash": str(policy["approved_proof_ref"]),
            "posting_rule_release_hash": str(validation["posting_rule_release_hash"]),
            "project_id": str(source["project_id"]),
            "project_code": str(source["project_code"]),
            "debit_original": _money4(source["debit_original"]),
            "credit_original": _money4(source["credit_original"]),
            "original_currency": str(source["original_currency"]),
            "debit_functional": _money4(converted["debit_functional"]),
            "credit_functional": _money4(converted["credit_functional"]),
            "functional_currency": str(validation["functional_currency"]),
            "fx_rate_snapshot_id": (
                None if fx_snapshot is None else str(fx_snapshot["rate_snapshot_id"])
            ),
            "fx_rate_snapshot_hash": (
                None if fx_snapshot is None else str(fx_snapshot["snapshot_hash"])
            ),
            "source_record_line_ref": str(source["source_record_line_ref"]),
            "description": source["description"],
            "dimensions_json": {
                "business_work_code": str(candidate["business_work_code"]),
                "source_kind": str(candidate["source_kind"]),
            },
            "evidence_hash": str(source["evidence_hash"]),
            "line_hash": "",
        }
        line["line_hash"] = build_line_hash(line)
        lines.append(line)
    recognition_date = date.fromisoformat(str(validation["recognition_date"]))
    header = {
        "tenant_id": command.tenant_id,
        "company_id": command.company_id,
        "journal_id": journal_id,
        "candidate_id": command.candidate_id,
        "candidate_revision": command.expected_candidate_revision,
        "candidate_hash": command.expected_candidate_hash,
        "period_id": str(period["period_id"]),
        "posting_sequence": posting_sequence,
        "journal_no": (
            f"{command.tenant_id[:16].upper()}-{period['fiscal_year']}-"
            f"{posting_sequence:06d}"
        ),
        "state": "POSTED",
        "transaction_kind": "STANDARD",
        "recognition_date": recognition_date,
        "posting_date": recognition_date,
        "functional_currency": str(validation["functional_currency"]),
        "source_document_id": str(candidate["document_envelope_id"]),
        "source_document_revision": int(document["document_revision"]),
        "source_document_hash": str(revision["approved_document_hash"]),
        "accounting_acceptance_id": acceptance_id,
        "posting_rule_release_hash": str(validation["posting_rule_release_hash"]),
        "fx_rate_set_hash": str(validation["fx_rate_set_hash"]),
        "reversal_of_journal_id": None,
        "business_operation_id": command.business_operation_id,
        "idempotency_key": command.idempotency_key,
        "payload_hash": command.payload_hash,
        "line_count": len(lines),
        "total_debit_functional": _money4(validation["totals"]["debit_functional"]),
        "total_credit_functional": _money4(validation["totals"]["credit_functional"]),
        "journal_hash": "",
        "posted_at": posted_at,
    }
    header["journal_hash"] = build_journal_hash(
        header, line_hashes=[line["line_hash"] for line in lines]
    )
    return {"acceptance": acceptance, "header": header, "lines": lines}


def _derived_uuid(command: JournalPostCommand, suffix: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/eos/journal-posting/"
            f"{command.tenant_id}/{command.business_operation_id}/{suffix}",
        )
    )


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"{field} has invalid stable-reference syntax")
    return normalized


def _hash_ref(field: str, value: object) -> str:
    if not isinstance(value, str) or _HASH_REF.fullmatch(value) is None:
        raise _invalid(f"{field} must be a SHA-256 hash reference")
    return value


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer")
    return value


def _money4(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _aware_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _invalid(detail: str) -> EosJournalPostingError:
    return EosJournalPostingError("EOS_JOURNAL_POST_INVALID", detail, status_code=422)


def _stale(detail: str) -> EosJournalPostingError:
    return EosJournalPostingError("EOS_JOURNAL_POST_STALE", detail, status_code=409)


def _business_error(
    error_code: str,
    detail: str,
    *,
    status_code: int,
    retryable: bool = False,
) -> EosBusinessOperationError:
    return EosBusinessOperationError(
        error_code,
        detail,
        status_code=status_code,
        retryable=retryable,
    )
