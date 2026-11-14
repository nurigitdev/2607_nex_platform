from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
    Boolean,
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

from .business_transactions import EOS_METADATA
from .cost_source_pools import EOS_COST_SOURCE_POOL_TABLE
from .legal_entities import (
    EOS_PROJECT_COMPANY_BINDING_TABLE,
)
from .project_work_assignments import EOS_PROJECT_WORK_ASSIGNMENT_TABLE
from .projects import EOS_PROJECT_TABLE

PAYROLL_POSTING_EVIDENCE_SCHEMA = "eos_payroll_posting_evidence.v1"
LABOR_EFFORT_SNAPSHOT_SCHEMA = "eos_labor_effort_snapshot.v1"

PAYROLL_COMPONENT_CLASSES = frozenset(
    {
        "BASE_SALARY",
        "OVERTIME",
        "BONUS_INCENTIVE",
        "EMPLOYER_INSURANCE",
        "EMPLOYER_TAX",
        "WELFARE_BENEFIT",
        "PAID_NON_PRODUCTIVE",
        "CORRECTION_REVERSAL",
        "OTHER_APPROVED",
    }
)
LABOR_EFFORT_BASIS_KINDS = frozenset({"ACTUAL_APPROVED", "APPROVED_PLAN_FALLBACK"})
LABOR_EFFORT_UNITS = frozenset({"MAN_DAY", "HOUR"})
LABOR_EFFORT_STATES = frozenset({"APPROVED", "SUPERSEDED", "REVOKED"})

_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_STABLE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,255}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_MONEY_QUANTUM = Decimal("0.0001")
_EFFORT_QUANTUM = Decimal("0.0001")
_PAYROLL_NAMESPACE = uuid.UUID("24d26aba-a56b-50f0-a931-e717cd08a8be")
_EFFORT_NAMESPACE = uuid.UUID("3d00f9b0-0845-54b4-b6b9-729f8774dd9c")


EOS_PAYROLL_POST_EVIDENCE_TABLE = Table(
    "eos_payroll_post_evidence",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("evidence_id", Uuid(as_uuid=False), primary_key=True),
    Column("payroll_run_id", String(128), nullable=False),
    Column("payroll_period_start", Date, nullable=False),
    Column("payroll_period_end", Date, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("pool_id", Uuid(as_uuid=False), nullable=False),
    Column("journal_id", Uuid(as_uuid=False), nullable=False),
    Column("journal_line_no", Integer, nullable=False),
    Column("period_id", Uuid(as_uuid=False), nullable=False),
    Column("eligible_component_id", String(128), nullable=False),
    Column("payroll_component_class", String(32), nullable=False),
    Column("organization_ref", String(256), nullable=True),
    Column("account_id", Uuid(as_uuid=False), nullable=False),
    Column("eligible_amount_functional", Numeric(20, 4), nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("payroll_source_ref", String(256), nullable=False),
    Column("payroll_source_hash", String(71), nullable=False),
    Column("approval_ref", String(256), nullable=False),
    Column("approval_hash", String(71), nullable=False),
    Column("posting_mapping_hash", String(71), nullable=False),
    Column("reconciliation_state", String(16), nullable=False),
    Column("privacy_class", String(32), nullable=False),
    Column("evidence_hash", String(71), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "payroll_run_id",
        "revision",
        "pool_id",
        name="ux_eos_payroll_post_identity",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "evidence_hash",
        name="ux_eos_payroll_post_hash",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "pool_id"),
        (
            "eos_cost_source_pool.tenant_id",
            "eos_cost_source_pool.company_id",
            "eos_cost_source_pool.pool_id",
        ),
        name="fk_eos_payroll_post_pool",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "period_id"),
        (
            "eos_accounting_period.tenant_id",
            "eos_accounting_period.company_id",
            "eos_accounting_period.period_id",
        ),
        name="fk_eos_payroll_post_period",
    ),
    CheckConstraint("revision > 0", name="ck_eos_payroll_post_revision"),
    CheckConstraint(
        "payroll_period_end >= payroll_period_start",
        name="ck_eos_payroll_post_period",
    ),
    CheckConstraint("journal_line_no > 0", name="ck_eos_payroll_post_line"),
    CheckConstraint(
        "eligible_amount_functional <> 0", name="ck_eos_payroll_post_amount"
    ),
    CheckConstraint(
        "reconciliation_state IN ('VERIFIED','PENDING','BLOCKED')",
        name="ck_eos_payroll_post_reconcile",
    ),
    CheckConstraint(
        "privacy_class = 'PAYROLL_AGGREGATE'",
        name="ck_eos_payroll_post_privacy",
    ),
)
Index(
    "ix_eos_payroll_post_period",
    EOS_PAYROLL_POST_EVIDENCE_TABLE.c.tenant_id,
    EOS_PAYROLL_POST_EVIDENCE_TABLE.c.company_id,
    EOS_PAYROLL_POST_EVIDENCE_TABLE.c.payroll_period_end,
    EOS_PAYROLL_POST_EVIDENCE_TABLE.c.payroll_run_id,
)


