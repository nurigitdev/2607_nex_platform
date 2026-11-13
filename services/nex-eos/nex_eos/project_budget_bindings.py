from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
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

from .authorization import AuthorizationSource
from .budgets import (
    EOS_BUDGET_TABLE,
    EosBudgetError,
    load_final_approval_context,
    require_exact_business_approval,
    require_fresh_authorization,
)
from .business_transactions import (
    EOS_METADATA,
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .legal_entities import EOS_PROJECT_COMPANY_BINDING_TABLE
from .project_work_codes import EOS_PROJECT_WORK_CODE_SET_TABLE
from .projects import EOS_PROJECT_TABLE

PROJECT_BUDGET_BINDING_COMMIT_OPERATION = "PROJECT.BUDGET_BINDING.COMMIT"
PROJECT_BUDGET_BINDING_LIST_OPERATION = "PROJECT.BUDGET_BINDING.LIST"
PROJECT_BUDGET_BIND_SCOPE = "finance:budget:bind"
PROJECT_BUDGET_BINDING_SCHEMA = "eos_project_budget_binding_commit.v1"
PROJECT_BUDGET_BINDING_RESULT_SCHEMA = "eos_project_budget_binding_result.v1"
PROJECT_BUDGET_ALLOCATION_MODES = frozenset({"LIMIT_AMOUNT", "PERCENTAGE"})

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_MONEY = re.compile(r"^(?:0|[1-9][0-9]{0,15})\.[0-9]{4}$")
_RATIO = re.compile(r"^(?:0|1)(?:\.[0-9]{1,12})?$")


EOS_PROJECT_BUDGET_BINDING_TABLE = Table(
    "eos_project_budget_binding",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), primary_key=True),
    Column("binding_id", Uuid(as_uuid=False), primary_key=True),
    Column("binding_version", Integer, primary_key=True),
    Column("project_code", String(11), nullable=False),
    Column("budget_id", Uuid(as_uuid=False), nullable=False),
    Column("budget_version", Integer, nullable=False),
    Column("allocation_mode", String(24), nullable=False),
    Column("allocation_limit_amount", Numeric(20, 4), nullable=True),
    Column("allocation_percent", Numeric(18, 12), nullable=True),
    Column("approved_work_set_revision", Integer, nullable=False),
    Column("approved_by", String(128), nullable=False),
    Column("approved_proof", String(256), nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_until", Date, nullable=True),
    Column("binding_hash", String(71), nullable=False),
    Column("state", String(16), nullable=False),
    Column("business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id", "company_id", "binding_hash", name="ux_eos_project_budget_hash"
    ),
    UniqueConstraint(
        "tenant_id", "business_operation_id", name="ux_eos_project_budget_operation"
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_project_budget_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "budget_id", "budget_version"),
        (
            "eos_budget.tenant_id",
            "eos_budget.company_id",
            "eos_budget.budget_id",
            "eos_budget.budget_version",
        ),
        name="fk_eos_project_budget_budget",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id", "approved_work_set_revision"),
        (
            "eos_project_work_code_set.tenant_id",
            "eos_project_work_code_set.project_id",
            "eos_project_work_code_set.revision",
        ),
        name="fk_eos_project_budget_work_set",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_project_budget_operation",
    ),
    CheckConstraint("binding_version > 0", name="ck_eos_project_budget_version"),
    CheckConstraint("budget_version > 0", name="ck_eos_project_budget_budget_version"),
    CheckConstraint(
        "allocation_mode IN ('LIMIT_AMOUNT','PERCENTAGE')",
        name="ck_eos_project_budget_mode",
    ),
    CheckConstraint(
        "(allocation_mode = 'LIMIT_AMOUNT' AND allocation_limit_amount > 0 "
        "AND allocation_percent IS NULL) OR "
        "(allocation_mode = 'PERCENTAGE' AND allocation_limit_amount IS NULL "
        "AND allocation_percent > 0 AND allocation_percent <= 1)",
        name="ck_eos_project_budget_value",
    ),
    CheckConstraint(
        "valid_until IS NULL OR valid_until >= valid_from",
        name="ck_eos_project_budget_period",
    ),
    CheckConstraint("state = 'APPROVED'", name="ck_eos_project_budget_state"),
)


