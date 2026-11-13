from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .accounts import EOS_ACCOUNT_TABLE
from .approval_instances import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
)
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import (
    EOS_METADATA,
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .legal_entities import EOS_LEGAL_ENTITY_TABLE

BUDGET_COMMIT_OPERATION = "FINANCE.BUDGET.COMMIT"
BUDGET_GET_OPERATION = "FINANCE.BUDGET.GET"
BUDGET_APPROVE_SCOPE = "finance:budget:approve"
BUDGET_COMMIT_SCHEMA = "eos_budget_commit.v1"
BUDGET_RESULT_SCHEMA = "eos_budget_result.v1"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_MONEY = re.compile(r"^(?:0|[1-9][0-9]{0,15})\.[0-9]{4}$")


EOS_BUDGET_TABLE = Table(
    "eos_budget",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("budget_id", Uuid(as_uuid=False), primary_key=True),
    Column("budget_version", Integer, primary_key=True),
    Column("fiscal_year", Integer, nullable=False),
    Column("account_id", Uuid(as_uuid=False), nullable=True),
    Column("budget_category", String(64), nullable=False),
    Column("approved_currency", String(3), nullable=False),
    Column("approved_functional_amount", Numeric(20, 4), nullable=False),
    Column("approved_by", String(128), nullable=False),
    Column("approved_proof", String(256), nullable=False),
    Column("source_ref", String(256), nullable=False),
    Column("source_hash", String(71), nullable=False),
    Column("budget_hash", String(71), nullable=False),
    Column("state", String(16), nullable=False),
    Column("business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id", "company_id", "budget_hash", name="ux_eos_budget_hash"
    ),
    UniqueConstraint(
        "tenant_id", "business_operation_id", name="ux_eos_budget_operation"
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_budget_company",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_budget_account",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_budget_operation",
    ),
    CheckConstraint("budget_version > 0", name="ck_eos_budget_version"),
    CheckConstraint("fiscal_year BETWEEN 2000 AND 9999", name="ck_eos_budget_year"),
    CheckConstraint("approved_functional_amount > 0", name="ck_eos_budget_amount"),
    CheckConstraint("state = 'APPROVED'", name="ck_eos_budget_state"),
)


class EosBudgetError(RuntimeError):
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
class BudgetCommitCommand:
    tenant_id: str
    company_id: str
    business_operation_id: str
    idempotency_key: str
    payload_hash: str
    approval_proof_id: str
    budget_id: str
    budget_version: int
    fiscal_year: int
    account_id: str | None
    budget_category: str
    approved_currency: str
    approved_functional_amount: Decimal
    source_ref: str
    source_hash: str

    def business_payload(self) -> dict[str, Any]:
        return {
            "schema_version": BUDGET_COMMIT_SCHEMA,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "budget": {
                "budget_id": self.budget_id,
                "budget_version": self.budget_version,
                "fiscal_year": self.fiscal_year,
                "account_id": self.account_id,
                "budget_category": self.budget_category,
                "approved_currency": self.approved_currency,
                "approved_functional_amount": format(
                    self.approved_functional_amount, ".4f"
                ),
                "source_ref": self.source_ref,
                "source_hash": self.source_hash,
            },
        }


class SqlAlchemyEosBudgetRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load_approval_context(
        self, *, tenant_id: str, approval_proof_id: str
    ) -> Mapping[str, Any] | None:
        try:
            with self._session_factory() as session:
                return load_final_approval_context(
                    session,
                    tenant_id=tenant_id,
                    approval_proof_id=approval_proof_id,
                )
        except SQLAlchemyError as exc:
            raise _unavailable("Budget approval persistence is unavailable") from exc

    def create_in_session(
        self,
        session: Session,
        command: BudgetCommitCommand,
        approval: Mapping[str, Any],
        *,
        created_at: datetime,
    ) -> dict[str, Any]:
        company = (
            session.execute(
                select(EOS_LEGAL_ENTITY_TABLE).where(
                    EOS_LEGAL_ENTITY_TABLE.c.tenant_id == command.tenant_id,
                    EOS_LEGAL_ENTITY_TABLE.c.company_id == command.company_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if company is None:
            raise _not_found("LegalEntity was not found in tenant scope")
        if company["status"] != "ACTIVE":
            raise _conflict("Budget requires an active LegalEntity")
        if company["functional_currency"] != command.approved_currency:
            raise _conflict(
                "Budget currency must equal LegalEntity functional currency"
            )
        if command.account_id is not None:
            account = (
                session.execute(
                    select(EOS_ACCOUNT_TABLE.c.status).where(
                        EOS_ACCOUNT_TABLE.c.tenant_id == command.tenant_id,
                        EOS_ACCOUNT_TABLE.c.account_id == command.account_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if account is None:
                raise _not_found("Budget account was not found in tenant scope")
            if account["status"] != "ACTIVE":
                raise _conflict("Budget account must be active")
        existing = self.get_in_session(session, command)
        budget_hash = budget_payload_hash(command)
        if existing is not None:
            if existing["budget_hash"] != budget_hash:
                raise _conflict("Budget revision has different immutable semantics")
            return existing
        latest = session.scalar(
            select(EOS_BUDGET_TABLE.c.budget_version)
            .where(
                EOS_BUDGET_TABLE.c.tenant_id == command.tenant_id,
                EOS_BUDGET_TABLE.c.company_id == command.company_id,
                EOS_BUDGET_TABLE.c.budget_id == command.budget_id,
            )
            .order_by(EOS_BUDGET_TABLE.c.budget_version.desc())
            .limit(1)
        )
        expected = 1 if latest is None else int(latest) + 1
        if command.budget_version != expected:
            raise _conflict(
                f"Budget version must be the next immutable revision {expected}"
            )
        record = {
            "tenant_id": command.tenant_id,
            "company_id": command.company_id,
            "budget_id": command.budget_id,
            "budget_version": command.budget_version,
            "fiscal_year": command.fiscal_year,
            "account_id": command.account_id,
            "budget_category": command.budget_category,
            "approved_currency": command.approved_currency,
            "approved_functional_amount": command.approved_functional_amount,
            "approved_by": approval["decided_by_id"],
            "approved_proof": approval["approval_proof_ref"],
            "source_ref": command.source_ref,
            "source_hash": command.source_hash,
            "budget_hash": budget_hash,
            "state": "APPROVED",
            "business_operation_id": command.business_operation_id,
            "created_at": created_at,
        }
        session.execute(EOS_BUDGET_TABLE.insert().values(**record))
        return record

    def get_in_session(
        self, session: Session, command: BudgetCommitCommand
    ) -> dict[str, Any] | None:
        row = (
            session.execute(
                select(EOS_BUDGET_TABLE).where(
                    EOS_BUDGET_TABLE.c.tenant_id == command.tenant_id,
                    EOS_BUDGET_TABLE.c.company_id == command.company_id,
                    EOS_BUDGET_TABLE.c.budget_id == command.budget_id,
                    EOS_BUDGET_TABLE.c.budget_version == command.budget_version,
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def get(
        self,
        *,
        tenant_id: str,
        company_id: str,
        budget_id: str,
        budget_version: int,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_BUDGET_TABLE).where(
                            EOS_BUDGET_TABLE.c.tenant_id == tenant_id,
                            EOS_BUDGET_TABLE.c.company_id == company_id,
                            EOS_BUDGET_TABLE.c.budget_id == budget_id,
                            EOS_BUDGET_TABLE.c.budget_version == budget_version,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as exc:
            raise _unavailable("Budget persistence is unavailable") from exc
        return dict(row) if row is not None else None


class EosBudgetService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyEosBudgetRepository,
        coordinator: EosBusinessTransactionCoordinator,
        authorization_source: AuthorizationSource,
        clock=None,
    ) -> None:
        self._repository = repository
        self._coordinator = coordinator
        self._authorization_source = authorization_source
        self._clock = clock or (lambda: datetime.now(UTC))

    def commit(
        self, *, tenant_id: str, company_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        command = parse_budget_commit(
            tenant_id=tenant_id, company_id=company_id, payload=payload
        )
        if budget_payload_hash(command) != command.payload_hash:
            raise _invalid("payload_hash", "does not match canonical Budget semantics")
        approval = self._repository.load_approval_context(
            tenant_id=command.tenant_id,
            approval_proof_id=command.approval_proof_id,
        )
        if approval is None:
            raise _not_found("Final BUSINESS_FORMAL approval proof was not found")
        require_exact_business_approval(
            approval,
            operation=BUDGET_COMMIT_OPERATION,
            payload_hash=command.payload_hash,
            protected_operation_ref=(
                f"eos.budget:{command.budget_id}:version:{command.budget_version}"
            ),
        )
        authorization_revision = require_fresh_authorization(
            self._authorization_source,
            tenant_id=command.tenant_id,
            subject_id=str(approval["decided_by_id"]),
            required_scope=BUDGET_APPROVE_SCOPE,
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise EosBusinessOperationError(
                    "EOS_BUDGET_TRANSACTION_REQUIRED",
                    "Budget commit requires an active EOS database transaction",
                    status_code=500,
                )
            try:
                record = self._repository.create_in_session(
                    session,
                    command,
                    approval,
                    created_at=_aware_time("clock", self._clock()),
                )
            except EosBudgetError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
            return {
                "business_result_ref": (
                    f"eos.budget:{record['budget_id']}:version:{record['budget_version']}"
                ),
                "budget_id": str(record["budget_id"]),
                "company_id": str(record["company_id"]),
                "budget_version": int(record["budget_version"]),
                "budget_hash": str(record["budget_hash"]),
                "approved_functional_amount": _money_wire(
                    record["approved_functional_amount"]
                ),
                "approved_currency": str(record["approved_currency"]),
                "authorization_revision_hash": authorization_revision,
            }

        try:
            transaction = self._coordinator.execute(
                EosBusinessOperationRequest(
                    tenant_id=command.tenant_id,
                    business_operation_id=command.business_operation_id,
                    idempotency_key=command.idempotency_key,
                    operation=BUDGET_COMMIT_OPERATION,
                    payload_hash=command.payload_hash,
                ),
                mutation,
            )
        except EosBusinessOperationError as exc:
            raise EosBudgetError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return _transaction_projection(transaction)

    def get(
        self,
        *,
        tenant_id: str,
        company_id: str,
        budget_id: str,
        budget_version: int,
    ) -> dict[str, Any]:
        identity = {
            "tenant_id": _scoped_id("tenant_id", tenant_id),
            "company_id": _uuid("company_id", company_id),
            "budget_id": _uuid("budget_id", budget_id),
            "budget_version": _positive_int("budget_version", budget_version),
        }
        record = self._repository.get(**identity)
        if record is None:
            raise _not_found(
                "Budget revision was not found in tenant and company scope"
            )
        return _budget_projection(record)


def parse_budget_commit(
    *, tenant_id: str, company_id: str, payload: Mapping[str, Any]
) -> BudgetCommitCommand:
    expected = {
        "schema_version",
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "approval_proof_id",
        "budget",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise _invalid("payload", "must contain only canonical Budget commit fields")
    if payload.get("schema_version") != BUDGET_COMMIT_SCHEMA:
        raise _invalid("schema_version", "is not supported")
    budget = payload.get("budget")
    fields = {
        "budget_id",
        "budget_version",
        "fiscal_year",
        "account_id",
        "budget_category",
        "approved_currency",
        "approved_functional_amount",
        "source_ref",
        "source_hash",
    }
    if not isinstance(budget, Mapping) or set(budget) != fields:
        raise _invalid("budget", "must contain only canonical Budget fields")
    account_id = budget.get("account_id")
    return BudgetCommitCommand(
        tenant_id=_scoped_id("tenant_id", tenant_id),
        company_id=_uuid("company_id", company_id),
        business_operation_id=_uuid(
            "business_operation_id", payload.get("business_operation_id")
        ),
        idempotency_key=_text("idempotency_key", payload.get("idempotency_key"), 256),
        payload_hash=_hash_ref("payload_hash", payload.get("payload_hash")),
        approval_proof_id=_uuid("approval_proof_id", payload.get("approval_proof_id")),
        budget_id=_uuid("budget_id", budget.get("budget_id")),
        budget_version=_positive_int("budget_version", budget.get("budget_version")),
        fiscal_year=_fiscal_year(budget.get("fiscal_year")),
        account_id=None if account_id is None else _uuid("account_id", account_id),
        budget_category=_text("budget_category", budget.get("budget_category"), 64),
        approved_currency=_pattern_text(
            "approved_currency", budget.get("approved_currency"), _CURRENCY
        ),
        approved_functional_amount=_positive_money(
            "approved_functional_amount", budget.get("approved_functional_amount")
        ),
        source_ref=_text("source_ref", budget.get("source_ref"), 256),
        source_hash=_hash_ref("source_hash", budget.get("source_hash")),
    )


def budget_payload_hash(command: BudgetCommitCommand) -> str:
    return semantic_sha256_hash_ref(
        {"domain": "EOS-BUDGET-V1", **command.business_payload()}
    )


def load_final_approval_context(
    session: Session, *, tenant_id: str, approval_proof_id: str
) -> dict[str, Any] | None:
    proof = EOS_APPROVAL_PROOF_TABLE
    instance = EOS_APPROVAL_INSTANCE_TABLE
    decision = EOS_APPROVAL_DECISION_TABLE
    row = (
        session.execute(
            select(
                proof.c.approval_proof_id,
                proof.c.business_operation_id,
                proof.c.approval_domain,
                proof.c.protected_operation_ref,
                proof.c.payload_hash,
                proof.c.policy_hash,
                instance.c.state.label("instance_state"),
                instance.c.operation,
                instance.c.payload_hash.label("instance_payload_hash"),
                instance.c.policy_hash.label("instance_policy_hash"),
                instance.c.business_operation_id.label("instance_operation_id"),
                decision.c.decision,
                decision.c.authorized_by_oa,
                decision.c.decided_by_id,
            )
            .select_from(
                proof.join(
                    instance,
                    (proof.c.tenant_id == instance.c.tenant_id)
                    & (proof.c.approval_instance_id == instance.c.approval_instance_id),
                ).join(
                    decision,
                    (proof.c.tenant_id == decision.c.tenant_id)
                    & (proof.c.final_wc_decision_id == decision.c.wc_decision_id),
                )
            )
            .where(
                proof.c.tenant_id == tenant_id,
                proof.c.approval_proof_id == approval_proof_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return {
        **dict(row),
        "approval_proof_ref": f"eos.approval-proof:{approval_proof_id}",
    }


def require_exact_business_approval(
    context: Mapping[str, Any],
    *,
    operation: str,
    payload_hash: str,
    protected_operation_ref: str,
) -> None:
    if (
        context["approval_domain"] != "BUSINESS_FORMAL"
        or context["instance_state"] != "APPROVED"
        or context["decision"] != "APPROVE"
        or context["authorized_by_oa"] is not True
    ):
        raise _conflict("Approval proof is not a final authorized approval")
    if (
        context["payload_hash"] != payload_hash
        or context["instance_payload_hash"] != payload_hash
        or context["operation"] != operation
        or context["protected_operation_ref"] != protected_operation_ref
        or context["policy_hash"] != context["instance_policy_hash"]
        or context["business_operation_id"] != context["instance_operation_id"]
    ):
        raise EosBudgetError(
            "EOS_BUDGET_PROOF_MISMATCH",
            "Approval proof does not bind the exact governed payload",
            status_code=409,
        )


def require_fresh_authorization(
    source: AuthorizationSource,
    *,
    tenant_id: str,
    subject_id: str,
    required_scope: str,
) -> str:
    try:
        value = source.effective_authorization(
            tenant_id=tenant_id, subject_id=subject_id
        )
    except AuthorizationSubjectDenied as exc:
        raise _denied("OA denied the current approver") from exc
    except Exception as exc:
        raise _unavailable("OA effective authorization is unavailable") from exc
    scopes = value.get("scopes") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or value.get("active") is not True
        or value.get("tenant_id") != tenant_id
        or value.get("subject_id") != subject_id
        or isinstance(scopes, (str, bytes))
        or not isinstance(scopes, Sequence)
        or required_scope not in scopes
    ):
        raise _denied("Active OA Budget authority is required")
    revision = value.get("revision_hash")
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None:
        raise _denied("OA authorization revision is malformed")
    return revision


def _transaction_projection(transaction) -> dict[str, Any]:
    return {
        "schema_version": BUDGET_RESULT_SCHEMA,
        "tenant_id": transaction.tenant_id,
        "business_operation_id": transaction.business_operation_id,
        "idempotency_key": transaction.idempotency_key,
        "payload_hash": transaction.payload_hash,
        "commit_state": transaction.commit_state,
        "idempotency_disposition": "CREATED" if transaction.created else "REPLAYED",
        **transaction.result,
        "outbox": {
            "outbox_id": transaction.outbox_id,
            "event_id": transaction.event_id,
            "event_type": transaction.event_type,
            "event_payload_hash": transaction.event_payload_hash,
        },
    }


def _budget_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BUDGET_RESULT_SCHEMA,
        "operation": BUDGET_GET_OPERATION,
        "tenant_id": str(record["tenant_id"]),
        "company_id": str(record["company_id"]),
        "budget_id": str(record["budget_id"]),
        "budget_version": int(record["budget_version"]),
        "fiscal_year": int(record["fiscal_year"]),
        "account_id": None
        if record["account_id"] is None
        else str(record["account_id"]),
        "budget_category": str(record["budget_category"]),
        "approved_currency": str(record["approved_currency"]),
        "approved_functional_amount": _money_wire(record["approved_functional_amount"]),
        "approved_proof": str(record["approved_proof"]),
        "source_ref": str(record["source_ref"]),
        "source_hash": str(record["source_hash"]),
        "budget_hash": str(record["budget_hash"]),
        "state": str(record["state"]),
    }


def _money_wire(value: object) -> str:
    return format(Decimal(value), ".4f")


def _positive_money(field_name: str, value: object) -> Decimal:
    if not isinstance(value, str) or _MONEY.fullmatch(value) is None:
        raise _invalid(field_name, "must be a canonical four-decimal amount")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise _invalid(field_name, "must be decimal") from exc
    if result <= 0:
        raise _invalid(field_name, "must be greater than zero")
    return result


def _fiscal_year(value: object) -> int:
    year = _positive_int("fiscal_year", value)
    if year < 2000 or year > 9999:
        raise _invalid("fiscal_year", "must be between 2000 and 9999")
    return year


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(field_name, "must be a positive integer")
    return value


def _uuid(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(field_name, "must be a UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _scoped_id(field_name: str, value: object) -> str:
    return _pattern_text(field_name, value, _SCOPED_ID)


def _hash_ref(field_name: str, value: object) -> str:
    return _pattern_text(field_name, value, _HASH_REF)


def _pattern_text(field_name: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _invalid(field_name, "has an invalid format")
    return value


def _text(field_name: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value.strip() != value
        or not value.isprintable()
    ):
        raise _invalid(field_name, "has an invalid format")
    return value


def _aware_time(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(field_name, "must be timezone-aware")
    return value


def _invalid(field_name: str, detail: str) -> EosBudgetError:
    return EosBudgetError(
        "EOS_BUDGET_INVALID", f"{field_name} {detail}", status_code=422
    )


def _not_found(detail: str) -> EosBudgetError:
    return EosBudgetError("EOS_BUDGET_NOT_FOUND", detail, status_code=404)


def _conflict(detail: str) -> EosBudgetError:
    return EosBudgetError("EOS_BUDGET_CONFLICT", detail, status_code=409)


def _denied(detail: str) -> EosBudgetError:
    return EosBudgetError("EOS_BUDGET_AUTHORIZATION_DENIED", detail, status_code=403)


def _unavailable(detail: str) -> EosBudgetError:
    return EosBudgetError(
        "EOS_BUDGET_UNAVAILABLE", detail, status_code=503, retryable=True
    )