EOS_LABOR_EFFORT_SNAPSHOT_TABLE = Table(
    "eos_labor_effort_snapshot",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("snapshot_id", Uuid(as_uuid=False), primary_key=True),
    Column("effort_period_start", Date, nullable=False),
    Column("effort_period_end", Date, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("basis_kind", String(32), nullable=False),
    Column("effort_unit", String(16), nullable=False),
    Column("source_ref", String(256), nullable=False),
    Column("source_hash", String(71), nullable=False),
    Column("evidence_cutoff_at", DateTime(timezone=True), nullable=False),
    Column("approval_ref", String(256), nullable=False),
    Column("approval_hash", String(71), nullable=False),
    Column("state", String(16), nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("privacy_class", String(32), nullable=False),
    Column("snapshot_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "source_ref",
        "revision",
        name="ux_eos_labor_snapshot_source",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "snapshot_hash",
        name="ux_eos_labor_snapshot_hash",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_labor_snapshot_company",
    ),
    CheckConstraint("revision > 0", name="ck_eos_labor_snapshot_revision"),
    CheckConstraint(
        "effort_period_end >= effort_period_start",
        name="ck_eos_labor_snapshot_period",
    ),
    CheckConstraint(
        "basis_kind IN ('ACTUAL_APPROVED','APPROVED_PLAN_FALLBACK')",
        name="ck_eos_labor_snapshot_basis",
    ),
    CheckConstraint(
        "effort_unit IN ('MAN_DAY','HOUR')", name="ck_eos_labor_snapshot_unit"
    ),
    CheckConstraint(
        "state IN ('APPROVED','SUPERSEDED','REVOKED')",
        name="ck_eos_labor_snapshot_state",
    ),
    CheckConstraint(
        "privacy_class = 'LABOR_AGGREGATE'",
        name="ck_eos_labor_snapshot_privacy",
    ),
)
Index(
    "ix_eos_labor_snapshot_period",
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.tenant_id,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.company_id,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.effort_period_end,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.state,
)


EOS_LABOR_EFFORT_LINE_TABLE = Table(
    "eos_labor_effort_line",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("snapshot_id", Uuid(as_uuid=False), primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("project_code", String(11), nullable=False),
    Column("work_code", String(16), nullable=True),
    Column("organization_ref", String(256), nullable=True),
    Column("grade_band", String(64), nullable=True),
    Column("cost_cohort", String(64), nullable=True),
    Column("effort_units", Numeric(16, 4), nullable=False),
    Column("population_count", Integer, nullable=False),
    Column("minimum_population", Integer, nullable=False),
    Column("ordinary_view_suppressed", Boolean, nullable=False),
    Column("work_assignment_id", Uuid(as_uuid=False), nullable=True),
    Column("basis_source_ref", String(256), nullable=False),
    Column("basis_source_hash", String(71), nullable=False),
    Column("line_hash", String(71), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "snapshot_id"),
        (
            "eos_labor_effort_snapshot.tenant_id",
            "eos_labor_effort_snapshot.company_id",
            "eos_labor_effort_snapshot.snapshot_id",
        ),
        name="fk_eos_labor_effort_snapshot",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_labor_effort_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "work_assignment_id"),
        (
            "eos_project_work_assignment.tenant_id",
            "eos_project_work_assignment.assignment_id",
        ),
        name="fk_eos_labor_effort_assignment",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "snapshot_id",
        "line_hash",
        name="ux_eos_labor_effort_line_hash",
    ),
    CheckConstraint("line_no > 0", name="ck_eos_labor_effort_line"),
    CheckConstraint("effort_units > 0", name="ck_eos_labor_effort_units"),
    CheckConstraint(
        "population_count > 0 AND minimum_population > 0",
        name="ck_eos_labor_effort_population",
    ),
)
Index(
    "ix_eos_labor_effort_project",
    EOS_LABOR_EFFORT_LINE_TABLE.c.tenant_id,
    EOS_LABOR_EFFORT_LINE_TABLE.c.company_id,
    EOS_LABOR_EFFORT_LINE_TABLE.c.project_id,
    EOS_LABOR_EFFORT_LINE_TABLE.c.work_code,
)


class EosPayrollLaborBridgeError(RuntimeError):
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
class PayrollPostingEvidenceInput:
    tenant_id: str
    company_id: str
    payroll_run_id: str
    payroll_period_start: date
    payroll_period_end: date
    revision: int
    pool_id: str
    payroll_component_class: str
    payroll_source_ref: str
    payroll_source_hash: str
    approval_ref: str
    approval_hash: str
    organization_ref: str | None = None


@dataclass(frozen=True)
class LaborEffortLineInput:
    project_id: str
    project_code: str
    work_code: str | None
    effort_units: Decimal
    population_count: int
    minimum_population: int
    basis_source_ref: str | None = None
    basis_source_hash: str | None = None
    work_assignment_id: str | None = None
    organization_ref: str | None = None
    grade_band: str | None = None
    cost_cohort: str | None = None


@dataclass(frozen=True)
class LaborEffortSnapshotInput:
    tenant_id: str
    company_id: str
    effort_period_start: date
    effort_period_end: date
    revision: int
    basis_kind: str
    effort_unit: str
    source_ref: str
    source_hash: str
    evidence_cutoff_at: datetime
    approval_ref: str
    approval_hash: str
    approved_at: datetime
    lines: Sequence[LaborEffortLineInput]


class SqlAlchemyEosPayrollLaborBridgeRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append_payroll_evidence(
        self, value: PayrollPostingEvidenceInput, *, recorded_at: datetime
    ) -> tuple[dict[str, Any], bool]:
        validated = _validate_payroll_input(value)
        try:
            with self._session_factory.begin() as session:
                pool = _load_payroll_pool(
                    session,
                    tenant_id=validated.tenant_id,
                    company_id=validated.company_id,
                    pool_id=validated.pool_id,
                )
                if pool is None:
                    raise _not_found("Payroll SourcePool was not found")
                record = _build_payroll_record(validated, pool, recorded_at)
                existing = _payroll_identity_row(session, record)
                if existing is not None:
                    return _require_replay(existing, record, "evidence_hash"), False
                session.execute(
                    EOS_PAYROLL_POST_EVIDENCE_TABLE.insert().values(**record)
                )
                return record, True
        except EosPayrollLaborBridgeError:
            raise
        except IntegrityError as exc:
            return self._payroll_race_replay(value, recorded_at, exc)
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def append_effort_snapshot(
        self, value: LaborEffortSnapshotInput, *, created_at: datetime
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], bool]:
        validated = _validate_snapshot_input(value)
        try:
            with self._session_factory.begin() as session:
                lines = _build_effort_lines(session, validated)
                header = _build_snapshot_record(validated, lines, created_at)
                existing = _snapshot_identity_row(session, header)
                if existing is not None:
                    stored = _require_replay(existing, header, "snapshot_hash")
                    return stored, _snapshot_lines(session, stored), False
                session.execute(
                    EOS_LABOR_EFFORT_SNAPSHOT_TABLE.insert().values(**header)
                )
                session.execute(EOS_LABOR_EFFORT_LINE_TABLE.insert(), lines)
                return header, tuple(lines), True
        except EosPayrollLaborBridgeError:
            raise
        except IntegrityError as exc:
            return self._snapshot_race_replay(value, created_at, exc)
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def get_payroll_evidence(
        self, *, tenant_id: str, company_id: str, evidence_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_PAYROLL_POST_EVIDENCE_TABLE).where(
                            EOS_PAYROLL_POST_EVIDENCE_TABLE.c.tenant_id
                            == _tenant(tenant_id),
                            EOS_PAYROLL_POST_EVIDENCE_TABLE.c.company_id
                            == _uuid("company_id", company_id),
                            EOS_PAYROLL_POST_EVIDENCE_TABLE.c.evidence_id
                            == _uuid("evidence_id", evidence_id),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except EosPayrollLaborBridgeError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(row) if row is not None else None

    def get_effort_snapshot(
        self, *, tenant_id: str, company_id: str, snapshot_id: str
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_LABOR_EFFORT_SNAPSHOT_TABLE).where(
                            EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.tenant_id
                            == _tenant(tenant_id),
                            EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.company_id
                            == _uuid("company_id", company_id),
                            EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.snapshot_id
                            == _uuid("snapshot_id", snapshot_id),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None
                header = dict(row)
                return header, _snapshot_lines(session, header)
        except EosPayrollLaborBridgeError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def _payroll_race_replay(
        self,
        value: PayrollPostingEvidenceInput,
        recorded_at: datetime,
        cause: Exception,
    ) -> tuple[dict[str, Any], bool]:
        try:
            with self._session_factory() as session:
                pool = _load_payroll_pool(
                    session,
                    tenant_id=value.tenant_id,
                    company_id=value.company_id,
                    pool_id=value.pool_id,
                )
                if pool is None:
                    raise _not_found("Payroll SourcePool was not found")
                record = _build_payroll_record(value, pool, recorded_at)
                existing = _payroll_identity_row(session, record)
                if existing is None:
                    raise _persistence_error() from cause
                return _require_replay(existing, record, "evidence_hash"), False
        except EosPayrollLaborBridgeError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def _snapshot_race_replay(
        self,
        value: LaborEffortSnapshotInput,
        created_at: datetime,
        cause: Exception,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], bool]:
        try:
            with self._session_factory() as session:
                lines = _build_effort_lines(session, value)
                header = _build_snapshot_record(value, lines, created_at)
                existing = _snapshot_identity_row(session, header)
                if existing is None:
                    raise _persistence_error() from cause
                stored = _require_replay(existing, header, "snapshot_hash")
                return stored, _snapshot_lines(session, stored), False
        except EosPayrollLaborBridgeError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc


class EosPayrollLaborBridgeService:
    def __init__(
        self,
        repository: SqlAlchemyEosPayrollLaborBridgeRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def admit_payroll_posting(
        self, value: PayrollPostingEvidenceInput
    ) -> dict[str, Any]:
        record, created = self._repository.append_payroll_evidence(
            value, recorded_at=_utc_time("recorded_at", self._clock())
        )
        return _payroll_projection(record, created=created)

    def admit_labor_effort(self, value: LaborEffortSnapshotInput) -> dict[str, Any]:
        header, lines, created = self._repository.append_effort_snapshot(
            value, created_at=_utc_time("created_at", self._clock())
        )
        return _effort_projection(header, lines, created=created)

    def get_payroll_posting(
        self, *, tenant_id: str, company_id: str, evidence_id: str
    ) -> dict[str, Any]:
        record = self._repository.get_payroll_evidence(
            tenant_id=tenant_id, company_id=company_id, evidence_id=evidence_id
        )
        if record is None:
            raise _not_found("PayrollPostingEvidence was not found")
        return _payroll_projection(record, created=False)

    def get_labor_effort(
        self, *, tenant_id: str, company_id: str, snapshot_id: str
    ) -> dict[str, Any]:
        stored = self._repository.get_effort_snapshot(
            tenant_id=tenant_id, company_id=company_id, snapshot_id=snapshot_id
        )
        if stored is None:
            raise _not_found("LaborEffortSnapshot was not found")
        return _effort_projection(*stored, created=False)


def _validate_payroll_input(
    value: PayrollPostingEvidenceInput,
) -> PayrollPostingEvidenceInput:
    if not isinstance(value, PayrollPostingEvidenceInput):
        raise _invalid("payroll_evidence", "must be typed input")
    _tenant(value.tenant_id)
    _uuid("company_id", value.company_id)
    _stable_ref("payroll_run_id", value.payroll_run_id, maximum=128)
    _date_range(value.payroll_period_start, value.payroll_period_end)
    _positive_int("revision", value.revision)
    _uuid("pool_id", value.pool_id)
    _choice(
        "payroll_component_class",
        value.payroll_component_class,
        PAYROLL_COMPONENT_CLASSES,
    )
    _stable_ref("payroll_source_ref", value.payroll_source_ref)
    _hash("payroll_source_hash", value.payroll_source_hash)
    _stable_ref("approval_ref", value.approval_ref)
    _hash("approval_hash", value.approval_hash)
    _optional_ref("organization_ref", value.organization_ref)
    return value


def _validate_snapshot_input(
    value: LaborEffortSnapshotInput,
) -> LaborEffortSnapshotInput:
    if not isinstance(value, LaborEffortSnapshotInput):
        raise _invalid("labor_effort_snapshot", "must be typed input")
    _tenant(value.tenant_id)
    _uuid("company_id", value.company_id)
    _date_range(value.effort_period_start, value.effort_period_end)
    _positive_int("revision", value.revision)
    basis_kind = _choice("basis_kind", value.basis_kind, LABOR_EFFORT_BASIS_KINDS)
    effort_unit = _choice("effort_unit", value.effort_unit, LABOR_EFFORT_UNITS)
    if basis_kind == "APPROVED_PLAN_FALLBACK" and effort_unit != "MAN_DAY":
        raise _invalid("effort_unit", "plan fallback requires MAN_DAY")
    _stable_ref("source_ref", value.source_ref)
    _hash("source_hash", value.source_hash)
    _utc_time("evidence_cutoff_at", value.evidence_cutoff_at)
    _stable_ref("approval_ref", value.approval_ref)
    _hash("approval_hash", value.approval_hash)
    _utc_time("approved_at", value.approved_at)
    if value.approved_at < value.evidence_cutoff_at:
        raise _invalid("approved_at", "cannot be before evidence cutoff")
    if not isinstance(value.lines, Sequence) or isinstance(value.lines, (str, bytes)):
        raise _invalid("lines", "must be a non-empty sequence")
    if not value.lines:
        raise _invalid("lines", "must not be empty")
    return value


def _load_payroll_pool(
    session: Session, *, tenant_id: str, company_id: str, pool_id: str
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_COST_SOURCE_POOL_TABLE).where(
                EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == _tenant(tenant_id),
                EOS_COST_SOURCE_POOL_TABLE.c.company_id
                == _uuid("company_id", company_id),
                EOS_COST_SOURCE_POOL_TABLE.c.pool_id == _uuid("pool_id", pool_id),
            )
        )
        .mappings()
        .one_or_none()
    )


