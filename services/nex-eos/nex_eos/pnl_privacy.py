from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import Uuid

from .cost_allocations import EOS_COST_ALLOCATION_BATCH_TABLE
from .payroll_labor_bridge import (
    EOS_LABOR_EFFORT_LINE_TABLE,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
)
from .payroll_project_allocations import EOS_PAYROLL_PROJECT_ALLOCATION_TABLE
from .project_authorization import EosProjectAuthorizationEvidence
from .project_pnl import EOS_METADATA

PROJECT_PNL_PRIVACY_POLICY_VERSION = "project-pnl-privacy.v1"
PROJECT_PNL_QUERY_SHAPE = "PROJECT_PERIOD_LATEST_NO_FILTERS"


EOS_PNL_PRIVACY_GUARD_TABLE = Table(
    "eos_pnl_privacy_guard",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("subject_id", String(128), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), primary_key=True),
    Column("period_id", Uuid(as_uuid=False), primary_key=True),
    Column("projection_id", Uuid(as_uuid=False), nullable=False),
    Column("projection_version", Integer, nullable=False),
    Column("privacy_fingerprint", String(71), nullable=False),
    Column("population_floor", Integer, nullable=False),
    Column("minimum_population", Integer, nullable=False),
    Column("payroll_component_count", Integer, nullable=False),
    Column("authorization_decision_hash", String(71), nullable=False),
    Column("admitted_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "projection_id"),
        (
            "eos_project_pnl_projection.tenant_id",
            "eos_project_pnl_projection.company_id",
            "eos_project_pnl_projection.projection_id",
        ),
        name="fk_eos_pnl_privacy_projection",
    ),
    CheckConstraint("projection_version > 0", name="ck_eos_pnl_privacy_version"),
    CheckConstraint(
        "population_floor > 0 AND minimum_population > 0 "
        "AND population_floor >= minimum_population",
        name="ck_eos_pnl_privacy_population",
    ),
    CheckConstraint(
        "payroll_component_count > 0", name="ck_eos_pnl_privacy_components"
    ),
)
Index(
    "ix_eos_pnl_privacy_project",
    EOS_PNL_PRIVACY_GUARD_TABLE.c.tenant_id,
    EOS_PNL_PRIVACY_GUARD_TABLE.c.company_id,
    EOS_PNL_PRIVACY_GUARD_TABLE.c.project_id,
    EOS_PNL_PRIVACY_GUARD_TABLE.c.period_id,
)


class EosPnlPrivacyError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
        reason_code: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        self.reason_code = reason_code
        super().__init__(detail)


@dataclass(frozen=True)
class PnlPrivacyPopulationFact:
    snapshot_id: str
    line_no: int
    population_count: int
    minimum_population: int
    ordinary_view_suppressed: bool
    line_hash: str


@dataclass(frozen=True)
class PnlPrivacyGuardAdmission:
    tenant_id: str
    company_id: str
    subject_id: str
    project_id: str
    period_id: str
    projection_id: str
    projection_version: int
    privacy_fingerprint: str
    population_floor: int
    minimum_population: int
    payroll_component_count: int
    authorization_decision_hash: str
    admitted_at: datetime


class PnlPrivacyRepository(Protocol):
    def population_facts(
        self,
        *,
        tenant_id: str,
        company_id: str,
        project_id: str,
        period_id: str,
        as_of: datetime,
    ) -> tuple[PnlPrivacyPopulationFact, ...]: ...

    def admit_guard(
        self, value: PnlPrivacyGuardAdmission
    ) -> tuple[PnlPrivacyGuardAdmission, bool]: ...


@dataclass
class InMemoryPnlPrivacyRepository:
    facts: tuple[PnlPrivacyPopulationFact, ...] = ()
    guards: dict[tuple[str, str, str, str, str], PnlPrivacyGuardAdmission] = field(
        default_factory=dict
    )

    def population_facts(
        self,
        *,
        tenant_id: str,
        company_id: str,
        project_id: str,
        period_id: str,
        as_of: datetime,
    ) -> tuple[PnlPrivacyPopulationFact, ...]:
        del tenant_id, company_id, project_id, period_id, as_of
        return self.facts

    def admit_guard(
        self, value: PnlPrivacyGuardAdmission
    ) -> tuple[PnlPrivacyGuardAdmission, bool]:
        key = _guard_key(value)
        existing = self.guards.get(key)
        if existing is not None:
            return existing, False
        self.guards[key] = value
        return value, True


class SqlAlchemyEosPnlPrivacyRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def population_facts(
        self,
        *,
        tenant_id: str,
        company_id: str,
        project_id: str,
        period_id: str,
        as_of: datetime,
    ) -> tuple[PnlPrivacyPopulationFact, ...]:
        line = EOS_LABOR_EFFORT_LINE_TABLE
        snapshot = EOS_LABOR_EFFORT_SNAPSHOT_TABLE
        allocation = EOS_PAYROLL_PROJECT_ALLOCATION_TABLE
        batch = EOS_COST_ALLOCATION_BATCH_TABLE
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        select(
                            line.c.snapshot_id,
                            line.c.line_no,
                            line.c.population_count,
                            line.c.minimum_population,
                            line.c.ordinary_view_suppressed,
                            line.c.line_hash,
                        )
                        .distinct()
                        .join(
                            snapshot,
                            (snapshot.c.tenant_id == line.c.tenant_id)
                            & (snapshot.c.company_id == line.c.company_id)
                            & (snapshot.c.snapshot_id == line.c.snapshot_id),
                        )
                        .join(
                            allocation,
                            (allocation.c.tenant_id == snapshot.c.tenant_id)
                            & (allocation.c.company_id == snapshot.c.company_id)
                            & (
                                allocation.c.effort_snapshot_id
                                == snapshot.c.snapshot_id
                            ),
                        )
                        .join(
                            batch,
                            (batch.c.tenant_id == allocation.c.tenant_id)
                            & (batch.c.company_id == allocation.c.company_id)
                            & (batch.c.batch_id == allocation.c.batch_id),
                        )
                        .where(
                            line.c.tenant_id == tenant_id,
                            line.c.company_id == company_id,
                            line.c.project_id == project_id,
                            batch.c.period_id == period_id,
                            allocation.c.created_at <= as_of,
                            snapshot.c.created_at <= as_of,
                        )
                        .order_by(line.c.snapshot_id, line.c.line_no)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise _unavailable("Payroll privacy evidence is unavailable") from exc
        return tuple(
            PnlPrivacyPopulationFact(
                snapshot_id=str(row["snapshot_id"]),
                line_no=int(row["line_no"]),
                population_count=int(row["population_count"]),
                minimum_population=int(row["minimum_population"]),
                ordinary_view_suppressed=bool(row["ordinary_view_suppressed"]),
                line_hash=str(row["line_hash"]),
            )
            for row in rows
        )

    def admit_guard(
        self, value: PnlPrivacyGuardAdmission
    ) -> tuple[PnlPrivacyGuardAdmission, bool]:
        try:
            with self._session_factory.begin() as session:
                existing = _guard_row(session, value)
                if existing is not None:
                    return _guard_admission(existing), False
                session.execute(
                    EOS_PNL_PRIVACY_GUARD_TABLE.insert().values(**_guard_record(value))
                )
                return value, True
        except IntegrityError as exc:
            try:
                with self._session_factory() as session:
                    existing = _guard_row(session, value)
            except SQLAlchemyError as replay_exc:
                raise _unavailable(
                    "P&L privacy guard replay is unavailable"
                ) from replay_exc
            if existing is None:
                raise _unavailable(
                    "P&L privacy guard race could not be resolved"
                ) from exc
            return _guard_admission(existing), False
        except SQLAlchemyError as exc:
            raise _unavailable("P&L privacy guard persistence is unavailable") from exc