class EosProjectBudgetBindingError(RuntimeError):
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
class ProjectBudgetBindingCommand:
    tenant_id: str
    company_id: str
    business_operation_id: str
    idempotency_key: str
    payload_hash: str
    approval_proof_id: str
    binding_id: str
    binding_version: int
    project_id: str
    project_code: str
    budget_id: str
    budget_version: int
    allocation_mode: str
    allocation_limit_amount: Decimal | None
    allocation_percent: Decimal | None
    approved_work_set_revision: int
    valid_from: date
    valid_until: date | None

    def business_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROJECT_BUDGET_BINDING_SCHEMA,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "binding": {
                "binding_id": self.binding_id,
                "binding_version": self.binding_version,
                "project_id": self.project_id,
                "project_code": self.project_code,
                "budget_id": self.budget_id,
                "budget_version": self.budget_version,
                "allocation_mode": self.allocation_mode,
                "allocation_limit_amount": (
                    None
                    if self.allocation_limit_amount is None
                    else format(self.allocation_limit_amount, ".4f")
                ),
                "allocation_percent": (
                    None
                    if self.allocation_percent is None
                    else format(self.allocation_percent, ".12f")
                ),
                "approved_work_set_revision": self.approved_work_set_revision,
                "valid_from": self.valid_from.isoformat(),
                "valid_until": (
                    None if self.valid_until is None else self.valid_until.isoformat()
                ),
            },
        }