def _build_payroll_record(
    value: PayrollPostingEvidenceInput,
    pool: Mapping[str, Any],
    recorded_at: datetime,
) -> dict[str, Any]:
    if str(pool["source_kind"]) != "PAYROLL":
        raise _ineligible("SourcePool is not admitted as PAYROLL")
    if str(pool["account_category"]) != "EXPENSE":
        raise _ineligible("Payroll evidence requires an eligible expense component")
    if str(pool["pool_state"]) in {"REVERSED", "ON_HOLD"}:
        raise _ineligible("Payroll SourcePool is not available for evidence admission")
    amount = _amount("eligible_amount_functional", pool["eligible_amount_functional"])
    currency = str(pool["functional_currency"])
    if not _CURRENCY.fullmatch(currency):
        raise _ineligible("Payroll SourcePool currency is invalid")
    identity = (
        f"{value.tenant_id}/{value.company_id}/{value.payroll_run_id}/"
        f"{value.revision}/{value.pool_id}"
    )
    mapping_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-PAYROLL-POSTING-MAPPING-V1",
            "pool_id": value.pool_id,
            "journal_id": str(pool["journal_id"]),
            "journal_line_no": int(pool["journal_line_no"]),
            "eligible_component_id": str(pool["eligible_component_id"]),
            "account_id": str(pool["account_id"]),
            "eligible_amount_functional": _decimal_text(amount),
            "functional_currency": currency,
            "source_hash": str(pool["source_hash"]),
            "source_journal_hash": str(pool["source_journal_hash"]),
        }
    )
    evidence_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-PAYROLL-POSTING-EVIDENCE-V1",
            "identity": identity,
            "payroll_period_start": value.payroll_period_start.isoformat(),
            "payroll_period_end": value.payroll_period_end.isoformat(),
            "component_class": value.payroll_component_class,
            "organization_ref": value.organization_ref,
            "payroll_source_ref": value.payroll_source_ref,
            "payroll_source_hash": value.payroll_source_hash,
            "approval_ref": value.approval_ref,
            "approval_hash": value.approval_hash,
            "posting_mapping_hash": mapping_hash,
        }
    )
    return {
        "tenant_id": value.tenant_id,
        "company_id": value.company_id,
        "evidence_id": str(uuid.uuid5(_PAYROLL_NAMESPACE, identity)),
        "payroll_run_id": value.payroll_run_id,
        "payroll_period_start": value.payroll_period_start,
        "payroll_period_end": value.payroll_period_end,
        "revision": value.revision,
        "pool_id": value.pool_id,
        "journal_id": str(pool["journal_id"]),
        "journal_line_no": int(pool["journal_line_no"]),
        "period_id": str(pool["period_id"]),
        "eligible_component_id": str(pool["eligible_component_id"]),
        "payroll_component_class": value.payroll_component_class,
        "organization_ref": value.organization_ref,
        "account_id": str(pool["account_id"]),
        "eligible_amount_functional": amount,
        "functional_currency": currency,
        "payroll_source_ref": value.payroll_source_ref,
        "payroll_source_hash": value.payroll_source_hash,
        "approval_ref": value.approval_ref,
        "approval_hash": value.approval_hash,
        "posting_mapping_hash": mapping_hash,
        "reconciliation_state": "VERIFIED",
        "privacy_class": "PAYROLL_AGGREGATE",
        "evidence_hash": evidence_hash,
        "recorded_at": _utc_time("recorded_at", recorded_at),
    }


