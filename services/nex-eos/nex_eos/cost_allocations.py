from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
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
    Uuid,
    select,
    update,
)
from sqlalchemy.orm import Session, sessionmaker

from .accounting_periods import EOS_ACCOUNTING_PERIOD_TABLE
from .allocation_plans import (
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
)
from .business_transactions import (
    EOS_METADATA,
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .cost_source_pools import EOS_COST_SOURCE_POOL_TABLE

COST_ALLOCATION_RUN_OPERATION = "FINANCE.COST_ALLOCATION.RUN"
COST_ALLOCATION_VERIFY_OPERATION = "FINANCE.COST_ALLOCATION.VERIFY"
COST_ALLOCATION_EVENT_TYPE = "FINANCE.COST_ALLOCATION_COMMITTED.v1"
COST_ALLOCATION_RUN_SCHEMA = "eos_cost_allocation_run.v1"
COST_ALLOCATION_BATCH_SCHEMA = "eos_cost_allocation_batch.v1"
COST_ALLOCATION_CURRENCY_SCALE = 4

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


EOS_COST_ALLOCATION_BATCH_TABLE = Table(
    "eos_cost_allocation_batch",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("batch_id", Uuid(as_uuid=False), primary_key=True),
    Column("plan_id", Uuid(as_uuid=False), nullable=False),
    Column("plan_revision", Integer, nullable=False),
    Column("period_id", Uuid(as_uuid=False), nullable=False),
    Column("source_set_hash", String(71), nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("state", String(32), nullable=False),
    Column("allocated_total", Numeric(20, 4), nullable=False),
    Column("unallocated_total", Numeric(20, 4), nullable=False),
    Column("reconciliation_hash", String(71), nullable=True),
    Column("business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("outbox_event_id", Uuid(as_uuid=False), nullable=True),
    Column("committed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "plan_id", "plan_revision"),
        (
            "eos_cost_allocation_plan.tenant_id",
            "eos_cost_allocation_plan.company_id",
            "eos_cost_allocation_plan.plan_id",
            "eos_cost_allocation_plan.plan_revision",
        ),
        name="fk_eos_cost_batch_plan",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "period_id"),
        (
            "eos_accounting_period.tenant_id",
            "eos_accounting_period.company_id",
            "eos_accounting_period.period_id",
        ),
        name="fk_eos_cost_batch_period",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_cost_batch_operation",
    ),
    CheckConstraint(
        "state IN ('DRAFT','COMMITTED','RECONCILIATION_FAILED','REVERSED')",
        name="ck_eos_cost_batch_state",
    ),
)

EOS_COST_ALLOCATION_LINE_TABLE = Table(
    "eos_cost_allocation_line",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("batch_id", Uuid(as_uuid=False), primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("pool_id", Uuid(as_uuid=False), nullable=False),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("project_code", String(11), nullable=False),
    Column("work_code", String(32), nullable=True),
    Column("basis_source_ref", String(256), nullable=False),
    Column("basis_source_hash", String(71), nullable=False),
    Column("basis_units", Numeric(24, 8), nullable=False),
    Column("allocation_ratio", Numeric(18, 12), nullable=False),
    Column("allocated_amount_functional", Numeric(20, 4), nullable=False),
    Column("rounding_delta", Numeric(20, 4), nullable=False),
    Column("allocation_mode", String(32), nullable=False),
    Column("original_source_line_ref", String(256), nullable=False),
    Column("evidence_hash", String(71), nullable=False),
    Column("status", String(16), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "batch_id"),
        (
            "eos_cost_allocation_batch.tenant_id",
            "eos_cost_allocation_batch.company_id",
            "eos_cost_allocation_batch.batch_id",
        ),
        name="fk_eos_cost_line_batch",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "pool_id"),
        (
            "eos_cost_source_pool.tenant_id",
            "eos_cost_source_pool.company_id",
            "eos_cost_source_pool.pool_id",
        ),
        name="fk_eos_cost_line_pool",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_cost_line_project",
    ),
    CheckConstraint("line_no > 0", name="ck_eos_cost_line_no"),
    CheckConstraint(
        "allocation_ratio >= 0 AND allocation_ratio <= 1",
        name="ck_eos_cost_line_ratio",
    ),
    CheckConstraint(
        "allocation_mode IN ('MANAGEMENT_ALLOCATION','GL_COST_TRANSFER')",
        name="ck_eos_cost_line_mode",
    ),
    CheckConstraint(
        "status IN ('ALLOCATED','REVERSED')", name="ck_eos_cost_line_status"
    ),
)


class EosCostAllocationError(RuntimeError):
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
class AllocationSourceInput:
    pool_id: str
    unallocated_amount: Decimal


@dataclass(frozen=True)
class CostAllocationRunCommand:
    tenant_id: str
    company_id: str
    business_operation_id: str
    idempotency_key: str
    payload_hash: str
    batch_id: str
    plan_id: str
    plan_revision: int
    period_id: str
    functional_currency: str
    sources: tuple[AllocationSourceInput, ...]

    def business_payload(self) -> dict[str, Any]:
        return {
            "schema_version": COST_ALLOCATION_RUN_SCHEMA,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "batch_id": self.batch_id,
            "plan_id": self.plan_id,
            "plan_revision": self.plan_revision,
            "period_id": self.period_id,
            "functional_currency": self.functional_currency,
            "currency_scale": COST_ALLOCATION_CURRENCY_SCALE,
            "sources": [
                {
                    "pool_id": item.pool_id,
                    "unallocated_amount_functional": _amount_text(
                        item.unallocated_amount
                    ),
                }
                for item in self.sources
            ],
        }


class EosCostAllocationService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        coordinator: EosBusinessTransactionCoordinator,
        clock=None,
    ) -> None:
        self._session_factory = session_factory
        self._coordinator = coordinator
        self._clock = clock or (lambda: datetime.now(UTC))

    def run(
        self,
        *,
        tenant_id: str,
        company_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        command = parse_cost_allocation_run(
            tenant_id=tenant_id, company_id=company_id, payload=payload
        )
        if cost_allocation_payload_hash(command) != command.payload_hash:
            raise _invalid("Canonical Cost Allocation payload hash does not match")
        request = EosBusinessOperationRequest(
            tenant_id=command.tenant_id,
            business_operation_id=command.business_operation_id,
            idempotency_key=command.idempotency_key,
            operation=COST_ALLOCATION_RUN_OPERATION,
            payload_hash=command.payload_hash,
            event_type=COST_ALLOCATION_EVENT_TYPE,
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise EosBusinessOperationError(
                    "EOS_COST_ALLOCATION_TRANSACTION_REQUIRED",
                    "Cost Allocation requires an active EOS database transaction",
                    status_code=500,
                )
            try:
                return self._commit_in_session(session, command)
            except EosCostAllocationError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc

        try:
            transaction = self._coordinator.execute(request, mutation)
        except EosBusinessOperationError as exc:
            raise EosCostAllocationError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return _transaction_projection(transaction)

    def _commit_in_session(
        self, session: Session, command: CostAllocationRunCommand
    ) -> dict[str, Any]:
        if (
            _load_batch(
                session,
                tenant_id=command.tenant_id,
                company_id=command.company_id,
                batch_id=command.batch_id,
            )
            is not None
        ):
            raise _conflict("Allocation Batch identity already has different semantics")
        period = _lock_period(session, command)
        plan, plan_lines = _lock_plan(session, command)
        pools = _lock_pools(session, command)
        source_set_hash = build_source_set_hash(pools)
        staged_lines: list[dict[str, Any]] = []
        conservation: list[dict[str, Any]] = []
        allocated_total = Decimal(0)
        unallocated_total = Decimal(0)
        next_line_no = 1
        source_inputs = {item.pool_id: item for item in command.sources}
        for pool in pools:
            requested = source_inputs[str(pool["pool_id"])]
            _require_pool_is_eligible(
                pool,
                command=command,
                plan=plan,
                period=period,
                unallocated=requested.unallocated_amount,
            )
            eligible = _amount(pool["eligible_amount_functional"])
            distributable = eligible - requested.unallocated_amount
            allocations = deterministic_allocate(
                amount=distributable,
                plan_lines=plan_lines,
                basis_priority=_basis_priority(str(plan["basis_kind"])),
            )
            pool_total = sum(
                (item["allocated_amount_functional"] for item in allocations),
                Decimal(0),
            )
            if pool_total + requested.unallocated_amount != eligible:
                raise _conservation_failed()
            for item in allocations:
                record = _allocation_line_record(
                    command=command,
                    plan=plan,
                    pool=pool,
                    allocation=item,
                    line_no=next_line_no,
                )
                staged_lines.append(record)
                next_line_no += 1
            conservation.append(
                {
                    "pool_id": str(pool["pool_id"]),
                    "source_hash": str(pool["source_hash"]),
                    "eligible_amount_functional": _amount_text(eligible),
                    "direct_amount_functional": _amount_text(Decimal(0)),
                    "allocated_amount_functional": _amount_text(pool_total),
                    "unallocated_amount_functional": _amount_text(
                        requested.unallocated_amount
                    ),
                }
            )
            allocated_total += pool_total
            unallocated_total += requested.unallocated_amount
        committed_at = _aware_time("clock", self._clock())
        reconciliation_hash = build_reconciliation_hash(
            command=command,
            plan_hash=str(plan["plan_hash"]),
            source_set_hash=source_set_hash,
            conservation=conservation,
            lines=staged_lines,
            allocated_total=allocated_total,
            unallocated_total=unallocated_total,
        )
        batch = {
            "tenant_id": command.tenant_id,
            "company_id": command.company_id,
            "batch_id": command.batch_id,
            "plan_id": command.plan_id,
            "plan_revision": command.plan_revision,
            "period_id": command.period_id,
            "source_set_hash": source_set_hash,
            "functional_currency": command.functional_currency,
            "state": "COMMITTED",
            "allocated_total": allocated_total,
            "unallocated_total": unallocated_total,
            "reconciliation_hash": reconciliation_hash,
            "business_operation_id": command.business_operation_id,
            "idempotency_key": command.idempotency_key,
            "outbox_event_id": None,
            "committed_at": committed_at,
            "created_at": committed_at,
        }
        session.execute(EOS_COST_ALLOCATION_BATCH_TABLE.insert().values(**batch))
        if staged_lines:
            session.execute(EOS_COST_ALLOCATION_LINE_TABLE.insert(), staged_lines)
        for pool in pools:
            changed = session.execute(
                update(EOS_COST_SOURCE_POOL_TABLE)
                .where(
                    EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == command.tenant_id,
                    EOS_COST_SOURCE_POOL_TABLE.c.company_id == command.company_id,
                    EOS_COST_SOURCE_POOL_TABLE.c.pool_id == pool["pool_id"],
                    EOS_COST_SOURCE_POOL_TABLE.c.pool_state == "OPEN",
                )
                .values(pool_state="ALLOCATED")
            ).rowcount
            if changed != 1:
                raise _conflict("Allocation SourcePool state changed concurrently")
        return {
            "business_result_ref": f"eos.cost-allocation-batch:{command.batch_id}",
            "company_id": command.company_id,
            "batch_id": command.batch_id,
            "plan_id": command.plan_id,
            "plan_revision": command.plan_revision,
            "period_id": command.period_id,
            "source_set_hash": source_set_hash,
            "functional_currency": command.functional_currency,
            "allocated_total": _amount_text(allocated_total),
            "unallocated_total": _amount_text(unallocated_total),
            "reconciliation_hash": reconciliation_hash,
            "line_count": len(staged_lines),
            "pool_count": len(pools),
            "committed_at": _wire_time(committed_at),
        }


def parse_cost_allocation_run(
    *, tenant_id: str, company_id: str, payload: Mapping[str, Any]
) -> CostAllocationRunCommand:
    expected = {
        "schema_version",
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "batch_id",
        "plan_id",
        "plan_revision",
        "period_id",
        "functional_currency",
        "currency_scale",
        "sources",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise _invalid("Cost Allocation command fields are not canonical")
    if payload.get("schema_version") != COST_ALLOCATION_RUN_SCHEMA:
        raise _invalid("Cost Allocation command schema is not supported")
    if payload.get("currency_scale") != COST_ALLOCATION_CURRENCY_SCALE:
        raise _invalid("Cost Allocation currency scale must match EOS precision")
    source_value = payload.get("sources")
    if (
        isinstance(source_value, (str, bytes))
        or not isinstance(source_value, Sequence)
        or not source_value
    ):
        raise _invalid("Cost Allocation sources must be a non-empty array")
    sources: list[AllocationSourceInput] = []
    for value in source_value:
        if not isinstance(value, Mapping) or set(value) != {
            "pool_id",
            "unallocated_amount_functional",
        }:
            raise _invalid("Cost Allocation source fields are not canonical")
        sources.append(
            AllocationSourceInput(
                pool_id=_uuid("pool_id", value.get("pool_id")),
                unallocated_amount=_amount(value.get("unallocated_amount_functional")),
            )
        )
    if [item.pool_id for item in sources] != sorted({item.pool_id for item in sources}):
        raise _invalid("Cost Allocation sources must be unique and sorted by pool_id")
    return CostAllocationRunCommand(
        tenant_id=_scoped_id("tenant_id", tenant_id),
        company_id=_uuid("company_id", company_id),
        business_operation_id=_uuid(
            "business_operation_id", payload.get("business_operation_id")
        ),
        idempotency_key=_text(
            "idempotency_key", payload.get("idempotency_key"), maximum=128
        ),
        payload_hash=_hash("payload_hash", payload.get("payload_hash")),
        batch_id=_uuid("batch_id", payload.get("batch_id")),
        plan_id=_uuid("plan_id", payload.get("plan_id")),
        plan_revision=_positive_int("plan_revision", payload.get("plan_revision")),
        period_id=_uuid("period_id", payload.get("period_id")),
        functional_currency=_currency(payload.get("functional_currency")),
        sources=tuple(sources),
    )


def cost_allocation_payload_hash(command: CostAllocationRunCommand) -> str:
    return semantic_sha256_hash_ref(
        {"domain": "EOS-COST-ALLOCATION-RUN-V1", **command.business_payload()}
    )


def deterministic_allocate(
    *, amount: Decimal, plan_lines: Sequence[Mapping[str, Any]], basis_priority: int
) -> list[dict[str, Any]]:
    amount = _amount(amount)
    if not plan_lines:
        raise _invalid("Allocation plan must contain target lines")
    unit = Decimal("0.0001")
    ordered = sorted(
        plan_lines,
        key=lambda item: (
            basis_priority,
            str(item["project_id"]),
            str(item.get("work_code") or ""),
        ),
    )
    allocations: list[dict[str, Any]] = []
    for line in ordered:
        ratio = _ratio(line["allocation_ratio"])
        exact = amount * ratio
        base = exact.quantize(unit, rounding=ROUND_DOWN)
        allocations.append(
            {
                "plan_line": line,
                "allocated_amount_functional": base,
                "rounding_delta": Decimal(0),
            }
        )
    remainder = amount - sum(
        (item["allocated_amount_functional"] for item in allocations), Decimal(0)
    )
    units = int((abs(remainder) / unit).to_integral_exact())
    if units > len(allocations):
        raise _conservation_failed()
    adjustment = unit if remainder > 0 else -unit
    for index in range(units):
        allocations[index]["allocated_amount_functional"] += adjustment
        allocations[index]["rounding_delta"] = adjustment
    if (
        sum((item["allocated_amount_functional"] for item in allocations), Decimal(0))
        != amount
    ):
        raise _conservation_failed()
    return allocations


def build_source_set_hash(pools: Sequence[Mapping[str, Any]]) -> str:
    return semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-SOURCE-SET-V1",
            "sources": [
                {
                    "pool_id": str(pool["pool_id"]),
                    "source_hash": str(pool["source_hash"]),
                    "eligible_amount_functional": _amount_text(
                        pool["eligible_amount_functional"]
                    ),
                    "period_id": str(pool["period_id"]),
                    "functional_currency": str(pool["functional_currency"]),
                }
                for pool in sorted(pools, key=lambda item: str(item["pool_id"]))
            ],
        }
    )


def build_reconciliation_hash(
    *,
    command: CostAllocationRunCommand,
    plan_hash: str,
    source_set_hash: str,
    conservation: Sequence[Mapping[str, Any]],
    lines: Sequence[Mapping[str, Any]],
    allocated_total: Decimal,
    unallocated_total: Decimal,
) -> str:
    return semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-RECONCILIATION-V1",
            "tenant_id": command.tenant_id,
            "company_id": command.company_id,
            "batch_id": command.batch_id,
            "plan_id": command.plan_id,
            "plan_revision": command.plan_revision,
            "plan_hash": plan_hash,
            "period_id": command.period_id,
            "source_set_hash": source_set_hash,
            "functional_currency": command.functional_currency,
            "allocated_total": _amount_text(allocated_total),
            "unallocated_total": _amount_text(unallocated_total),
            "conservation": [dict(item) for item in conservation],
            "line_evidence_hashes": [str(item["evidence_hash"]) for item in lines],
        }
    )