class SqlAlchemyEosProjectBudgetBindingRepository:
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
            raise _unavailable(
                "Project Budget approval persistence is unavailable"
            ) from exc

    def create_in_session(
        self,
        session: Session,
        command: ProjectBudgetBindingCommand,
        approval: Mapping[str, Any],
        *,
        created_at: datetime,
    ) -> dict[str, Any]:
        project = (
            session.execute(
                select(
                    EOS_PROJECT_TABLE.c.project_code, EOS_PROJECT_TABLE.c.status
                ).where(
                    EOS_PROJECT_TABLE.c.tenant_id == command.tenant_id,
                    EOS_PROJECT_TABLE.c.project_id == command.project_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if project is None or project["project_code"] != command.project_code:
            raise _not_found("Approved Project identity was not found")
        if project["status"] not in {"ACTIVE", "CLOSING"}:
            raise _conflict("Project must be ACTIVE or CLOSING")
        company_binding = session.scalar(
            select(EOS_PROJECT_COMPANY_BINDING_TABLE.c.binding_id).where(
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id == command.tenant_id,
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id == command.project_id,
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.company_id == command.company_id,
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.state == "APPROVED",
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_from <= command.valid_from,
                (
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until.is_(None)
                    | (
                        EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until
                        > command.valid_from
                    )
                ),
            )
        )
        if company_binding is None:
            raise _conflict("Project has no effective approved company binding")
        budget = (
            session.execute(
                select(EOS_BUDGET_TABLE).where(
                    EOS_BUDGET_TABLE.c.tenant_id == command.tenant_id,
                    EOS_BUDGET_TABLE.c.company_id == command.company_id,
                    EOS_BUDGET_TABLE.c.budget_id == command.budget_id,
                    EOS_BUDGET_TABLE.c.budget_version == command.budget_version,
                    EOS_BUDGET_TABLE.c.state == "APPROVED",
                )
            )
            .mappings()
            .one_or_none()
        )
        if budget is None:
            raise _not_found("Approved Budget revision was not found")
        work_set = session.scalar(
            select(EOS_PROJECT_WORK_CODE_SET_TABLE.c.work_set_id).where(
                EOS_PROJECT_WORK_CODE_SET_TABLE.c.tenant_id == command.tenant_id,
                EOS_PROJECT_WORK_CODE_SET_TABLE.c.project_id == command.project_id,
                EOS_PROJECT_WORK_CODE_SET_TABLE.c.revision
                == command.approved_work_set_revision,
                EOS_PROJECT_WORK_CODE_SET_TABLE.c.state == "APPROVED",
            )
        )
        if work_set is None:
            raise _conflict("Approved D12 WorkCodeSet revision was not found")
        existing = self.get_in_session(session, command)
        binding_hash = project_budget_binding_payload_hash(command)
        if existing is not None:
            if existing["binding_hash"] != binding_hash:
                raise _conflict(
                    "Project Budget binding revision has different semantics"
                )
            return existing
        latest = session.scalar(
            select(EOS_PROJECT_BUDGET_BINDING_TABLE.c.binding_version)
            .where(
                EOS_PROJECT_BUDGET_BINDING_TABLE.c.tenant_id == command.tenant_id,
                EOS_PROJECT_BUDGET_BINDING_TABLE.c.company_id == command.company_id,
                EOS_PROJECT_BUDGET_BINDING_TABLE.c.project_id == command.project_id,
                EOS_PROJECT_BUDGET_BINDING_TABLE.c.binding_id == command.binding_id,
            )
            .order_by(EOS_PROJECT_BUDGET_BINDING_TABLE.c.binding_version.desc())
            .limit(1)
        )
        expected = 1 if latest is None else int(latest) + 1
        if command.binding_version != expected:
            raise _conflict(
                f"Project Budget binding version must be the next revision {expected}"
            )
        self._require_budget_capacity(session, command, budget)
        record = {
            **{
                key: getattr(command, key)
                for key in (
                    "tenant_id",
                    "company_id",
                    "project_id",
                    "binding_id",
                    "binding_version",
                    "project_code",
                    "budget_id",
                    "budget_version",
                    "allocation_mode",
                    "allocation_limit_amount",
                    "allocation_percent",
                    "approved_work_set_revision",
                    "valid_from",
                    "valid_until",
                    "business_operation_id",
                )
            },
            "approved_by": approval["decided_by_id"],
            "approved_proof": approval["approval_proof_ref"],
            "binding_hash": binding_hash,
            "state": "APPROVED",
            "created_at": created_at,
        }
        session.execute(EOS_PROJECT_BUDGET_BINDING_TABLE.insert().values(**record))
        return record

    def _require_budget_capacity(
        self,
        session: Session,
        command: ProjectBudgetBindingCommand,
        budget: Mapping[str, Any],
    ) -> None:
        table = EOS_PROJECT_BUDGET_BINDING_TABLE
        rows = session.execute(
            select(
                table.c.allocation_mode,
                table.c.allocation_limit_amount,
                table.c.allocation_percent,
            ).where(
                table.c.tenant_id == command.tenant_id,
                table.c.company_id == command.company_id,
                table.c.budget_id == command.budget_id,
                table.c.budget_version == command.budget_version,
                table.c.state == "APPROVED",
            )
        ).mappings()
        existing = list(rows)
        if any(row["allocation_mode"] != command.allocation_mode for row in existing):
            raise _conflict("One Budget revision cannot mix allocation modes")
        if command.allocation_mode == "LIMIT_AMOUNT":
            total = sum(
                (Decimal(row["allocation_limit_amount"]) for row in existing),
                command.allocation_limit_amount or Decimal(0),
            )
            if total > Decimal(budget["approved_functional_amount"]):
                raise _conflict(
                    "Project allocation limits exceed approved Budget amount"
                )
        else:
            total = sum(
                (Decimal(row["allocation_percent"]) for row in existing),
                command.allocation_percent or Decimal(0),
            )
            if total > Decimal(1):
                raise _conflict("Project allocation percentages exceed one")

    def get_in_session(
        self, session: Session, command: ProjectBudgetBindingCommand
    ) -> dict[str, Any] | None:
        row = (
            session.execute(
                select(EOS_PROJECT_BUDGET_BINDING_TABLE).where(
                    EOS_PROJECT_BUDGET_BINDING_TABLE.c.tenant_id == command.tenant_id,
                    EOS_PROJECT_BUDGET_BINDING_TABLE.c.company_id == command.company_id,
                    EOS_PROJECT_BUDGET_BINDING_TABLE.c.project_id == command.project_id,
                    EOS_PROJECT_BUDGET_BINDING_TABLE.c.binding_id == command.binding_id,
                    EOS_PROJECT_BUDGET_BINDING_TABLE.c.binding_version
                    == command.binding_version,
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def list_for_project(
        self, *, tenant_id: str, company_id: str, project_id: str
    ) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    select(EOS_PROJECT_BUDGET_BINDING_TABLE)
                    .where(
                        EOS_PROJECT_BUDGET_BINDING_TABLE.c.tenant_id == tenant_id,
                        EOS_PROJECT_BUDGET_BINDING_TABLE.c.company_id == company_id,
                        EOS_PROJECT_BUDGET_BINDING_TABLE.c.project_id == project_id,
                    )
                    .order_by(
                        EOS_PROJECT_BUDGET_BINDING_TABLE.c.binding_id,
                        EOS_PROJECT_BUDGET_BINDING_TABLE.c.binding_version,
                    )
                ).mappings()
                return [dict(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable(
                "Project Budget binding persistence is unavailable"
            ) from exc


class EosProjectBudgetBindingService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyEosProjectBudgetBindingRepository,
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
        command = parse_project_budget_binding_commit(
            tenant_id=tenant_id, company_id=company_id, payload=payload
        )
        if project_budget_binding_payload_hash(command) != command.payload_hash:
            raise _invalid("payload_hash", "does not match canonical binding semantics")
        approval = self._repository.load_approval_context(
            tenant_id=command.tenant_id,
            approval_proof_id=command.approval_proof_id,
        )
        if approval is None:
            raise _not_found("Final BUSINESS_FORMAL approval proof was not found")
        try:
            require_exact_business_approval(
                approval,
                operation=PROJECT_BUDGET_BINDING_COMMIT_OPERATION,
                payload_hash=command.payload_hash,
                protected_operation_ref=(
                    f"eos.project-budget-binding:{command.binding_id}:"
                    f"version:{command.binding_version}"
                ),
            )
            authorization_revision = require_fresh_authorization(
                self._authorization_source,
                tenant_id=command.tenant_id,
                subject_id=str(approval["decided_by_id"]),
                required_scope=PROJECT_BUDGET_BIND_SCOPE,
            )
        except EosBudgetError as exc:
            raise _from_budget_error(exc) from exc

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise EosBusinessOperationError(
                    "EOS_PROJECT_BUDGET_TRANSACTION_REQUIRED",
                    "Project Budget binding requires an EOS transaction",
                    status_code=500,
                )
            try:
                record = self._repository.create_in_session(
                    session,
                    command,
                    approval,
                    created_at=_aware_time(self._clock()),
                )
            except EosProjectBudgetBindingError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
            return {
                "business_result_ref": (
                    f"eos.project-budget-binding:{record['binding_id']}:"
                    f"version:{record['binding_version']}"
                ),
                "company_id": str(record["company_id"]),
                "binding_id": str(record["binding_id"]),
                "binding_version": int(record["binding_version"]),
                "binding_hash": str(record["binding_hash"]),
                "project_id": str(record["project_id"]),
                "project_code": str(record["project_code"]),
                "budget_id": str(record["budget_id"]),
                "budget_version": int(record["budget_version"]),
                "authorization_revision_hash": authorization_revision,
            }

        try:
            transaction = self._coordinator.execute(
                EosBusinessOperationRequest(
                    tenant_id=command.tenant_id,
                    business_operation_id=command.business_operation_id,
                    idempotency_key=command.idempotency_key,
                    operation=PROJECT_BUDGET_BINDING_COMMIT_OPERATION,
                    payload_hash=command.payload_hash,
                ),
                mutation,
            )
        except EosBusinessOperationError as exc:
            raise EosProjectBudgetBindingError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return {
            "schema_version": PROJECT_BUDGET_BINDING_RESULT_SCHEMA,
            "tenant_id": transaction.tenant_id,
            "business_operation_id": transaction.business_operation_id,
            "payload_hash": transaction.payload_hash,
            "commit_state": transaction.commit_state,
            "idempotency_disposition": "CREATED" if transaction.created else "REPLAYED",
            **transaction.result,
        }

    def list_for_project(
        self, *, tenant_id: str, company_id: str, project_id: str
    ) -> dict[str, Any]:
        identity = {
            "tenant_id": _pattern_text("tenant_id", tenant_id, _SCOPED_ID),
            "company_id": _uuid("company_id", company_id),
            "project_id": _uuid("project_id", project_id),
        }
        rows = self._repository.list_for_project(**identity)
        return {
            "schema_version": "eos_project_budget_binding_list.v1",
            "operation": PROJECT_BUDGET_BINDING_LIST_OPERATION,
            **identity,
            "bindings": [_projection(row) for row in rows],
        }


def parse_project_budget_binding_commit(
    *, tenant_id: str, company_id: str, payload: Mapping[str, Any]
) -> ProjectBudgetBindingCommand:
    expected = {
        "schema_version",
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "approval_proof_id",
        "binding",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise _invalid("payload", "must contain only canonical binding commit fields")
    if payload.get("schema_version") != PROJECT_BUDGET_BINDING_SCHEMA:
        raise _invalid("schema_version", "is not supported")
    binding = payload.get("binding")
    fields = {
        "binding_id",
        "binding_version",
        "project_id",
        "project_code",
        "budget_id",
        "budget_version",
        "allocation_mode",
        "allocation_limit_amount",
        "allocation_percent",
        "approved_work_set_revision",
        "valid_from",
        "valid_until",
    }
    if not isinstance(binding, Mapping) or set(binding) != fields:
        raise _invalid("binding", "must contain only canonical binding fields")
    mode = _choice(
        "allocation_mode",
        binding.get("allocation_mode"),
        PROJECT_BUDGET_ALLOCATION_MODES,
    )
    amount = _optional_decimal(
        "allocation_limit_amount", binding.get("allocation_limit_amount"), _MONEY
    )
    percent = _optional_decimal(
        "allocation_percent", binding.get("allocation_percent"), _RATIO
    )
    if (mode == "LIMIT_AMOUNT" and (amount is None or percent is not None)) or (
        mode == "PERCENTAGE" and (percent is None or amount is not None)
    ):
        raise _invalid("allocation_mode", "must select exactly one matching value")
    valid_from = _date_value("valid_from", binding.get("valid_from"))
    valid_until = _optional_date("valid_until", binding.get("valid_until"))
    if valid_until is not None and valid_until < valid_from:
        raise _invalid("valid_until", "cannot precede valid_from")
    return ProjectBudgetBindingCommand(
        tenant_id=_pattern_text("tenant_id", tenant_id, _SCOPED_ID),
        company_id=_uuid("company_id", company_id),
        business_operation_id=_uuid(
            "business_operation_id", payload.get("business_operation_id")
        ),
        idempotency_key=_text("idempotency_key", payload.get("idempotency_key"), 256),
        payload_hash=_pattern_text(
            "payload_hash", payload.get("payload_hash"), _HASH_REF
        ),
        approval_proof_id=_uuid("approval_proof_id", payload.get("approval_proof_id")),
        binding_id=_uuid("binding_id", binding.get("binding_id")),
        binding_version=_positive_int(
            "binding_version", binding.get("binding_version")
        ),
        project_id=_uuid("project_id", binding.get("project_id")),
        project_code=_pattern_text(
            "project_code", binding.get("project_code"), _PROJECT_CODE
        ),
        budget_id=_uuid("budget_id", binding.get("budget_id")),
        budget_version=_positive_int("budget_version", binding.get("budget_version")),
        allocation_mode=mode,
        allocation_limit_amount=amount,
        allocation_percent=percent,
        approved_work_set_revision=_positive_int(
            "approved_work_set_revision", binding.get("approved_work_set_revision")
        ),
        valid_from=valid_from,
        valid_until=valid_until,
    )


def project_budget_binding_payload_hash(command: ProjectBudgetBindingCommand) -> str:
    return semantic_sha256_hash_ref(
        {"domain": "EOS-PROJECT-BUDGET-BINDING-V1", **command.business_payload()}
    )


def _projection(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": str(record["binding_id"]),
        "binding_version": int(record["binding_version"]),
        "project_code": str(record["project_code"]),
        "budget_id": str(record["budget_id"]),
        "budget_version": int(record["budget_version"]),
        "allocation_mode": str(record["allocation_mode"]),
        "allocation_limit_amount": (
            None
            if record["allocation_limit_amount"] is None
            else format(Decimal(record["allocation_limit_amount"]), ".4f")
        ),
        "allocation_percent": (
            None
            if record["allocation_percent"] is None
            else format(Decimal(record["allocation_percent"]), ".12f")
        ),
        "approved_work_set_revision": int(record["approved_work_set_revision"]),
        "valid_from": record["valid_from"].isoformat(),
        "valid_until": None
        if record["valid_until"] is None
        else record["valid_until"].isoformat(),
        "binding_hash": str(record["binding_hash"]),
        "state": str(record["state"]),
    }


def _optional_decimal(
    field_name: str, value: object, pattern: re.Pattern[str]
) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _invalid(field_name, "has an invalid decimal format")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise _invalid(field_name, "must be decimal") from exc
    if result <= 0:
        raise _invalid(field_name, "must be greater than zero")
    return result


def _date_value(field_name: str, value: object) -> date:
    if not isinstance(value, str):
        raise _invalid(field_name, "must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid(field_name, "must be an ISO date") from exc


def _optional_date(field_name: str, value: object) -> date | None:
    return None if value is None else _date_value(field_name, value)


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


def _choice(field_name: str, value: object, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _invalid(field_name, f"must be one of {sorted(choices)}")
    return value


def _aware_time(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("clock", "must return a timezone-aware datetime")
    return value


def _invalid(field_name: str, detail: str) -> EosProjectBudgetBindingError:
    return EosProjectBudgetBindingError(
        "EOS_PROJECT_BUDGET_BINDING_INVALID", f"{field_name} {detail}", status_code=422
    )


def _not_found(detail: str) -> EosProjectBudgetBindingError:
    return EosProjectBudgetBindingError(
        "EOS_PROJECT_BUDGET_BINDING_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosProjectBudgetBindingError:
    return EosProjectBudgetBindingError(
        "EOS_PROJECT_BUDGET_BINDING_CONFLICT", detail, status_code=409
    )


def _unavailable(detail: str) -> EosProjectBudgetBindingError:
    return EosProjectBudgetBindingError(
        "EOS_PROJECT_BUDGET_BINDING_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )


def _from_budget_error(exc: EosBudgetError) -> EosProjectBudgetBindingError:
    return EosProjectBudgetBindingError(
        exc.error_code.replace("EOS_BUDGET", "EOS_PROJECT_BUDGET_BINDING"),
        exc.detail,
        status_code=exc.status_code,
        retryable=exc.retryable,
    )