def _build_effort_lines(
    session: Session, snapshot: LaborEffortSnapshotInput
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str]] = set()
    for raw in snapshot.lines:
        if not isinstance(raw, LaborEffortLineInput):
            raise _invalid("lines", "must contain typed LaborEffortLineInput values")
        project_id = _uuid("project_id", raw.project_id)
        project_code = _project_code(raw.project_code)
        work_code = _optional_work_code(raw.work_code)
        effort_units = _effort("effort_units", raw.effort_units)
        population_count = _positive_int("population_count", raw.population_count)
        minimum_population = _positive_int("minimum_population", raw.minimum_population)
        _require_project_company(
            session,
            tenant_id=snapshot.tenant_id,
            company_id=snapshot.company_id,
            project_id=project_id,
            project_code=project_code,
            effective_start=snapshot.effort_period_start,
            effective_end=snapshot.effort_period_end,
        )
        if snapshot.basis_kind == "APPROVED_PLAN_FALLBACK":
            source_ref, source_hash, grade_band = _require_plan_assignment(
                session, snapshot=snapshot, line=raw, effort_units=effort_units
            )
        else:
            if raw.work_assignment_id is not None:
                raise _invalid(
                    "work_assignment_id",
                    "actual effort cannot masquerade as a plan fallback",
                )
            source_ref = _stable_ref("basis_source_ref", raw.basis_source_ref)
            source_hash = _hash("basis_source_hash", raw.basis_source_hash)
            grade_band = _optional_dimension("grade_band", raw.grade_band)
        organization_ref = _optional_ref("organization_ref", raw.organization_ref)
        cost_cohort = _optional_dimension("cost_cohort", raw.cost_cohort)
        identity = (project_id, work_code, source_ref)
        if identity in seen:
            raise _invalid("lines", "contain duplicate Project/work/source identity")
        seen.add(identity)
        prepared.append(
            {
                "project_id": project_id,
                "project_code": project_code,
                "work_code": work_code,
                "organization_ref": organization_ref,
                "grade_band": grade_band,
                "cost_cohort": cost_cohort,
                "effort_units": effort_units,
                "population_count": population_count,
                "minimum_population": minimum_population,
                "ordinary_view_suppressed": population_count < minimum_population,
                "work_assignment_id": (
                    _uuid("work_assignment_id", raw.work_assignment_id)
                    if raw.work_assignment_id is not None
                    else None
                ),
                "basis_source_ref": source_ref,
                "basis_source_hash": source_hash,
            }
        )
    prepared.sort(
        key=lambda item: (
            item["project_code"],
            item["work_code"] or "",
            item["basis_source_ref"],
        )
    )
    records: list[dict[str, Any]] = []
    snapshot_identity = (
        f"{snapshot.tenant_id}/{snapshot.company_id}/{snapshot.source_ref}/"
        f"{snapshot.revision}"
    )
    snapshot_id = str(uuid.uuid5(_EFFORT_NAMESPACE, snapshot_identity))
    for line_no, item in enumerate(prepared, start=1):
        line_hash = semantic_sha256_hash_ref(
            {
                "domain": "EOS-LABOR-EFFORT-LINE-V1",
                "snapshot_identity": snapshot_identity,
                "project_id": item["project_id"],
                "project_code": item["project_code"],
                "work_code": item["work_code"],
                "organization_ref": item["organization_ref"],
                "grade_band": item["grade_band"],
                "cost_cohort": item["cost_cohort"],
                "effort_units": _decimal_text(item["effort_units"]),
                "population_count": item["population_count"],
                "minimum_population": item["minimum_population"],
                "basis_source_ref": item["basis_source_ref"],
                "basis_source_hash": item["basis_source_hash"],
            }
        )
        records.append(
            {
                "tenant_id": snapshot.tenant_id,
                "company_id": snapshot.company_id,
                "snapshot_id": snapshot_id,
                "line_no": line_no,
                **item,
                "line_hash": line_hash,
            }
        )
    return records