def _lock_period(
    session: Session, command: CostAllocationRunCommand
) -> Mapping[str, Any]:
    row = (
        session.execute(
            select(EOS_ACCOUNTING_PERIOD_TABLE)
            .where(
                EOS_ACCOUNTING_PERIOD_TABLE.c.tenant_id == command.tenant_id,
                EOS_ACCOUNTING_PERIOD_TABLE.c.company_id == command.company_id,
                EOS_ACCOUNTING_PERIOD_TABLE.c.period_id == command.period_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _not_found("AccountingPeriod was not found in company scope")
    if row["state"] not in {"OPEN", "CLOSING"}:
        raise _conflict("Cost Allocation requires an OPEN or CLOSING period")
    return row


def _lock_plan(
    session: Session, command: CostAllocationRunCommand
) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    plan = (
        session.execute(
            select(EOS_COST_ALLOCATION_PLAN_TABLE)
            .where(
                EOS_COST_ALLOCATION_PLAN_TABLE.c.tenant_id == command.tenant_id,
                EOS_COST_ALLOCATION_PLAN_TABLE.c.company_id == command.company_id,
                EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_id == command.plan_id,
                EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_revision == command.plan_revision,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if plan is None:
        raise _not_found("Approved AllocationPlan revision was not found")
    if plan["state"] != "APPROVED":
        raise _conflict("AllocationPlan revision is not APPROVED")
    lines = list(
        session.execute(
            select(EOS_COST_ALLOCATION_PLAN_LINE_TABLE)
            .where(
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.tenant_id == command.tenant_id,
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.company_id == command.company_id,
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.plan_id == command.plan_id,
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.plan_revision
                == command.plan_revision,
            )
            .order_by(EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.line_no)
        ).mappings()
    )
    if not lines:
        raise _conflict("AllocationPlan revision has no target lines")
    return plan, lines


def _lock_pools(
    session: Session, command: CostAllocationRunCommand
) -> list[Mapping[str, Any]]:
    pool_ids = [item.pool_id for item in command.sources]
    rows = list(
        session.execute(
            select(EOS_COST_SOURCE_POOL_TABLE)
            .where(
                EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == command.tenant_id,
                EOS_COST_SOURCE_POOL_TABLE.c.company_id == command.company_id,
                EOS_COST_SOURCE_POOL_TABLE.c.pool_id.in_(pool_ids),
            )
            .order_by(EOS_COST_SOURCE_POOL_TABLE.c.pool_id)
            .with_for_update()
        ).mappings()
    )
    if [str(row["pool_id"]) for row in rows] != pool_ids:
        raise _not_found("One or more SourcePools were not found in company scope")
    return rows


def _require_pool_is_eligible(
    pool: Mapping[str, Any],
    *,
    command: CostAllocationRunCommand,
    plan: Mapping[str, Any],
    period: Mapping[str, Any],
    unallocated: Decimal,
) -> None:
    if pool["pool_state"] != "OPEN":
        raise _conflict("SourcePool is not OPEN for allocation")
    if pool["allocation_mode"] != "MANAGEMENT_ALLOCATION":
        raise EosCostAllocationError(
            "EOS_COST_ALLOCATION_MODE_CONFLICT",
            "Only MANAGEMENT_ALLOCATION SourcePools may enter this batch",
            status_code=409,
        )
    if (
        str(pool["period_id"]) != command.period_id
        or str(pool["functional_currency"]) != command.functional_currency
        or str(pool["source_kind"]) != str(plan["source_kind"])
    ):
        raise _conflict("SourcePool period, currency, or source kind differs from plan")
    recognition_date = pool["recognition_date"]
    if not isinstance(recognition_date, date):
        raise _conflict("SourcePool recognition date is malformed")
    if not (period["start_date"] <= recognition_date <= period["end_date"]):
        raise _conflict("SourcePool recognition date is outside the batch period")
    if recognition_date < plan["effective_start"] or (
        plan["effective_end"] is not None and recognition_date > plan["effective_end"]
    ):
        raise _conflict("AllocationPlan is not effective for the SourcePool")
    eligible = _amount(pool["eligible_amount_functional"])
    if eligible > 0 and not (Decimal(0) <= unallocated <= eligible):
        raise _conservation_failed()
    if eligible < 0 and not (eligible <= unallocated <= Decimal(0)):
        raise _conservation_failed()


def _allocation_line_record(
    *,
    command: CostAllocationRunCommand,
    plan: Mapping[str, Any],
    pool: Mapping[str, Any],
    allocation: Mapping[str, Any],
    line_no: int,
) -> dict[str, Any]:
    plan_line = allocation["plan_line"]
    amount = _amount(allocation["allocated_amount_functional"])
    rounding_delta = _amount(allocation["rounding_delta"])
    evidence_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-LINE-V1",
            "batch_id": command.batch_id,
            "pool_id": str(pool["pool_id"]),
            "source_hash": str(pool["source_hash"]),
            "plan_hash": str(plan["plan_hash"]),
            "plan_line_hash": str(plan_line["line_hash"]),
            "allocated_amount_functional": _amount_text(amount),
            "rounding_delta": _amount_text(rounding_delta),
        }
    )
    return {
        "tenant_id": command.tenant_id,
        "company_id": command.company_id,
        "batch_id": command.batch_id,
        "line_no": line_no,
        "pool_id": str(pool["pool_id"]),
        "project_id": str(plan_line["project_id"]),
        "project_code": str(plan_line["project_code"]),
        "work_code": plan_line["work_code"],
        "basis_source_ref": str(plan["basis_source_ref"]),
        "basis_source_hash": str(plan["basis_source_hash"]),
        "basis_units": Decimal(str(plan_line["basis_units"])),
        "allocation_ratio": Decimal(str(plan_line["allocation_ratio"])),
        "allocated_amount_functional": amount,
        "rounding_delta": rounding_delta,
        "allocation_mode": "MANAGEMENT_ALLOCATION",
        "original_source_line_ref": (
            f"eos.journal:{pool['journal_id']}:line:{pool['journal_line_no']}"
        ),
        "evidence_hash": evidence_hash,
        "status": "ALLOCATED",
    }


def _load_batch(
    session: Session, *, tenant_id: str, company_id: str, batch_id: str
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_COST_ALLOCATION_BATCH_TABLE).where(
                EOS_COST_ALLOCATION_BATCH_TABLE.c.tenant_id == tenant_id,
                EOS_COST_ALLOCATION_BATCH_TABLE.c.company_id == company_id,
                EOS_COST_ALLOCATION_BATCH_TABLE.c.batch_id == batch_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _transaction_projection(transaction) -> dict[str, Any]:
    return {
        "schema_version": COST_ALLOCATION_BATCH_SCHEMA,
        "operation": COST_ALLOCATION_RUN_OPERATION,
        "idempotency_disposition": (
            "CREATED" if transaction.created else "EXACT_REPLAY"
        ),
        "tenant_id": transaction.tenant_id,
        "business_operation_id": transaction.business_operation_id,
        "idempotency_key": transaction.idempotency_key,
        "payload_hash": transaction.payload_hash,
        "commit_state": transaction.commit_state,
        **transaction.result,
        "outbox": {
            "outbox_id": transaction.outbox_id,
            "event_id": transaction.event_id,
            "event_type": transaction.event_type,
            "event_payload_hash": transaction.event_payload_hash,
            "delivery_state": "PENDING",
        },
    }


def _basis_priority(value: str) -> int:
    return {
        "ACTUAL_WORK": 1,
        "USAGE": 1,
        "APPROVED_PLAN": 2,
        "HEADCOUNT_CASCADE": 3,
        "JUSTIFIED_PERCENTAGE": 4,
    }[value]


def _amount(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid("Cost Allocation amount must be a decimal") from exc
    if not amount.is_finite() or amount.as_tuple().exponent < -4:
        raise _invalid("Cost Allocation amount must have at most four decimals")
    return amount.quantize(Decimal("0.0001"))


def _ratio(value: object) -> Decimal:
    try:
        ratio = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid("Allocation ratio must be a decimal") from exc
    if not ratio.is_finite() or ratio < 0 or ratio > 1:
        raise _invalid("Allocation ratio must be between zero and one")
    return ratio


def _amount_text(value: object) -> str:
    return format(_amount(value), "f")


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field_name} must be a positive integer")
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _hash(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _HASH_REF.fullmatch(value) is None:
        raise _invalid(f"{field_name} must be a sha256 hash reference")
    return value


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid(f"{field_name} has an invalid format")
    return value


def _text(field_name: str, value: object, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value.strip() != value
        or not value.isprintable()
    ):
        raise _invalid(f"{field_name} has an invalid format")
    return value


def _currency(value: object) -> str:
    if not isinstance(value, str) or _CURRENCY.fullmatch(value) is None:
        raise _invalid("functional_currency must be an uppercase ISO code")
    return value


def _aware_time(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EosCostAllocationError(
            "EOS_COST_ALLOCATION_CLOCK_INVALID",
            f"{field_name} must be timezone-aware",
            status_code=500,
        )
    return value.astimezone(UTC)


def _wire_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> EosCostAllocationError:
    return EosCostAllocationError(
        "EOS_COST_ALLOCATION_INVALID", detail, status_code=422
    )


def _not_found(detail: str) -> EosCostAllocationError:
    return EosCostAllocationError(
        "EOS_COST_ALLOCATION_REFERENCE_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosCostAllocationError:
    return EosCostAllocationError(
        "EOS_COST_ALLOCATION_CONFLICT", detail, status_code=409
    )


def _conservation_failed() -> EosCostAllocationError:
    return EosCostAllocationError(
        "EOS_COST_ALLOCATION_CONSERVATION_FAILED",
        "Eligible amount does not equal direct, allocated, and unallocated amounts",
        status_code=422,
    )
