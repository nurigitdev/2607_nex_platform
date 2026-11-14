from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
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

from .accounting_periods import EOS_ACCOUNTING_PERIOD_TABLE
from .business_transactions import EOS_METADATA
from .legal_entities import EOS_LEGAL_ENTITY_TABLE
from .projects import EOS_PROJECT_TABLE

PROJECT_PNL_PROJECTION_SCHEMA = "eos_project_pnl_projection.v1"
PROJECT_PNL_RECONCILIATION_STATUSES = frozenset(
    {"VERIFIED", "PENDING", "BLOCKED", "PARTIAL"}
)
PROJECT_PNL_FRESHNESS_STATUSES = frozenset({"CURRENT", "STALE", "UNKNOWN"})
PROJECT_PNL_DATA_CLASSIFICATIONS = frozenset(
    {"INTERNAL_FINANCIAL", "CONFIDENTIAL_FINANCIAL", "PAYROLL_SENSITIVE"}
)
PROJECT_PNL_SOURCE_KINDS = frozenset(
    {
        "REVENUE",
        "PAYROLL",
        "MATERIAL",
        "SERVICE",
        "SHARED_EXPENSE",
        "FX_GAIN_LOSS",
        "OTHER",
    }
)

_CLASSIFICATION_ROLLUPS: Mapping[str, tuple[str, bool]] = {
    "POSTED_REVENUE": ("REVENUE", True),
    "POSTED_DIRECT_COST": ("DIRECT_COST", True),
    "POSTED_ALLOCATED_COST": ("ALLOCATED_COST", True),
    "POSTED_LABOR_ALLOCATED": ("ALLOCATED_COST", True),
    "UNALLOCATED": ("UNALLOCATED_COST", False),
    "POSTED_PAYROLL_UNALLOCATED": ("UNALLOCATED_COST", False),
    "UNALLOCATED_LABOR_OVERHEAD": ("UNALLOCATED_COST", False),
    "APPROVED_NOT_POSTED": ("NONFINAL", False),
    "LABOR_ALLOCATION_PROVISIONAL": ("PROVISIONAL", False),
    "PLANNED_BUDGET": ("BUDGET", False),
    "FORECAST": ("FORECAST", False),
    "PLANNED_LABOR": ("FORECAST", False),
    "BOM_FORECAST": ("FORECAST", False),
    "MATERIAL_COMMITTED": ("COMMITMENT", False),
    "UNASSIGNED_INVENTORY": ("COMMITMENT", False),
    "LABOR_ADJUSTMENT": ("ALLOCATED_COST", True),
    "MATERIAL_VARIANCE": ("ADJUSTMENT", True),
    "FX_REALIZED_GAIN_LOSS": ("ADJUSTMENT", True),
    "FX_UNREALIZED_GAIN_LOSS": ("ADJUSTMENT", True),
}
PROJECT_PNL_CLASSIFICATIONS = frozenset(_CLASSIFICATION_ROLLUPS)
PROJECT_PNL_ROLLUP_CLASSES = frozenset(
    rollup for rollup, _confirmed in _CLASSIFICATION_ROLLUPS.values()
)

_SIGNED_CLASSIFICATIONS = frozenset(
    {
        "POSTED_REVENUE",
        "POSTED_DIRECT_COST",
        "POSTED_ALLOCATED_COST",
        "POSTED_LABOR_ALLOCATED",
        "UNALLOCATED",
        "POSTED_PAYROLL_UNALLOCATED",
        "UNALLOCATED_LABOR_OVERHEAD",
        "LABOR_ADJUSTMENT",
        "MATERIAL_VARIANCE",
        "FX_REALIZED_GAIN_LOSS",
        "FX_UNREALIZED_GAIN_LOSS",
    }
)
_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_MONEY_QUANTUM = Decimal("0.0001")


