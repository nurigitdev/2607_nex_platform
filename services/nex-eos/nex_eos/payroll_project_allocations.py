from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
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
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

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
from .cost_allocations import (
    EOS_COST_ALLOCATION_BATCH_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
    EosCostAllocationError,
    EosCostAllocationService,
    cost_allocation_payload_hash,
    deterministic_allocate,
    parse_cost_allocation_run,
)
from .cost_source_pools import EOS_COST_SOURCE_POOL_TABLE
from .payroll_labor_bridge import (
    EOS_LABOR_EFFORT_LINE_TABLE,
    EOS_LABOR_EFFORT_SNAPSHOT_TABLE,
    EOS_PAYROLL_POST_EVIDENCE_TABLE,
)
from .projects import EOS_PROJECT_TABLE

PAYROLL_PROJECT_ALLOCATION_SCHEMA = "eos_payroll_project_allocation.v1"
PAYROLL_PROJECT_ADJUSTMENT_SCHEMA = "eos_payroll_project_adjustment.v1"
PAYROLL_PROJECT_ADJUST_OPERATION = "FINANCE.PAYROLL_PROJECT_ALLOCATION.ADJUST"
PAYROLL_PROJECT_ADJUST_EVENT = "FINANCE.PAYROLL_PROJECT_ALLOCATION_ADJUSTED.v1"

PAYROLL_RESIDUAL_TREATMENTS = frozenset(
    {"RETAIN_UNALLOCATED", "ALLOCATE_INDIRECT_OVERHEAD", "OPERATING_PROJECT"}
)
PAYROLL_ALLOCATION_STATUSES = frozenset({"PROVISIONAL", "CONFIRMED"})

_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_MONEY = Decimal("0.0001")
_EFFORT = Decimal("0.0001")
_RATIO = Decimal("0.000000000001")
_ALLOCATION_NAMESPACE = uuid.UUID("74f87cc1-b634-5729-89ef-5109d7bba783")
_BATCH_NAMESPACE = uuid.UUID("612c41bc-cba9-5455-bbbd-2dfa40d1d9cb")
_OPERATION_NAMESPACE = uuid.UUID("f1c79a0a-b7e9-5fb1-8c31-d09d203968ee")
_ADJUSTMENT_NAMESPACE = uuid.UUID("6682582f-9cc0-5bbe-b1aa-5670b2711b31")


EOS_PAYROLL_PROJECT_ALLOCATION_TABLE = Table(
    "eos_payroll_project_alloc",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("allocation_id", Uuid(as_uuid=False), primary_key=True),
    Column("allocation_revision", Integer, nullable=False),
    Column("payroll_evidence_id", Uuid(as_uuid=False), nullable=False),
    Column("effort_snapshot_id", Uuid(as_uuid=False), nullable=False),
    Column("plan_id", Uuid(as_uuid=False), nullable=False),
    Column("plan_revision", Integer, nullable=False),
    Column("batch_id", Uuid(as_uuid=False), nullable=False),
    Column("basis_kind", String(32), nullable=False),
    Column("allocation_status", String(16), nullable=False),
    Column("residual_treatment", String(32), nullable=False),
    Column("project_effort_units", Numeric(20, 4), nullable=False),
    Column("residual_effort_units", Numeric(20, 4), nullable=False),
    Column("allocated_total", Numeric(20, 4), nullable=False),
    Column("residual_total", Numeric(20, 4), nullable=False),
    Column("policy_hash", String(71), nullable=False),
    Column("allocation_hash", String(71), nullable=False),
    Column("supersedes_allocation_id", Uuid(as_uuid=False), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "batch_id",
        "allocation_revision",
        name="ux_eos_payroll_alloc_revision",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "allocation_hash",
        name="ux_eos_payroll_alloc_hash",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "payroll_evidence_id"),
        (
            "eos_payroll_post_evidence.tenant_id",
            "eos_payroll_post_evidence.company_id",
            "eos_payroll_post_evidence.evidence_id",
        ),
        name="fk_eos_payroll_alloc_evidence",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "effort_snapshot_id"),
        (
            "eos_labor_effort_snapshot.tenant_id",
            "eos_labor_effort_snapshot.company_id",
            "eos_labor_effort_snapshot.snapshot_id",
        ),
        name="fk_eos_payroll_alloc_snapshot",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "plan_id", "plan_revision"),
        (
            "eos_cost_allocation_plan.tenant_id",
            "eos_cost_allocation_plan.company_id",
            "eos_cost_allocation_plan.plan_id",
            "eos_cost_allocation_plan.plan_revision",
        ),
        name="fk_eos_payroll_alloc_plan",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "batch_id"),
        (
            "eos_cost_allocation_batch.tenant_id",
            "eos_cost_allocation_batch.company_id",
            "eos_cost_allocation_batch.batch_id",
        ),
        name="fk_eos_payroll_alloc_batch",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "supersedes_allocation_id"),
        (
            "eos_payroll_project_alloc.tenant_id",
            "eos_payroll_project_alloc.company_id",
            "eos_payroll_project_alloc.allocation_id",
        ),
        name="fk_eos_payroll_alloc_prior",
    ),
    CheckConstraint("allocation_revision > 0", name="ck_eos_payroll_alloc_revision"),
    CheckConstraint(
        "basis_kind IN ('ACTUAL_APPROVED','APPROVED_PLAN_FALLBACK')",
        name="ck_eos_payroll_alloc_basis",
    ),
    CheckConstraint(
        "allocation_status IN ('PROVISIONAL','CONFIRMED')",
        name="ck_eos_payroll_alloc_status",
    ),
    CheckConstraint(
        "residual_treatment IN ('RETAIN_UNALLOCATED',"
        "'ALLOCATE_INDIRECT_OVERHEAD','OPERATING_PROJECT')",
        name="ck_eos_payroll_alloc_residual",
    ),
    CheckConstraint(
        "project_effort_units > 0 AND residual_effort_units >= 0",
        name="ck_eos_payroll_alloc_effort",
    ),
)
Index(
    "ix_eos_payroll_alloc_evidence",
    EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.tenant_id,
    EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.company_id,
    EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.payroll_evidence_id,
    EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.allocation_revision,
)


