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

from .business_transactions import EOS_METADATA
from .cost_source_pools import EOS_COST_SOURCE_POOL_TABLE
from .material_commitments import (
    EOS_MATERIAL_ATTRIBUTION_TABLE,
    EOS_MATERIAL_COMMITMENT_TABLE,
)

MATERIAL_CONSUMPTION_SCHEMA = "eos_material_consumption.v1"
MATERIAL_CONSUMPTION_RECONCILIATION_STATES = frozenset({"VERIFIED"})

_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_STABLE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,255}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNIT = re.compile(r"^[A-Z][A-Z0-9_]{0,15}$")
_MONEY = Decimal("0.0001")
_QUANTITY = Decimal("0.0001")
_NAMESPACE = uuid.UUID("48f6723d-d7c4-5b44-aa7d-9f764f6b0f51")


EOS_MATERIAL_CONSUMPTION_TABLE = Table(
    "eos_material_consumption",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("consumption_id", Uuid(as_uuid=False), primary_key=True),
    Column("consumption_ref", String(256), nullable=False),
    Column("consumption_revision", Integer, nullable=False),
    Column("component_ref", String(256), nullable=False),
    Column("cost_pool_id", Uuid(as_uuid=False), nullable=False),
    Column("period_id", Uuid(as_uuid=False), nullable=False),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("project_code", String(11), nullable=False),
    Column("work_code", String(16), nullable=True),
    Column("material_ref", String(256), nullable=False),
    Column("quantity_unit", String(16), nullable=False),
    Column("consumed_quantity", Numeric(20, 4), nullable=False),
    Column("recognized_cost_functional", Numeric(20, 4), nullable=False),
    Column("released_carrying_amount_functional", Numeric(20, 4), nullable=False),
    Column("valuation_variance_functional", Numeric(20, 4), nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("evidence_ref", String(256), nullable=False),
    Column("evidence_hash", String(71), nullable=False),
    Column("approval_ref", String(256), nullable=False),
    Column("approval_hash", String(71), nullable=False),
    Column("policy_hash", String(71), nullable=False),
    Column("reconciliation_state", String(16), nullable=False),
    Column("consumption_hash", String(71), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "consumption_ref",
        "consumption_revision",
        "component_ref",
        name="ux_eos_material_consume_source",
    ),
    UniqueConstraint(
        "tenant_id", "company_id", "cost_pool_id", name="ux_eos_material_consume_pool"
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "consumption_hash",
        name="ux_eos_material_consume_hash",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "cost_pool_id"),
        (
            "eos_cost_source_pool.tenant_id",
            "eos_cost_source_pool.company_id",
            "eos_cost_source_pool.pool_id",
        ),
        name="fk_eos_material_consume_pool",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_material_consume_project",
    ),
    CheckConstraint("consumption_revision > 0", name="ck_eos_material_consume_revision"),
    CheckConstraint(
        "consumed_quantity > 0 AND recognized_cost_functional > 0 "
        "AND released_carrying_amount_functional > 0",
        name="ck_eos_material_consume_positive",
    ),
    CheckConstraint(
        "valuation_variance_functional = recognized_cost_functional - "
        "released_carrying_amount_functional",
        name="ck_eos_material_consume_variance",
    ),
    CheckConstraint(
        "reconciliation_state = 'VERIFIED'",
        name="ck_eos_material_consume_reconcile",
    ),
)
Index(
    "ix_eos_material_consume_project",
    EOS_MATERIAL_CONSUMPTION_TABLE.c.tenant_id,
    EOS_MATERIAL_CONSUMPTION_TABLE.c.company_id,
    EOS_MATERIAL_CONSUMPTION_TABLE.c.project_id,
    EOS_MATERIAL_CONSUMPTION_TABLE.c.period_id,
    EOS_MATERIAL_CONSUMPTION_TABLE.c.created_at,
)


