from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nex_runtime.semantic_hashes import (
    eos_fx_policy_hash_ref,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import (
    JSON,
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
    or_,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import EOS_METADATA
from .legal_entities import EOS_LEGAL_ENTITY_TABLE

FX_POLICY_PURPOSES = frozenset(
    {
        "TRANSACTION_SPOT",
        "MONETARY_CLOSE",
        "SETTLEMENT_REFERENCE",
        "TAX_VALUATION",
    }
)
FX_RATE_KINDS = frozenset({"MARKET_BASE", "DERIVED_CROSS", "APPROVED_EXCEPTION"})
FX_PUBLICATION_SELECTORS = frozenset({"FIRST", "FINAL", "AS_OF_TIMESTAMP"})
FX_ROUNDING_MODES = frozenset({"HALF_EVEN"})
FINANCE_FX_PUBLISH_SCOPE = "finance:fx:publish"
FINANCE_FX_READ_SCOPE = "finance:fx:read"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")

EOS_FX_RATE_POLICY_TABLE = Table(
    "eos_fx_rate_policy",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("policy_id", Uuid(as_uuid=False), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("purpose", String(32), nullable=False),
    Column("base_currency", String(3), nullable=False),
    Column("quote_currency", String(3), nullable=False),
    Column("rate_kind", String(32), nullable=False),
    Column("source_provider_id", String(128), nullable=False),
    Column("publication_selector", String(32), nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("effective_to", Date, nullable=True),
    Column("allow_previous_business_day", Boolean, nullable=False),
    Column("max_staleness_business_days", Integer, nullable=False),
    Column("rounding_mode", String(32), nullable=False),
    Column("rate_decimal_scale", Integer, nullable=False),
    Column("approved_by", String(128), nullable=False),
    Column("approval_proof_hash", String(71), nullable=False),
    Column("policy_hash", String(71), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_fx_rate_policy_company",
    ),
    UniqueConstraint("tenant_id", "policy_hash", name="ux_eos_fx_rate_policy_hash"),
    CheckConstraint("effective_to IS NULL OR effective_to > effective_from"),
)
Index(
    "ix_eos_fx_rate_policy_resolve",
    EOS_FX_RATE_POLICY_TABLE.c.tenant_id,
    EOS_FX_RATE_POLICY_TABLE.c.company_id,
    EOS_FX_RATE_POLICY_TABLE.c.purpose,
    EOS_FX_RATE_POLICY_TABLE.c.base_currency,
    EOS_FX_RATE_POLICY_TABLE.c.quote_currency,
    EOS_FX_RATE_POLICY_TABLE.c.status,
    EOS_FX_RATE_POLICY_TABLE.c.effective_from,
    EOS_FX_RATE_POLICY_TABLE.c.effective_to,
)

EOS_FX_MARKET_RATE_TABLE = Table(
    "eos_fx_market_rate",
    EOS_METADATA,
    Column("market_rate_id", Uuid(as_uuid=False), primary_key=True),
    Column("source_provider_id", String(128), nullable=False),
    Column("source_record_id", String(256), nullable=False),
    Column("publication_issue", String(64), nullable=False),
    Column("base_currency", String(3), nullable=False),
    Column("quote_currency", String(3), nullable=False),
    Column("quote_unit", Numeric(18, 6), nullable=False),
    Column("published_rate", Numeric(28, 12), nullable=False),
    Column("rate_date", Date, nullable=False),
    Column("rate_as_of", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("is_final", Boolean, nullable=False),
    Column("source_uri", String(2048), nullable=False),
    Column("source_sha256", String(71), nullable=False),
    Column("source_timezone", String(64), nullable=False),
    Column("provenance_json", JSON, nullable=False),
    Column("market_rate_hash", String(71), nullable=False),
    Column("market_admitted_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "source_provider_id",
        "source_record_id",
        "publication_issue",
        "base_currency",
        "quote_currency",
        "rate_date",
        name="ux_eos_fx_market_rate_source",
    ),
    UniqueConstraint("market_rate_hash", name="ux_eos_fx_market_rate_hash"),
)
Index(
    "ix_eos_fx_market_rate_lookup",
    EOS_FX_MARKET_RATE_TABLE.c.source_provider_id,
    EOS_FX_MARKET_RATE_TABLE.c.base_currency,
    EOS_FX_MARKET_RATE_TABLE.c.quote_currency,
    EOS_FX_MARKET_RATE_TABLE.c.rate_date,
    EOS_FX_MARKET_RATE_TABLE.c.published_at,
)

EOS_FX_RATE_SNAPSHOT_TABLE = Table(
    "eos_fx_rate_snapshot",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("rate_snapshot_id", Uuid(as_uuid=False), primary_key=True),
    Column("market_rate_id", Uuid(as_uuid=False), nullable=False),
    Column("rate_policy_id", Uuid(as_uuid=False), nullable=False),
    Column("rate_policy_version", Integer, nullable=False),
    Column("normalized_rate", Numeric(28, 12), nullable=False),
    Column("desired_rate_date", Date, nullable=False),
    Column("effective_business_date", Date, nullable=False),
    Column("calendar_ref", String(128), nullable=False),
    Column("snapshot_hash", String(71), nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("approved_state", String(16), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "rate_policy_id", "rate_policy_version"),
        (
            "eos_fx_rate_policy.tenant_id",
            "eos_fx_rate_policy.company_id",
            "eos_fx_rate_policy.policy_id",
            "eos_fx_rate_policy.version",
        ),
        name="fk_eos_fx_rate_snapshot_policy",
    ),
    ForeignKeyConstraint(
        ("market_rate_id",),
        ("eos_fx_market_rate.market_rate_id",),
        name="fk_eos_fx_rate_snapshot_market",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "rate_policy_id",
        "rate_policy_version",
        "market_rate_id",
        name="ux_eos_fx_rate_snapshot_adoption",
    ),
    UniqueConstraint("tenant_id", "snapshot_hash", name="ux_eos_fx_rate_snapshot_hash"),
)
Index(
    "ix_eos_fx_rate_snapshot_resolve",
    EOS_FX_RATE_SNAPSHOT_TABLE.c.tenant_id,
    EOS_FX_RATE_SNAPSHOT_TABLE.c.company_id,
    EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_policy_id,
    EOS_FX_RATE_SNAPSHOT_TABLE.c.market_rate_id,
    EOS_FX_RATE_SNAPSHOT_TABLE.c.approved_state,
    EOS_FX_RATE_SNAPSHOT_TABLE.c.effective_business_date,
)


class EosFxRateError(RuntimeError):
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
class FxRatePolicyInput:
    tenant_id: str
    company_id: str
    policy_id: str
    version: int
    purpose: str
    base_currency: str
    quote_currency: str
    rate_kind: str
    source_provider_id: str
    publication_selector: str
    effective_from: date
    allow_previous_business_day: bool
    max_staleness_business_days: int
    rounding_mode: str
    rate_decimal_scale: int
    approved_by: str
    approval_proof_hash: str
    policy_hash: str
    effective_to: date | None = None


@dataclass(frozen=True)
class FxRateSnapshotInput:
    tenant_id: str
    company_id: str
    rate_snapshot_id: str
    rate_policy_id: str
    rate_policy_version: int
    source_provider_id: str
    base_currency: str
    quote_currency: str
    quote_unit: Decimal
    published_rate: Decimal
    desired_rate_date: date
    rate_date: date
    rate_as_of: datetime
    published_at: datetime
    publication_issue: str
    is_final: bool
    source_record_id: str
    source_uri: str
    source_sha256: str
    calendar_ref: str
    source_timezone: str
    provenance: Mapping[str, Any]


class SqlAlchemyEosFxRateRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_approved_policy(self, value: FxRatePolicyInput) -> dict[str, Any]:
        record = _policy_record(value)
        try:
            with self._session_factory.begin() as session:
                self._lock_policy_scope(session, record)
                existing = self._policy_by_id(session, record)
                if existing is not None:
                    if _policy_semantics(existing) == _policy_semantics(record):
                        return _wire(existing)
                    raise _conflict("FX policy identity has different semantics")
                self._require_active_company(session, record)
                overlap_conditions = [
                    EOS_FX_RATE_POLICY_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_FX_RATE_POLICY_TABLE.c.company_id == record["company_id"],
                    EOS_FX_RATE_POLICY_TABLE.c.purpose == record["purpose"],
                    EOS_FX_RATE_POLICY_TABLE.c.base_currency == record["base_currency"],
                    EOS_FX_RATE_POLICY_TABLE.c.quote_currency
                    == record["quote_currency"],
                    EOS_FX_RATE_POLICY_TABLE.c.status == "APPROVED",
                    or_(
                        EOS_FX_RATE_POLICY_TABLE.c.effective_to.is_(None),
                        EOS_FX_RATE_POLICY_TABLE.c.effective_to
                        > record["effective_from"],
                    ),
                ]
                if record["effective_to"] is not None:
                    overlap_conditions.append(
                        EOS_FX_RATE_POLICY_TABLE.c.effective_from
                        < record["effective_to"]
                    )
                overlap = session.execute(
                    select(EOS_FX_RATE_POLICY_TABLE.c.policy_id)
                    .where(*overlap_conditions)
                    .limit(1)
                ).scalar_one_or_none()
                if overlap is not None:
                    raise _conflict("approved FX policy effective interval overlaps")
                session.execute(EOS_FX_RATE_POLICY_TABLE.insert().values(**record))
        except EosFxRateError:
            raise
        except IntegrityError as exc:
            raise _conflict("FX policy violates an identity or interval guard") from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return _wire(record)

    def import_approved_snapshot(self, value: FxRateSnapshotInput) -> dict[str, Any]:
        normalized = _snapshot_values(value)
        try:
            with self._session_factory.begin() as session:
                policy = self._policy_for_snapshot(session, normalized)
                self._lock_market_source(session, normalized)
                market = self._admit_market_rate(session, normalized)
                record = _snapshot_record(normalized, policy, market)
                existing = self._snapshot_by_id(session, record)
                if existing is not None:
                    if _snapshot_semantics(existing) == _snapshot_semantics(record):
                        return _snapshot_wire(existing, market)
                    raise _conflict("FX RateSnapshot identity has different semantics")
                adoption = self._snapshot_by_adoption(session, record)
                if adoption is not None:
                    if _snapshot_adoption_semantics(
                        adoption
                    ) == _snapshot_adoption_semantics(record):
                        return _snapshot_wire(adoption, market)
                    raise _conflict(
                        "FX market observation was already adopted with different semantics"
                    )
                session.execute(EOS_FX_RATE_SNAPSHOT_TABLE.insert().values(**record))
        except EosFxRateError:
            raise
        except IntegrityError as exc:
            raise _conflict("FX RateSnapshot violates an identity guard") from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return _snapshot_wire(record, market)

    def resolve_rate(
        self,
        *,
        tenant_id: str,
        company_id: str,
        purpose: str,
        base_currency: str,
        quote_currency: str,
        desired_rate_date: date,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        company_id = _uuid("company_id", company_id)
        purpose = _choice("purpose", purpose, FX_POLICY_PURPOSES)
        base_currency = _currency("base_currency", base_currency)
        quote_currency = _currency("quote_currency", quote_currency)
        if base_currency == quote_currency:
            raise _invalid("base_currency and quote_currency must differ")
        desired_rate_date = _date("desired_rate_date", desired_rate_date)
        as_of = _aware_datetime("as_of", as_of or datetime.now(UTC))
        try:
            with self._session_factory() as session:
                policies = (
                    session.execute(
                        select(EOS_FX_RATE_POLICY_TABLE).where(
                            EOS_FX_RATE_POLICY_TABLE.c.tenant_id == tenant_id,
                            EOS_FX_RATE_POLICY_TABLE.c.company_id == company_id,
                            EOS_FX_RATE_POLICY_TABLE.c.purpose == purpose,
                            EOS_FX_RATE_POLICY_TABLE.c.base_currency == base_currency,
                            EOS_FX_RATE_POLICY_TABLE.c.quote_currency == quote_currency,
                            EOS_FX_RATE_POLICY_TABLE.c.status == "APPROVED",
                            EOS_FX_RATE_POLICY_TABLE.c.effective_from
                            <= desired_rate_date,
                            or_(
                                EOS_FX_RATE_POLICY_TABLE.c.effective_to.is_(None),
                                EOS_FX_RATE_POLICY_TABLE.c.effective_to
                                > desired_rate_date,
                            ),
                        )
                    )
                    .mappings()
                    .all()
                )
                if len(policies) != 1:
                    raise _rate_unavailable(
                        "exactly one effective approved FX policy is required"
                    )
                policy = policies[0]
                snapshot = (
                    session.execute(
                        select(*_snapshot_projection())
                        .select_from(
                            EOS_FX_RATE_SNAPSHOT_TABLE.join(
                                EOS_FX_MARKET_RATE_TABLE,
                                EOS_FX_RATE_SNAPSHOT_TABLE.c.market_rate_id
                                == EOS_FX_MARKET_RATE_TABLE.c.market_rate_id,
                            )
                        )
                        .where(
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.tenant_id == tenant_id,
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.company_id == company_id,
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_policy_id
                            == policy["policy_id"],
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_policy_version
                            == policy["version"],
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.approved_state == "APPROVED",
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.effective_business_date
                            <= desired_rate_date,
                            EOS_FX_MARKET_RATE_TABLE.c.published_at <= as_of,
                        )
                        .order_by(
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.effective_business_date.desc(),
                            EOS_FX_MARKET_RATE_TABLE.c.published_at.desc(),
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_snapshot_id,
                        )
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
        except EosFxRateError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        if snapshot is None:
            raise _rate_unavailable("no trusted FX RateSnapshot is available")
        selected_date = snapshot["effective_business_date"]
        staleness = _business_day_distance(selected_date, desired_rate_date)
        if (
            selected_date != desired_rate_date
            and not policy["allow_previous_business_day"]
        ):
            raise _stale("previous-business-day fallback is not approved")
        if staleness > policy["max_staleness_business_days"]:
            raise _stale("FX RateSnapshot exceeds approved staleness")
        return {
            **_wire(snapshot),
            "purpose": policy["purpose"],
            "policy_hash": policy["policy_hash"],
            "desired_rate_date": desired_rate_date.isoformat(),
            "selected_rate_date": selected_date.isoformat(),
            "staleness_business_days": staleness,
        }

    def list_rate_history(
        self,
        *,
        tenant_id: str,
        company_id: str,
        purpose: str,
        base_currency: str,
        quote_currency: str,
        date_from: date,
        date_to: date,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        company_id = _uuid("company_id", company_id)
        purpose = _choice("purpose", purpose, FX_POLICY_PURPOSES)
        base_currency = _currency("base_currency", base_currency)
        quote_currency = _currency("quote_currency", quote_currency)
        if base_currency == quote_currency:
            raise _invalid("base_currency and quote_currency must differ")
        date_from = _date("date_from", date_from)
        date_to = _date("date_to", date_to)
        if date_to < date_from:
            raise _invalid("date_to must not precede date_from")
        limit = _bounded_int("limit", limit, 1, 500)
        policy_join_condition = (
            (
                EOS_FX_RATE_POLICY_TABLE.c.tenant_id
                == EOS_FX_RATE_SNAPSHOT_TABLE.c.tenant_id
            )
            & (
                EOS_FX_RATE_POLICY_TABLE.c.company_id
                == EOS_FX_RATE_SNAPSHOT_TABLE.c.company_id
            )
            & (
                EOS_FX_RATE_POLICY_TABLE.c.policy_id
                == EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_policy_id
            )
            & (
                EOS_FX_RATE_POLICY_TABLE.c.version
                == EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_policy_version
            )
        )
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        select(
                            *_snapshot_projection(),
                            EOS_FX_RATE_POLICY_TABLE.c.purpose.label("purpose"),
                            EOS_FX_RATE_POLICY_TABLE.c.policy_hash.label("policy_hash"),
                        )
                        .select_from(
                            EOS_FX_RATE_SNAPSHOT_TABLE.join(
                                EOS_FX_RATE_POLICY_TABLE, policy_join_condition
                            ).join(
                                EOS_FX_MARKET_RATE_TABLE,
                                EOS_FX_RATE_SNAPSHOT_TABLE.c.market_rate_id
                                == EOS_FX_MARKET_RATE_TABLE.c.market_rate_id,
                            )
                        )
                        .where(
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.tenant_id == tenant_id,
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.company_id == company_id,
                            EOS_FX_RATE_POLICY_TABLE.c.purpose == purpose,
                            EOS_FX_MARKET_RATE_TABLE.c.base_currency == base_currency,
                            EOS_FX_MARKET_RATE_TABLE.c.quote_currency == quote_currency,
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.approved_state == "APPROVED",
                            EOS_FX_MARKET_RATE_TABLE.c.rate_date >= date_from,
                            EOS_FX_MARKET_RATE_TABLE.c.rate_date <= date_to,
                        )
                        .order_by(
                            EOS_FX_MARKET_RATE_TABLE.c.rate_date.desc(),
                            EOS_FX_MARKET_RATE_TABLE.c.published_at.desc(),
                            EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_snapshot_id,
                        )
                        .limit(limit)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return [_wire(row) for row in rows]

    @staticmethod
    def _lock_market_source(session: Session, record: Mapping[str, Any]) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            scope = ":".join(
                str(record[field])
                for field in (
                    "source_provider_id",
                    "source_record_id",
                    "publication_issue",
                    "base_currency",
                    "quote_currency",
                    "rate_date",
                )
            )
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"fx-market:{scope}"},
            )

    @classmethod
    def _admit_market_rate(
        cls, session: Session, values: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        record = _market_rate_record(values)
        by_id = cls._market_rate_by_id(session, record)
        if by_id is not None:
            if _market_source_semantics(by_id) == _market_source_semantics(record):
                return by_id
            raise _conflict("FX MarketRate identity has different semantics")
        by_source = cls._market_rate_by_source(session, record)
        if by_source is not None:
            if _market_source_semantics(by_source) == _market_source_semantics(record):
                return by_source
            raise _conflict("global FX source record/date/issue has different content")
        session.execute(EOS_FX_MARKET_RATE_TABLE.insert().values(**record))
        return record

    @staticmethod
    def _market_rate_by_id(
        session: Session, record: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_FX_MARKET_RATE_TABLE).where(
                    EOS_FX_MARKET_RATE_TABLE.c.market_rate_id
                    == record["market_rate_id"]
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _market_rate_by_source(
        session: Session, record: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_FX_MARKET_RATE_TABLE).where(
                    EOS_FX_MARKET_RATE_TABLE.c.source_provider_id
                    == record["source_provider_id"],
                    EOS_FX_MARKET_RATE_TABLE.c.source_record_id
                    == record["source_record_id"],
                    EOS_FX_MARKET_RATE_TABLE.c.publication_issue
                    == record["publication_issue"],
                    EOS_FX_MARKET_RATE_TABLE.c.base_currency == record["base_currency"],
                    EOS_FX_MARKET_RATE_TABLE.c.quote_currency
                    == record["quote_currency"],
                    EOS_FX_MARKET_RATE_TABLE.c.rate_date == record["rate_date"],
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _lock_policy_scope(session: Session, record: Mapping[str, Any]) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            scope = ":".join(
                str(record[field])
                for field in (
                    "tenant_id",
                    "company_id",
                    "purpose",
                    "base_currency",
                    "quote_currency",
                )
            )
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": scope},
            )

    @staticmethod
    def _policy_by_id(
        session: Session, record: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_FX_RATE_POLICY_TABLE).where(
                    EOS_FX_RATE_POLICY_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_FX_RATE_POLICY_TABLE.c.company_id == record["company_id"],
                    EOS_FX_RATE_POLICY_TABLE.c.policy_id == record["policy_id"],
                    EOS_FX_RATE_POLICY_TABLE.c.version == record["version"],
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _snapshot_by_id(
        session: Session, record: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_FX_RATE_SNAPSHOT_TABLE).where(
                    EOS_FX_RATE_SNAPSHOT_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_snapshot_id
                    == record["rate_snapshot_id"],
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _snapshot_by_adoption(
        session: Session, record: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_FX_RATE_SNAPSHOT_TABLE).where(
                    EOS_FX_RATE_SNAPSHOT_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_FX_RATE_SNAPSHOT_TABLE.c.company_id == record["company_id"],
                    EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_policy_id
                    == record["rate_policy_id"],
                    EOS_FX_RATE_SNAPSHOT_TABLE.c.rate_policy_version
                    == record["rate_policy_version"],
                    EOS_FX_RATE_SNAPSHOT_TABLE.c.market_rate_id
                    == record["market_rate_id"],
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _require_active_company(session: Session, record: Mapping[str, Any]) -> None:
        company = (
            session.execute(
                select(
                    EOS_LEGAL_ENTITY_TABLE.c.status,
                    EOS_LEGAL_ENTITY_TABLE.c.effective_from,
                ).where(
                    EOS_LEGAL_ENTITY_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_LEGAL_ENTITY_TABLE.c.company_id == record["company_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if company is None:
            raise _not_found("LegalEntity was not found in tenant scope")
        if (
            company["status"] != "ACTIVE"
            or company["effective_from"] > record["effective_from"]
        ):
            raise _conflict("LegalEntity is not active at FX policy effective date")

    @staticmethod
    def _policy_for_snapshot(
        session: Session, record: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        policy = (
            session.execute(
                select(EOS_FX_RATE_POLICY_TABLE).where(
                    EOS_FX_RATE_POLICY_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_FX_RATE_POLICY_TABLE.c.company_id == record["company_id"],
                    EOS_FX_RATE_POLICY_TABLE.c.policy_id == record["rate_policy_id"],
                    EOS_FX_RATE_POLICY_TABLE.c.version == record["rate_policy_version"],
                    EOS_FX_RATE_POLICY_TABLE.c.status == "APPROVED",
                )
            )
            .mappings()
            .one_or_none()
        )
        if policy is None:
            raise _rate_unavailable("approved FX policy was not found")
        if (
            policy["source_provider_id"] != record["source_provider_id"]
            or policy["base_currency"] != record["base_currency"]
            or policy["quote_currency"] != record["quote_currency"]
            or not (
                policy["effective_from"]
                <= record["rate_date"]
                < (policy["effective_to"] or date.max)
            )
        ):
            raise _conflict("FX RateSnapshot does not match its approved policy")
        selector = policy["publication_selector"]
        if selector == "FIRST" and record["is_final"]:
            raise _conflict("FIRST policy cannot admit a final publication")
        if selector == "FINAL" and not record["is_final"]:
            raise _conflict("FINAL policy requires a final publication")
        return policy


class EosFxRateService:
    def __init__(
        self,
        repository: SqlAlchemyEosFxRateRepository,
        authorization_source: AuthorizationSource,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source

    def create_approved_policy(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._authorize(tenant_id, requester_subject_id, FINANCE_FX_PUBLISH_SCOPE)
        return self._repository.create_approved_policy(
            _policy_input(tenant_id, payload)
        )

    def import_rates(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._authorize(tenant_id, requester_subject_id, FINANCE_FX_PUBLISH_SCOPE)
        if not isinstance(payload, Mapping):
            raise _invalid("payload must be an object")
        items = payload.get("snapshots")
        if (
            isinstance(items, (str, bytes))
            or not isinstance(items, Sequence)
            or not items
        ):
            raise _invalid("snapshots must be a non-empty array")
        if len(items) > 500:
            raise _invalid("snapshots batch cannot exceed 500 records")
        imported = [
            self._repository.import_approved_snapshot(_snapshot_input(tenant_id, item))
            for item in items
        ]
        return {"operation": "FINANCE.FX_RATE.IMPORT", "snapshots": imported}

    def resolve_rate(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        company_id: str,
        purpose: str,
        base_currency: str,
        quote_currency: str,
        desired_rate_date: date,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        self._authorize(tenant_id, requester_subject_id, FINANCE_FX_READ_SCOPE)
        return self._repository.resolve_rate(
            tenant_id=tenant_id,
            company_id=company_id,
            purpose=purpose,
            base_currency=base_currency,
            quote_currency=quote_currency,
            desired_rate_date=desired_rate_date,
            as_of=as_of,
        )

    def list_rate_history(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        company_id: str,
        purpose: str,
        base_currency: str,
        quote_currency: str,
        date_from: date,
        date_to: date,
        limit: int = 200,
    ) -> dict[str, Any]:
        self._authorize(tenant_id, requester_subject_id, FINANCE_FX_READ_SCOPE)
        return {
            "operation": "FINANCE.FX_RATE.HISTORY",
            "snapshots": self._repository.list_rate_history(
                tenant_id=tenant_id,
                company_id=company_id,
                purpose=purpose,
                base_currency=base_currency,
                quote_currency=quote_currency,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            ),
        }

    def _authorize(self, tenant_id: str, subject_id: str, scope: str) -> None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        subject_id = _scoped_id("requester_subject_id", subject_id)
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied(scope) from exc
        except Exception as exc:
            raise _authority_unavailable() from exc
        if not isinstance(value, Mapping):
            raise _authority_unavailable()
        scopes = value.get("scopes")
        if (
            value.get("active") is not True
            or value.get("tenant_id") != tenant_id
            or value.get("subject_id") != subject_id
        ):
            raise _denied(scope)
        if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Sequence):
            raise _authority_unavailable()
        if any(not isinstance(item, str) or not item for item in scopes):
            raise _authority_unavailable()
        if scope not in scopes:
            raise _denied(scope)
        revision = value.get("revision_hash")
        if not isinstance(revision, str) or _REVISION_HASH.fullmatch(revision) is None:
            raise _authority_unavailable()


def fx_policy_hash(value: Mapping[str, Any]) -> str:
    return eos_fx_policy_hash_ref(value)


def _policy_input(tenant_id: str, value: object) -> FxRatePolicyInput:
    if not isinstance(value, Mapping):
        raise _invalid("policy payload must be an object")
    fields = {
        "company_id",
        "policy_id",
        "version",
        "purpose",
        "base_currency",
        "quote_currency",
        "rate_kind",
        "source_provider_id",
        "publication_selector",
        "effective_from",
        "effective_to",
        "allow_previous_business_day",
        "max_staleness_business_days",
        "rounding_mode",
        "rate_decimal_scale",
        "approved_by",
        "approval_proof_hash",
        "policy_hash",
    }
    _reject_unknown(value, fields)
    return FxRatePolicyInput(
        tenant_id=tenant_id,
        company_id=value.get("company_id"),
        policy_id=value.get("policy_id"),
        version=value.get("version"),
        purpose=value.get("purpose"),
        base_currency=value.get("base_currency"),
        quote_currency=value.get("quote_currency"),
        rate_kind=value.get("rate_kind"),
        source_provider_id=value.get("source_provider_id"),
        publication_selector=value.get("publication_selector"),
        effective_from=_parse_date("effective_from", value.get("effective_from")),
        effective_to=_optional_date("effective_to", value.get("effective_to")),
        allow_previous_business_day=value.get("allow_previous_business_day"),
        max_staleness_business_days=value.get("max_staleness_business_days"),
        rounding_mode=value.get("rounding_mode"),
        rate_decimal_scale=value.get("rate_decimal_scale"),
        approved_by=value.get("approved_by"),
        approval_proof_hash=value.get("approval_proof_hash"),
        policy_hash=value.get("policy_hash"),
    )


def _snapshot_input(tenant_id: str, value: object) -> FxRateSnapshotInput:
    if not isinstance(value, Mapping):
        raise _invalid("each snapshot must be an object")
    fields = {
        "company_id",
        "rate_snapshot_id",
        "rate_policy_id",
        "rate_policy_version",
        "source_provider_id",
        "base_currency",
        "quote_currency",
        "quote_unit",
        "published_rate",
        "desired_rate_date",
        "rate_date",
        "rate_as_of",
        "published_at",
        "publication_issue",
        "is_final",
        "source_record_id",
        "source_uri",
        "source_sha256",
        "calendar_ref",
        "source_timezone",
        "provenance",
    }
    _reject_unknown(value, fields)
    return FxRateSnapshotInput(
        tenant_id=tenant_id,
        company_id=value.get("company_id"),
        rate_snapshot_id=value.get("rate_snapshot_id"),
        rate_policy_id=value.get("rate_policy_id"),
        rate_policy_version=value.get("rate_policy_version"),
        source_provider_id=value.get("source_provider_id"),
        base_currency=value.get("base_currency"),
        quote_currency=value.get("quote_currency"),
        quote_unit=_decimal("quote_unit", value.get("quote_unit")),
        published_rate=_decimal("published_rate", value.get("published_rate")),
        desired_rate_date=_parse_date(
            "desired_rate_date", value.get("desired_rate_date")
        ),
        rate_date=_parse_date("rate_date", value.get("rate_date")),
        rate_as_of=_parse_datetime("rate_as_of", value.get("rate_as_of")),
        published_at=_parse_datetime("published_at", value.get("published_at")),
        publication_issue=value.get("publication_issue"),
        is_final=value.get("is_final"),
        source_record_id=value.get("source_record_id"),
        source_uri=value.get("source_uri"),
        source_sha256=value.get("source_sha256"),
        calendar_ref=value.get("calendar_ref"),
        source_timezone=value.get("source_timezone"),
        provenance=value.get("provenance"),
    )


def _policy_record(value: FxRatePolicyInput) -> dict[str, Any]:
    if not isinstance(value, FxRatePolicyInput):
        raise _invalid("value must be FxRatePolicyInput")
    effective_from = _date("effective_from", value.effective_from)
    effective_to = (
        None
        if value.effective_to is None
        else _date("effective_to", value.effective_to)
    )
    if effective_to is not None and effective_to <= effective_from:
        raise _invalid("effective_to must be after effective_from")
    allow_previous = _boolean(
        "allow_previous_business_day", value.allow_previous_business_day
    )
    staleness = _bounded_int(
        "max_staleness_business_days", value.max_staleness_business_days, 0, 366
    )
    if not allow_previous and staleness != 0:
        raise _invalid("staleness must be zero when previous-day fallback is disabled")
    base = _currency("base_currency", value.base_currency)
    quote = _currency("quote_currency", value.quote_currency)
    if base == quote:
        raise _invalid("base_currency and quote_currency must differ")
    semantics = {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "company_id": _uuid("company_id", value.company_id),
        "policy_id": _uuid("policy_id", value.policy_id),
        "version": _bounded_int("version", value.version, 1, 2**31 - 1),
        "purpose": _choice("purpose", value.purpose, FX_POLICY_PURPOSES),
        "base_currency": base,
        "quote_currency": quote,
        "rate_kind": _choice("rate_kind", value.rate_kind, FX_RATE_KINDS),
        "source_provider_id": _text(
            "source_provider_id", value.source_provider_id, maximum=128
        ),
        "publication_selector": _choice(
            "publication_selector",
            value.publication_selector,
            FX_PUBLICATION_SELECTORS,
        ),
        "effective_from": effective_from.isoformat(),
        "effective_to": effective_to.isoformat() if effective_to else None,
        "allow_previous_business_day": allow_previous,
        "max_staleness_business_days": staleness,
        "rounding_mode": _choice(
            "rounding_mode", value.rounding_mode, FX_ROUNDING_MODES
        ),
        "rate_decimal_scale": _bounded_int(
            "rate_decimal_scale", value.rate_decimal_scale, 0, 12
        ),
        "approved_by": _scoped_id("approved_by", value.approved_by),
        "approval_proof_hash": _hash_ref(
            "approval_proof_hash", value.approval_proof_hash
        ),
    }
    expected_hash = fx_policy_hash(semantics)
    if _hash_ref("policy_hash", value.policy_hash) != expected_hash:
        raise _invalid("policy_hash does not match canonical FX policy semantics")
    return {
        **semantics,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "policy_hash": expected_hash,
        "status": "APPROVED",
        "created_at": datetime.now(UTC),
    }


def _snapshot_values(value: FxRateSnapshotInput) -> dict[str, Any]:
    if not isinstance(value, FxRateSnapshotInput):
        raise _invalid("value must be FxRateSnapshotInput")
    quote_unit = _positive_decimal("quote_unit", value.quote_unit)
    published_rate = _positive_decimal("published_rate", value.published_rate)
    published_at = _aware_datetime("published_at", value.published_at)
    rate_as_of = _aware_datetime("rate_as_of", value.rate_as_of)
    timezone = _text("source_timezone", value.source_timezone, maximum=64)
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise _invalid("source_timezone must be an IANA timezone") from exc
    if not isinstance(value.provenance, Mapping):
        raise _invalid("provenance must be an object")
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "company_id": _uuid("company_id", value.company_id),
        "rate_snapshot_id": _uuid("rate_snapshot_id", value.rate_snapshot_id),
        "rate_policy_id": _uuid("rate_policy_id", value.rate_policy_id),
        "rate_policy_version": _bounded_int(
            "rate_policy_version", value.rate_policy_version, 1, 2**31 - 1
        ),
        "source_provider_id": _text(
            "source_provider_id", value.source_provider_id, maximum=128
        ),
        "base_currency": _currency("base_currency", value.base_currency),
        "quote_currency": _currency("quote_currency", value.quote_currency),
        "quote_unit": quote_unit,
        "published_rate": published_rate,
        "desired_rate_date": _date("desired_rate_date", value.desired_rate_date),
        "rate_date": _date("rate_date", value.rate_date),
        "rate_as_of": rate_as_of,
        "published_at": published_at,
        "publication_issue": _text(
            "publication_issue", value.publication_issue, maximum=64
        ),
        "is_final": _boolean("is_final", value.is_final),
        "source_record_id": _text(
            "source_record_id", value.source_record_id, maximum=256
        ),
        "source_uri": _uri(value.source_uri),
        "source_sha256": _hash_ref("source_sha256", value.source_sha256),
        "calendar_ref": _text("calendar_ref", value.calendar_ref, maximum=128),
        "source_timezone": timezone,
        "provenance_json": dict(value.provenance),
    }


def _market_rate_record(values: Mapping[str, Any]) -> dict[str, Any]:
    identity = {
        field: values[field]
        for field in (
            "source_provider_id",
            "source_record_id",
            "publication_issue",
            "base_currency",
            "quote_currency",
            "rate_date",
        )
    }
    semantics = {
        **identity,
        "quote_unit": values["quote_unit"],
        "published_rate": values["published_rate"],
        "rate_as_of": values["rate_as_of"],
        "published_at": values["published_at"],
        "is_final": values["is_final"],
        "source_uri": values["source_uri"],
        "source_sha256": values["source_sha256"],
        "source_timezone": values["source_timezone"],
        "provenance_json": values["provenance_json"],
    }
    wire_identity = {field: _json_value(item) for field, item in identity.items()}
    hash_values = {field: _json_value(item) for field, item in semantics.items()}
    return {
        "market_rate_id": str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                semantic_sha256_hash_ref(
                    {"domain": "EOS-FX-MARKET-RATE-IDENTITY-V1", **wire_identity}
                ),
            )
        ),
        **semantics,
        "market_rate_hash": semantic_sha256_hash_ref(
            {"domain": "EOS-FX-MARKET-RATE-V1", **hash_values}
        ),
        "market_admitted_at": datetime.now(UTC),
    }


def _snapshot_record(
    values: Mapping[str, Any],
    policy: Mapping[str, Any],
    market: Mapping[str, Any],
) -> dict[str, Any]:
    scale = policy["rate_decimal_scale"]
    quantum = Decimal(1).scaleb(-scale)
    normalized = (market["published_rate"] / market["quote_unit"]).quantize(
        quantum, rounding=ROUND_HALF_EVEN
    )
    semantics = {
        "tenant_id": values["tenant_id"],
        "company_id": values["company_id"],
        "rate_snapshot_id": values["rate_snapshot_id"],
        "market_rate_id": market["market_rate_id"],
        "rate_policy_id": values["rate_policy_id"],
        "rate_policy_version": values["rate_policy_version"],
        "normalized_rate": normalized,
        "desired_rate_date": values["desired_rate_date"],
        "effective_business_date": market["rate_date"],
        "calendar_ref": values["calendar_ref"],
        "approved_state": "APPROVED",
    }
    hash_values = {
        key: _json_value(item)
        for key, item in semantics.items()
        if key != "approved_state"
    }
    return {
        **semantics,
        "snapshot_hash": semantic_sha256_hash_ref(
            {"domain": "EOS-FX-RATE-SNAPSHOT-V2", **hash_values}
        ),
        "imported_at": datetime.now(UTC),
    }


def _policy_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        value[field]
        for field in (
            "tenant_id",
            "company_id",
            "policy_id",
            "version",
            "purpose",
            "base_currency",
            "quote_currency",
            "rate_kind",
            "source_provider_id",
            "publication_selector",
            "effective_from",
            "effective_to",
            "allow_previous_business_day",
            "max_staleness_business_days",
            "rounding_mode",
            "rate_decimal_scale",
            "approved_by",
            "approval_proof_hash",
            "policy_hash",
            "status",
        )
    )


def _snapshot_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _json_value(value[field])
        for field in (
            "tenant_id",
            "company_id",
            "rate_snapshot_id",
            "market_rate_id",
            "rate_policy_id",
            "rate_policy_version",
            "normalized_rate",
            "desired_rate_date",
            "effective_business_date",
            "calendar_ref",
            "approved_state",
        )
    )


def _snapshot_adoption_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _json_value(value[field])
        for field in (
            "tenant_id",
            "company_id",
            "market_rate_id",
            "rate_policy_id",
            "rate_policy_version",
            "normalized_rate",
            "desired_rate_date",
            "effective_business_date",
            "calendar_ref",
            "approved_state",
        )
    )


def _market_source_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _json_value(value[field])
        for field in (
            "source_provider_id",
            "source_record_id",
            "publication_issue",
            "base_currency",
            "quote_currency",
            "quote_unit",
            "published_rate",
            "rate_date",
            "rate_as_of",
            "published_at",
            "is_final",
            "source_uri",
            "source_sha256",
            "source_timezone",
        )
    )


def _snapshot_projection() -> tuple[Any, ...]:
    return (
        *tuple(EOS_FX_RATE_SNAPSHOT_TABLE.c),
        *tuple(
            column
            for column in EOS_FX_MARKET_RATE_TABLE.c
            if column.name != "market_rate_id"
        ),
    )


def _snapshot_wire(
    snapshot: Mapping[str, Any], market: Mapping[str, Any]
) -> dict[str, Any]:
    return _wire({**dict(market), **dict(snapshot)})


def _wire(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _json_value(item) for key, item in value.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _business_day_distance(selected: date, desired: date) -> int:
    if selected > desired:
        raise _invalid("selected FX date cannot follow desired date")
    if selected == desired:
        return 0
    cursor = selected + timedelta(days=1)
    business_days = 0
    while cursor <= desired:
        if cursor.weekday() < 5:
            business_days += 1
        cursor += timedelta(days=1)
    return max(1, business_days)


def _reject_unknown(value: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(str(field) for field in value if field not in allowed)
    if unknown:
        raise _invalid("payload contains unsupported fields: " + ", ".join(unknown))


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


def _currency(field: str, value: object) -> str:
    if not isinstance(value, str) or _CURRENCY.fullmatch(value) is None:
        raise _invalid(f"{field} must be a three-letter uppercase currency code")
    return value


def _choice(field: str, value: object, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _invalid(f"{field} must be one of: {', '.join(sorted(choices))}")
    return value


def _date(field: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(f"{field} must be a date")
    return value


def _parse_date(field: str, value: object) -> date:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be an ISO date") from exc


def _optional_date(field: str, value: object) -> date | None:
    return None if value is None else _parse_date(field, value)


def _parse_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an ISO datetime") from exc
    return _aware_datetime(field, parsed)


def _aware_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _decimal(field: str, value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise _invalid(f"{field} must be a decimal string or number")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid(f"{field} must be a decimal string or number") from exc


def _positive_decimal(field: str, value: object) -> Decimal:
    normalized = _decimal(field, value)
    if not normalized.is_finite() or normalized <= 0:
        raise _invalid(f"{field} must be finite and greater than zero")
    return normalized


def _bounded_int(field: str, value: object, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise _invalid(f"{field} must be between {minimum} and {maximum}")
    return value


def _boolean(field: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise _invalid(f"{field} must be a boolean")
    return value


def _text(field: str, value: object, *, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(f"{field} must contain 1..{maximum} characters")
    return normalized


def _uri(value: object) -> str:
    normalized = _text("source_uri", value, maximum=2048)
    if not normalized.startswith(("https://", "http://")):
        raise _invalid("source_uri must use http or https")
    return normalized


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a SHA-256 hash reference") from exc


def _invalid(detail: str) -> EosFxRateError:
    return EosFxRateError("EOS_FX_RATE_INVALID", detail, status_code=422)


def _not_found(detail: str) -> EosFxRateError:
    return EosFxRateError("EOS_FX_RATE_NOT_FOUND", detail, status_code=404)


def _conflict(detail: str) -> EosFxRateError:
    return EosFxRateError("EOS_FX_RATE_CONFLICT", detail, status_code=409)


def _rate_unavailable(detail: str) -> EosFxRateError:
    return EosFxRateError("FX_RATE_UNAVAILABLE", detail, status_code=409)


def _stale(detail: str) -> EosFxRateError:
    return EosFxRateError("FX_RATE_STALE_OR_UNTRUSTED", detail, status_code=409)


def _denied(scope: str) -> EosFxRateError:
    return EosFxRateError(
        "EOS_FX_RATE_AUTHORIZATION_DENIED",
        f"Fresh OA authority for {scope} is required",
        status_code=403,
    )


def _authority_unavailable() -> EosFxRateError:
    return EosFxRateError(
        "EOS_FX_RATE_AUTHORITY_UNAVAILABLE",
        "OA FX authority is unavailable or malformed",
        status_code=503,
        retryable=True,
    )


def _unavailable() -> EosFxRateError:
    return EosFxRateError(
        "EOS_FX_RATE_PERSISTENCE_UNAVAILABLE",
        "FX policy and RateSnapshot persistence is unavailable",
        status_code=503,
        retryable=True,
    )