# This table already exists from migration 2541. W60 adds optional payroll
# lineage without changing generic allocation-adjustment semantics.
EOS_COST_ALLOCATION_ADJUSTMENT_TABLE = Table(
    "eos_cost_allocation_adjustment",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("adjustment_id", Uuid(as_uuid=False), primary_key=True),
    Column("original_batch_id", Uuid(as_uuid=False), nullable=True),
    Column("original_batch_line_no", Integer, nullable=True),
    Column("original_journal_id", Uuid(as_uuid=False), nullable=False),
    Column("new_journal_id", Uuid(as_uuid=False), nullable=True),
    Column("delta_amount", Numeric(20, 4), nullable=False),
    Column("reason", String(512), nullable=False),
    Column("effective_period_id", Uuid(as_uuid=False), nullable=False),
    Column("approved_proof", String(256), nullable=False),
    Column("operation_id", Uuid(as_uuid=False), nullable=False),
    Column("adjustment_hash", String(71), nullable=False),
    Column("payroll_allocation_id", Uuid(as_uuid=False), nullable=True),
    Column("payroll_evidence_id", Uuid(as_uuid=False), nullable=True),
    Column("prior_snapshot_id", Uuid(as_uuid=False), nullable=True),
    Column("replacement_snapshot_id", Uuid(as_uuid=False), nullable=True),
    Column("target_project_id", Uuid(as_uuid=False), nullable=True),
    Column("target_project_code", String(11), nullable=True),
    Column("work_code", String(32), nullable=True),
    Column("adjustment_kind", String(32), nullable=True),
    Column("basis_source_ref", String(256), nullable=True),
    Column("basis_source_hash", String(71), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "adjustment_hash",
        name="ux_eos_cost_adjustment_hash",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "original_batch_id", "original_batch_line_no"),
        (
            "eos_cost_allocation_line.tenant_id",
            "eos_cost_allocation_line.company_id",
            "eos_cost_allocation_line.batch_id",
            "eos_cost_allocation_line.line_no",
        ),
        name="fk_eos_cost_adjustment_line",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "original_journal_id"),
        (
            "eos_journal_header.tenant_id",
            "eos_journal_header.company_id",
            "eos_journal_header.journal_id",
        ),
        name="fk_eos_cost_adjustment_journal",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "new_journal_id"),
        (
            "eos_journal_header.tenant_id",
            "eos_journal_header.company_id",
            "eos_journal_header.journal_id",
        ),
        name="fk_eos_cost_adjustment_new_journal",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "effective_period_id"),
        (
            "eos_accounting_period.tenant_id",
            "eos_accounting_period.company_id",
            "eos_accounting_period.period_id",
        ),
        name="fk_eos_cost_adjustment_period",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_cost_adjustment_operation",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "target_project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_cost_adjustment_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "payroll_allocation_id"),
        (
            "eos_payroll_project_alloc.tenant_id",
            "eos_payroll_project_alloc.company_id",
            "eos_payroll_project_alloc.allocation_id",
        ),
        name="fk_eos_cost_adjustment_payroll",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "payroll_evidence_id"),
        (
            "eos_payroll_post_evidence.tenant_id",
            "eos_payroll_post_evidence.company_id",
            "eos_payroll_post_evidence.evidence_id",
        ),
        name="fk_eos_cost_adjustment_evidence",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "prior_snapshot_id"),
        (
            "eos_labor_effort_snapshot.tenant_id",
            "eos_labor_effort_snapshot.company_id",
            "eos_labor_effort_snapshot.snapshot_id",
        ),
        name="fk_eos_cost_adjustment_prior_snap",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "replacement_snapshot_id"),
        (
            "eos_labor_effort_snapshot.tenant_id",
            "eos_labor_effort_snapshot.company_id",
            "eos_labor_effort_snapshot.snapshot_id",
        ),
        name="fk_eos_cost_adjustment_repl_snap",
    ),
    CheckConstraint("delta_amount <> 0", name="ck_eos_cost_adjustment_delta"),
)


class EosPayrollProjectAllocationError(RuntimeError):
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
class PayrollProjectAllocationRequest:
    tenant_id: str
    company_id: str
    payroll_evidence_id: str
    effort_snapshot_id: str
    plan_id: str
    plan_revision: int
    policy_hash: str
    residual_treatment: str
    residual_effort_units: Decimal = Decimal(0)
    operating_project_id: str | None = None
    operating_project_code: str | None = None


@dataclass(frozen=True)
class PayrollProjectAdjustmentRequest:
    tenant_id: str
    company_id: str
    supersedes_allocation_id: str
    effort_snapshot_id: str
    plan_id: str
    plan_revision: int
    policy_hash: str
    residual_treatment: str
    residual_effort_units: Decimal = Decimal(0)
    operating_project_id: str | None = None
    operating_project_code: str | None = None


@dataclass(frozen=True)
class _Target:
    project_id: str
    project_code: str
    work_code: str | None
    basis_units: Decimal
    allocation_ratio: Decimal
    eligibility_hash: str


@dataclass(frozen=True)
class _Prepared:
    request: PayrollProjectAllocationRequest
    evidence: Mapping[str, Any]
    snapshot: Mapping[str, Any]
    plan: Mapping[str, Any]
    targets: tuple[_Target, ...]
    allocation_id: str
    allocation_hash: str
    batch_id: str
    business_operation_id: str
    idempotency_key: str
    status: str
    project_effort_units: Decimal
    residual_effort_units: Decimal
    allocated_total: Decimal
    residual_total: Decimal


