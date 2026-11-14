from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Sequence
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
    Index,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .account_catalog import EOS_COMPANY_ACCOUNT_POLICY_TABLE
from .accounts import EOS_ACCOUNT_TABLE
from .business_transactions import EOS_METADATA
from .journals import EOS_JOURNAL_HEADER_TABLE, EOS_JOURNAL_LINE_TABLE
from .legal_entities import EOS_PROJECT_COMPANY_BINDING_TABLE
from .projects import EOS_PROJECT_TABLE

MATERIAL_COMMITMENT_SCHEMA = "eos_material_commitment.v1"
MATERIAL_ATTRIBUTION_KINDS = frozenset({"PROJECT", "UNASSIGNED"})
MATERIAL_BASIS_KINDS = frozenset(
    {"DIRECT_PROJECT", "APPROVED_QUANTITY", "APPROVED_RATIO", "BOM_PLAN", "UNASSIGNED"}
)
MATERIAL_RECONCILIATION_STATES = frozenset({"VERIFIED", "PENDING", "BLOCKED"})

_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_STABLE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,255}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNIT = re.compile(r"^[A-Z][A-Z0-9_]{0,15}$")
_MONEY = Decimal("0.0001")
_QUANTITY = Decimal("0.0001")
_NAMESPACE = uuid.UUID("17af06af-5213-5321-952f-7419fbe27e3d")


EOS_MATERIAL_COMMITMENT_TABLE = Table(
    "eos_material_commitment",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("commitment_id", Uuid(as_uuid=False), primary_key=True),
    Column("acquisition_ref", String(256), nullable=False),
    Column("acquisition_revision", Integer, nullable=False),
    Column("component_ref", String(256), nullable=False),
    Column("journal_id", Uuid(as_uuid=False), nullable=False),
    Column("journal_line_no", Integer, nullable=False),
    Column("period_id", Uuid(as_uuid=False), nullable=False),
    Column("account_id", Uuid(as_uuid=False), nullable=False),
    Column("source_project_id", Uuid(as_uuid=False), nullable=False),
    Column("source_project_code", String(11), nullable=False),
    Column("material_ref", String(256), nullable=False),
    Column("lot_ref", String(256), nullable=True),
    Column("quantity_unit", String(16), nullable=False),
    Column("acquired_quantity", Numeric(20, 4), nullable=False),
    Column("acquisition_amount_functional", Numeric(20, 4), nullable=False),
    Column("assigned_quantity", Numeric(20, 4), nullable=False),
    Column("assigned_amount_functional", Numeric(20, 4), nullable=False),
    Column("unassigned_quantity", Numeric(20, 4), nullable=False),
    Column("unassigned_amount_functional", Numeric(20, 4), nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("evidence_ref", String(256), nullable=False),
    Column("evidence_hash", String(71), nullable=False),
    Column("approval_ref", String(256), nullable=False),
    Column("approval_hash", String(71), nullable=False),
    Column("policy_hash", String(71), nullable=False),
    Column("reconciliation_state", String(16), nullable=False),
    Column("commitment_hash", String(71), nullable=False),
    Column("acquired_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "acquisition_ref",
        "acquisition_revision",
        "component_ref",
        name="ux_eos_material_commit_source",
    ),
    UniqueConstraint(
        "tenant_id", "company_id", "commitment_hash", name="ux_eos_material_commit_hash"
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "journal_id", "journal_line_no"),
        (
            "eos_journal_line.tenant_id",
            "eos_journal_line.company_id",
            "eos_journal_line.journal_id",
            "eos_journal_line.line_no",
        ),
        name="fk_eos_material_commit_journal",
    ),
    CheckConstraint("acquisition_revision > 0", name="ck_eos_material_commit_revision"),
    CheckConstraint("journal_line_no > 0", name="ck_eos_material_commit_line"),
    CheckConstraint(
        "acquired_quantity > 0 AND acquisition_amount_functional > 0",
        name="ck_eos_material_commit_positive",
    ),
    CheckConstraint(
        "assigned_quantity >= 0 AND unassigned_quantity >= 0 "
        "AND acquired_quantity = assigned_quantity + unassigned_quantity",
        name="ck_eos_material_commit_qty_balance",
    ),
    CheckConstraint(
        "assigned_amount_functional >= 0 AND unassigned_amount_functional >= 0 "
        "AND acquisition_amount_functional = assigned_amount_functional + "
        "unassigned_amount_functional",
        name="ck_eos_material_commit_amt_balance",
    ),
    CheckConstraint(
        "reconciliation_state IN ('VERIFIED','PENDING','BLOCKED')",
        name="ck_eos_material_commit_reconcile",
    ),
)
Index(
    "ix_eos_material_commit_journal",
    EOS_MATERIAL_COMMITMENT_TABLE.c.tenant_id,
    EOS_MATERIAL_COMMITMENT_TABLE.c.company_id,
    EOS_MATERIAL_COMMITMENT_TABLE.c.journal_id,
    EOS_MATERIAL_COMMITMENT_TABLE.c.journal_line_no,
)
Index(
    "ix_eos_material_commit_queue",
    EOS_MATERIAL_COMMITMENT_TABLE.c.tenant_id,
    EOS_MATERIAL_COMMITMENT_TABLE.c.company_id,
    EOS_MATERIAL_COMMITMENT_TABLE.c.reconciliation_state,
    EOS_MATERIAL_COMMITMENT_TABLE.c.acquired_at,
)