class EosProjectPnlPrivacyGuard:
    def __init__(self, repository: PnlPrivacyRepository) -> None:
        self._repository = repository

    def protect(
        self,
        projection: Mapping[str, Any],
        *,
        subject_id: str,
        authorization: EosProjectAuthorizationEvidence,
        historical_version_requested: bool,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        document = dict(projection)
        payroll_components = tuple(
            component
            for component in _components(document)
            if component.get("source_kind") == "PAYROLL"
            or component.get("data_classification") == "PAYROLL_SENSITIVE"
        )
        if not payroll_components:
            return document
        if historical_version_requested:
            raise _denied("HISTORICAL_VERSION_DIFFERENCE")

        as_of = _aware_datetime(document.get("as_of"))
        facts = self._repository.population_facts(
            tenant_id=str(document["tenant_id"]),
            company_id=str(document["company_id"]),
            project_id=str(document["project_id"]),
            period_id=str(document["period_id"]),
            as_of=as_of,
        )
        if not facts:
            raise _denied("POPULATION_EVIDENCE_MISSING")
        if any(
            fact.ordinary_view_suppressed
            or fact.population_count < fact.minimum_population
            for fact in facts
        ):
            raise _denied("SMALL_CELL_SUPPRESSED")

        population_floor = min(fact.population_count for fact in facts)
        minimum_population = max(fact.minimum_population for fact in facts)
        fingerprint = _privacy_fingerprint(
            document=document,
            payroll_components=payroll_components,
            facts=facts,
        )
        admission = PnlPrivacyGuardAdmission(
            tenant_id=str(document["tenant_id"]),
            company_id=str(document["company_id"]),
            subject_id=subject_id,
            project_id=str(document["project_id"]),
            period_id=str(document["period_id"]),
            projection_id=str(document["projection_id"]),
            projection_version=int(document["projection_version"]),
            privacy_fingerprint=fingerprint,
            population_floor=population_floor,
            minimum_population=minimum_population,
            payroll_component_count=len(payroll_components),
            authorization_decision_hash=_authorization_hash(authorization),
            admitted_at=observed_at or datetime.now(UTC),
        )
        stored, _created = self._repository.admit_guard(admission)
        if stored.privacy_fingerprint != admission.privacy_fingerprint:
            raise _denied("PAYROLL_FINGERPRINT_CHANGED")
        return document


def _privacy_fingerprint(
    *,
    document: Mapping[str, Any],
    payroll_components: Sequence[Mapping[str, Any]],
    facts: Sequence[PnlPrivacyPopulationFact],
) -> str:
    return semantic_sha256_hash_ref(
        {
            "domain": "EOS-PROJECT-PNL-PRIVACY-GUARD-V1",
            "policy_version": PROJECT_PNL_PRIVACY_POLICY_VERSION,
            "query_shape": PROJECT_PNL_QUERY_SHAPE,
            "tenant_id": document["tenant_id"],
            "company_id": document["company_id"],
            "project_id": document["project_id"],
            "period_id": document["period_id"],
            "payroll_components": [
                {
                    "classification": item.get("classification"),
                    "functional_amount": item.get("functional_amount"),
                    "source_hash": item.get("source_hash"),
                    "component_hash": item.get("component_hash"),
                }
                for item in sorted(
                    payroll_components,
                    key=lambda item: (
                        int(item.get("line_no", 0)),
                        str(item.get("component_hash", "")),
                    ),
                )
            ],
            "population_facts": [
                {
                    "line_hash": fact.line_hash,
                    "population_count": fact.population_count,
                    "minimum_population": fact.minimum_population,
                }
                for fact in sorted(facts, key=lambda item: item.line_hash)
            ],
        }
    )


def _authorization_hash(value: EosProjectAuthorizationEvidence) -> str:
    return semantic_sha256_hash_ref(
        {
            "domain": "EOS-PROJECT-PNL-AUTHORIZATION-DECISION-V1",
            "decision_ref": value.decision_ref,
            "project_code": value.project_code,
            "project_role": value.project_role,
            "source_version": value.source_version,
            "authorization_revision_hash": value.authorization_revision_hash,
            "decided_at": value.decided_at,
        }
    )


def _components(document: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = document.get("components")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _unavailable("P&L projection components are malformed")
    if not all(isinstance(item, Mapping) for item in value):
        raise _unavailable("P&L projection components are malformed")
    return tuple(value)


def _aware_datetime(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _unavailable("P&L projection as_of is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _unavailable("P&L projection as_of is malformed")
    return parsed


def _guard_key(value: PnlPrivacyGuardAdmission) -> tuple[str, str, str, str, str]:
    return (
        value.tenant_id,
        value.company_id,
        value.subject_id,
        value.project_id,
        value.period_id,
    )


def _guard_record(value: PnlPrivacyGuardAdmission) -> dict[str, Any]:
    return {
        field_name: getattr(value, field_name)
        for field_name in PnlPrivacyGuardAdmission.__dataclass_fields__
    }


def _guard_row(
    session: Session, value: PnlPrivacyGuardAdmission
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_PNL_PRIVACY_GUARD_TABLE).where(
                EOS_PNL_PRIVACY_GUARD_TABLE.c.tenant_id == value.tenant_id,
                EOS_PNL_PRIVACY_GUARD_TABLE.c.company_id == value.company_id,
                EOS_PNL_PRIVACY_GUARD_TABLE.c.subject_id == value.subject_id,
                EOS_PNL_PRIVACY_GUARD_TABLE.c.project_id == value.project_id,
                EOS_PNL_PRIVACY_GUARD_TABLE.c.period_id == value.period_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _guard_admission(row: Mapping[str, Any]) -> PnlPrivacyGuardAdmission:
    return PnlPrivacyGuardAdmission(
        tenant_id=str(row["tenant_id"]),
        company_id=str(row["company_id"]),
        subject_id=str(row["subject_id"]),
        project_id=str(row["project_id"]),
        period_id=str(row["period_id"]),
        projection_id=str(row["projection_id"]),
        projection_version=int(row["projection_version"]),
        privacy_fingerprint=str(row["privacy_fingerprint"]),
        population_floor=int(row["population_floor"]),
        minimum_population=int(row["minimum_population"]),
        payroll_component_count=int(row["payroll_component_count"]),
        authorization_decision_hash=str(row["authorization_decision_hash"]),
        admitted_at=row["admitted_at"],
    )


def _denied(reason_code: str) -> EosPnlPrivacyError:
    return EosPnlPrivacyError(
        "PAYROLL_PRIVACY_DENIED",
        "Project P&L payroll aggregate is not available for this query",
        status_code=403,
        reason_code=reason_code,
    )


def _unavailable(detail: str) -> EosPnlPrivacyError:
    return EosPnlPrivacyError(
        "PNL_PRIVACY_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )
