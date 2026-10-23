from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime import build_unit_of_work
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
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .accounts import EOS_ACCOUNT_TABLE
from .approval_contracts import (
    EOS_APPROVAL_DOMAINS,
    EOS_APPROVAL_LADDER,
    EOS_APPROVAL_RISK_LEVELS,
)
from .business_transactions import EOS_METADATA
from .organization import EOS_POSITION_TYPES
from .projects import EOS_PROJECT_TABLE

EOS_APPROVAL_POLICY_STATUSES = frozenset({"ACTIVE", "INACTIVE"})
EOS_APPROVAL_SEPARATION_POLICIES = frozenset({"REQUESTER_EXCLUDED"})
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TRANSACTION_TYPE = re.compile(r"^[A-Z][A-Z0-9_.]{0,127}$")
_MONEY_QUANTUM = Decimal("0.01")
_MAX_MONEY = Decimal("999999999999999999.99")

EOS_APPROVAL_POLICY_TABLE = Table(
    "eos_approval_policy",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("approval_policy_id", Uuid(as_uuid=False), primary_key=True),
    Column("policy_key", String(128), nullable=False),
    Column("version", Integer, nullable=False),
    Column("name", String(256), nullable=False),
    Column("approval_domain", String(32), nullable=False),
    Column("risk_level", String(16), nullable=True),
    Column("minimum_amount", Numeric(20, 2), nullable=True),
    Column("maximum_amount", Numeric(20, 2), nullable=True),
    Column("project_id", Uuid(as_uuid=False), nullable=True),
    Column("account_id", Uuid(as_uuid=False), nullable=True),
    Column("transaction_type", String(128), nullable=True),
    Column("status", String(16), nullable=False),
    Column("effective_from", DateTime(timezone=True), nullable=False),
    Column("effective_until", DateTime(timezone=True), nullable=True),
    Column("policy_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "policy_key",
        "version",
        name="ux_eos_approval_policy_version",
    ),
    UniqueConstraint("tenant_id", "policy_hash", name="ux_eos_approval_policy_hash"),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_approval_policy_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_approval_policy_account",
    ),
    CheckConstraint(
        "minimum_amount IS NULL OR minimum_amount >= 0",
        name="ck_eos_approval_policy_minimum",
    ),
    CheckConstraint(
        "maximum_amount IS NULL OR maximum_amount >= 0",
        name="ck_eos_approval_policy_maximum",
    ),
    CheckConstraint(
        "minimum_amount IS NULL OR maximum_amount IS NULL "
        "OR maximum_amount > minimum_amount",
        name="ck_eos_approval_policy_amount_range",
    ),
)
Index(
    "ix_eos_approval_policy_select",
    EOS_APPROVAL_POLICY_TABLE.c.tenant_id,
    EOS_APPROVAL_POLICY_TABLE.c.approval_domain,
    EOS_APPROVAL_POLICY_TABLE.c.status,
    EOS_APPROVAL_POLICY_TABLE.c.effective_from,
    EOS_APPROVAL_POLICY_TABLE.c.effective_until,
)

EOS_APPROVAL_POLICY_STAGE_TABLE = Table(
    "eos_approval_policy_stage",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("approval_policy_id", Uuid(as_uuid=False), primary_key=True),
    Column("stage_order", Integer, primary_key=True),
    Column("position_type", String(32), nullable=False),
    Column("quorum_count", Integer, nullable=False),
    Column("separation_policy", String(32), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "approval_policy_id"),
        (
            "eos_approval_policy.tenant_id",
            "eos_approval_policy.approval_policy_id",
        ),
        name="fk_eos_approval_policy_stage_policy",
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "tenant_id",
        "approval_policy_id",
        "position_type",
        name="ux_eos_approval_policy_stage_position",
    ),
    CheckConstraint(
        "stage_order BETWEEN 1 AND 5",
        name="ck_eos_approval_policy_stage_order",
    ),
    CheckConstraint("quorum_count > 0", name="ck_eos_approval_policy_stage_quorum"),
)


class EosApprovalPolicyError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class ApprovalPolicyStageInput:
    position_type: str
    quorum_count: int = 1
    separation_policy: str = "REQUESTER_EXCLUDED"


@dataclass(frozen=True)
class ApprovalPolicyInput:
    tenant_id: str
    approval_policy_id: str
    policy_key: str
    name: str
    approval_domain: str
    effective_from: datetime
    stages: Sequence[ApprovalPolicyStageInput]
    version: int = 1
    risk_level: str | None = None
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None
    project_id: str | None = None
    account_id: str | None = None
    transaction_type: str | None = None
    status: str = "ACTIVE"
    effective_until: datetime | None = None