def _require_project_company(
    session: Session,
    *,
    tenant_id: str,
    company_id: str,
    project_id: str,
    project_code: str,
    effective_start: date,
    effective_end: date,
) -> None:
    row = session.execute(
        select(EOS_PROJECT_TABLE.c.status)
        .join(
            EOS_PROJECT_COMPANY_BINDING_TABLE,
            (
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id
                == EOS_PROJECT_TABLE.c.tenant_id
            )
            & (
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id
                == EOS_PROJECT_TABLE.c.project_id
            ),
        )
        .where(
            EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
            EOS_PROJECT_TABLE.c.project_id == project_id,
            EOS_PROJECT_TABLE.c.project_code == project_code,
            EOS_PROJECT_COMPANY_BINDING_TABLE.c.company_id == company_id,
            EOS_PROJECT_COMPANY_BINDING_TABLE.c.state == "APPROVED",
            EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_from <= effective_start,
            (
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until.is_(None)
                | (EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until >= effective_end)
            ),
        )
    ).scalar_one_or_none()
    if row is None:
        raise _ineligible("Project/company binding does not cover the effort period")
    if row not in {"ACTIVE", "CLOSING"}:
        raise _ineligible("Project is not active for labor effort attribution")


def _require_plan_assignment(
    session: Session,
    *,
    snapshot: LaborEffortSnapshotInput,
    line: LaborEffortLineInput,
    effort_units: Decimal,
) -> tuple[str, str, str]:
    if line.work_assignment_id is None:
        raise _invalid(
            "work_assignment_id", "plan fallback requires an approved WorkAssignment"
        )
    assignment_id = _uuid("work_assignment_id", line.work_assignment_id)
    row = (
        session.execute(
            select(EOS_PROJECT_WORK_ASSIGNMENT_TABLE).where(
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.tenant_id == snapshot.tenant_id,
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.assignment_id == assignment_id,
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.project_id == line.project_id,
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.work_code_id == line.work_code,
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.performer_kind == "HUMAN",
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_from
                <= snapshot.effort_period_start,
                (
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until.is_(None)
                    | (
                        EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until
                        >= snapshot.effort_period_end
                    )
                ),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _ineligible("Approved WorkAssignment does not cover the effort line")
    if _effort("planned_man_days", row["planned_man_days"]) != effort_units:
        raise _ineligible("Plan fallback effort must equal approved planned Man-Day")
    expected_ref = f"eos.work-assignment:{assignment_id}"
    if line.basis_source_ref not in (None, expected_ref):
        raise _invalid("basis_source_ref", "does not match WorkAssignment lineage")
    if line.basis_source_hash not in (None, str(row["assignment_hash"])):
        raise _invalid("basis_source_hash", "does not match WorkAssignment hash")
    if line.grade_band not in (None, str(row["planned_grade_id"])):
        raise _invalid("grade_band", "does not match approved planned Grade")
    return expected_ref, str(row["assignment_hash"]), str(row["planned_grade_id"])


def _build_snapshot_record(
    value: LaborEffortSnapshotInput,
    lines: Sequence[Mapping[str, Any]],
    created_at: datetime,
) -> dict[str, Any]:
    identity = (
        f"{value.tenant_id}/{value.company_id}/{value.source_ref}/{value.revision}"
    )
    snapshot_id = str(uuid.uuid5(_EFFORT_NAMESPACE, identity))
    snapshot_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-LABOR-EFFORT-SNAPSHOT-V1",
            "identity": identity,
            "effort_period_start": value.effort_period_start.isoformat(),
            "effort_period_end": value.effort_period_end.isoformat(),
            "basis_kind": value.basis_kind,
            "effort_unit": value.effort_unit,
            "source_hash": value.source_hash,
            "evidence_cutoff_at": _wire_time(value.evidence_cutoff_at),
            "approval_ref": value.approval_ref,
            "approval_hash": value.approval_hash,
            "approved_at": _wire_time(value.approved_at),
            "line_hashes": [str(item["line_hash"]) for item in lines],
        }
    )
    return {
        "tenant_id": value.tenant_id,
        "company_id": value.company_id,
        "snapshot_id": snapshot_id,
        "effort_period_start": value.effort_period_start,
        "effort_period_end": value.effort_period_end,
        "revision": value.revision,
        "basis_kind": value.basis_kind,
        "effort_unit": value.effort_unit,
        "source_ref": value.source_ref,
        "source_hash": value.source_hash,
        "evidence_cutoff_at": _utc_time("evidence_cutoff_at", value.evidence_cutoff_at),
        "approval_ref": value.approval_ref,
        "approval_hash": value.approval_hash,
        "state": "APPROVED",
        "approved_at": _utc_time("approved_at", value.approved_at),
        "privacy_class": "LABOR_AGGREGATE",
        "snapshot_hash": snapshot_hash,
        "created_at": _utc_time("created_at", created_at),
    }


def _payroll_identity_row(
    session: Session, record: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_PAYROLL_POST_EVIDENCE_TABLE).where(
                EOS_PAYROLL_POST_EVIDENCE_TABLE.c.tenant_id == record["tenant_id"],
                EOS_PAYROLL_POST_EVIDENCE_TABLE.c.company_id == record["company_id"],
                EOS_PAYROLL_POST_EVIDENCE_TABLE.c.payroll_run_id
                == record["payroll_run_id"],
                EOS_PAYROLL_POST_EVIDENCE_TABLE.c.revision == record["revision"],
                EOS_PAYROLL_POST_EVIDENCE_TABLE.c.pool_id == record["pool_id"],
            )
        )
        .mappings()
        .one_or_none()
    )