EOS_PROJECT_PNL_PROJECTION_TABLE = Table(
    "eos_project_pnl_projection",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("projection_id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("project_code", String(11), nullable=False),
    Column("period_id", Uuid(as_uuid=False), nullable=False),
    Column("projection_version", Integer, nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("posting_watermark", String(256), nullable=False),
    Column("posting_watermark_at", DateTime(timezone=True), nullable=False),
    Column("allocation_watermark", String(256), nullable=False),
    Column("allocation_watermark_at", DateTime(timezone=True), nullable=False),
    Column("budget_watermark", String(256), nullable=True),
    Column("budget_watermark_at", DateTime(timezone=True), nullable=True),
    Column("payroll_evidence_watermark", String(256), nullable=True),
    Column("payroll_evidence_watermark_at", DateTime(timezone=True), nullable=True),
    Column("labor_effort_watermark", String(256), nullable=True),
    Column("labor_effort_watermark_at", DateTime(timezone=True), nullable=True),
    Column("material_commitment_watermark", String(256), nullable=True),
    Column("material_commitment_watermark_at", DateTime(timezone=True), nullable=True),
    Column("reconciliation_status", String(16), nullable=False),
    Column("freshness_status", String(16), nullable=False),
    Column("staleness_seconds", BigInteger, nullable=False),
    Column("posted_revenue", Numeric(20, 4), nullable=False),
    Column("posted_direct_cost", Numeric(20, 4), nullable=False),
    Column("posted_allocated_cost", Numeric(20, 4), nullable=False),
    Column("posted_operating_result", Numeric(20, 4), nullable=False),
    Column("operating_unallocated_cost", Numeric(20, 4), nullable=False),
    Column("planned_budget", Numeric(20, 4), nullable=False),
    Column("budget_actual", Numeric(20, 4), nullable=False),
    Column("budget_variance", Numeric(20, 4), nullable=False),
    Column("approved_not_posted", Numeric(20, 4), nullable=False),
    Column("forecast", Numeric(20, 4), nullable=False),
    Column("data_classification", String(32), nullable=False),
    Column("projection_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "project_id",
        "period_id",
        "projection_version",
        name="ux_eos_project_pnl_version",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "projection_hash",
        name="ux_eos_project_pnl_hash",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_project_pnl_company",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_project_pnl_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "period_id"),
        (
            "eos_accounting_period.tenant_id",
            "eos_accounting_period.company_id",
            "eos_accounting_period.period_id",
        ),
        name="fk_eos_project_pnl_period",
    ),
    CheckConstraint("projection_version > 0", name="ck_eos_project_pnl_version"),
    CheckConstraint("staleness_seconds >= 0", name="ck_eos_project_pnl_staleness"),
    CheckConstraint(
        "posted_revenue >= 0 AND posted_direct_cost >= 0 "
        "AND posted_allocated_cost >= 0 AND operating_unallocated_cost >= 0 "
        "AND planned_budget >= 0 AND budget_actual >= 0 "
        "AND approved_not_posted >= 0 AND forecast >= 0",
        name="ck_eos_project_pnl_amounts",
    ),
    CheckConstraint(
        "posted_operating_result = "
        "posted_revenue - posted_direct_cost - posted_allocated_cost",
        name="ck_eos_project_pnl_result",
    ),
)
Index(
    "ix_eos_project_pnl_lookup",
    EOS_PROJECT_PNL_PROJECTION_TABLE.c.tenant_id,
    EOS_PROJECT_PNL_PROJECTION_TABLE.c.company_id,
    EOS_PROJECT_PNL_PROJECTION_TABLE.c.project_id,
    EOS_PROJECT_PNL_PROJECTION_TABLE.c.period_id,
    EOS_PROJECT_PNL_PROJECTION_TABLE.c.projection_version,
)
Index(
    "ix_eos_project_pnl_freshness",
    EOS_PROJECT_PNL_PROJECTION_TABLE.c.tenant_id,
    EOS_PROJECT_PNL_PROJECTION_TABLE.c.company_id,
    EOS_PROJECT_PNL_PROJECTION_TABLE.c.freshness_status,
    EOS_PROJECT_PNL_PROJECTION_TABLE.c.as_of,
)


EOS_PROJECT_PNL_COMPONENT_TABLE = Table(
    "eos_project_pnl_component",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("projection_id", Uuid(as_uuid=False), primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("classification", String(40), nullable=False),
    Column("rollup_class", String(24), nullable=False),
    Column("source_kind", String(24), nullable=False),
    Column("account_id", Uuid(as_uuid=False), nullable=True),
    Column("work_code", String(32), nullable=True),
    Column("functional_amount", Numeric(20, 4), nullable=False),
    Column("confirmed", Boolean, nullable=False),
    Column("source_ref", String(256), nullable=False),
    Column("source_hash", String(71), nullable=False),
    Column("data_classification", String(32), nullable=False),
    Column("component_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "projection_id",
        "component_hash",
        name="ux_eos_project_pnl_component_hash",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "projection_id"),
        (
            "eos_project_pnl_projection.tenant_id",
            "eos_project_pnl_projection.company_id",
            "eos_project_pnl_projection.projection_id",
        ),
        name="fk_eos_project_pnl_component_projection",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_project_pnl_component_account",
    ),
    CheckConstraint("line_no > 0", name="ck_eos_project_pnl_component_line"),
    CheckConstraint(
        "functional_amount <> 0",
        name="ck_eos_project_pnl_component_amount",
    ),
)
Index(
    "ix_eos_project_pnl_component_class",
    EOS_PROJECT_PNL_COMPONENT_TABLE.c.tenant_id,
    EOS_PROJECT_PNL_COMPONENT_TABLE.c.company_id,
    EOS_PROJECT_PNL_COMPONENT_TABLE.c.projection_id,
    EOS_PROJECT_PNL_COMPONENT_TABLE.c.classification,
)
Index(
    "ix_eos_project_pnl_component_source",
    EOS_PROJECT_PNL_COMPONENT_TABLE.c.tenant_id,
    EOS_PROJECT_PNL_COMPONENT_TABLE.c.company_id,
    EOS_PROJECT_PNL_COMPONENT_TABLE.c.source_hash,
)


class EosProjectPnlPersistenceError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class ProjectPnlComponentDraft:
    classification: str
    source_kind: str
    functional_amount: Decimal
    source_ref: str
    source_hash: str
    account_id: str | None = None
    work_code: str | None = None
    data_classification: str = "INTERNAL_FINANCIAL"


@dataclass(frozen=True)
class ProjectPnlProjectionDraft:
    tenant_id: str
    company_id: str
    projection_id: str
    project_id: str
    project_code: str
    period_id: str
    projection_version: int
    functional_currency: str
    as_of: datetime
    posting_watermark: str
    posting_watermark_at: datetime
    allocation_watermark: str
    allocation_watermark_at: datetime
    reconciliation_status: str
    freshness_status: str
    staleness_seconds: int
    budget_watermark: str | None = None
    budget_watermark_at: datetime | None = None
    payroll_evidence_watermark: str | None = None
    payroll_evidence_watermark_at: datetime | None = None
    labor_effort_watermark: str | None = None
    labor_effort_watermark_at: datetime | None = None
    material_commitment_watermark: str | None = None
    material_commitment_watermark_at: datetime | None = None
    data_classification: str = "INTERNAL_FINANCIAL"


class SqlAlchemyEosProjectPnlRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append(
        self,
        draft: ProjectPnlProjectionDraft,
        components: Sequence[ProjectPnlComponentDraft],
    ) -> dict[str, Any]:
        header, lines = build_project_pnl_records(draft, components)
        try:
            with self._session_factory.begin() as session:
                self._validate_authorities(session, header)
                existing = self._get_version_in_session(
                    session,
                    tenant_id=header["tenant_id"],
                    company_id=header["company_id"],
                    project_id=header["project_id"],
                    period_id=header["period_id"],
                    projection_version=header["projection_version"],
                )
                if existing is not None:
                    if existing["projection_hash"] != header["projection_hash"]:
                        raise _conflict(
                            "Project P&L projection version has different semantics"
                        )
                    return self._load_wire_in_session(session, existing)
                latest = session.scalar(
                    select(EOS_PROJECT_PNL_PROJECTION_TABLE.c.projection_version)
                    .where(
                        EOS_PROJECT_PNL_PROJECTION_TABLE.c.tenant_id
                        == header["tenant_id"],
                        EOS_PROJECT_PNL_PROJECTION_TABLE.c.company_id
                        == header["company_id"],
                        EOS_PROJECT_PNL_PROJECTION_TABLE.c.project_id
                        == header["project_id"],
                        EOS_PROJECT_PNL_PROJECTION_TABLE.c.period_id
                        == header["period_id"],
                    )
                    .order_by(
                        EOS_PROJECT_PNL_PROJECTION_TABLE.c.projection_version.desc()
                    )
                    .limit(1)
                )
                expected = 1 if latest is None else int(latest) + 1
                if header["projection_version"] != expected:
                    raise _conflict(
                        "Project P&L projection version must be the next immutable "
                        f"revision {expected}"
                    )
                session.execute(
                    EOS_PROJECT_PNL_PROJECTION_TABLE.insert().values(**header)
                )
                if lines:
                    session.execute(EOS_PROJECT_PNL_COMPONENT_TABLE.insert(), lines)
                return _wire_projection(header, lines)
        except EosProjectPnlPersistenceError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Project P&L persistence conflicts with current state"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable("Project P&L persistence is unavailable") from exc

    def get(
        self,
        *,
        tenant_id: str,
        company_id: str,
        project_id: str,
        period_id: str,
        projection_version: int | None = None,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                statement = select(EOS_PROJECT_PNL_PROJECTION_TABLE).where(
                    EOS_PROJECT_PNL_PROJECTION_TABLE.c.tenant_id == _tenant(tenant_id),
                    EOS_PROJECT_PNL_PROJECTION_TABLE.c.company_id
                    == _uuid("company_id", company_id),
                    EOS_PROJECT_PNL_PROJECTION_TABLE.c.project_id
                    == _uuid("project_id", project_id),
                    EOS_PROJECT_PNL_PROJECTION_TABLE.c.period_id
                    == _uuid("period_id", period_id),
                )
                if projection_version is None:
                    statement = statement.order_by(
                        EOS_PROJECT_PNL_PROJECTION_TABLE.c.projection_version.desc()
                    ).limit(1)
                else:
                    statement = statement.where(
                        EOS_PROJECT_PNL_PROJECTION_TABLE.c.projection_version
                        == _positive_int("projection_version", projection_version)
                    )
                row = session.execute(statement).mappings().one_or_none()
                return (
                    self._load_wire_in_session(session, dict(row))
                    if row is not None
                    else None
                )
        except EosProjectPnlPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable("Project P&L persistence is unavailable") from exc

    @staticmethod
    def _get_version_in_session(
        session: Session,
        *,
        tenant_id: str,
        company_id: str,
        project_id: str,
        period_id: str,
        projection_version: int,
    ) -> dict[str, Any] | None:
        row = (
            session.execute(
                select(EOS_PROJECT_PNL_PROJECTION_TABLE).where(
                    EOS_PROJECT_PNL_PROJECTION_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_PNL_PROJECTION_TABLE.c.company_id == company_id,
                    EOS_PROJECT_PNL_PROJECTION_TABLE.c.project_id == project_id,
                    EOS_PROJECT_PNL_PROJECTION_TABLE.c.period_id == period_id,
                    EOS_PROJECT_PNL_PROJECTION_TABLE.c.projection_version
                    == projection_version,
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    @staticmethod
    def _load_wire_in_session(
        session: Session, header: Mapping[str, Any]
    ) -> dict[str, Any]:
        lines = [
            dict(row)
            for row in session.execute(
                select(EOS_PROJECT_PNL_COMPONENT_TABLE)
                .where(
                    EOS_PROJECT_PNL_COMPONENT_TABLE.c.tenant_id == header["tenant_id"],
                    EOS_PROJECT_PNL_COMPONENT_TABLE.c.company_id
                    == header["company_id"],
                    EOS_PROJECT_PNL_COMPONENT_TABLE.c.projection_id
                    == header["projection_id"],
                )
                .order_by(EOS_PROJECT_PNL_COMPONENT_TABLE.c.line_no)
            ).mappings()
        ]
        return _wire_projection(header, lines)

    @staticmethod
    def _validate_authorities(session: Session, header: Mapping[str, Any]) -> None:
        company = (
            session.execute(
                select(EOS_LEGAL_ENTITY_TABLE).where(
                    EOS_LEGAL_ENTITY_TABLE.c.tenant_id == header["tenant_id"],
                    EOS_LEGAL_ENTITY_TABLE.c.company_id == header["company_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if company is None:
            raise _not_found("LegalEntity was not found in tenant scope")
        if company["functional_currency"] != header["functional_currency"]:
            raise _conflict(
                "Project P&L currency must equal LegalEntity functional currency"
            )
        project = (
            session.execute(
                select(EOS_PROJECT_TABLE.c.project_code).where(
                    EOS_PROJECT_TABLE.c.tenant_id == header["tenant_id"],
                    EOS_PROJECT_TABLE.c.project_id == header["project_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if project is None:
            raise _not_found("Project was not found in tenant scope")
        if project["project_code"] != header["project_code"]:
            raise _conflict("Project P&L Project Code differs from Project authority")
        period = session.scalar(
            select(EOS_ACCOUNTING_PERIOD_TABLE.c.period_id).where(
                EOS_ACCOUNTING_PERIOD_TABLE.c.tenant_id == header["tenant_id"],
                EOS_ACCOUNTING_PERIOD_TABLE.c.company_id == header["company_id"],
                EOS_ACCOUNTING_PERIOD_TABLE.c.period_id == header["period_id"],
            )
        )
        if period is None:
            raise _not_found("AccountingPeriod was not found in company scope")


def build_project_pnl_records(
    draft: ProjectPnlProjectionDraft,
    components: Sequence[ProjectPnlComponentDraft],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tenant_id = _tenant(draft.tenant_id)
    company_id = _uuid("company_id", draft.company_id)
    projection_id = _uuid("projection_id", draft.projection_id)
    project_id = _uuid("project_id", draft.project_id)
    period_id = _uuid("period_id", draft.period_id)
    project_code = _project_code(draft.project_code)
    version = _positive_int("projection_version", draft.projection_version)
    currency = _currency(draft.functional_currency)
    as_of = _aware_datetime("as_of", draft.as_of)
    posting_watermark, posting_at = _required_watermark(
        "posting_watermark", draft.posting_watermark, draft.posting_watermark_at
    )
    allocation_watermark, allocation_at = _required_watermark(
        "allocation_watermark",
        draft.allocation_watermark,
        draft.allocation_watermark_at,
    )
    optional_watermarks = {
        "budget": _optional_watermark(
            "budget_watermark", draft.budget_watermark, draft.budget_watermark_at
        ),
        "payroll_evidence": _optional_watermark(
            "payroll_evidence_watermark",
            draft.payroll_evidence_watermark,
            draft.payroll_evidence_watermark_at,
        ),
        "labor_effort": _optional_watermark(
            "labor_effort_watermark",
            draft.labor_effort_watermark,
            draft.labor_effort_watermark_at,
        ),
        "material_commitment": _optional_watermark(
            "material_commitment_watermark",
            draft.material_commitment_watermark,
            draft.material_commitment_watermark_at,
        ),
    }
    watermark_times = [posting_at, allocation_at]
    watermark_times.extend(
        value[1] for value in optional_watermarks.values() if value[1] is not None
    )
    if any(value > as_of for value in watermark_times):
        raise _invalid("as_of", "must not precede a source watermark")
    reconciliation_status = _choice(
        "reconciliation_status",
        draft.reconciliation_status,
        PROJECT_PNL_RECONCILIATION_STATUSES,
    )
    freshness_status = _choice(
        "freshness_status", draft.freshness_status, PROJECT_PNL_FRESHNESS_STATUSES
    )
    staleness_seconds = _non_negative_int("staleness_seconds", draft.staleness_seconds)
    data_classification = _choice(
        "data_classification",
        draft.data_classification,
        PROJECT_PNL_DATA_CLASSIFICATIONS,
    )
    created_at = as_of
    lines = [
        _component_record(
            tenant_id=tenant_id,
            company_id=company_id,
            projection_id=projection_id,
            line_no=index,
            value=value,
            created_at=created_at,
        )
        for index, value in enumerate(components, 1)
    ]
    totals = _projection_totals(lines)
    header = {
        "tenant_id": tenant_id,
        "company_id": company_id,
        "projection_id": projection_id,
        "project_id": project_id,
        "project_code": project_code,
        "period_id": period_id,
        "projection_version": version,
        "functional_currency": currency,
        "as_of": as_of,
        "posting_watermark": posting_watermark,
        "posting_watermark_at": posting_at,
        "allocation_watermark": allocation_watermark,
        "allocation_watermark_at": allocation_at,
        "budget_watermark": optional_watermarks["budget"][0],
        "budget_watermark_at": optional_watermarks["budget"][1],
        "payroll_evidence_watermark": optional_watermarks["payroll_evidence"][0],
        "payroll_evidence_watermark_at": optional_watermarks["payroll_evidence"][1],
        "labor_effort_watermark": optional_watermarks["labor_effort"][0],
        "labor_effort_watermark_at": optional_watermarks["labor_effort"][1],
        "material_commitment_watermark": optional_watermarks["material_commitment"][0],
        "material_commitment_watermark_at": optional_watermarks["material_commitment"][
            1
        ],
        "reconciliation_status": reconciliation_status,
        "freshness_status": freshness_status,
        "staleness_seconds": staleness_seconds,
        **totals,
        "data_classification": data_classification,
        "created_at": created_at,
    }
    header["projection_hash"] = semantic_sha256_hash_ref(
        {
            **_hashable_header(header),
            "component_hashes": [line["component_hash"] for line in lines],
        }
    )
    return header, lines


def _component_record(
    *,
    tenant_id: str,
    company_id: str,
    projection_id: str,
    line_no: int,
    value: ProjectPnlComponentDraft,
    created_at: datetime,
) -> dict[str, Any]:
    classification = _choice(
        "classification", value.classification, PROJECT_PNL_CLASSIFICATIONS
    )
    rollup_class, confirmed = _CLASSIFICATION_ROLLUPS[classification]
    amount = _money("functional_amount", value.functional_amount)
    if amount == 0:
        raise _invalid("functional_amount", "must not be zero")
    if classification not in _SIGNED_CLASSIFICATIONS and amount < 0:
        raise _invalid("functional_amount", "must be positive for this classification")
    record = {
        "tenant_id": tenant_id,
        "company_id": company_id,
        "projection_id": projection_id,
        "line_no": line_no,
        "classification": classification,
        "rollup_class": rollup_class,
        "source_kind": _choice(
            "source_kind", value.source_kind, PROJECT_PNL_SOURCE_KINDS
        ),
        "account_id": (
            _uuid("account_id", value.account_id)
            if value.account_id is not None
            else None
        ),
        "work_code": (
            _text("work_code", value.work_code, 32)
            if value.work_code is not None
            else None
        ),
        "functional_amount": amount,
        "confirmed": confirmed,
        "source_ref": _text("source_ref", value.source_ref, 256),
        "source_hash": _hash_ref("source_hash", value.source_hash),
        "data_classification": _choice(
            "data_classification",
            value.data_classification,
            PROJECT_PNL_DATA_CLASSIFICATIONS,
        ),
        "created_at": created_at,
    }
    record["component_hash"] = semantic_sha256_hash_ref(
        {key: _wire_value(item) for key, item in record.items() if key != "created_at"}
    )
    return record


def _projection_totals(lines: Sequence[Mapping[str, Any]]) -> dict[str, Decimal]:
    by_rollup = {rollup: Decimal("0.0000") for rollup in PROJECT_PNL_ROLLUP_CLASSES}
    for line in lines:
        by_rollup[str(line["rollup_class"])] += Decimal(str(line["functional_amount"]))
    posted_revenue = by_rollup["REVENUE"]
    posted_direct_cost = by_rollup["DIRECT_COST"]
    posted_allocated_cost = by_rollup["ALLOCATED_COST"]
    planned_budget = by_rollup["BUDGET"]
    budget_actual = posted_direct_cost + posted_allocated_cost
    return {
        "posted_revenue": posted_revenue,
        "posted_direct_cost": posted_direct_cost,
        "posted_allocated_cost": posted_allocated_cost,
        "posted_operating_result": (
            posted_revenue - posted_direct_cost - posted_allocated_cost
        ),
        "operating_unallocated_cost": by_rollup["UNALLOCATED_COST"],
        "planned_budget": planned_budget,
        "budget_actual": budget_actual,
        "budget_variance": planned_budget - budget_actual,
        "approved_not_posted": by_rollup["NONFINAL"],
        "forecast": by_rollup["FORECAST"],
    }


def _hashable_header(header: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _wire_value(value)
        for key, value in header.items()
        if key not in {"projection_hash", "created_at"}
    }


def _wire_projection(
    header: Mapping[str, Any], lines: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": PROJECT_PNL_PROJECTION_SCHEMA,
        **{
            key: _wire_value(value)
            for key, value in header.items()
            if key != "created_at"
        },
        "components": [
            {
                key: _wire_value(value)
                for key, value in line.items()
                if key not in {"tenant_id", "company_id", "projection_id", "created_at"}
            }
            for line in lines
        ],
    }


def _wire_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, ".4f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _tenant(value: Any) -> str:
    text = str(value).strip()
    if not _TENANT.fullmatch(text):
        raise _invalid("tenant_id", "has invalid format")
    return text


def _uuid(name: str, value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(name, "must be a UUID") from exc


def _project_code(value: Any) -> str:
    text = str(value).strip().upper()
    if not _PROJECT_CODE.fullmatch(text):
        raise _invalid("project_code", "must be an approved 11-character code")
    return text


def _currency(value: Any) -> str:
    text = str(value).strip().upper()
    if not _CURRENCY.fullmatch(text):
        raise _invalid("functional_currency", "must be an ISO 4217 code")
    return text


def _text(name: str, value: Any, limit: int) -> str:
    text = str(value).strip()
    if not text or len(text) > limit:
        raise _invalid(name, f"must contain 1..{limit} characters")
    return text


def _hash_ref(name: str, value: Any) -> str:
    text = str(value).strip()
    if not _HASH_REF.fullmatch(text):
        raise _invalid(name, "must be a sha256 reference")
    return text


def _choice(name: str, value: Any, choices: frozenset[str]) -> str:
    text = str(value).strip().upper()
    if text not in choices:
        raise _invalid(name, f"must be one of {sorted(choices)}")
    return text


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _invalid(name, "must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(name, "must be a positive integer") from exc
    if parsed <= 0:
        raise _invalid(name, "must be a positive integer")
    return parsed


def _non_negative_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _invalid(name, "must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(name, "must be a non-negative integer") from exc
    if parsed < 0:
        raise _invalid(name, "must be a non-negative integer")
    return parsed


def _money(name: str, value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid(name, "must be a decimal amount") from exc
    if not parsed.is_finite():
        raise _invalid(name, "must be finite")
    return parsed.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _aware_datetime(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(name, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _required_watermark(
    name: str, value: Any, observed_at: Any
) -> tuple[str, datetime]:
    return _text(name, value, 256), _aware_datetime(f"{name}_at", observed_at)


def _optional_watermark(
    name: str, value: Any | None, observed_at: Any | None
) -> tuple[str | None, datetime | None]:
    if value is None and observed_at is None:
        return None, None
    if value is None or observed_at is None:
        raise _invalid(name, "reference and observed-at must be provided together")
    return _required_watermark(name, value, observed_at)


def _invalid(name: str, detail: str) -> EosProjectPnlPersistenceError:
    return EosProjectPnlPersistenceError(
        "PROJECT_PNL_INVALID_ARGUMENT", f"{name} {detail}", status_code=400
    )


def _not_found(detail: str) -> EosProjectPnlPersistenceError:
    return EosProjectPnlPersistenceError(
        "PROJECT_PNL_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosProjectPnlPersistenceError:
    return EosProjectPnlPersistenceError(
        "PROJECT_PNL_CONFLICT", detail, status_code=409
    )


def _unavailable(detail: str) -> EosProjectPnlPersistenceError:
    return EosProjectPnlPersistenceError(
        "PROJECT_PNL_UNAVAILABLE", detail, status_code=503
    )