EOS_MATERIAL_ATTRIBUTION_TABLE = Table(
    "eos_material_attribution",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("commitment_id", Uuid(as_uuid=False), primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("attribution_kind", String(16), nullable=False),
    Column("project_id", Uuid(as_uuid=False), nullable=True),
    Column("project_code", String(11), nullable=True),
    Column("work_code", String(16), nullable=True),
    Column("attributed_quantity", Numeric(20, 4), nullable=False),
    Column("attributed_amount_functional", Numeric(20, 4), nullable=False),
    Column("basis_kind", String(32), nullable=False),
    Column("basis_ref", String(256), nullable=False),
    Column("basis_hash", String(71), nullable=False),
    Column("line_hash", String(71), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "commitment_id"),
        (
            "eos_material_commitment.tenant_id",
            "eos_material_commitment.company_id",
            "eos_material_commitment.commitment_id",
        ),
        name="fk_eos_material_attr_commit",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_material_attr_project",
    ),
    UniqueConstraint(
        "tenant_id", "company_id", "commitment_id", "line_hash", name="ux_eos_material_attr_hash"
    ),
    CheckConstraint("line_no > 0", name="ck_eos_material_attr_line"),
    CheckConstraint(
        "attributed_quantity > 0 AND attributed_amount_functional > 0",
        name="ck_eos_material_attr_positive",
    ),
    CheckConstraint(
        "attribution_kind IN ('PROJECT','UNASSIGNED')",
        name="ck_eos_material_attr_kind",
    ),
    CheckConstraint(
        "basis_kind IN ('DIRECT_PROJECT','APPROVED_QUANTITY','APPROVED_RATIO','BOM_PLAN','UNASSIGNED')",
        name="ck_eos_material_attr_basis",
    ),
    CheckConstraint(
        "(attribution_kind = 'PROJECT' AND project_id IS NOT NULL AND project_code IS NOT NULL "
        "AND basis_kind <> 'UNASSIGNED') OR "
        "(attribution_kind = 'UNASSIGNED' AND project_id IS NULL AND project_code IS NULL "
        "AND work_code IS NULL AND basis_kind = 'UNASSIGNED')",
        name="ck_eos_material_attr_target",
    ),
)
Index(
    "ix_eos_material_attr_project",
    EOS_MATERIAL_ATTRIBUTION_TABLE.c.tenant_id,
    EOS_MATERIAL_ATTRIBUTION_TABLE.c.company_id,
    EOS_MATERIAL_ATTRIBUTION_TABLE.c.project_id,
    EOS_MATERIAL_ATTRIBUTION_TABLE.c.commitment_id,
)
Index(
    "ix_eos_material_attr_unassigned",
    EOS_MATERIAL_ATTRIBUTION_TABLE.c.tenant_id,
    EOS_MATERIAL_ATTRIBUTION_TABLE.c.company_id,
    EOS_MATERIAL_ATTRIBUTION_TABLE.c.attribution_kind,
    EOS_MATERIAL_ATTRIBUTION_TABLE.c.commitment_id,
)


