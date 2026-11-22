from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .account_catalog import (
    EOS_COMPANY_ACCOUNT_POLICY_TABLE,
    EOS_POSTING_RULE_RELEASE_TABLE,
)
from .accounts import EOS_ACCOUNT_TABLE
from .business_transactions import EOS_METADATA
from .journal_operations import EosJournalOperationError, EosJournalOperationService
from .journals import EOS_JOURNAL_HEADER_TABLE, EOS_JOURNAL_LINE_TABLE
from .legal_entities import EOS_PROJECT_COMPANY_BINDING_TABLE
from .projects import EOS_PROJECT_TABLE

COST_SOURCE_POOL_ADMIT_OPERATION = "FINANCE.COST_SOURCE_POOL.ADMIT"
COST_SOURCE_POOL_GET_OPERATION = "FINANCE.COST_SOURCE_POOL.GET"
COST_SOURCE_POOL_SCHEMA = "eos_cost_source_pool.v1"

COST_SOURCE_KINDS = frozenset(
    {
        "PAYROLL",
        "PURCHASE",
        "SERVICE",
        "SHARED_EXPENSE",
        "REVENUE",
        "FX_GAIN_LOSS",
        "OTHER",
    }
)
COST_ALLOCATION_MODES = frozenset({"DIRECT", "MANAGEMENT_ALLOCATION"})

_EXPENSE_SOURCE_KINDS = frozenset(
    {"PAYROLL", "PURCHASE", "SERVICE", "SHARED_EXPENSE", "OTHER"}
)
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_POOL_NAMESPACE = uuid.UUID("e1a94254-62a0-5f31-a8e8-3f5fd2f0e04c")

EOS_COST_SOURCE_POOL_TABLE = Table(
    "eos_cost_source_pool",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("pool_id", Uuid(as_uuid=False), primary_key=True),
    Column("journal_id", Uuid(as_uuid=False), nullable=False),
    Column("journal_line_no", Integer, nullable=False),
    Column("eligible_component_id", String(128), nullable=False),
    Column("source_business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("source_project_id", Uuid(as_uuid=False), nullable=False),
    Column("source_project_code", String(11), nullable=False),
    Column("source_kind", String(32), nullable=False),
    Column("allocation_mode", String(32), nullable=False),
    Column("source_amount_functional", Numeric(20, 4), nullable=False),
    Column("eligible_amount_functional", Numeric(20, 4), nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("account_id", Uuid(as_uuid=False), nullable=False),
    Column("account_category", String(16), nullable=False),
    Column("monetary_class", String(16), nullable=False),
    Column("recognition_date", Date, nullable=False),
    Column("recognized_at", DateTime(timezone=True), nullable=False),
    Column("period_id", Uuid(as_uuid=False), nullable=False),
    Column("source_record_ref", String(256), nullable=False),
    Column("source_hash", String(71), nullable=False),
    Column("eligibility_policy_hash", String(71), nullable=False),
    Column("pool_state", String(16), nullable=False),
    Column("source_journal_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "journal_id",
        "journal_line_no",
        "eligible_component_id",
        name="ux_eos_cost_pool_source",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "journal_id"),
        (
            "eos_journal_header.tenant_id",
            "eos_journal_header.company_id",
            "eos_journal_header.journal_id",
        ),
        name="fk_eos_cost_pool_journal",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "journal_id", "journal_line_no"),
        (
            "eos_journal_line.tenant_id",
            "eos_journal_line.company_id",
            "eos_journal_line.journal_id",
            "eos_journal_line.line_no",
        ),
        name="fk_eos_cost_pool_line",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "source_business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_cost_pool_operation",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "source_project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_cost_pool_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_cost_pool_account",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "period_id"),
        (
            "eos_accounting_period.tenant_id",
            "eos_accounting_period.company_id",
            "eos_accounting_period.period_id",
        ),
        name="fk_eos_cost_pool_period",
    ),
    CheckConstraint("journal_line_no > 0", name="ck_eos_cost_pool_line_no"),
    CheckConstraint(
        "source_kind IN ('PAYROLL','PURCHASE','SERVICE','SHARED_EXPENSE',"
        "'REVENUE','FX_GAIN_LOSS','OTHER')",
        name="ck_eos_cost_pool_source_kind",
    ),
    CheckConstraint(
        "allocation_mode IN ('DIRECT','MANAGEMENT_ALLOCATION','GL_COST_TRANSFER')",
        name="ck_eos_cost_pool_mode",
    ),
    CheckConstraint(
        "account_category IN ('REVENUE','EXPENSE')",
        name="ck_eos_cost_pool_category",
    ),
    CheckConstraint(
        "monetary_class IN ('MONETARY','NON_MONETARY')",
        name="ck_eos_cost_pool_monetary",
    ),
    CheckConstraint(
        "pool_state IN ('OPEN','ALLOCATED','REVERSED','ON_HOLD')",
        name="ck_eos_cost_pool_state",
    ),
)
Index(
    "ix_eos_cost_pool_state",
    EOS_COST_SOURCE_POOL_TABLE.c.tenant_id,
    EOS_COST_SOURCE_POOL_TABLE.c.company_id,
    EOS_COST_SOURCE_POOL_TABLE.c.pool_state,
    EOS_COST_SOURCE_POOL_TABLE.c.recognition_date,
    EOS_COST_SOURCE_POOL_TABLE.c.pool_id,
)
Index(
    "ix_eos_cost_pool_project",
    EOS_COST_SOURCE_POOL_TABLE.c.tenant_id,
    EOS_COST_SOURCE_POOL_TABLE.c.company_id,
    EOS_COST_SOURCE_POOL_TABLE.c.source_project_id,
    EOS_COST_SOURCE_POOL_TABLE.c.recognition_date,
)