def _snapshot_identity_row(
    session: Session, record: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_LABOR_EFFORT_SNAPSHOT_TABLE).where(
                EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.tenant_id == record["tenant_id"],
                EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.company_id == record["company_id"],
                EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.source_ref == record["source_ref"],
                EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.revision == record["revision"],
            )
        )
        .mappings()
        .one_or_none()
    )


def _snapshot_lines(
    session: Session, header: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    rows = (
        session.execute(
            select(EOS_LABOR_EFFORT_LINE_TABLE)
            .where(
                EOS_LABOR_EFFORT_LINE_TABLE.c.tenant_id == header["tenant_id"],
                EOS_LABOR_EFFORT_LINE_TABLE.c.company_id == header["company_id"],
                EOS_LABOR_EFFORT_LINE_TABLE.c.snapshot_id == header["snapshot_id"],
            )
            .order_by(EOS_LABOR_EFFORT_LINE_TABLE.c.line_no)
        )
        .mappings()
        .all()
    )
    return tuple(dict(row) for row in rows)


def _require_replay(
    existing: Mapping[str, Any], requested: Mapping[str, Any], hash_field: str
) -> dict[str, Any]:
    if str(existing[hash_field]) != str(requested[hash_field]):
        raise EosPayrollLaborBridgeError(
            "EOS_PAYROLL_LABOR_CONFLICT",
            "Identity already exists with different immutable semantics",
            status_code=409,
        )
    return dict(existing)


def _payroll_projection(record: Mapping[str, Any], *, created: bool) -> dict[str, Any]:
    return {
        "schema_version": PAYROLL_POSTING_EVIDENCE_SCHEMA,
        "idempotency_disposition": "CREATED" if created else "EXACT_REPLAY",
        **{
            field: str(record[field])
            for field in (
                "tenant_id",
                "company_id",
                "evidence_id",
                "payroll_run_id",
                "pool_id",
                "journal_id",
                "period_id",
                "eligible_component_id",
                "payroll_component_class",
                "account_id",
                "functional_currency",
                "payroll_source_ref",
                "payroll_source_hash",
                "approval_ref",
                "approval_hash",
                "posting_mapping_hash",
                "reconciliation_state",
                "privacy_class",
                "evidence_hash",
            )
        },
        "payroll_period_start": record["payroll_period_start"].isoformat(),
        "payroll_period_end": record["payroll_period_end"].isoformat(),
        "revision": int(record["revision"]),
        "journal_line_no": int(record["journal_line_no"]),
        "organization_ref": record["organization_ref"],
        "eligible_amount_functional": _decimal_text(
            record["eligible_amount_functional"]
        ),
        "recorded_at": _wire_time(record["recorded_at"]),
    }


def _effort_projection(
    header: Mapping[str, Any],
    lines: Sequence[Mapping[str, Any]],
    *,
    created: bool,
) -> dict[str, Any]:
    return {
        "schema_version": LABOR_EFFORT_SNAPSHOT_SCHEMA,
        "idempotency_disposition": "CREATED" if created else "EXACT_REPLAY",
        "tenant_id": str(header["tenant_id"]),
        "company_id": str(header["company_id"]),
        "snapshot_id": str(header["snapshot_id"]),
        "effort_period_start": header["effort_period_start"].isoformat(),
        "effort_period_end": header["effort_period_end"].isoformat(),
        "revision": int(header["revision"]),
        "basis_kind": str(header["basis_kind"]),
        "effort_unit": str(header["effort_unit"]),
        "source_ref": str(header["source_ref"]),
        "source_hash": str(header["source_hash"]),
        "evidence_cutoff_at": _wire_time(header["evidence_cutoff_at"]),
        "approval_ref": str(header["approval_ref"]),
        "approval_hash": str(header["approval_hash"]),
        "state": str(header["state"]),
        "approved_at": _wire_time(header["approved_at"]),
        "privacy_class": str(header["privacy_class"]),
        "snapshot_hash": str(header["snapshot_hash"]),
        "created_at": _wire_time(header["created_at"]),
        "lines": [
            {
                "line_no": int(line["line_no"]),
                "project_id": str(line["project_id"]),
                "project_code": str(line["project_code"]),
                "work_code": line["work_code"],
                "organization_ref": line["organization_ref"],
                "grade_band": line["grade_band"],
                "cost_cohort": line["cost_cohort"],
                "effort_units": _decimal_text(line["effort_units"]),
                "population_count": int(line["population_count"]),
                "minimum_population": int(line["minimum_population"]),
                "ordinary_view_suppressed": bool(line["ordinary_view_suppressed"]),
                "work_assignment_id": (
                    str(line["work_assignment_id"])
                    if line["work_assignment_id"] is not None
                    else None
                ),
                "basis_source_ref": str(line["basis_source_ref"]),
                "basis_source_hash": str(line["basis_source_hash"]),
                "line_hash": str(line["line_hash"]),
            }
            for line in lines
        ],
    }


def _tenant(value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _TENANT.fullmatch(normalized):
        raise _invalid("tenant_id", "has invalid syntax")
    return normalized


def _stable_ref(field_name: str, value: object, *, maximum: int = 256) -> str:
    normalized = str(value).strip() if value is not None else ""
    if len(normalized) > maximum or not _STABLE_REF.fullmatch(normalized):
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _optional_ref(field_name: str, value: object) -> str | None:
    return None if value is None else _stable_ref(field_name, value)


def _optional_dimension(field_name: str, value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or len(normalized) > 64:
        raise _invalid(field_name, "must be a non-empty value up to 64 characters")
    return normalized


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _hash(field_name: str, value: object) -> str:
    normalized = str(value) if value is not None else ""
    if not _HASH_REF.fullmatch(normalized):
        raise _invalid(field_name, "must be a sha256 hash reference")
    return normalized


def _project_code(value: object) -> str:
    normalized = str(value).upper() if value is not None else ""
    if not _PROJECT_CODE.fullmatch(normalized):
        raise _invalid("project_code", "must be an approved Project Code")
    return normalized


def _optional_work_code(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).upper()
    if not _WORK_CODE.fullmatch(normalized):
        raise _invalid("work_code", "must be an FL WorkCode")
    return normalized


def _choice(field_name: str, value: object, admitted: frozenset[str]) -> str:
    normalized = str(value).upper() if value is not None else ""
    if normalized not in admitted:
        raise _invalid(field_name, f"must be one of {sorted(admitted)}")
    return normalized


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool):
        raise _invalid(field_name, "must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(field_name, "must be a positive integer") from exc
    if normalized <= 0 or str(normalized) != str(value):
        raise _invalid(field_name, "must be a positive integer")
    return normalized


def _amount(field_name: str, value: object) -> Decimal:
    return _decimal(field_name, value, quantum=_MONEY_QUANTUM, allow_zero=False)


def _effort(field_name: str, value: object) -> Decimal:
    amount = _decimal(field_name, value, quantum=_EFFORT_QUANTUM, allow_zero=False)
    if amount < 0:
        raise _invalid(field_name, "must be positive")
    return amount


def _decimal(
    field_name: str, value: object, *, quantum: Decimal, allow_zero: bool
) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid(field_name, "must be a decimal") from exc
    if (
        not amount.is_finite()
        or amount.as_tuple().exponent < quantum.as_tuple().exponent
    ):
        raise _invalid(field_name, "has unsupported precision")
    if not allow_zero and amount == 0:
        raise _invalid(field_name, "must not be zero")
    return amount.quantize(quantum)


def _date_range(start: object, end: object) -> None:
    if not isinstance(start, date) or isinstance(start, datetime):
        raise _invalid("period_start", "must be a date")
    if not isinstance(end, date) or isinstance(end, datetime):
        raise _invalid("period_end", "must be a date")
    if end < start:
        raise _invalid("period_end", "cannot be before period_start")


def _utc_time(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(field_name, "must be timezone-aware")
    return value.astimezone(UTC)


def _wire_time(value: object) -> str:
    if not isinstance(value, datetime):
        raise _invalid("datetime", "must be a datetime")
    normalized = (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    )
    return normalized.isoformat().replace("+00:00", "Z")


def _decimal_text(value: object) -> str:
    return format(Decimal(str(value)).quantize(_MONEY_QUANTUM), "f")


def _invalid(field_name: str, detail: str) -> EosPayrollLaborBridgeError:
    return EosPayrollLaborBridgeError(
        "EOS_PAYROLL_LABOR_INVALID",
        f"{field_name} {detail}",
        status_code=422,
    )


def _ineligible(detail: str) -> EosPayrollLaborBridgeError:
    return EosPayrollLaborBridgeError(
        "EOS_PAYROLL_LABOR_INELIGIBLE", detail, status_code=409
    )


def _not_found(detail: str) -> EosPayrollLaborBridgeError:
    return EosPayrollLaborBridgeError(
        "EOS_PAYROLL_LABOR_NOT_FOUND", detail, status_code=404
    )


def _persistence_error() -> EosPayrollLaborBridgeError:
    return EosPayrollLaborBridgeError(
        "EOS_PAYROLL_LABOR_PERSISTENCE_UNAVAILABLE",
        "Payroll/labor bridge persistence is unavailable",
        status_code=503,
        retryable=True,
    )