class EosMaterialCommitmentError(RuntimeError):
    def __init__(
        self, error_code: str, detail: str, *, status_code: int, retryable: bool = False
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class MaterialAttributionInput:
    attribution_kind: str
    attributed_quantity: Decimal
    attributed_amount_functional: Decimal
    basis_kind: str
    basis_ref: str
    basis_hash: str
    project_id: str | None = None
    project_code: str | None = None
    work_code: str | None = None


@dataclass(frozen=True)
class MaterialCommitmentInput:
    tenant_id: str
    company_id: str
    acquisition_ref: str
    acquisition_revision: int
    component_ref: str
    journal_id: str
    journal_line_no: int
    material_ref: str
    quantity_unit: str
    acquired_quantity: Decimal
    acquisition_amount_functional: Decimal
    evidence_ref: str
    evidence_hash: str
    approval_ref: str
    approval_hash: str
    policy_hash: str
    acquired_at: datetime
    attributions: Sequence[MaterialAttributionInput]
    reconciliation_state: str = "VERIFIED"
    lot_ref: str | None = None


class SqlAlchemyEosMaterialCommitmentRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def append(self, value: MaterialCommitmentInput) -> tuple[dict[str, Any], bool]:
        normalized = _validate_input(value)
        created_at = _utc("created_at", self._clock())
        try:
            with self._session_factory.begin() as session:
                journal = _load_journal_line(session, normalized)
                lines = _build_lines(session, normalized)
                header = _build_header(normalized, journal, lines, created_at)
                existing = _identity_row(session, header)
                if existing is not None:
                    return _replay_projection(session, existing, header), False
                _require_available_journal_amount(session, header, journal)
                session.execute(EOS_MATERIAL_COMMITMENT_TABLE.insert().values(**header))
                session.execute(EOS_MATERIAL_ATTRIBUTION_TABLE.insert(), lines)
                return _projection(header, lines, disposition="CREATED"), True
        except EosMaterialCommitmentError:
            raise
        except IntegrityError as exc:
            return self._race_replay(normalized, created_at, exc)
        except SQLAlchemyError as exc:
            raise _error(
                "MATERIAL_COMMITMENT_UNAVAILABLE",
                "Material commitment persistence is unavailable",
                503,
                retryable=True,
            ) from exc

    def get(
        self, *, tenant_id: str, company_id: str, commitment_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_MATERIAL_COMMITMENT_TABLE).where(
                            EOS_MATERIAL_COMMITMENT_TABLE.c.tenant_id == _tenant(tenant_id),
                            EOS_MATERIAL_COMMITMENT_TABLE.c.company_id == _uuid("company_id", company_id),
                            EOS_MATERIAL_COMMITMENT_TABLE.c.commitment_id == _uuid("commitment_id", commitment_id),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None
                lines = _stored_lines(session, row)
                return _projection(dict(row), lines, disposition="READ")
        except EosMaterialCommitmentError:
            raise
        except SQLAlchemyError as exc:
            raise _error(
                "MATERIAL_COMMITMENT_UNAVAILABLE",
                "Material commitment persistence is unavailable",
                503,
                retryable=True,
            ) from exc

    def _race_replay(
        self, value: MaterialCommitmentInput, created_at: datetime, cause: Exception
    ) -> tuple[dict[str, Any], bool]:
        try:
            with self._session_factory() as session:
                journal = _load_journal_line(session, value)
                lines = _build_lines(session, value)
                header = _build_header(value, journal, lines, created_at)
                existing = _identity_row(session, header)
                if existing is None:
                    raise _error(
                        "MATERIAL_COMMITMENT_CONFLICT",
                        "Concurrent material commitment could not be reconciled",
                        409,
                    ) from cause
                return _replay_projection(session, existing, header), False
        except EosMaterialCommitmentError:
            raise
        except SQLAlchemyError as exc:
            raise _error(
                "MATERIAL_COMMITMENT_UNAVAILABLE",
                "Material commitment persistence is unavailable",
                503,
                retryable=True,
            ) from exc


class EosMaterialCommitmentService:
    def __init__(self, repository: SqlAlchemyEosMaterialCommitmentRepository) -> None:
        self._repository = repository

    def admit(self, value: MaterialCommitmentInput) -> dict[str, Any]:
        result, _created = self._repository.append(value)
        return result

    def get(
        self, *, tenant_id: str, company_id: str, commitment_id: str
    ) -> dict[str, Any] | None:
        return self._repository.get(
            tenant_id=tenant_id, company_id=company_id, commitment_id=commitment_id
        )


def _validate_input(value: MaterialCommitmentInput) -> MaterialCommitmentInput:
    if not value.attributions:
        raise _invalid("attributions must not be empty")
    state = value.reconciliation_state.strip().upper()
    if state not in MATERIAL_RECONCILIATION_STATES:
        raise _invalid("reconciliation_state is unsupported")
    unit = value.quantity_unit.strip().upper()
    if not _UNIT.fullmatch(unit):
        raise _invalid("quantity_unit is invalid")
    acquired_at = _utc("acquired_at", value.acquired_at)
    return MaterialCommitmentInput(
        tenant_id=_tenant(value.tenant_id),
        company_id=_uuid("company_id", value.company_id),
        acquisition_ref=_ref("acquisition_ref", value.acquisition_ref),
        acquisition_revision=_positive_int("acquisition_revision", value.acquisition_revision),
        component_ref=_ref("component_ref", value.component_ref),
        journal_id=_uuid("journal_id", value.journal_id),
        journal_line_no=_positive_int("journal_line_no", value.journal_line_no),
        material_ref=_ref("material_ref", value.material_ref),
        quantity_unit=unit,
        acquired_quantity=_positive_decimal("acquired_quantity", value.acquired_quantity, _QUANTITY),
        acquisition_amount_functional=_positive_decimal(
            "acquisition_amount_functional", value.acquisition_amount_functional, _MONEY
        ),
        evidence_ref=_ref("evidence_ref", value.evidence_ref),
        evidence_hash=_hash("evidence_hash", value.evidence_hash),
        approval_ref=_ref("approval_ref", value.approval_ref),
        approval_hash=_hash("approval_hash", value.approval_hash),
        policy_hash=_hash("policy_hash", value.policy_hash),
        acquired_at=acquired_at,
        attributions=tuple(value.attributions),
        reconciliation_state=state,
        lot_ref=_optional_ref("lot_ref", value.lot_ref),
    )


def _load_journal_line(session: Session, value: MaterialCommitmentInput) -> dict[str, Any]:
    row = (
        session.execute(
            select(
                EOS_JOURNAL_LINE_TABLE,
                EOS_JOURNAL_HEADER_TABLE.c.period_id,
                EOS_JOURNAL_HEADER_TABLE.c.state,
                EOS_JOURNAL_HEADER_TABLE.c.recognition_date,
                EOS_ACCOUNT_TABLE.c.category.label("account_category"),
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.is_monetary,
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.state.label("policy_state"),
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.valid_from,
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.valid_until,
            )
            .join(
                EOS_JOURNAL_HEADER_TABLE,
                (EOS_JOURNAL_HEADER_TABLE.c.tenant_id == EOS_JOURNAL_LINE_TABLE.c.tenant_id)
                & (EOS_JOURNAL_HEADER_TABLE.c.company_id == EOS_JOURNAL_LINE_TABLE.c.company_id)
                & (EOS_JOURNAL_HEADER_TABLE.c.journal_id == EOS_JOURNAL_LINE_TABLE.c.journal_id),
            )
            .join(
                EOS_ACCOUNT_TABLE,
                (EOS_ACCOUNT_TABLE.c.tenant_id == EOS_JOURNAL_LINE_TABLE.c.tenant_id)
                & (EOS_ACCOUNT_TABLE.c.account_id == EOS_JOURNAL_LINE_TABLE.c.account_id),
            )
            .join(
                EOS_COMPANY_ACCOUNT_POLICY_TABLE,
                (EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.tenant_id == EOS_JOURNAL_LINE_TABLE.c.tenant_id)
                & (EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.policy_id == EOS_JOURNAL_LINE_TABLE.c.account_policy_id),
            )
            .where(
                EOS_JOURNAL_LINE_TABLE.c.tenant_id == value.tenant_id,
                EOS_JOURNAL_LINE_TABLE.c.company_id == value.company_id,
                EOS_JOURNAL_LINE_TABLE.c.journal_id == value.journal_id,
                EOS_JOURNAL_LINE_TABLE.c.line_no == value.journal_line_no,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error("MATERIAL_SOURCE_NOT_FOUND", "Posted Journal line was not found", 404)
    result = dict(row)
    if result["state"] != "POSTED":
        raise _invalid("Material commitment requires a POSTED Journal")
    if result["account_category"] != "ASSET" or result["is_monetary"]:
        raise _invalid("Material commitment requires a non-monetary ASSET account")
    recognition_date = result["recognition_date"]
    if (
        result["policy_state"] != "APPROVED"
        or result["valid_from"] > recognition_date
        or (result["valid_until"] is not None and result["valid_until"] < recognition_date)
    ):
        raise _invalid("Material commitment requires an effective approved account policy")
    available = _money(result["debit_functional"] - result["credit_functional"])
    if available <= 0:
        raise _invalid("Material acquisition Journal line must have a positive debit balance")
    result["available_amount"] = available
    return result


def _build_lines(
    session: Session, value: MaterialCommitmentInput
) -> tuple[dict[str, Any], ...]:
    lines: list[dict[str, Any]] = []
    unassigned_count = 0
    targets: set[tuple[str, str | None]] = set()
    for line_no, item in enumerate(value.attributions, start=1):
        kind = item.attribution_kind.strip().upper()
        basis = item.basis_kind.strip().upper()
        if kind not in MATERIAL_ATTRIBUTION_KINDS or basis not in MATERIAL_BASIS_KINDS:
            raise _invalid("Material attribution kind or basis is unsupported")
        project_id = project_code = work_code = None
        if kind == "UNASSIGNED":
            unassigned_count += 1
            if basis != "UNASSIGNED" or item.project_id or item.project_code or item.work_code:
                raise _invalid("UNASSIGNED attribution must not carry Project or work identity")
        else:
            if basis == "UNASSIGNED":
                raise _invalid("PROJECT attribution must carry an approved allocation basis")
            project_id = _uuid("project_id", item.project_id)
            project_code = _project_code(item.project_code)
            work_code = _optional_work_code(item.work_code)
            target = (project_id, work_code)
            if target in targets:
                raise _invalid("Material attribution contains a duplicate Project/work target")
            targets.add(target)
            _require_project(session, value, project_id, project_code)
        quantity = _positive_decimal("attributed_quantity", item.attributed_quantity, _QUANTITY)
        amount = _positive_decimal(
            "attributed_amount_functional", item.attributed_amount_functional, _MONEY
        )
        canonical = {
            "line_no": line_no,
            "attribution_kind": kind,
            "project_id": project_id,
            "project_code": project_code,
            "work_code": work_code,
            "attributed_quantity": format(quantity, "f"),
            "attributed_amount_functional": format(amount, "f"),
            "basis_kind": basis,
            "basis_ref": _ref("basis_ref", item.basis_ref),
            "basis_hash": _hash("basis_hash", item.basis_hash),
        }
        lines.append(
            {
                "tenant_id": value.tenant_id,
                "company_id": value.company_id,
                "commitment_id": "",
                **canonical,
                "attributed_quantity": quantity,
                "attributed_amount_functional": amount,
                "line_hash": semantic_sha256_hash_ref(
                    {"domain": "EOS-MATERIAL-ATTRIBUTION-V1", **canonical}
                ),
            }
        )
    if unassigned_count > 1:
        raise _invalid("At most one UNASSIGNED attribution is allowed")
    quantity_total = sum((line["attributed_quantity"] for line in lines), Decimal())
    amount_total = sum(
        (line["attributed_amount_functional"] for line in lines), Decimal()
    )
    if _quantity(quantity_total) != value.acquired_quantity:
        raise _invalid("Attributed quantity must conserve acquired quantity")
    if _money(amount_total) != value.acquisition_amount_functional:
        raise _invalid("Attributed amount must conserve acquisition amount")
    return tuple(lines)


def _require_project(
    session: Session,
    value: MaterialCommitmentInput,
    project_id: str,
    project_code: str,
) -> None:
    row = (
        session.execute(
            select(EOS_PROJECT_TABLE.c.project_code, EOS_PROJECT_TABLE.c.status)
            .join(
                EOS_PROJECT_COMPANY_BINDING_TABLE,
                (EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id == EOS_PROJECT_TABLE.c.tenant_id)
                & (EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id == EOS_PROJECT_TABLE.c.project_id),
            )
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == value.tenant_id,
                EOS_PROJECT_TABLE.c.project_id == project_id,
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.company_id == value.company_id,
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.state == "APPROVED",
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_from <= value.acquired_at.date(),
                (
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until.is_(None)
                    | (EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until >= value.acquired_at.date())
                ),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _invalid("Material attribution Project has no effective company binding")
    if row["project_code"] != project_code:
        raise _invalid("Material attribution Project Code differs from authority")
    if row["status"] not in {"ACTIVE", "CLOSING"}:
        raise _invalid("Material attribution Project is not cost eligible")


def _build_header(
    value: MaterialCommitmentInput,
    journal: dict[str, Any],
    lines: Sequence[dict[str, Any]],
    created_at: datetime,
) -> dict[str, Any]:
    commitment_id = str(
        uuid.uuid5(
            _NAMESPACE,
            "/".join(
                (
                    value.tenant_id,
                    value.company_id,
                    value.acquisition_ref,
                    str(value.acquisition_revision),
                    value.component_ref,
                )
            ),
        )
    )
    for line in lines:
        line["commitment_id"] = commitment_id
    assigned = [line for line in lines if line["attribution_kind"] == "PROJECT"]
    unassigned = [line for line in lines if line["attribution_kind"] == "UNASSIGNED"]
    canonical = {
        "tenant_id": value.tenant_id,
        "company_id": value.company_id,
        "commitment_id": commitment_id,
        "acquisition_ref": value.acquisition_ref,
        "acquisition_revision": value.acquisition_revision,
        "component_ref": value.component_ref,
        "journal_id": value.journal_id,
        "journal_line_no": value.journal_line_no,
        "material_ref": value.material_ref,
        "lot_ref": value.lot_ref,
        "quantity_unit": value.quantity_unit,
        "acquired_quantity": format(value.acquired_quantity, "f"),
        "acquisition_amount_functional": format(value.acquisition_amount_functional, "f"),
        "evidence_ref": value.evidence_ref,
        "evidence_hash": value.evidence_hash,
        "approval_ref": value.approval_ref,
        "approval_hash": value.approval_hash,
        "policy_hash": value.policy_hash,
        "reconciliation_state": value.reconciliation_state,
        "acquired_at": value.acquired_at.isoformat(),
        "line_hashes": [line["line_hash"] for line in lines],
    }
    record = {
        **canonical,
        "period_id": journal["period_id"],
        "account_id": journal["account_id"],
        "source_project_id": journal["project_id"],
        "source_project_code": journal["project_code"],
        "acquired_quantity": value.acquired_quantity,
        "acquisition_amount_functional": value.acquisition_amount_functional,
        "assigned_quantity": _quantity(
            sum((line["attributed_quantity"] for line in assigned), Decimal())
        ),
        "assigned_amount_functional": _money(
            sum((line["attributed_amount_functional"] for line in assigned), Decimal())
        ),
        "unassigned_quantity": _quantity(
            sum((line["attributed_quantity"] for line in unassigned), Decimal())
        ),
        "unassigned_amount_functional": _money(
            sum((line["attributed_amount_functional"] for line in unassigned), Decimal())
        ),
        "functional_currency": journal["functional_currency"],
        "commitment_hash": semantic_sha256_hash_ref(
            {"domain": "EOS-MATERIAL-COMMITMENT-V1", **canonical}
        ),
        "acquired_at": value.acquired_at,
        "created_at": created_at,
    }
    record.pop("line_hashes")
    return record


def _require_available_journal_amount(
    session: Session, header: dict[str, Any], journal: dict[str, Any]
) -> None:
    used = session.execute(
        select(func.coalesce(func.sum(EOS_MATERIAL_COMMITMENT_TABLE.c.acquisition_amount_functional), 0)).where(
            EOS_MATERIAL_COMMITMENT_TABLE.c.tenant_id == header["tenant_id"],
            EOS_MATERIAL_COMMITMENT_TABLE.c.company_id == header["company_id"],
            EOS_MATERIAL_COMMITMENT_TABLE.c.journal_id == header["journal_id"],
            EOS_MATERIAL_COMMITMENT_TABLE.c.journal_line_no == header["journal_line_no"],
        )
    ).scalar_one()
    if _money(used + header["acquisition_amount_functional"]) > journal["available_amount"]:
        raise _error(
            "MATERIAL_SOURCE_OVERCOMMITTED",
            "Material commitment exceeds the positive ASSET Journal line amount",
            409,
        )


def _identity_row(session: Session, header: dict[str, Any]) -> dict[str, Any] | None:
    row = (
        session.execute(
            select(EOS_MATERIAL_COMMITMENT_TABLE).where(
                EOS_MATERIAL_COMMITMENT_TABLE.c.tenant_id == header["tenant_id"],
                EOS_MATERIAL_COMMITMENT_TABLE.c.company_id == header["company_id"],
                EOS_MATERIAL_COMMITMENT_TABLE.c.acquisition_ref == header["acquisition_ref"],
                EOS_MATERIAL_COMMITMENT_TABLE.c.acquisition_revision == header["acquisition_revision"],
                EOS_MATERIAL_COMMITMENT_TABLE.c.component_ref == header["component_ref"],
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _stored_lines(session: Session, header: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = session.execute(
        select(EOS_MATERIAL_ATTRIBUTION_TABLE)
        .where(
            EOS_MATERIAL_ATTRIBUTION_TABLE.c.tenant_id == header["tenant_id"],
            EOS_MATERIAL_ATTRIBUTION_TABLE.c.company_id == header["company_id"],
            EOS_MATERIAL_ATTRIBUTION_TABLE.c.commitment_id == header["commitment_id"],
        )
        .order_by(EOS_MATERIAL_ATTRIBUTION_TABLE.c.line_no)
    ).mappings()
    return tuple(dict(row) for row in rows)


def _replay_projection(
    session: Session, existing: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    if existing["commitment_hash"] != expected["commitment_hash"]:
        raise _error(
            "MATERIAL_COMMITMENT_CONFLICT",
            "Material commitment identity was reused with different semantics",
            409,
        )
    return _projection(existing, _stored_lines(session, existing), disposition="EXACT_REPLAY")


def _projection(
    header: dict[str, Any], lines: Sequence[dict[str, Any]], *, disposition: str
) -> dict[str, Any]:
    projected = dict(header)
    for key in (
        "acquired_quantity",
        "acquisition_amount_functional",
        "assigned_quantity",
        "assigned_amount_functional",
        "unassigned_quantity",
        "unassigned_amount_functional",
    ):
        projected[key] = format(Decimal(header[key]).quantize(_MONEY), "f")
    projected["schema_version"] = MATERIAL_COMMITMENT_SCHEMA
    projected["disposition"] = disposition
    projected["attributions"] = [
        {
            **dict(line),
            "attributed_quantity": format(Decimal(line["attributed_quantity"]).quantize(_QUANTITY), "f"),
            "attributed_amount_functional": format(
                Decimal(line["attributed_amount_functional"]).quantize(_MONEY), "f"
            ),
        }
        for line in lines
    ]
    return projected


def _error(code: str, detail: str, status: int, *, retryable: bool = False) -> EosMaterialCommitmentError:
    return EosMaterialCommitmentError(code, detail, status_code=status, retryable=retryable)


def _invalid(detail: str) -> EosMaterialCommitmentError:
    return _error("MATERIAL_COMMITMENT_INVALID", detail, 422)


def _tenant(value: str) -> str:
    normalized = str(value).strip()
    if not _TENANT.fullmatch(normalized):
        raise _invalid("tenant_id is invalid")
    return normalized


def _uuid(name: str, value: str | None) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{name} must be a UUID") from exc


def _ref(name: str, value: str) -> str:
    normalized = str(value).strip()
    if not _STABLE_REF.fullmatch(normalized):
        raise _invalid(f"{name} is invalid")
    return normalized


def _optional_ref(name: str, value: str | None) -> str | None:
    return None if value is None else _ref(name, value)


def _hash(name: str, value: str) -> str:
    normalized = str(value).strip().lower()
    if not _HASH_REF.fullmatch(normalized):
        raise _invalid(f"{name} must be a sha256 reference")
    return normalized


def _project_code(value: str | None) -> str:
    normalized = str(value or "").strip().upper()
    if not _PROJECT_CODE.fullmatch(normalized):
        raise _invalid("project_code is invalid")
    return normalized


def _optional_work_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    if not _WORK_CODE.fullmatch(normalized):
        raise _invalid("work_code is invalid")
    return normalized


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(f"{name} must be a positive integer")
    return value


def _positive_decimal(name: str, value: Decimal, quantum: Decimal) -> Decimal:
    try:
        normalized = Decimal(str(value)).quantize(quantum)
    except (InvalidOperation, ValueError) as exc:
        raise _invalid(f"{name} must be a decimal") from exc
    if not normalized.is_finite() or normalized <= 0:
        raise _invalid(f"{name} must be positive")
    return normalized


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_MONEY)


def _quantity(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_QUANTITY)


def _utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise _invalid(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