class SqlAlchemyEosPayrollProjectAllocationRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock=None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def prepare(self, request: PayrollProjectAllocationRequest) -> _Prepared:
        normalized = _normalize_request(request)
        try:
            with self._session_factory() as session:
                return _prepare_in_session(session, normalized)
        except EosPayrollProjectAllocationError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def record_initial(
        self, prepared: _Prepared, allocation_result: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        try:
            with self._session_factory.begin() as session:
                existing = _load_allocation(
                    session,
                    tenant_id=prepared.request.tenant_id,
                    company_id=prepared.request.company_id,
                    allocation_id=prepared.allocation_id,
                )
                if existing is not None:
                    if existing["allocation_hash"] != prepared.allocation_hash:
                        raise _conflict(
                            "Payroll allocation identity has different semantics"
                        )
                    return _allocation_projection(existing), False
                if str(allocation_result.get("batch_id")) != prepared.batch_id:
                    raise _conflict("Cost Allocation result batch differs from request")
                batch = _load_batch(session, prepared)
                if batch is None or batch["state"] != "COMMITTED":
                    raise _conflict("Committed Cost Allocation batch was not found")
                record = _allocation_record(
                    prepared,
                    revision=1,
                    supersedes=None,
                    created_at=_aware_time("clock", self._clock()),
                )
                session.execute(
                    EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.insert().values(**record)
                )
                return _allocation_projection(record), True
        except EosPayrollProjectAllocationError:
            raise
        except IntegrityError as exc:
            raise _conflict("Payroll allocation persistence conflicts") from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def apply_adjustment(
        self,
        session: Session,
        command: PayrollProjectAdjustmentRequest,
        *,
        operation_id: str,
    ) -> dict[str, Any]:
        normalized = _normalize_adjustment(command)
        prior = _load_allocation(
            session,
            tenant_id=normalized.tenant_id,
            company_id=normalized.company_id,
            allocation_id=normalized.supersedes_allocation_id,
            lock=True,
        )
        if prior is None:
            raise _not_found("Prior Payroll Project Allocation was not found")
        successor = session.scalar(
            select(EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.allocation_id).where(
                EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.tenant_id
                == normalized.tenant_id,
                EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.company_id
                == normalized.company_id,
                EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.supersedes_allocation_id
                == normalized.supersedes_allocation_id,
            )
        )
        if successor is not None:
            raise _conflict(
                "Prior Payroll Project Allocation is not the latest revision"
            )
        replacement_request = PayrollProjectAllocationRequest(
            tenant_id=normalized.tenant_id,
            company_id=normalized.company_id,
            payroll_evidence_id=str(prior["payroll_evidence_id"]),
            effort_snapshot_id=normalized.effort_snapshot_id,
            plan_id=normalized.plan_id,
            plan_revision=normalized.plan_revision,
            policy_hash=normalized.policy_hash,
            residual_treatment=normalized.residual_treatment,
            residual_effort_units=normalized.residual_effort_units,
            operating_project_id=normalized.operating_project_id,
            operating_project_code=normalized.operating_project_code,
        )
        prepared = _prepare_in_session(session, replacement_request)
        if prepared.batch_id == prior["batch_id"]:
            raise _conflict("Replacement allocation must use a new semantic revision")
        if (
            prepared.status == "PROVISIONAL"
            and prior["allocation_status"] == "CONFIRMED"
        ):
            raise _conflict("Confirmed labor allocation cannot regress to provisional")
        old_snapshot = _load_snapshot(
            session,
            normalized.tenant_id,
            normalized.company_id,
            str(prior["effort_snapshot_id"]),
        )
        if old_snapshot is None or int(prepared.snapshot["revision"]) <= int(
            old_snapshot["revision"]
        ):
            raise _conflict("Replacement effort snapshot must have a later revision")

        base_lines = _load_batch_lines(
            session,
            tenant_id=normalized.tenant_id,
            company_id=normalized.company_id,
            batch_id=str(prior["batch_id"]),
        )
        current = _current_amounts(
            session,
            tenant_id=normalized.tenant_id,
            company_id=normalized.company_id,
            batch_id=str(prior["batch_id"]),
            base_lines=base_lines,
        )
        desired = _desired_amounts(prepared)
        if _money(sum(desired.values(), Decimal()) + prepared.residual_total) != _money(
            prepared.evidence["eligible_amount_functional"]
        ):
            raise _conflict("Replacement allocation does not conserve payroll amount")

        revision = int(prior["allocation_revision"]) + 1
        allocation_id = _revision_allocation_id(
            prepared.allocation_hash,
            str(prior["batch_id"]),
            revision,
        )
        transition = (
            "PROVISIONAL_TO_ACTUAL"
            if prior["allocation_status"] == "PROVISIONAL"
            and prepared.status == "CONFIRMED"
            else "ACTUAL_CORRECTION"
        )
        now = _aware_time("clock", self._clock())
        base_by_project = {str(item["project_id"]): item for item in base_lines}
        target_by_project = {item.project_id: item for item in prepared.targets}
        deltas = {
            project_id: _money(desired.get(project_id, Decimal()) - amount)
            for project_id, amount in {
                **{key: Decimal() for key in desired},
                **current,
            }.items()
        }
        adjustment_records: list[dict[str, Any]] = []
        for project_id in sorted(deltas):
            delta = deltas[project_id]
            if delta == 0:
                continue
            target = target_by_project.get(project_id)
            base = base_by_project.get(project_id)
            if target is None:
                if base is None:
                    raise _not_found("Adjustment target Project lineage was not found")
                project_code = str(base["project_code"])
                work_code = (
                    str(base["work_code"]) if base["work_code"] is not None else None
                )
            else:
                project_code = target.project_code
                work_code = target.work_code
            adjustment_hash = semantic_sha256_hash_ref(
                {
                    "domain": "EOS-PAYROLL-LABOR-ADJUSTMENT-V1",
                    "prior_allocation_id": str(prior["allocation_id"]),
                    "allocation_id": allocation_id,
                    "project_id": project_id,
                    "delta_amount": _amount_text(delta),
                    "snapshot_hash": str(prepared.snapshot["snapshot_hash"]),
                    "policy_hash": prepared.request.policy_hash,
                }
            )
            adjustment_records.append(
                {
                    "tenant_id": normalized.tenant_id,
                    "company_id": normalized.company_id,
                    "adjustment_id": str(
                        uuid.uuid5(_ADJUSTMENT_NAMESPACE, adjustment_hash)
                    ),
                    "original_batch_id": str(prior["batch_id"]) if base else None,
                    "original_batch_line_no": int(base["line_no"]) if base else None,
                    "original_journal_id": str(prepared.evidence["journal_id"]),
                    "new_journal_id": None,
                    "delta_amount": delta,
                    "reason": transition,
                    "effective_period_id": str(prepared.evidence["period_id"]),
                    "approved_proof": str(prepared.plan["approved_proof"]),
                    "operation_id": operation_id,
                    "adjustment_hash": adjustment_hash,
                    "payroll_allocation_id": allocation_id,
                    "payroll_evidence_id": str(prepared.evidence["evidence_id"]),
                    "prior_snapshot_id": str(prior["effort_snapshot_id"]),
                    "replacement_snapshot_id": str(prepared.snapshot["snapshot_id"]),
                    "target_project_id": project_id,
                    "target_project_code": project_code,
                    "work_code": work_code,
                    "adjustment_kind": transition,
                    "basis_source_ref": str(prepared.snapshot["source_ref"]),
                    "basis_source_hash": str(prepared.snapshot["snapshot_hash"]),
                    "created_at": now,
                }
            )
        if not adjustment_records and prepared.residual_total == _money(
            prior["residual_total"]
        ):
            raise _conflict("Replacement snapshot does not change allocation semantics")

        record = _allocation_record(
            prepared,
            revision=revision,
            supersedes=str(prior["allocation_id"]),
            created_at=now,
            allocation_id=allocation_id,
            batch_id=str(prior["batch_id"]),
        )
        session.execute(EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.insert().values(**record))
        if adjustment_records:
            session.execute(
                EOS_COST_ALLOCATION_ADJUSTMENT_TABLE.insert(), adjustment_records
            )
        return {
            **_allocation_projection(record),
            "adjustment_kind": transition,
            "adjustment_count": len(adjustment_records),
            "adjustment_total": _amount_text(sum(deltas.values(), Decimal())),
        }


class EosPayrollProjectAllocationService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyEosPayrollProjectAllocationRepository,
        cost_allocation_service: EosCostAllocationService,
        coordinator: EosBusinessTransactionCoordinator,
    ) -> None:
        self._repository = repository
        self._cost_allocation_service = cost_allocation_service
        self._coordinator = coordinator

    def allocate(self, request: PayrollProjectAllocationRequest) -> dict[str, Any]:
        prepared = self._repository.prepare(request)
        payload = _cost_allocation_payload(prepared)
        try:
            result = self._cost_allocation_service.run(
                tenant_id=prepared.request.tenant_id,
                company_id=prepared.request.company_id,
                payload=payload,
            )
        except EosCostAllocationError as exc:
            raise EosPayrollProjectAllocationError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        projection, created = self._repository.record_initial(prepared, result)
        return {
            "schema_version": PAYROLL_PROJECT_ALLOCATION_SCHEMA,
            "disposition": "CREATED" if created else "EXACT_REPLAY",
            **projection,
            "cost_allocation": result,
        }

    def adjust(self, request: PayrollProjectAdjustmentRequest) -> dict[str, Any]:
        normalized = _normalize_adjustment(request)
        payload_hash = _adjustment_payload_hash(normalized)
        operation_id = str(uuid.uuid5(_OPERATION_NAMESPACE, payload_hash))
        transaction_request = EosBusinessOperationRequest(
            tenant_id=normalized.tenant_id,
            business_operation_id=operation_id,
            idempotency_key=f"payroll-adjust:{payload_hash[7:55]}",
            operation=PAYROLL_PROJECT_ADJUST_OPERATION,
            payload_hash=payload_hash,
            event_type=PAYROLL_PROJECT_ADJUST_EVENT,
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise EosBusinessOperationError(
                    "EOS_PAYROLL_ALLOCATION_TRANSACTION_REQUIRED",
                    "Payroll adjustment requires an EOS database transaction",
                    status_code=500,
                )
            try:
                return self._repository.apply_adjustment(
                    session, normalized, operation_id=operation_id
                )
            except EosPayrollProjectAllocationError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc

        try:
            result = self._coordinator.execute(transaction_request, mutation)
        except EosBusinessOperationError as exc:
            raise EosPayrollProjectAllocationError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return {
            "schema_version": PAYROLL_PROJECT_ADJUSTMENT_SCHEMA,
            "disposition": "CREATED" if result.created else "EXACT_REPLAY",
            "tenant_id": result.tenant_id,
            "business_operation_id": result.business_operation_id,
            "payload_hash": result.payload_hash,
            **result.result,
            "outbox": {
                "event_id": result.event_id,
                "event_type": result.event_type,
                "event_payload_hash": result.event_payload_hash,
                "delivery_state": "PENDING",
            },
        }


def _prepare_in_session(
    session: Session, request: PayrollProjectAllocationRequest
) -> _Prepared:
    evidence = _load_evidence(
        session, request.tenant_id, request.company_id, request.payroll_evidence_id
    )
    if evidence is None:
        raise _not_found("PayrollPostingEvidence was not found")
    if evidence["reconciliation_state"] != "VERIFIED":
        raise _conflict("PayrollPostingEvidence is not reconciled")
    snapshot = _load_snapshot(
        session, request.tenant_id, request.company_id, request.effort_snapshot_id
    )
    if snapshot is None:
        raise _not_found("LaborEffortSnapshot was not found")
    if snapshot["state"] != "APPROVED":
        raise _conflict("LaborEffortSnapshot is not APPROVED")
    if (
        snapshot["effort_period_start"] < evidence["payroll_period_start"]
        or snapshot["effort_period_end"] > evidence["payroll_period_end"]
    ):
        raise _conflict("Labor effort period is outside the PayrollRun period")
    lines = _load_effort_lines(session, request, snapshot)
    if not lines:
        raise _conflict("LaborEffortSnapshot has no Project effort lines")
    plan, plan_lines = _load_plan_with_lines(session, request)
    if plan is None:
        raise _not_found("Approved Payroll AllocationPlan was not found")
    if plan["state"] != "APPROVED" or plan["source_kind"] != "PAYROLL":
        raise _conflict("AllocationPlan is not an approved PAYROLL plan")
    if plan["rule_release_hash"] != request.policy_hash:
        raise _conflict("Payroll allocation policy differs from released plan")
    expected_basis = (
        "ACTUAL_WORK"
        if snapshot["basis_kind"] == "ACTUAL_APPROVED"
        else "APPROVED_PLAN"
    )
    if plan["basis_kind"] != expected_basis:
        raise _conflict("AllocationPlan basis differs from LaborEffortSnapshot")
    pool = _load_pool(session, evidence)
    if pool is None or pool["source_kind"] != "PAYROLL":
        raise _conflict("Payroll evidence SourcePool is unavailable")
    if pool["pool_state"] not in {"OPEN", "ALLOCATED"}:
        raise _conflict("Payroll SourcePool is not allocatable")
    if str(pool["period_id"]) != str(evidence["period_id"]):
        raise _conflict("Payroll SourcePool period differs from evidence")

    targets = _build_targets(session, request, snapshot, lines)
    _require_plan_matches(plan_lines, targets)
    project_effort = _effort(sum((item["effort_units"] for item in lines), Decimal()))
    total_effort = project_effort + request.residual_effort_units
    residual_total = (
        _money(
            Decimal(str(evidence["eligible_amount_functional"]))
            * request.residual_effort_units
            / total_effort
        )
        if request.residual_treatment == "RETAIN_UNALLOCATED"
        and request.residual_effort_units > 0
        else Decimal("0.0000")
    )
    allocated_total = _money(
        Decimal(str(evidence["eligible_amount_functional"])) - residual_total
    )
    semantic = {
        "domain": "EOS-PAYROLL-PROJECT-ALLOCATION-V1",
        "tenant_id": request.tenant_id,
        "company_id": request.company_id,
        "payroll_evidence_hash": str(evidence["evidence_hash"]),
        "effort_snapshot_hash": str(snapshot["snapshot_hash"]),
        "plan_id": request.plan_id,
        "plan_revision": request.plan_revision,
        "plan_hash": str(plan["plan_hash"]),
        "policy_hash": request.policy_hash,
        "residual_treatment": request.residual_treatment,
        "project_effort_units": _effort_text(project_effort),
        "residual_effort_units": _effort_text(request.residual_effort_units),
        "allocated_total": _amount_text(allocated_total),
        "residual_total": _amount_text(residual_total),
        "targets": [_target_wire(item) for item in targets],
    }
    allocation_hash = semantic_sha256_hash_ref(semantic)
    allocation_id = str(uuid.uuid5(_ALLOCATION_NAMESPACE, allocation_hash))
    batch_id = str(uuid.uuid5(_BATCH_NAMESPACE, allocation_hash))
    operation_id = str(uuid.uuid5(_OPERATION_NAMESPACE, allocation_hash))
    return _Prepared(
        request=request,
        evidence=evidence,
        snapshot=snapshot,
        plan=plan,
        targets=targets,
        allocation_id=allocation_id,
        allocation_hash=allocation_hash,
        batch_id=batch_id,
        business_operation_id=operation_id,
        idempotency_key=f"payroll-allocate:{allocation_hash[7:55]}",
        status=(
            "CONFIRMED"
            if snapshot["basis_kind"] == "ACTUAL_APPROVED"
            else "PROVISIONAL"
        ),
        project_effort_units=project_effort,
        residual_effort_units=request.residual_effort_units,
        allocated_total=allocated_total,
        residual_total=residual_total,
    )


def _build_targets(
    session: Session,
    request: PayrollProjectAllocationRequest,
    snapshot: Mapping[str, Any],
    lines: Sequence[Mapping[str, Any]],
) -> tuple[_Target, ...]:
    grouped: dict[str, dict[str, Any]] = {}
    for line in lines:
        project_id = str(line["project_id"])
        item = grouped.setdefault(
            project_id,
            {
                "project_id": project_id,
                "project_code": str(line["project_code"]),
                "work_codes": set(),
                "basis_units": Decimal(),
                "line_hashes": [],
            },
        )
        item["basis_units"] += Decimal(str(line["effort_units"]))
        if line["work_code"] is not None:
            item["work_codes"].add(str(line["work_code"]))
        item["line_hashes"].append(str(line["line_hash"]))

    if request.residual_treatment == "OPERATING_PROJECT":
        if (
            request.operating_project_id is None
            or request.operating_project_code is None
        ):
            raise _invalid("OPERATING_PROJECT requires a governed target Project")
        project = _load_project(
            session, request.tenant_id, request.operating_project_id
        )
        if project is None or project["project_code"] != request.operating_project_code:
            raise _conflict("Operating Project authority does not match request")
        if project["status"] not in {"ACTIVE", "CLOSING"}:
            raise _conflict("Operating Project is not financially active")
        item = grouped.setdefault(
            request.operating_project_id,
            {
                "project_id": request.operating_project_id,
                "project_code": request.operating_project_code,
                "work_codes": set(),
                "basis_units": Decimal(),
                "line_hashes": [],
            },
        )
        item["basis_units"] += request.residual_effort_units
        item["line_hashes"].append(
            semantic_sha256_hash_ref(
                {
                    "domain": "EOS-PAYROLL-OPERATING-PROJECT-RESIDUAL-V1",
                    "snapshot_hash": str(snapshot["snapshot_hash"]),
                    "project_id": request.operating_project_id,
                    "residual_effort_units": _effort_text(
                        request.residual_effort_units
                    ),
                    "policy_hash": request.policy_hash,
                }
            )
        )

    ordered = [grouped[key] for key in sorted(grouped)]
    total = _effort(sum((item["basis_units"] for item in ordered), Decimal()))
    ratios = _deterministic_ratios([_effort(item["basis_units"]) for item in ordered])
    targets: list[_Target] = []
    for item, ratio in zip(ordered, ratios, strict=True):
        work_codes = sorted(item["work_codes"])
        work_code = work_codes[0] if len(work_codes) == 1 else None
        eligibility_hash = semantic_sha256_hash_ref(
            {
                "domain": "EOS-PAYROLL-ALLOCATION-ELIGIBILITY-V1",
                "snapshot_hash": str(snapshot["snapshot_hash"]),
                "project_id": item["project_id"],
                "project_code": item["project_code"],
                "basis_units": _effort_text(item["basis_units"]),
                "line_hashes": sorted(item["line_hashes"]),
                "policy_hash": request.policy_hash,
            }
        )
        targets.append(
            _Target(
                project_id=item["project_id"],
                project_code=item["project_code"],
                work_code=work_code,
                basis_units=_effort(item["basis_units"]),
                allocation_ratio=ratio,
                eligibility_hash=eligibility_hash,
            )
        )
    if total <= 0:
        raise _invalid("Payroll allocation requires positive Project effort")
    return tuple(targets)


def _require_plan_matches(
    plan_lines: Sequence[Mapping[str, Any]], targets: Sequence[_Target]
) -> None:
    if len(plan_lines) != len(targets):
        raise _conflict("AllocationPlan targets differ from labor effort targets")
    for line, target in zip(
        sorted(plan_lines, key=lambda value: str(value["project_id"])),
        targets,
        strict=True,
    ):
        if (
            str(line["project_id"]) != target.project_id
            or str(line["project_code"]) != target.project_code
            or (str(line["work_code"]) if line["work_code"] is not None else None)
            != target.work_code
            or _effort(line["basis_units"]) != target.basis_units
            or _ratio(line["allocation_ratio"]) != target.allocation_ratio
            or str(line["eligibility_hash"]) != target.eligibility_hash
        ):
            raise _conflict(
                "AllocationPlan line differs from approved labor effort semantics"
            )


def _cost_allocation_payload(prepared: _Prepared) -> dict[str, Any]:
    value = {
        "schema_version": "eos_cost_allocation_run.v1",
        "business_operation_id": prepared.business_operation_id,
        "idempotency_key": prepared.idempotency_key,
        "payload_hash": "sha256:" + "0" * 64,
        "batch_id": prepared.batch_id,
        "plan_id": prepared.request.plan_id,
        "plan_revision": prepared.request.plan_revision,
        "period_id": str(prepared.evidence["period_id"]),
        "functional_currency": str(prepared.evidence["functional_currency"]),
        "currency_scale": 4,
        "sources": [
            {
                "pool_id": str(prepared.evidence["pool_id"]),
                "unallocated_amount_functional": _amount_text(prepared.residual_total),
            }
        ],
    }
    parsed = parse_cost_allocation_run(
        tenant_id=prepared.request.tenant_id,
        company_id=prepared.request.company_id,
        payload=value,
    )
    value["payload_hash"] = cost_allocation_payload_hash(parsed)
    return value


def _desired_amounts(prepared: _Prepared) -> dict[str, Decimal]:
    plan_lines = [
        {
            "project_id": item.project_id,
            "work_code": item.work_code,
            "allocation_ratio": item.allocation_ratio,
        }
        for item in prepared.targets
    ]
    allocated = deterministic_allocate(
        amount=prepared.allocated_total,
        plan_lines=plan_lines,
        basis_priority=(1 if prepared.status == "CONFIRMED" else 2),
    )
    return {
        str(item["plan_line"]["project_id"]): _money(
            item["allocated_amount_functional"]
        )
        for item in allocated
    }


def _current_amounts(
    session: Session,
    *,
    tenant_id: str,
    company_id: str,
    batch_id: str,
    base_lines: Sequence[Mapping[str, Any]],
) -> dict[str, Decimal]:
    current = defaultdict(Decimal)
    for line in base_lines:
        current[str(line["project_id"])] += Decimal(
            str(line["allocated_amount_functional"])
        )
    allocation_ids = select(EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.allocation_id).where(
        EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.tenant_id == tenant_id,
        EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.company_id == company_id,
        EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.batch_id == batch_id,
    )
    adjustments = session.execute(
        select(EOS_COST_ALLOCATION_ADJUSTMENT_TABLE).where(
            EOS_COST_ALLOCATION_ADJUSTMENT_TABLE.c.tenant_id == tenant_id,
            EOS_COST_ALLOCATION_ADJUSTMENT_TABLE.c.company_id == company_id,
            EOS_COST_ALLOCATION_ADJUSTMENT_TABLE.c.payroll_allocation_id.in_(
                allocation_ids
            ),
        )
    ).mappings()
    for item in adjustments:
        current[str(item["target_project_id"])] += Decimal(str(item["delta_amount"]))
    return {key: _money(value) for key, value in current.items() if value != 0}


def _allocation_record(
    prepared: _Prepared,
    *,
    revision: int,
    supersedes: str | None,
    created_at: datetime,
    allocation_id: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    return {
        "tenant_id": prepared.request.tenant_id,
        "company_id": prepared.request.company_id,
        "allocation_id": allocation_id or prepared.allocation_id,
        "allocation_revision": revision,
        "payroll_evidence_id": str(prepared.evidence["evidence_id"]),
        "effort_snapshot_id": str(prepared.snapshot["snapshot_id"]),
        "plan_id": prepared.request.plan_id,
        "plan_revision": prepared.request.plan_revision,
        "batch_id": batch_id or prepared.batch_id,
        "basis_kind": str(prepared.snapshot["basis_kind"]),
        "allocation_status": prepared.status,
        "residual_treatment": prepared.request.residual_treatment,
        "project_effort_units": prepared.project_effort_units,
        "residual_effort_units": prepared.residual_effort_units,
        "allocated_total": prepared.allocated_total,
        "residual_total": prepared.residual_total,
        "policy_hash": prepared.request.policy_hash,
        "allocation_hash": prepared.allocation_hash,
        "supersedes_allocation_id": supersedes,
        "created_at": created_at,
    }


def _allocation_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": str(value["tenant_id"]),
        "company_id": str(value["company_id"]),
        "allocation_id": str(value["allocation_id"]),
        "allocation_revision": int(value["allocation_revision"]),
        "payroll_evidence_id": str(value["payroll_evidence_id"]),
        "effort_snapshot_id": str(value["effort_snapshot_id"]),
        "plan_id": str(value["plan_id"]),
        "plan_revision": int(value["plan_revision"]),
        "batch_id": str(value["batch_id"]),
        "basis_kind": str(value["basis_kind"]),
        "allocation_status": str(value["allocation_status"]),
        "residual_treatment": str(value["residual_treatment"]),
        "project_effort_units": _effort_text(value["project_effort_units"]),
        "residual_effort_units": _effort_text(value["residual_effort_units"]),
        "allocated_total": _amount_text(value["allocated_total"]),
        "residual_total": _amount_text(value["residual_total"]),
        "policy_hash": str(value["policy_hash"]),
        "allocation_hash": str(value["allocation_hash"]),
        "supersedes_allocation_id": (
            str(value["supersedes_allocation_id"])
            if value["supersedes_allocation_id"] is not None
            else None
        ),
        "created_at": _wire_time(value["created_at"]),
    }


def _normalize_request(
    value: PayrollProjectAllocationRequest,
) -> PayrollProjectAllocationRequest:
    if not isinstance(value, PayrollProjectAllocationRequest):
        raise _invalid("Payroll allocation request has an invalid type")
    residual_treatment = _choice(
        "residual_treatment", value.residual_treatment, PAYROLL_RESIDUAL_TREATMENTS
    )
    residual_units = _effort(value.residual_effort_units)
    if residual_units < 0:
        raise _invalid("residual_effort_units must be non-negative")
    operating_id = (
        _uuid("operating_project_id", value.operating_project_id)
        if value.operating_project_id is not None
        else None
    )
    operating_code = (
        _project_code(value.operating_project_code)
        if value.operating_project_code is not None
        else None
    )
    if residual_treatment == "OPERATING_PROJECT":
        if residual_units <= 0 or operating_id is None or operating_code is None:
            raise _invalid(
                "OPERATING_PROJECT requires positive residual effort and Project"
            )
    elif operating_id is not None or operating_code is not None:
        raise _invalid("Operating Project is only valid for OPERATING_PROJECT")
    return PayrollProjectAllocationRequest(
        tenant_id=_tenant(value.tenant_id),
        company_id=_uuid("company_id", value.company_id),
        payroll_evidence_id=_uuid("payroll_evidence_id", value.payroll_evidence_id),
        effort_snapshot_id=_uuid("effort_snapshot_id", value.effort_snapshot_id),
        plan_id=_uuid("plan_id", value.plan_id),
        plan_revision=_positive_int("plan_revision", value.plan_revision),
        policy_hash=_hash("policy_hash", value.policy_hash),
        residual_treatment=residual_treatment,
        residual_effort_units=residual_units,
        operating_project_id=operating_id,
        operating_project_code=operating_code,
    )


def _normalize_adjustment(
    value: PayrollProjectAdjustmentRequest,
) -> PayrollProjectAdjustmentRequest:
    if not isinstance(value, PayrollProjectAdjustmentRequest):
        raise _invalid("Payroll adjustment request has an invalid type")
    normalized = _normalize_request(
        PayrollProjectAllocationRequest(
            tenant_id=value.tenant_id,
            company_id=value.company_id,
            payroll_evidence_id=str(uuid.UUID(int=0)),
            effort_snapshot_id=value.effort_snapshot_id,
            plan_id=value.plan_id,
            plan_revision=value.plan_revision,
            policy_hash=value.policy_hash,
            residual_treatment=value.residual_treatment,
            residual_effort_units=value.residual_effort_units,
            operating_project_id=value.operating_project_id,
            operating_project_code=value.operating_project_code,
        )
    )
    return PayrollProjectAdjustmentRequest(
        tenant_id=normalized.tenant_id,
        company_id=normalized.company_id,
        supersedes_allocation_id=_uuid(
            "supersedes_allocation_id", value.supersedes_allocation_id
        ),
        effort_snapshot_id=normalized.effort_snapshot_id,
        plan_id=normalized.plan_id,
        plan_revision=normalized.plan_revision,
        policy_hash=normalized.policy_hash,
        residual_treatment=normalized.residual_treatment,
        residual_effort_units=normalized.residual_effort_units,
        operating_project_id=normalized.operating_project_id,
        operating_project_code=normalized.operating_project_code,
    )


def _deterministic_ratios(units: Sequence[Decimal]) -> tuple[Decimal, ...]:
    total = sum(units, Decimal())
    if total <= 0:
        raise _invalid("Payroll allocation basis total must be positive")
    values = [(item / total).quantize(_RATIO, rounding=ROUND_DOWN) for item in units]
    remainder = Decimal(1) - sum(values, Decimal())
    count = int((remainder / _RATIO).to_integral_exact())
    if count > len(values):
        raise _conflict("Payroll allocation ratios cannot be reconciled")
    for index in range(count):
        values[index] += _RATIO
    return tuple(values)


def _load_evidence(
    session: Session, tenant_id: str, company_id: str, evidence_id: str
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_PAYROLL_POST_EVIDENCE_TABLE).where(
                EOS_PAYROLL_POST_EVIDENCE_TABLE.c.tenant_id == tenant_id,
                EOS_PAYROLL_POST_EVIDENCE_TABLE.c.company_id == company_id,
                EOS_PAYROLL_POST_EVIDENCE_TABLE.c.evidence_id == evidence_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _load_snapshot(
    session: Session, tenant_id: str, company_id: str, snapshot_id: str
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_LABOR_EFFORT_SNAPSHOT_TABLE).where(
                EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.tenant_id == tenant_id,
                EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.company_id == company_id,
                EOS_LABOR_EFFORT_SNAPSHOT_TABLE.c.snapshot_id == snapshot_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _load_effort_lines(
    session: Session,
    request: PayrollProjectAllocationRequest,
    snapshot: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    return list(
        session.execute(
            select(EOS_LABOR_EFFORT_LINE_TABLE)
            .where(
                EOS_LABOR_EFFORT_LINE_TABLE.c.tenant_id == request.tenant_id,
                EOS_LABOR_EFFORT_LINE_TABLE.c.company_id == request.company_id,
                EOS_LABOR_EFFORT_LINE_TABLE.c.snapshot_id == snapshot["snapshot_id"],
            )
            .order_by(EOS_LABOR_EFFORT_LINE_TABLE.c.line_no)
        ).mappings()
    )


def _load_plan_with_lines(
    session: Session, request: PayrollProjectAllocationRequest
) -> tuple[Mapping[str, Any] | None, list[Mapping[str, Any]]]:
    plan = (
        session.execute(
            select(EOS_COST_ALLOCATION_PLAN_TABLE).where(
                EOS_COST_ALLOCATION_PLAN_TABLE.c.tenant_id == request.tenant_id,
                EOS_COST_ALLOCATION_PLAN_TABLE.c.company_id == request.company_id,
                EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_id == request.plan_id,
                EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_revision == request.plan_revision,
            )
        )
        .mappings()
        .one_or_none()
    )
    if plan is None:
        return None, []
    lines = list(
        session.execute(
            select(EOS_COST_ALLOCATION_PLAN_LINE_TABLE)
            .where(
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.tenant_id == request.tenant_id,
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.company_id == request.company_id,
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.plan_id == request.plan_id,
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.plan_revision
                == request.plan_revision,
            )
            .order_by(EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.line_no)
        ).mappings()
    )
    return plan, lines


def _load_pool(
    session: Session, evidence: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_COST_SOURCE_POOL_TABLE).where(
                EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == evidence["tenant_id"],
                EOS_COST_SOURCE_POOL_TABLE.c.company_id == evidence["company_id"],
                EOS_COST_SOURCE_POOL_TABLE.c.pool_id == evidence["pool_id"],
            )
        )
        .mappings()
        .one_or_none()
    )


def _load_project(
    session: Session, tenant_id: str, project_id: str
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_PROJECT_TABLE.c.project_code, EOS_PROJECT_TABLE.c.status).where(
                EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_TABLE.c.project_id == project_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _load_batch(session: Session, prepared: _Prepared) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_COST_ALLOCATION_BATCH_TABLE).where(
                EOS_COST_ALLOCATION_BATCH_TABLE.c.tenant_id
                == prepared.request.tenant_id,
                EOS_COST_ALLOCATION_BATCH_TABLE.c.company_id
                == prepared.request.company_id,
                EOS_COST_ALLOCATION_BATCH_TABLE.c.batch_id == prepared.batch_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _load_batch_lines(
    session: Session, *, tenant_id: str, company_id: str, batch_id: str
) -> list[Mapping[str, Any]]:
    return list(
        session.execute(
            select(EOS_COST_ALLOCATION_LINE_TABLE)
            .where(
                EOS_COST_ALLOCATION_LINE_TABLE.c.tenant_id == tenant_id,
                EOS_COST_ALLOCATION_LINE_TABLE.c.company_id == company_id,
                EOS_COST_ALLOCATION_LINE_TABLE.c.batch_id == batch_id,
            )
            .order_by(EOS_COST_ALLOCATION_LINE_TABLE.c.line_no)
        ).mappings()
    )


def _load_allocation(
    session: Session,
    *,
    tenant_id: str,
    company_id: str,
    allocation_id: str,
    lock: bool = False,
) -> Mapping[str, Any] | None:
    statement = select(EOS_PAYROLL_PROJECT_ALLOCATION_TABLE).where(
        EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.tenant_id == tenant_id,
        EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.company_id == company_id,
        EOS_PAYROLL_PROJECT_ALLOCATION_TABLE.c.allocation_id == allocation_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.execute(statement).mappings().one_or_none()


def _revision_allocation_id(allocation_hash: str, batch_id: str, revision: int) -> str:
    return str(
        uuid.uuid5(
            _ALLOCATION_NAMESPACE,
            f"{allocation_hash}/{batch_id}/revision/{revision}",
        )
    )


def _adjustment_payload_hash(value: PayrollProjectAdjustmentRequest) -> str:
    return semantic_sha256_hash_ref(
        {
            "domain": "EOS-PAYROLL-PROJECT-ADJUSTMENT-REQUEST-V1",
            "tenant_id": value.tenant_id,
            "company_id": value.company_id,
            "supersedes_allocation_id": value.supersedes_allocation_id,
            "effort_snapshot_id": value.effort_snapshot_id,
            "plan_id": value.plan_id,
            "plan_revision": value.plan_revision,
            "policy_hash": value.policy_hash,
            "residual_treatment": value.residual_treatment,
            "residual_effort_units": _effort_text(value.residual_effort_units),
            "operating_project_id": value.operating_project_id,
            "operating_project_code": value.operating_project_code,
        }
    )


def _target_wire(value: _Target) -> dict[str, Any]:
    return {
        "project_id": value.project_id,
        "project_code": value.project_code,
        "work_code": value.work_code,
        "basis_units": _effort_text(value.basis_units),
        "allocation_ratio": format(value.allocation_ratio, "f"),
        "eligibility_hash": value.eligibility_hash,
    }


def _tenant(value: Any) -> str:
    if not isinstance(value, str) or _TENANT.fullmatch(value) is None:
        raise _invalid("tenant_id has an invalid format")
    return value


def _uuid(name: str, value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{name} must be a UUID") from exc


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(f"{name} must be a positive integer")
    return value


def _hash(name: str, value: Any) -> str:
    if not isinstance(value, str) or _HASH_REF.fullmatch(value) is None:
        raise _invalid(f"{name} must be a sha256 hash reference")
    return value


def _project_code(value: Any) -> str:
    if not isinstance(value, str) or _PROJECT_CODE.fullmatch(value) is None:
        raise _invalid("operating_project_code has an invalid format")
    return value


def _choice(name: str, value: Any, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _invalid(f"{name} is not supported")
    return value


def _decimal(value: Any, quantum: Decimal, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be a decimal") from exc
    if not parsed.is_finite():
        raise _invalid(f"{name} must be finite")
    quantized = parsed.quantize(quantum)
    if quantized != parsed:
        raise _invalid(f"{name} has excessive precision")
    return quantized


def _money(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise _invalid("amount must be a decimal") from exc
    if not parsed.is_finite():
        raise _invalid("amount must be finite")
    return parsed.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _effort(value: Any) -> Decimal:
    return _decimal(value, _EFFORT, "effort units")


def _ratio(value: Any) -> Decimal:
    return _decimal(value, _RATIO, "allocation ratio")


def _amount_text(value: Any) -> str:
    return format(_money(value), "f")


def _effort_text(value: Any) -> str:
    return format(_effort(value), "f")


def _aware_time(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _wire_time(value: Any) -> str:
    if not isinstance(value, datetime):
        raise _conflict("Persisted allocation time is malformed")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> EosPayrollProjectAllocationError:
    return EosPayrollProjectAllocationError(
        "EOS_PAYROLL_PROJECT_ALLOCATION_INVALID", detail, status_code=422
    )


def _not_found(detail: str) -> EosPayrollProjectAllocationError:
    return EosPayrollProjectAllocationError(
        "EOS_PAYROLL_PROJECT_ALLOCATION_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosPayrollProjectAllocationError:
    return EosPayrollProjectAllocationError(
        "EOS_PAYROLL_PROJECT_ALLOCATION_CONFLICT", detail, status_code=409
    )


def _unavailable() -> EosPayrollProjectAllocationError:
    return EosPayrollProjectAllocationError(
        "EOS_PAYROLL_PROJECT_ALLOCATION_UNAVAILABLE",
        "Payroll Project Allocation persistence is unavailable",
        status_code=503,
        retryable=True,
    )