@dataclass(frozen=True)
class ApprovalPolicySelection:
    tenant_id: str
    approval_domain: str
    risk_level: str
    amount: Decimal
    transaction_type: str
    effective_at: datetime
    project_id: str | None = None
    account_ids: Sequence[str] = ()


class SqlAlchemyEosApprovalPolicyRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_policy(self, value: ApprovalPolicyInput) -> dict[str, Any]:
        policy, stages = _policy_records(value)
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                self._require_reference(
                    transaction.db,
                    EOS_PROJECT_TABLE,
                    id_column="project_id",
                    tenant_id=policy["tenant_id"],
                    reference_id=policy["project_id"],
                )
                self._require_reference(
                    transaction.db,
                    EOS_ACCOUNT_TABLE,
                    id_column="account_id",
                    tenant_id=policy["tenant_id"],
                    reference_id=policy["account_id"],
                )
                transaction.db.execute(
                    EOS_APPROVAL_POLICY_TABLE.insert().values(**policy)
                )
                transaction.db.execute(EOS_APPROVAL_POLICY_STAGE_TABLE.insert(), stages)
        except EosApprovalPolicyError:
            raise
        except IntegrityError as exc:
            raise EosApprovalPolicyError(
                "EOS_APPROVAL_POLICY_CONFLICT",
                "Approval policy identity, version, or semantic hash conflicts",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return _projection(policy, stages)

    def get_policy(
        self, *, tenant_id: str, approval_policy_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        approval_policy_id = _uuid("approval_policy_id", approval_policy_id)
        try:
            with self._session_factory() as session:
                policy = (
                    session.execute(
                        select(EOS_APPROVAL_POLICY_TABLE).where(
                            EOS_APPROVAL_POLICY_TABLE.c.tenant_id == tenant_id,
                            EOS_APPROVAL_POLICY_TABLE.c.approval_policy_id
                            == approval_policy_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if policy is None:
                    return None
                stages = self._load_stages(
                    session,
                    tenant_id=tenant_id,
                    approval_policy_id=approval_policy_id,
                )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return _projection(dict(policy), stages)

    def resolve_policy(
        self, selection: ApprovalPolicySelection
    ) -> dict[str, Any] | None:
        request = _selection_record(selection)
        table = EOS_APPROVAL_POLICY_TABLE
        conditions = [
            table.c.tenant_id == request["tenant_id"],
            table.c.approval_domain == request["approval_domain"],
            table.c.status == "ACTIVE",
            table.c.effective_from <= request["effective_at"],
            or_(
                table.c.effective_until.is_(None),
                table.c.effective_until > request["effective_at"],
            ),
            or_(
                table.c.risk_level.is_(None),
                table.c.risk_level == request["risk_level"],
            ),
            or_(
                table.c.minimum_amount.is_(None),
                table.c.minimum_amount <= request["amount"],
            ),
            or_(
                table.c.maximum_amount.is_(None),
                table.c.maximum_amount > request["amount"],
            ),
            or_(
                table.c.transaction_type.is_(None),
                table.c.transaction_type == request["transaction_type"],
            ),
        ]
        if request["project_id"] is None:
            conditions.append(table.c.project_id.is_(None))
        else:
            conditions.append(
                or_(
                    table.c.project_id.is_(None),
                    table.c.project_id == request["project_id"],
                )
            )
        if request["account_ids"]:
            conditions.append(
                or_(
                    table.c.account_id.is_(None),
                    table.c.account_id.in_(request["account_ids"]),
                )
            )
        else:
            conditions.append(table.c.account_id.is_(None))

        try:
            with self._session_factory() as session:
                candidates = [
                    dict(row)
                    for row in session.execute(
                        select(table).where(*conditions)
                    ).mappings()
                ]
                if not candidates:
                    return None
                best = _select_one(candidates)
                stages = self._load_stages(
                    session,
                    tenant_id=best["tenant_id"],
                    approval_policy_id=best["approval_policy_id"],
                )
        except EosApprovalPolicyError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return _projection(best, stages)

    @staticmethod
    def _load_stages(
        session: Session, *, tenant_id: str, approval_policy_id: str
    ) -> list[dict[str, Any]]:
        rows = session.execute(
            select(EOS_APPROVAL_POLICY_STAGE_TABLE)
            .where(
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == tenant_id,
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id
                == approval_policy_id,
            )
            .order_by(EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order)
        ).mappings()
        return [dict(row) for row in rows]

    @staticmethod
    def _require_reference(
        session: Session,
        table: Table,
        *,
        id_column: str,
        tenant_id: str,
        reference_id: str | None,
    ) -> None:
        if reference_id is None:
            return
        found = session.execute(
            select(table.c[id_column]).where(
                table.c.tenant_id == tenant_id,
                table.c[id_column] == reference_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise EosApprovalPolicyError(
                "EOS_APPROVAL_POLICY_REFERENCE_NOT_FOUND",
                "Policy selector reference was not found in tenant scope",
                status_code=422,
            )


def _policy_records(
    value: ApprovalPolicyInput,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tenant_id = _scoped_id("tenant_id", value.tenant_id)
    approval_policy_id = _uuid("approval_policy_id", value.approval_policy_id)
    start, end = _period(value.effective_from, value.effective_until)
    minimum = _optional_money("minimum_amount", value.minimum_amount)
    maximum = _optional_money("maximum_amount", value.maximum_amount)
    if minimum is not None and maximum is not None and maximum <= minimum:
        raise _invalid("maximum_amount", "must be greater than minimum_amount")
    stage_values = _stages(value.stages)
    semantic = {
        "schema_version": "eos_approval_policy.v1",
        "tenant_id": tenant_id,
        "approval_policy_id": approval_policy_id,
        "policy_key": _scoped_id("policy_key", value.policy_key),
        "version": _positive_int("version", value.version),
        "name": _text("name", value.name, 256),
        "approval_domain": _choice(
            "approval_domain", value.approval_domain, EOS_APPROVAL_DOMAINS
        ),
        "risk_level": _optional_choice(
            "risk_level", value.risk_level, EOS_APPROVAL_RISK_LEVELS
        ),
        "minimum_amount": _money_text(minimum),
        "maximum_amount": _money_text(maximum),
        "project_id": _optional_uuid("project_id", value.project_id),
        "account_id": _optional_uuid("account_id", value.account_id),
        "transaction_type": _optional_transaction_type(value.transaction_type),
        "status": _choice("status", value.status, EOS_APPROVAL_POLICY_STATUSES),
        "effective_from": _timestamp(start),
        "effective_until": _timestamp(end) if end is not None else None,
        "stages": stage_values,
    }
    policy_hash = semantic_sha256_hash_ref(semantic)
    now = datetime.now(UTC)
    policy = {
        **{
            key: semantic[key]
            for key in semantic
            if key not in {"schema_version", "stages"}
        },
        "minimum_amount": minimum,
        "maximum_amount": maximum,
        "effective_from": start,
        "effective_until": end,
        "policy_hash": policy_hash,
        "created_at": now,
        "updated_at": now,
    }
    stages = [
        {
            "tenant_id": tenant_id,
            "approval_policy_id": approval_policy_id,
            "stage_order": index,
            **stage,
        }
        for index, stage in enumerate(stage_values, start=1)
    ]
    return policy, stages


def _selection_record(value: ApprovalPolicySelection) -> dict[str, Any]:
    account_ids = value.account_ids
    if isinstance(account_ids, (str, bytes)) or not isinstance(account_ids, Sequence):
        raise _invalid("account_ids", "must be a sequence")
    normalized_accounts = tuple(
        sorted({_uuid("account_ids", item) for item in account_ids})
    )
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "approval_domain": _choice(
            "approval_domain", value.approval_domain, EOS_APPROVAL_DOMAINS
        ),
        "risk_level": _choice("risk_level", value.risk_level, EOS_APPROVAL_RISK_LEVELS),
        "amount": _money("amount", value.amount),
        "transaction_type": _transaction_type(value.transaction_type),
        "effective_at": _aware_datetime("effective_at", value.effective_at),
        "project_id": _optional_uuid("project_id", value.project_id),
        "account_ids": normalized_accounts,
    }


def _stages(values: Sequence[ApprovalPolicyStageInput]) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid("stages", "must be a sequence")
    if not 1 <= len(values) <= len(EOS_APPROVAL_LADDER):
        raise _invalid("stages", "must contain 1..5 ordered stages")
    result: list[dict[str, Any]] = []
    ladder_positions: list[int] = []
    for value in values:
        if not isinstance(value, ApprovalPolicyStageInput):
            raise _invalid("stages", "must contain ApprovalPolicyStageInput values")
        position_type = _choice(
            "position_type", value.position_type, EOS_POSITION_TYPES
        )
        quorum_count = _positive_int("quorum_count", value.quorum_count)
        if quorum_count != 1:
            raise _invalid("quorum_count", "must be 1 in the P8.7 initial profile")
        separation_policy = _choice(
            "separation_policy",
            value.separation_policy,
            EOS_APPROVAL_SEPARATION_POLICIES,
        )
        ladder_positions.append(EOS_APPROVAL_LADDER.index(position_type))
        result.append(
            {
                "position_type": position_type,
                "quorum_count": quorum_count,
                "separation_policy": separation_policy,
            }
        )
    if ladder_positions != sorted(set(ladder_positions)):
        raise _invalid("stages", "must be a unique ordered leadership subset")
    return result


def _select_one(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [(policy, _specificity(policy)) for policy in candidates]
    highest = max(score for _, score in scored)
    winners = [policy for policy, score in scored if score == highest]
    if len(winners) != 1:
        raise EosApprovalPolicyError(
            "EOS_APPROVAL_POLICY_AMBIGUOUS",
            "Multiple equally specific approval policies match",
            status_code=409,
        )
    return winners[0]


def _specificity(policy: Mapping[str, Any]) -> int:
    return sum(
        policy[field] is not None
        for field in (
            "risk_level",
            "minimum_amount",
            "maximum_amount",
            "project_id",
            "account_id",
            "transaction_type",
        )
    )


def _projection(
    policy: Mapping[str, Any], stages: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": "eos_approval_policy.v1",
        "tenant_id": policy["tenant_id"],
        "approval_policy_id": str(policy["approval_policy_id"]),
        "policy_key": policy["policy_key"],
        "version": policy["version"],
        "name": policy["name"],
        "approval_domain": policy["approval_domain"],
        "selector": {
            "risk_level": policy["risk_level"],
            "minimum_amount": _money_text(policy["minimum_amount"]),
            "maximum_amount": _money_text(policy["maximum_amount"]),
            "project_id": (
                str(policy["project_id"]) if policy["project_id"] is not None else None
            ),
            "account_id": (
                str(policy["account_id"]) if policy["account_id"] is not None else None
            ),
            "transaction_type": policy["transaction_type"],
        },
        "status": policy["status"],
        "effective_from": _timestamp(policy["effective_from"]),
        "effective_until": (
            _timestamp(policy["effective_until"])
            if policy["effective_until"] is not None
            else None
        ),
        "stages": [
            {
                "stage_order": stage["stage_order"],
                "position_type": stage["position_type"],
                "quorum_count": stage["quorum_count"],
                "separation_policy": stage["separation_policy"],
            }
            for stage in stages
        ],
        "policy_hash": policy["policy_hash"],
    }


def _period(start: datetime, end: datetime | None) -> tuple[datetime, datetime | None]:
    normalized_start = _aware_datetime("effective_from", start)
    normalized_end = _aware_datetime("effective_until", end) if end else None
    if normalized_end is not None and normalized_end <= normalized_start:
        raise _invalid("effective_until", "must be later than effective_from")
    return normalized_start, normalized_end


def _money(field_name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise _invalid(field_name, "must be a finite non-negative Decimal")
    try:
        normalized = value.quantize(_MONEY_QUANTUM)
    except InvalidOperation as exc:
        raise _invalid(field_name, "is outside Decimal(20,2)") from exc
    if normalized != value or normalized > _MAX_MONEY:
        raise _invalid(field_name, "must fit Decimal(20,2) exactly")
    return normalized


def _optional_money(field_name: str, value: object) -> Decimal | None:
    return None if value is None else _money(field_name, value)


def _money_text(value: object) -> str | None:
    return None if value is None else f"{Decimal(value):.2f}"


def _transaction_type(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if not _TRANSACTION_TYPE.fullmatch(normalized):
        raise _invalid("transaction_type", "has invalid type syntax")
    return normalized


def _optional_transaction_type(value: object) -> str | None:
    return None if value is None else _transaction_type(value)


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _optional_uuid(field_name: str, value: object) -> str | None:
    return None if value is None else _uuid(field_name, value)


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _SCOPED_ID.fullmatch(normalized):
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field_name, f"must contain 1..{maximum} characters")
    return normalized


def _choice(field_name: str, value: object, choices: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in choices:
        raise _invalid(field_name, f"must be one of {sorted(choices)}")
    return normalized


def _optional_choice(
    field_name: str, value: object, choices: frozenset[str]
) -> str | None:
    return None if value is None else _choice(field_name, value, choices)


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field_name, "must be a positive integer")
    return value


def _aware_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(field_name, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(field_name: str, detail: str) -> EosApprovalPolicyError:
    return EosApprovalPolicyError(
        "EOS_APPROVAL_POLICY_INVALID",
        f"{field_name} {detail}",
        status_code=422,
    )


def _persistence_error() -> EosApprovalPolicyError:
    return EosApprovalPolicyError(
        "EOS_APPROVAL_POLICY_PERSISTENCE_FAILED",
        "Approval policy persistence is unavailable",
        status_code=503,
    )