EOS_MATERIAL_RELEASE_TABLE = Table(
    "eos_material_release",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("consumption_id", Uuid(as_uuid=False), primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("commitment_id", Uuid(as_uuid=False), nullable=False),
    Column("attribution_line_no", Integer, nullable=False),
    Column("released_quantity", Numeric(20, 4), nullable=False),
    Column("released_amount_functional", Numeric(20, 4), nullable=False),
    Column("line_hash", String(71), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "consumption_id",
        "commitment_id",
        "attribution_line_no",
        name="ux_eos_material_release_source",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "consumption_id",
        "line_hash",
        name="ux_eos_material_release_hash",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "consumption_id"),
        (
            "eos_material_consumption.tenant_id",
            "eos_material_consumption.company_id",
            "eos_material_consumption.consumption_id",
        ),
        name="fk_eos_material_release_consume",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "commitment_id", "attribution_line_no"),
        (
            "eos_material_attribution.tenant_id",
            "eos_material_attribution.company_id",
            "eos_material_attribution.commitment_id",
            "eos_material_attribution.line_no",
        ),
        name="fk_eos_material_release_attr",
    ),
    CheckConstraint(
        "line_no > 0 AND attribution_line_no > 0",
        name="ck_eos_material_release_line",
    ),
    CheckConstraint(
        "released_quantity > 0 AND released_amount_functional > 0",
        name="ck_eos_material_release_positive",
    ),
)
Index(
    "ix_eos_material_release_attr",
    EOS_MATERIAL_RELEASE_TABLE.c.tenant_id,
    EOS_MATERIAL_RELEASE_TABLE.c.company_id,
    EOS_MATERIAL_RELEASE_TABLE.c.commitment_id,
    EOS_MATERIAL_RELEASE_TABLE.c.attribution_line_no,
)


class EosMaterialConsumptionError(RuntimeError):
    def __init__(
        self, error_code: str, detail: str, *, status_code: int, retryable: bool = False
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class MaterialReleaseInput:
    commitment_id: str
    attribution_line_no: int
    released_quantity: Decimal
    released_amount_functional: Decimal


@dataclass(frozen=True)
class MaterialConsumptionInput:
    tenant_id: str
    company_id: str
    consumption_ref: str
    consumption_revision: int
    component_ref: str
    cost_pool_id: str
    project_id: str
    project_code: str
    material_ref: str
    quantity_unit: str
    consumed_quantity: Decimal
    evidence_ref: str
    evidence_hash: str
    approval_ref: str
    approval_hash: str
    policy_hash: str
    consumed_at: datetime
    releases: Sequence[MaterialReleaseInput]
    work_code: str | None = None
    reconciliation_state: str = "VERIFIED"


class SqlAlchemyEosMaterialConsumptionRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def append(self, value: MaterialConsumptionInput) -> tuple[dict[str, Any], bool]:
        normalized = _validate_input(value)
        created_at = _utc("created_at", self._clock())
        if normalized.consumed_at > created_at:
            raise _invalid("consumed_at must not be in the future")
        try:
            with self._session_factory.begin() as session:
                pool = _load_cost_pool(session, normalized)
                lines = _build_release_lines(session, normalized, pool)
                header = _build_header(normalized, pool, lines, created_at)
                existing = _identity_row(session, header)
                if existing is not None:
                    return _replay_projection(session, existing, header), False
                _require_pool_available(session, header)
                _require_release_capacity(session, lines)
                session.execute(EOS_MATERIAL_CONSUMPTION_TABLE.insert().values(**header))
                session.execute(EOS_MATERIAL_RELEASE_TABLE.insert(), lines)
                return _projection(header, lines, disposition="CREATED"), True
        except EosMaterialConsumptionError:
            raise
        except IntegrityError as exc:
            return self._race_replay(normalized, created_at, exc)
        except SQLAlchemyError as exc:
            raise _error(
                "MATERIAL_CONSUMPTION_UNAVAILABLE",
                "Material consumption persistence is unavailable",
                503,
                retryable=True,
            ) from exc

    def get(
        self, *, tenant_id: str, company_id: str, consumption_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_MATERIAL_CONSUMPTION_TABLE).where(
                            EOS_MATERIAL_CONSUMPTION_TABLE.c.tenant_id
                            == _tenant(tenant_id),
                            EOS_MATERIAL_CONSUMPTION_TABLE.c.company_id
                            == _uuid("company_id", company_id),
                            EOS_MATERIAL_CONSUMPTION_TABLE.c.consumption_id
                            == _uuid("consumption_id", consumption_id),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None
                lines = _stored_lines(session, row)
                return _projection(dict(row), lines, disposition="READ")
        except EosMaterialConsumptionError:
            raise
        except SQLAlchemyError as exc:
            raise _error(
                "MATERIAL_CONSUMPTION_UNAVAILABLE",
                "Material consumption persistence is unavailable",
                503,
                retryable=True,
            ) from exc

    def _race_replay(
        self, value: MaterialConsumptionInput, created_at: datetime, cause: Exception
    ) -> tuple[dict[str, Any], bool]:
        try:
            with self._session_factory() as session:
                pool = _load_cost_pool(session, value)
                lines = _build_release_lines(session, value, pool)
                header = _build_header(value, pool, lines, created_at)
                existing = _identity_row(session, header)
                if existing is None:
                    raise _error(
                        "MATERIAL_CONSUMPTION_CONFLICT",
                        "Concurrent material consumption could not be reconciled",
                        409,
                    ) from cause
                return _replay_projection(session, existing, header), False
        except EosMaterialConsumptionError:
            raise
        except SQLAlchemyError as exc:
            raise _error(
                "MATERIAL_CONSUMPTION_UNAVAILABLE",
                "Material consumption persistence is unavailable",
                503,
                retryable=True,
            ) from exc


class EosMaterialConsumptionService:
    def __init__(self, repository: SqlAlchemyEosMaterialConsumptionRepository) -> None:
        self._repository = repository

    def reconcile(self, value: MaterialConsumptionInput) -> dict[str, Any]:
        result, _created = self._repository.append(value)
        return result

    def get(
        self, *, tenant_id: str, company_id: str, consumption_id: str
    ) -> dict[str, Any] | None:
        return self._repository.get(
            tenant_id=tenant_id,
            company_id=company_id,
            consumption_id=consumption_id,
        )


def _validate_input(value: MaterialConsumptionInput) -> MaterialConsumptionInput:
    if not value.releases:
        raise _invalid("releases must not be empty")
    state = str(value.reconciliation_state).strip().upper()
    if state not in MATERIAL_CONSUMPTION_RECONCILIATION_STATES:
        raise _invalid("Only VERIFIED material consumption is admitted")
    unit = str(value.quantity_unit).strip().upper()
    if not _UNIT.fullmatch(unit):
        raise _invalid("quantity_unit is invalid")
    return MaterialConsumptionInput(
        tenant_id=_tenant(value.tenant_id),
        company_id=_uuid("company_id", value.company_id),
        consumption_ref=_ref("consumption_ref", value.consumption_ref),
        consumption_revision=_positive_int(
            "consumption_revision", value.consumption_revision
        ),
        component_ref=_ref("component_ref", value.component_ref),
        cost_pool_id=_uuid("cost_pool_id", value.cost_pool_id),
        project_id=_uuid("project_id", value.project_id),
        project_code=_project_code(value.project_code),
        material_ref=_ref("material_ref", value.material_ref),
        quantity_unit=unit,
        consumed_quantity=_positive_decimal(
            "consumed_quantity", value.consumed_quantity, _QUANTITY
        ),
        evidence_ref=_ref("evidence_ref", value.evidence_ref),
        evidence_hash=_hash("evidence_hash", value.evidence_hash),
        approval_ref=_ref("approval_ref", value.approval_ref),
        approval_hash=_hash("approval_hash", value.approval_hash),
        policy_hash=_hash("policy_hash", value.policy_hash),
        consumed_at=_utc("consumed_at", value.consumed_at),
        releases=tuple(value.releases),
        work_code=_optional_work_code(value.work_code),
        reconciliation_state=state,
    )


def _load_cost_pool(
    session: Session, value: MaterialConsumptionInput
) -> dict[str, Any]:
    row = (
        session.execute(
            select(EOS_COST_SOURCE_POOL_TABLE)
            .where(
                EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == value.tenant_id,
                EOS_COST_SOURCE_POOL_TABLE.c.company_id == value.company_id,
                EOS_COST_SOURCE_POOL_TABLE.c.pool_id == value.cost_pool_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error(
            "MATERIAL_COST_SOURCE_NOT_FOUND",
            "Material POSTED cost SourcePool was not found",
            404,
        )
    result = dict(row)
    if (
        result["source_kind"] != "PURCHASE"
        or result["allocation_mode"] != "DIRECT"
        or result["account_category"] != "EXPENSE"
        or result["pool_state"] != "ALLOCATED"
    ):
        raise _invalid(
            "Material consumption requires an ALLOCATED DIRECT PURCHASE expense SourcePool"
        )
    if (
        str(result["source_project_id"]) != value.project_id
        or str(result["source_project_code"]) != value.project_code
    ):
        raise _invalid("Material cost SourcePool Project differs from consumption target")
    recognized = _money(result["eligible_amount_functional"])
    if recognized <= 0:
        raise _invalid("Material cost SourcePool amount must be positive")
    result["recognized_cost"] = recognized
    return result


def _build_release_lines(
    session: Session,
    value: MaterialConsumptionInput,
    pool: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    requested: list[tuple[str, int, Decimal, Decimal]] = []
    identities: set[tuple[str, int]] = set()
    for item in value.releases:
        commitment_id = _uuid("commitment_id", item.commitment_id)
        attribution_line_no = _positive_int(
            "attribution_line_no", item.attribution_line_no
        )
        identity = (commitment_id, attribution_line_no)
        if identity in identities:
            raise _invalid("releases contain a duplicate attribution source")
        identities.add(identity)
        quantity = _positive_decimal(
            "released_quantity", item.released_quantity, _QUANTITY
        )
        amount = _positive_decimal(
            "released_amount_functional", item.released_amount_functional, _MONEY
        )
        requested.append((commitment_id, attribution_line_no, quantity, amount))

    requested.sort(key=lambda item: (item[0], item[1]))
    normalized: list[tuple[str, int, Decimal, Decimal, dict[str, Any]]] = []
    for commitment_id, attribution_line_no, quantity, amount in requested:
        source = _load_attribution_source(
            session,
            value=value,
            commitment_id=commitment_id,
            attribution_line_no=attribution_line_no,
        )
        if str(source["functional_currency"]) != str(pool["functional_currency"]):
            raise _invalid(
                "Material commitment and POSTED cost currencies differ"
            )
        normalized.append(
            (commitment_id, attribution_line_no, quantity, amount, source)
        )
    quantity_total = _quantity(sum((item[2] for item in normalized), Decimal()))
    if quantity_total != value.consumed_quantity:
        raise _invalid("Released quantity must equal consumed quantity")

    lines: list[dict[str, Any]] = []
    for line_no, (commitment_id, attribution_line_no, quantity, amount, _source) in enumerate(
        normalized, start=1
    ):
        canonical = {
            "line_no": line_no,
            "commitment_id": commitment_id,
            "attribution_line_no": attribution_line_no,
            "released_quantity": format(quantity, "f"),
            "released_amount_functional": format(amount, "f"),
        }
        lines.append(
            {
                "tenant_id": value.tenant_id,
                "company_id": value.company_id,
                "consumption_id": "",
                **canonical,
                "released_quantity": quantity,
                "released_amount_functional": amount,
                "line_hash": semantic_sha256_hash_ref(
                    {"domain": "EOS-MATERIAL-RELEASE-V1", **canonical}
                ),
            }
        )
    return tuple(lines)


def _load_attribution_source(
    session: Session,
    *,
    value: MaterialConsumptionInput,
    commitment_id: str,
    attribution_line_no: int,
) -> dict[str, Any]:
    row = (
        session.execute(
            select(EOS_MATERIAL_COMMITMENT_TABLE, EOS_MATERIAL_ATTRIBUTION_TABLE)
            .join(
                EOS_MATERIAL_ATTRIBUTION_TABLE,
                (EOS_MATERIAL_ATTRIBUTION_TABLE.c.tenant_id
                 == EOS_MATERIAL_COMMITMENT_TABLE.c.tenant_id)
                & (EOS_MATERIAL_ATTRIBUTION_TABLE.c.company_id
                   == EOS_MATERIAL_COMMITMENT_TABLE.c.company_id)
                & (EOS_MATERIAL_ATTRIBUTION_TABLE.c.commitment_id
                   == EOS_MATERIAL_COMMITMENT_TABLE.c.commitment_id),
            )
            .where(
                EOS_MATERIAL_COMMITMENT_TABLE.c.tenant_id == value.tenant_id,
                EOS_MATERIAL_COMMITMENT_TABLE.c.company_id == value.company_id,
                EOS_MATERIAL_COMMITMENT_TABLE.c.commitment_id == commitment_id,
                EOS_MATERIAL_ATTRIBUTION_TABLE.c.line_no == attribution_line_no,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error(
            "MATERIAL_COMMITMENT_SOURCE_NOT_FOUND",
            "Material commitment attribution source was not found",
            404,
        )
    result = dict(row)
    if result["reconciliation_state"] != "VERIFIED":
        raise _invalid("Material consumption requires a VERIFIED commitment")
    if (
        result["material_ref"] != value.material_ref
        or result["quantity_unit"] != value.quantity_unit
    ):
        raise _invalid("Material release identity differs from the commitment source")
    if result["functional_currency"] is None:
        raise _invalid("Material commitment currency is unavailable")
    if result["attribution_kind"] == "PROJECT" and (
        str(result["project_id"]) != value.project_id
        or str(result["project_code"]) != value.project_code
        or result["work_code"] != value.work_code
    ):
        raise _invalid("Project-attributed material cannot be consumed by another target")
    return result


def _build_header(
    value: MaterialConsumptionInput,
    pool: dict[str, Any],
    lines: Sequence[dict[str, Any]],
    created_at: datetime,
) -> dict[str, Any]:
    consumption_id = str(
        uuid.uuid5(
            _NAMESPACE,
            "/".join(
                (
                    value.tenant_id,
                    value.company_id,
                    value.consumption_ref,
                    str(value.consumption_revision),
                    value.component_ref,
                )
            ),
        )
    )
    for line in lines:
        line["consumption_id"] = consumption_id
    released = _money(
        sum((line["released_amount_functional"] for line in lines), Decimal())
    )
    recognized = pool["recognized_cost"]
    canonical = {
        "tenant_id": value.tenant_id,
        "company_id": value.company_id,
        "consumption_id": consumption_id,
        "consumption_ref": value.consumption_ref,
        "consumption_revision": value.consumption_revision,
        "component_ref": value.component_ref,
        "cost_pool_id": value.cost_pool_id,
        "project_id": value.project_id,
        "project_code": value.project_code,
        "work_code": value.work_code,
        "material_ref": value.material_ref,
        "quantity_unit": value.quantity_unit,
        "consumed_quantity": format(value.consumed_quantity, "f"),
        "recognized_cost_functional": format(recognized, "f"),
        "released_carrying_amount_functional": format(released, "f"),
        "valuation_variance_functional": format(_money(recognized - released), "f"),
        "functional_currency": pool["functional_currency"],
        "evidence_ref": value.evidence_ref,
        "evidence_hash": value.evidence_hash,
        "approval_ref": value.approval_ref,
        "approval_hash": value.approval_hash,
        "policy_hash": value.policy_hash,
        "reconciliation_state": value.reconciliation_state,
        "consumed_at": value.consumed_at.isoformat(),
        "line_hashes": [line["line_hash"] for line in lines],
    }
    record = {
        **canonical,
        "period_id": pool["period_id"],
        "consumed_quantity": value.consumed_quantity,
        "recognized_cost_functional": recognized,
        "released_carrying_amount_functional": released,
        "valuation_variance_functional": _money(recognized - released),
        "consumption_hash": semantic_sha256_hash_ref(
            {"domain": "EOS-MATERIAL-CONSUMPTION-V1", **canonical}
        ),
        "consumed_at": value.consumed_at,
        "created_at": created_at,
    }
    record.pop("line_hashes")
    return record


def _require_pool_available(session: Session, header: dict[str, Any]) -> None:
    used = session.execute(
        select(EOS_MATERIAL_CONSUMPTION_TABLE.c.consumption_id).where(
            EOS_MATERIAL_CONSUMPTION_TABLE.c.tenant_id == header["tenant_id"],
            EOS_MATERIAL_CONSUMPTION_TABLE.c.company_id == header["company_id"],
            EOS_MATERIAL_CONSUMPTION_TABLE.c.cost_pool_id == header["cost_pool_id"],
        )
    ).scalar_one_or_none()
    if used is not None:
        raise _error(
            "MATERIAL_COST_SOURCE_ALREADY_CONSUMED",
            "Material POSTED cost SourcePool is already bound to a consumption",
            409,
        )


def _require_release_capacity(
    session: Session, lines: Sequence[dict[str, Any]]
) -> None:
    for line in lines:
        source = (
            session.execute(
                select(EOS_MATERIAL_ATTRIBUTION_TABLE)
                .where(
                    EOS_MATERIAL_ATTRIBUTION_TABLE.c.tenant_id == line["tenant_id"],
                    EOS_MATERIAL_ATTRIBUTION_TABLE.c.company_id == line["company_id"],
                    EOS_MATERIAL_ATTRIBUTION_TABLE.c.commitment_id
                    == line["commitment_id"],
                    EOS_MATERIAL_ATTRIBUTION_TABLE.c.line_no
                    == line["attribution_line_no"],
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        used = session.execute(
            select(
                func.coalesce(func.sum(EOS_MATERIAL_RELEASE_TABLE.c.released_quantity), 0),
                func.coalesce(
                    func.sum(EOS_MATERIAL_RELEASE_TABLE.c.released_amount_functional), 0
                ),
            ).where(
                EOS_MATERIAL_RELEASE_TABLE.c.tenant_id == line["tenant_id"],
                EOS_MATERIAL_RELEASE_TABLE.c.company_id == line["company_id"],
                EOS_MATERIAL_RELEASE_TABLE.c.commitment_id == line["commitment_id"],
                EOS_MATERIAL_RELEASE_TABLE.c.attribution_line_no
                == line["attribution_line_no"],
            )
        ).one()
        if (
            _quantity(used[0] + line["released_quantity"])
            > _quantity(source["attributed_quantity"])
            or _money(used[1] + line["released_amount_functional"])
            > _money(source["attributed_amount_functional"])
        ):
            raise _error(
                "MATERIAL_COMMITMENT_OVER_RELEASED",
                "Material release exceeds remaining commitment quantity or value",
                409,
            )


def _identity_row(session: Session, header: dict[str, Any]) -> dict[str, Any] | None:
    row = (
        session.execute(
            select(EOS_MATERIAL_CONSUMPTION_TABLE).where(
                EOS_MATERIAL_CONSUMPTION_TABLE.c.tenant_id == header["tenant_id"],
                EOS_MATERIAL_CONSUMPTION_TABLE.c.company_id == header["company_id"],
                EOS_MATERIAL_CONSUMPTION_TABLE.c.consumption_ref
                == header["consumption_ref"],
                EOS_MATERIAL_CONSUMPTION_TABLE.c.consumption_revision
                == header["consumption_revision"],
                EOS_MATERIAL_CONSUMPTION_TABLE.c.component_ref
                == header["component_ref"],
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _stored_lines(
    session: Session, header: dict[str, Any]
) -> tuple[dict[str, Any], ...]:
    rows = session.execute(
        select(EOS_MATERIAL_RELEASE_TABLE)
        .where(
            EOS_MATERIAL_RELEASE_TABLE.c.tenant_id == header["tenant_id"],
            EOS_MATERIAL_RELEASE_TABLE.c.company_id == header["company_id"],
            EOS_MATERIAL_RELEASE_TABLE.c.consumption_id == header["consumption_id"],
        )
        .order_by(EOS_MATERIAL_RELEASE_TABLE.c.line_no)
    ).mappings()
    return tuple(dict(row) for row in rows)


def _replay_projection(
    session: Session, existing: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    if existing["consumption_hash"] != expected["consumption_hash"]:
        raise _error(
            "MATERIAL_CONSUMPTION_CONFLICT",
            "Material consumption identity was reused with different semantics",
            409,
        )
    return _projection(existing, _stored_lines(session, existing), disposition="EXACT_REPLAY")


def _projection(
    header: dict[str, Any], lines: Sequence[dict[str, Any]], *, disposition: str
) -> dict[str, Any]:
    projected = dict(header)
    for key in (
        "consumed_quantity",
        "recognized_cost_functional",
        "released_carrying_amount_functional",
        "valuation_variance_functional",
    ):
        projected[key] = format(Decimal(header[key]).quantize(_MONEY), "f")
    projected["schema_version"] = MATERIAL_CONSUMPTION_SCHEMA
    projected["disposition"] = disposition
    projected["releases"] = [
        {
            **dict(line),
            "released_quantity": format(
                Decimal(line["released_quantity"]).quantize(_QUANTITY), "f"
            ),
            "released_amount_functional": format(
                Decimal(line["released_amount_functional"]).quantize(_MONEY), "f"
            ),
        }
        for line in lines
    ]
    return projected


def _error(
    code: str, detail: str, status: int, *, retryable: bool = False
) -> EosMaterialConsumptionError:
    return EosMaterialConsumptionError(
        code, detail, status_code=status, retryable=retryable
    )


def _invalid(detail: str) -> EosMaterialConsumptionError:
    return _error("MATERIAL_CONSUMPTION_INVALID", detail, 422)


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


def _hash(name: str, value: str) -> str:
    normalized = str(value).strip().lower()
    if not _HASH_REF.fullmatch(normalized):
        raise _invalid(f"{name} must be a sha256 reference")
    return normalized


def _project_code(value: str) -> str:
    normalized = str(value).strip().upper()
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


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (ValueError, TypeError) as exc:
        raise _invalid(f"{name} must be a positive integer") from exc
    if parsed <= 0 or parsed != value:
        raise _invalid(f"{name} must be a positive integer")
    return parsed


def _positive_decimal(name: str, value: Any, quantum: Decimal) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid(f"{name} must be a decimal") from exc
    if not parsed.is_finite() or parsed <= 0 or parsed.as_tuple().exponent < -4:
        raise _invalid(f"{name} must be positive with at most four decimals")
    return parsed.quantize(quantum)


def _money(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid("amount must be a decimal") from exc
    if not parsed.is_finite():
        raise _invalid("amount must be finite")
    return parsed.quantize(_MONEY)


def _quantity(value: Any) -> Decimal:
    return _money(value).quantize(_QUANTITY)


def _utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