class EosCostSourcePoolError(RuntimeError):
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
class CostSourceFacts:
    tenant_id: str
    company_id: str
    journal_id: str
    journal_line_no: int
    business_operation_id: str
    journal_hash: str
    journal_state: str
    recognition_date: date
    period_id: str
    posted_at: datetime
    account_id: str
    account_category: str
    is_monetary: bool
    account_policy_release_hash: str
    posting_rule_release_hash: str
    project_id: str
    project_code: str
    project_status: str
    project_company_binding_hash: str
    debit_functional: Decimal
    credit_functional: Decimal
    functional_currency: str
    source_record_ref: str
    evidence_hash: str
    line_hash: str


class CostSourceFactsSource(Protocol):
    def load(
        self,
        *,
        tenant_id: str,
        company_id: str,
        journal_id: str,
        journal_line_no: int,
    ) -> CostSourceFacts | None: ...


class SqlAlchemyEosCostSourceFactsSource:
    """Loads exact, reconciled source facts from immutable PostedJournal state."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._operations = EosJournalOperationService(session_factory)

    def load(
        self,
        *,
        tenant_id: str,
        company_id: str,
        journal_id: str,
        journal_line_no: int,
    ) -> CostSourceFacts | None:
        try:
            with self._session_factory() as session:
                header = (
                    session.execute(
                        select(
                            EOS_JOURNAL_HEADER_TABLE.c.business_operation_id
                        ).where(
                            EOS_JOURNAL_HEADER_TABLE.c.tenant_id == tenant_id,
                            EOS_JOURNAL_HEADER_TABLE.c.company_id == company_id,
                            EOS_JOURNAL_HEADER_TABLE.c.journal_id == journal_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            if header is None:
                return None
            reconciliation = self._operations.reconcile(
                tenant_id=tenant_id,
                business_operation_id=str(header["business_operation_id"]),
            )
            if (
                reconciliation["reconciliation_status"] != "COMMITTED_CONFIRMED"
                or reconciliation["verification_status"] != "VERIFIED"
            ):
                raise EosCostSourcePoolError(
                    "EOS_COST_SOURCE_JOURNAL_UNVERIFIED",
                    "Cost source requires a verified committed PostedJournal",
                    status_code=409,
                )
            with self._session_factory() as session:
                row = (
                    session.execute(
                        _source_facts_statement(
                            tenant_id=tenant_id,
                            company_id=company_id,
                            journal_id=journal_id,
                            journal_line_no=journal_line_no,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except EosCostSourcePoolError:
            raise
        except EosJournalOperationError as exc:
            raise EosCostSourcePoolError(
                "EOS_COST_SOURCE_JOURNAL_UNVERIFIED",
                exc.detail,
                status_code=409 if exc.status_code < 500 else 503,
                retryable=exc.retryable,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        if row is None:
            return None
        return CostSourceFacts(
            tenant_id=str(row["tenant_id"]),
            company_id=str(row["company_id"]),
            journal_id=str(row["journal_id"]),
            journal_line_no=int(row["journal_line_no"]),
            business_operation_id=str(row["business_operation_id"]),
            journal_hash=str(row["journal_hash"]),
            journal_state=str(row["journal_state"]),
            recognition_date=row["recognition_date"],
            period_id=str(row["period_id"]),
            posted_at=row["posted_at"],
            account_id=str(row["account_id"]),
            account_category=str(row["account_category"]),
            is_monetary=bool(row["is_monetary"]),
            account_policy_release_hash=str(row["account_policy_release_hash"]),
            posting_rule_release_hash=str(row["posting_rule_release_hash"]),
            project_id=str(row["project_id"]),
            project_code=str(row["project_code"]),
            project_status=str(row["project_status"]),
            project_company_binding_hash=str(row["project_company_binding_hash"]),
            debit_functional=Decimal(row["debit_functional"]),
            credit_functional=Decimal(row["credit_functional"]),
            functional_currency=str(row["functional_currency"]),
            source_record_ref=str(row["source_record_ref"]),
            evidence_hash=str(row["evidence_hash"]),
            line_hash=str(row["line_hash"]),
        )


class SqlAlchemyEosCostSourcePoolRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_or_replay(
        self, record: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        try:
            with self._session_factory.begin() as session:
                existing = _source_row(session, record)
                if existing is not None:
                    return _require_exact_replay(existing, record), False
                session.execute(EOS_COST_SOURCE_POOL_TABLE.insert().values(**record))
                return dict(record), True
        except EosCostSourcePoolError:
            raise
        except IntegrityError:
            return self._replay_after_race(record)
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def get(
        self, *, tenant_id: str, company_id: str, pool_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_COST_SOURCE_POOL_TABLE).where(
                            EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == tenant_id,
                            EOS_COST_SOURCE_POOL_TABLE.c.company_id == company_id,
                            EOS_COST_SOURCE_POOL_TABLE.c.pool_id == pool_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(row) if row is not None else None

    def _replay_after_race(
        self, record: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        try:
            with self._session_factory() as session:
                existing = _source_row(session, record)
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        if existing is None:
            raise _persistence_error()
        return _require_exact_replay(existing, record), False


class EosCostSourcePoolService:
    def __init__(
        self,
        *,
        source: CostSourceFactsSource,
        repository: SqlAlchemyEosCostSourcePoolRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def admit(
        self,
        *,
        tenant_id: str,
        company_id: str,
        journal_id: str,
        journal_line_no: int,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        company_id = _uuid("company_id", company_id)
        journal_id = _uuid("journal_id", journal_id)
        journal_line_no = _positive_int("journal_line_no", journal_line_no)
        source_kind, allocation_mode = _admit_payload(payload)
        facts = self._source.load(
            tenant_id=tenant_id,
            company_id=company_id,
            journal_id=journal_id,
            journal_line_no=journal_line_no,
        )
        if facts is None:
            raise EosCostSourcePoolError(
                "EOS_COST_SOURCE_NOT_FOUND",
                "PostedJournal line or its effective Project-company binding was not found",
                status_code=404,
            )
        record = _build_pool_record(
            facts,
            source_kind=source_kind,
            allocation_mode=allocation_mode,
            created_at=_utc_time("created_at", self._clock()),
        )
        stored, created = self._repository.create_or_replay(record)
        return _projection(stored, created=created, operation=COST_SOURCE_POOL_ADMIT_OPERATION)

    def get(
        self, *, tenant_id: str, company_id: str, pool_id: str
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        company_id = _uuid("company_id", company_id)
        pool_id = _uuid("pool_id", pool_id)
        record = self._repository.get(
            tenant_id=tenant_id, company_id=company_id, pool_id=pool_id
        )
        if record is None:
            raise EosCostSourcePoolError(
                "EOS_COST_SOURCE_POOL_NOT_FOUND",
                "Cost SourcePool was not found in tenant and company scope",
                status_code=404,
            )
        return _projection(record, created=False, operation=COST_SOURCE_POOL_GET_OPERATION)


def _source_facts_statement(
    *, tenant_id: str, company_id: str, journal_id: str, journal_line_no: int
):
    header = EOS_JOURNAL_HEADER_TABLE
    line = EOS_JOURNAL_LINE_TABLE
    account = EOS_ACCOUNT_TABLE
    policy = EOS_COMPANY_ACCOUNT_POLICY_TABLE
    rule = EOS_POSTING_RULE_RELEASE_TABLE
    project = EOS_PROJECT_TABLE
    binding = EOS_PROJECT_COMPANY_BINDING_TABLE
    return (
        select(
            header.c.tenant_id,
            header.c.company_id,
            header.c.journal_id,
            line.c.line_no.label("journal_line_no"),
            header.c.business_operation_id,
            header.c.journal_hash,
            header.c.state.label("journal_state"),
            header.c.recognition_date,
            header.c.period_id,
            header.c.posted_at,
            line.c.account_id,
            account.c.category.label("account_category"),
            policy.c.is_monetary,
            policy.c.approved_proof_ref.label("account_policy_release_hash"),
            rule.c.rule_hash.label("posting_rule_release_hash"),
            line.c.project_id,
            line.c.project_code,
            project.c.status.label("project_status"),
            binding.c.approved_proof_hash.label("project_company_binding_hash"),
            line.c.debit_functional,
            line.c.credit_functional,
            line.c.functional_currency,
            line.c.source_record_line_ref.label("source_record_ref"),
            line.c.evidence_hash,
            line.c.line_hash,
        )
        .join(
            line,
            (line.c.tenant_id == header.c.tenant_id)
            & (line.c.company_id == header.c.company_id)
            & (line.c.journal_id == header.c.journal_id),
        )
        .join(
            account,
            (account.c.tenant_id == line.c.tenant_id)
            & (account.c.account_id == line.c.account_id),
        )
        .join(
            policy,
            (policy.c.tenant_id == line.c.tenant_id)
            & (policy.c.policy_id == line.c.account_policy_id)
            & (policy.c.company_id == line.c.company_id)
            & (policy.c.account_id == line.c.account_id),
        )
        .join(
            rule,
            (rule.c.tenant_id == policy.c.tenant_id)
            & (rule.c.posting_rule_id == policy.c.posting_rule_id)
            & (rule.c.company_id == policy.c.company_id),
        )
        .join(
            project,
            (project.c.tenant_id == line.c.tenant_id)
            & (project.c.project_id == line.c.project_id)
            & (project.c.project_code == line.c.project_code),
        )
        .join(
            binding,
            (binding.c.tenant_id == line.c.tenant_id)
            & (binding.c.project_id == line.c.project_id)
            & (binding.c.company_id == line.c.company_id)
            & (binding.c.state == "APPROVED")
            & (binding.c.valid_from <= header.c.recognition_date)
            & (
                binding.c.valid_until.is_(None)
                | (binding.c.valid_until > header.c.recognition_date)
            ),
        )
        .where(
            header.c.tenant_id == tenant_id,
            header.c.company_id == company_id,
            header.c.journal_id == journal_id,
            header.c.state == "POSTED",
            line.c.line_no == journal_line_no,
            line.c.account_policy_release_hash == policy.c.approved_proof_ref,
            line.c.posting_rule_release_hash == rule.c.rule_hash,
            project.c.status.in_(("ACTIVE", "CLOSING")),
        )
    )


def _admit_payload(payload: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "source_kind",
        "allocation_mode",
    }:
        raise _invalid("payload", "must contain only canonical admission fields")
    if payload.get("schema_version") != "eos_cost_source_pool_admit.v1":
        raise _invalid("schema_version", "is not supported")
    source_kind = _choice("source_kind", payload.get("source_kind"), COST_SOURCE_KINDS)
    allocation_mode = _choice(
        "allocation_mode", payload.get("allocation_mode"), COST_ALLOCATION_MODES
    )
    return source_kind, allocation_mode


def _build_pool_record(
    facts: CostSourceFacts,
    *,
    source_kind: str,
    allocation_mode: str,
    created_at: datetime,
) -> dict[str, Any]:
    if facts.journal_state != "POSTED":
        raise _ineligible("Source Journal is not POSTED")
    category = facts.account_category
    if category not in {"EXPENSE", "REVENUE"}:
        raise _ineligible(
            "Cash, liability, equity, inventory, asset, and deferred-cost lines are not eligible"
        )
    if source_kind in _EXPENSE_SOURCE_KINDS and category != "EXPENSE":
        raise _ineligible("Expense source kind requires an EXPENSE account")
    if source_kind == "REVENUE" and category != "REVENUE":
        raise _ineligible("REVENUE source kind requires a REVENUE account")
    if facts.project_status not in {"ACTIVE", "CLOSING"}:
        raise _ineligible("Source Project is not active for financial attribution")
    amount = (
        facts.debit_functional - facts.credit_functional
        if category == "EXPENSE"
        else facts.credit_functional - facts.debit_functional
    )
    amount = _decimal_amount("source_amount_functional", amount)
    if amount == 0:
        raise _ineligible("Zero-value Journal components cannot enter a SourcePool")
    component_id = f"ACCOUNT:{facts.account_id}"
    identity = (
        f"{facts.tenant_id}/{facts.company_id}/{facts.journal_id}/"
        f"{facts.journal_line_no}/{component_id}"
    )
    pool_id = str(uuid.uuid5(_POOL_NAMESPACE, identity))
    policy_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-SOURCE-ELIGIBILITY-POLICY-V1",
            "account_category": category,
            "account_policy_release_hash": facts.account_policy_release_hash,
            "posting_rule_release_hash": facts.posting_rule_release_hash,
            "project_company_binding_hash": facts.project_company_binding_hash,
            "source_kind": source_kind,
        }
    )
    source_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-SOURCE-POOL-V1",
            "identity": identity,
            "journal_hash": facts.journal_hash,
            "line_hash": facts.line_hash,
            "evidence_hash": facts.evidence_hash,
            "eligibility_policy_hash": policy_hash,
            "allocation_mode": allocation_mode,
            "source_amount_functional": _amount_text(amount),
        }
    )
    return {
        "tenant_id": facts.tenant_id,
        "company_id": facts.company_id,
        "pool_id": pool_id,
        "journal_id": facts.journal_id,
        "journal_line_no": facts.journal_line_no,
        "eligible_component_id": component_id,
        "source_business_operation_id": facts.business_operation_id,
        "source_project_id": facts.project_id,
        "source_project_code": facts.project_code,
        "source_kind": source_kind,
        "allocation_mode": allocation_mode,
        "source_amount_functional": amount,
        "eligible_amount_functional": amount,
        "functional_currency": facts.functional_currency,
        "account_id": facts.account_id,
        "account_category": category,
        "monetary_class": "MONETARY" if facts.is_monetary else "NON_MONETARY",
        "recognition_date": facts.recognition_date,
        "recognized_at": _utc_time("recognized_at", facts.posted_at),
        "period_id": facts.period_id,
        "source_record_ref": facts.source_record_ref,
        "source_hash": source_hash,
        "eligibility_policy_hash": policy_hash,
        "pool_state": "ALLOCATED" if allocation_mode == "DIRECT" else "OPEN",
        "source_journal_hash": facts.journal_hash,
        "created_at": created_at,
    }


def _source_row(
    session: Session, record: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_COST_SOURCE_POOL_TABLE).where(
                EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == record["tenant_id"],
                EOS_COST_SOURCE_POOL_TABLE.c.company_id == record["company_id"],
                EOS_COST_SOURCE_POOL_TABLE.c.journal_id == record["journal_id"],
                EOS_COST_SOURCE_POOL_TABLE.c.journal_line_no
                == record["journal_line_no"],
                EOS_COST_SOURCE_POOL_TABLE.c.eligible_component_id
                == record["eligible_component_id"],
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_exact_replay(
    existing: Mapping[str, Any], requested: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        str(existing["source_hash"]) != str(requested["source_hash"])
        or str(existing["allocation_mode"]) != str(requested["allocation_mode"])
        or str(existing["source_kind"]) != str(requested["source_kind"])
    ):
        raise EosCostSourcePoolError(
            "EOS_COST_SOURCE_POOL_CONFLICT",
            "Journal component already has a SourcePool with different semantics",
            status_code=409,
        )
    return dict(existing)


def _projection(
    record: Mapping[str, Any], *, created: bool, operation: str
) -> dict[str, Any]:
    return {
        "schema_version": COST_SOURCE_POOL_SCHEMA,
        "operation": operation,
        "idempotency_disposition": "CREATED" if created else "EXACT_REPLAY",
        "tenant_id": str(record["tenant_id"]),
        "company_id": str(record["company_id"]),
        "pool_id": str(record["pool_id"]),
        "journal_id": str(record["journal_id"]),
        "journal_line_no": int(record["journal_line_no"]),
        "eligible_component_id": str(record["eligible_component_id"]),
        "source_business_operation_id": str(record["source_business_operation_id"]),
        "source_project_id": str(record["source_project_id"]),
        "source_project_code": str(record["source_project_code"]),
        "source_kind": str(record["source_kind"]),
        "allocation_mode": str(record["allocation_mode"]),
        "source_amount_functional": _amount_text(record["source_amount_functional"]),
        "eligible_amount_functional": _amount_text(
            record["eligible_amount_functional"]
        ),
        "functional_currency": str(record["functional_currency"]),
        "account_id": str(record["account_id"]),
        "account_category": str(record["account_category"]),
        "monetary_class": str(record["monetary_class"]),
        "recognition_date": record["recognition_date"].isoformat(),
        "recognized_at": _wire_time(record["recognized_at"]),
        "period_id": str(record["period_id"]),
        "source_record_ref": str(record["source_record_ref"]),
        "source_hash": str(record["source_hash"]),
        "eligibility_policy_hash": str(record["eligibility_policy_hash"]),
        "pool_state": str(record["pool_state"]),
        "source_journal_hash": str(record["source_journal_hash"]),
        "created_at": _wire_time(record["created_at"]),
    }


def _amount_text(value: object) -> str:
    amount = _decimal_amount("amount", value).quantize(Decimal("0.0001"))
    return format(amount, "f")


def _decimal_amount(field_name: str, value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid(field_name, "must be a decimal amount") from exc
    if not amount.is_finite() or amount.as_tuple().exponent < -4:
        raise _invalid(field_name, "must be finite with at most four decimals")
    return amount


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _SCOPED_ID.fullmatch(normalized):
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field_name, "must be a positive integer")
    return value


def _choice(field_name: str, value: object, choices: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in choices:
        raise _invalid(field_name, f"must be one of {sorted(choices)}")
    return normalized


def _utc_time(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(field_name, "must be a timezone-aware timestamp")
    return value.astimezone(UTC)


def _wire_time(value: object) -> str:
    if not isinstance(value, datetime):
        raise _invalid("timestamp", "must be a timestamp")
    normalized = (
        value.replace(tzinfo=UTC)
        if value.tzinfo is None
        else value.astimezone(UTC)
    )
    return normalized.isoformat().replace("+00:00", "Z")


def _invalid(field_name: str, detail: str) -> EosCostSourcePoolError:
    return EosCostSourcePoolError(
        "EOS_COST_SOURCE_POOL_INVALID",
        f"{field_name} {detail}",
        status_code=422,
    )


def _ineligible(detail: str) -> EosCostSourcePoolError:
    return EosCostSourcePoolError(
        "EOS_COST_SOURCE_INELIGIBLE", detail, status_code=409
    )


def _persistence_error() -> EosCostSourcePoolError:
    return EosCostSourcePoolError(
        "EOS_COST_SOURCE_POOL_UNAVAILABLE",
        "Cost SourcePool persistence is unavailable",
        status_code=503,
        retryable=True,
    )
