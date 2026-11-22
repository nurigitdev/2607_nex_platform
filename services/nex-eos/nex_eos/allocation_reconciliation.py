from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .allocation_outbox_events import (
    EosAllocationOutboxEventError,
    admit_allocation_committed_event,
)
from .allocation_plans import (
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
)
from .business_transactions import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_OUTBOX_TABLE,
)
from .cost_allocations import (
    COST_ALLOCATION_EVENT_TYPE,
    COST_ALLOCATION_RUN_OPERATION,
    COST_ALLOCATION_VERIFY_OPERATION,
    EOS_COST_ALLOCATION_BATCH_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
    AllocationSourceInput,
    CostAllocationRunCommand,
    build_reconciliation_hash,
    build_source_set_hash,
)
from .cost_source_pools import EOS_COST_SOURCE_POOL_TABLE

COST_ALLOCATION_RECONCILIATION_SCHEMA = "eos_cost_allocation_reconciliation.v1"
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class EosAllocationReconciliationError(RuntimeError):
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


class EosAllocationReconciliationService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def verify_batch(
        self, *, tenant_id: str, company_id: str, batch_id: str
    ) -> dict[str, Any]:
        tenant_id = _tenant(tenant_id)
        company_id = _uuid("company_id", company_id)
        batch_id = _uuid("batch_id", batch_id)
        try:
            with self._session_factory() as session:
                batch = _one(
                    session,
                    select(EOS_COST_ALLOCATION_BATCH_TABLE).where(
                        EOS_COST_ALLOCATION_BATCH_TABLE.c.tenant_id == tenant_id,
                        EOS_COST_ALLOCATION_BATCH_TABLE.c.company_id == company_id,
                        EOS_COST_ALLOCATION_BATCH_TABLE.c.batch_id == batch_id,
                    ),
                )
                if batch is None:
                    raise EosAllocationReconciliationError(
                        "EOS_COST_ALLOCATION_BATCH_NOT_FOUND",
                        "Cost Allocation batch was not found",
                        status_code=404,
                    )
                business_operation_id = str(batch["business_operation_id"])
        except EosAllocationReconciliationError:
            raise
        except SQLAlchemyError as exc:
            raise EosAllocationReconciliationError(
                "EOS_COST_ALLOCATION_RECONCILIATION_UNAVAILABLE",
                "Cost Allocation reconciliation persistence is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        return self.verify(
            tenant_id=tenant_id,
            business_operation_id=business_operation_id,
        )

    def verify(self, *, tenant_id: str, business_operation_id: str) -> dict[str, Any]:
        tenant_id = _tenant(tenant_id)
        business_operation_id = _uuid(
            "business_operation_id", business_operation_id
        )
        try:
            with self._session_factory() as session:
                operation = _one(
                    session,
                    select(EOS_BUSINESS_OPERATION_TABLE).where(
                        EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == tenant_id,
                        EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                        == business_operation_id,
                    ),
                )
                if operation is None:
                    raise EosAllocationReconciliationError(
                        "EOS_COST_ALLOCATION_OPERATION_NOT_FOUND",
                        "Cost Allocation BusinessOperation was not found",
                        status_code=404,
                    )
                if operation["operation"] != COST_ALLOCATION_RUN_OPERATION:
                    raise EosAllocationReconciliationError(
                        "EOS_COST_ALLOCATION_OPERATION_TYPE_MISMATCH",
                        "BusinessOperation is not a Cost Allocation RUN",
                        status_code=409,
                    )
                if operation["commit_state"] == "PENDING":
                    return _pending_projection(operation)
                if operation["commit_state"] == "NOT_COMMITTED":
                    return _not_committed_projection(operation)
                if operation["commit_state"] != "COMMITTED":
                    raise EosAllocationReconciliationError(
                        "EOS_COST_ALLOCATION_COMMIT_STATE_INVALID",
                        "Cost Allocation BusinessOperation has an invalid commit state",
                        status_code=503,
                        retryable=True,
                    )
                return self._verify_committed(session, operation)
        except EosAllocationReconciliationError:
            raise
        except SQLAlchemyError as exc:
            raise EosAllocationReconciliationError(
                "EOS_COST_ALLOCATION_RECONCILIATION_UNAVAILABLE",
                "Cost Allocation reconciliation persistence is unavailable",
                status_code=503,
                retryable=True,
            ) from exc

    def _verify_committed(
        self, session: Session, operation: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            idempotency = _one(
                session,
                select(EOS_IDEMPOTENCY_TABLE).where(
                    EOS_IDEMPOTENCY_TABLE.c.tenant_id == operation["tenant_id"],
                    EOS_IDEMPOTENCY_TABLE.c.business_operation_id
                    == operation["business_operation_id"],
                ),
            )
            outbox = _one(
                session,
                select(EOS_OUTBOX_TABLE).where(
                    EOS_OUTBOX_TABLE.c.tenant_id == operation["tenant_id"],
                    EOS_OUTBOX_TABLE.c.business_operation_id
                    == operation["business_operation_id"],
                    EOS_OUTBOX_TABLE.c.event_type == COST_ALLOCATION_EVENT_TYPE,
                ),
            )
            batch = _one(
                session,
                select(EOS_COST_ALLOCATION_BATCH_TABLE).where(
                    EOS_COST_ALLOCATION_BATCH_TABLE.c.tenant_id
                    == operation["tenant_id"],
                    EOS_COST_ALLOCATION_BATCH_TABLE.c.business_operation_id
                    == operation["business_operation_id"],
                ),
            )
            if idempotency is None or outbox is None or batch is None:
                raise ValueError("Committed allocation lineage is incomplete")
            plan = _one(
                session,
                select(EOS_COST_ALLOCATION_PLAN_TABLE).where(
                    EOS_COST_ALLOCATION_PLAN_TABLE.c.tenant_id == batch["tenant_id"],
                    EOS_COST_ALLOCATION_PLAN_TABLE.c.company_id == batch["company_id"],
                    EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_id == batch["plan_id"],
                    EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_revision
                    == batch["plan_revision"],
                ),
            )
            if plan is None:
                raise ValueError("Committed allocation plan is missing")
            plan_lines = list(
                session.execute(
                    select(EOS_COST_ALLOCATION_PLAN_LINE_TABLE)
                    .where(
                        EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.tenant_id
                        == batch["tenant_id"],
                        EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.company_id
                        == batch["company_id"],
                        EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.plan_id
                        == batch["plan_id"],
                        EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.plan_revision
                        == batch["plan_revision"],
                    )
                    .order_by(EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.line_no)
                ).mappings()
            )
            lines = list(
                session.execute(
                    select(EOS_COST_ALLOCATION_LINE_TABLE)
                    .where(
                        EOS_COST_ALLOCATION_LINE_TABLE.c.tenant_id
                        == batch["tenant_id"],
                        EOS_COST_ALLOCATION_LINE_TABLE.c.company_id
                        == batch["company_id"],
                        EOS_COST_ALLOCATION_LINE_TABLE.c.batch_id == batch["batch_id"],
                    )
                    .order_by(EOS_COST_ALLOCATION_LINE_TABLE.c.line_no)
                ).mappings()
            )
            pool_ids = sorted({str(line["pool_id"]) for line in lines})
            pools = list(
                session.execute(
                    select(EOS_COST_SOURCE_POOL_TABLE)
                    .where(
                        EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == batch["tenant_id"],
                        EOS_COST_SOURCE_POOL_TABLE.c.company_id == batch["company_id"],
                        EOS_COST_SOURCE_POOL_TABLE.c.pool_id.in_(pool_ids),
                    )
                    .order_by(EOS_COST_SOURCE_POOL_TABLE.c.pool_id)
                ).mappings()
            )
            if not lines or [str(pool["pool_id"]) for pool in pools] != pool_ids:
                raise ValueError("Committed allocation source lineage is incomplete")
            command, conservation = _reconstructed_command(
                operation=operation,
                batch=batch,
                pools=pools,
                lines=lines,
            )
            _require_line_evidence(
                command=command,
                plan=plan,
                plan_lines=plan_lines,
                pools=pools,
                lines=lines,
            )
            source_set_hash = build_source_set_hash(pools)
            expected_hash = build_reconciliation_hash(
                command=command,
                plan_hash=str(plan["plan_hash"]),
                source_set_hash=source_set_hash,
                conservation=conservation,
                lines=lines,
                allocated_total=Decimal(str(batch["allocated_total"])),
                unallocated_total=Decimal(str(batch["unallocated_total"])),
            )
            _require_transaction_lineage(
                operation=operation,
                idempotency=idempotency,
                outbox=outbox,
                batch=batch,
                source_set_hash=source_set_hash,
                reconciliation_hash=expected_hash,
            )
            event = admit_allocation_committed_event(outbox["event_payload"])
            if (
                event["reconciliation_hash"] != expected_hash
                or event["batch_id"] != str(batch["batch_id"])
                or event["source_set_hash"] != source_set_hash
            ):
                raise ValueError("Cost Allocation outbox evidence has drifted")
        except (
            EosAllocationOutboxEventError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return _failed_projection(operation)

        try:
            reversed_pools = sorted(
                str(pool["pool_id"])
                for pool in pools
                if pool["pool_state"] == "REVERSED"
            )
            verification_status = (
                "ADJUSTMENT_REQUIRED" if reversed_pools else "VERIFIED"
            )
            return {
                **_base_projection(
                    operation,
                    reconciliation_status="COMMITTED_CONFIRMED",
                    verification_status=verification_status,
                    retry_disposition="DO_NOT_RERUN",
                ),
                "batch": _batch_projection(batch, len(lines), len(pools)),
                "conservation": conservation,
                "reversed_pool_ids": reversed_pools,
                "outbox": _outbox_projection(outbox),
            }
        except (KeyError, TypeError, ValueError):
            return _failed_projection(operation)


def _reconstructed_command(
    *,
    operation: Mapping[str, Any],
    batch: Mapping[str, Any],
    pools: list[Mapping[str, Any]],
    lines: list[Mapping[str, Any]],
) -> tuple[CostAllocationRunCommand, list[dict[str, Any]]]:
    lines_by_pool: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for line in lines:
        lines_by_pool[str(line["pool_id"])].append(line)
    sources: list[AllocationSourceInput] = []
    conservation: list[dict[str, Any]] = []
    allocated_total = Decimal(0)
    unallocated_total = Decimal(0)
    for pool in pools:
        pool_id = str(pool["pool_id"])
        allocated = sum(
            (
                Decimal(str(line["allocated_amount_functional"]))
                for line in lines_by_pool[pool_id]
            ),
            Decimal(0),
        )
        eligible = Decimal(str(pool["eligible_amount_functional"]))
        unallocated = eligible - allocated
        sources.append(AllocationSourceInput(pool_id, unallocated))
        allocated_total += allocated
        unallocated_total += unallocated
        conservation.append(
            {
                "pool_id": pool_id,
                "source_hash": str(pool["source_hash"]),
                "eligible_amount_functional": _amount_text(eligible),
                "direct_amount_functional": "0.0000",
                "allocated_amount_functional": _amount_text(allocated),
                "unallocated_amount_functional": _amount_text(unallocated),
            }
        )
    if allocated_total != Decimal(
        str(batch["allocated_total"])
    ) or unallocated_total != Decimal(str(batch["unallocated_total"])):
        raise ValueError("Cost Allocation totals do not conserve")
    command = CostAllocationRunCommand(
        tenant_id=str(batch["tenant_id"]),
        company_id=str(batch["company_id"]),
        business_operation_id=str(operation["business_operation_id"]),
        idempotency_key=str(operation["idempotency_key"]),
        payload_hash=str(operation["payload_hash"]),
        batch_id=str(batch["batch_id"]),
        plan_id=str(batch["plan_id"]),
        plan_revision=int(batch["plan_revision"]),
        period_id=str(batch["period_id"]),
        functional_currency=str(batch["functional_currency"]),
        sources=tuple(sources),
    )
    return command, conservation


def _require_line_evidence(
    *,
    command: CostAllocationRunCommand,
    plan: Mapping[str, Any],
    plan_lines: list[Mapping[str, Any]],
    pools: list[Mapping[str, Any]],
    lines: list[Mapping[str, Any]],
) -> None:
    plan_by_target = {
        (str(item["project_id"]), str(item["work_code"] or "")): item
        for item in plan_lines
    }
    pool_by_id = {str(item["pool_id"]): item for item in pools}
    for line in lines:
        target = (str(line["project_id"]), str(line["work_code"] or ""))
        plan_line = plan_by_target.get(target)
        pool = pool_by_id.get(str(line["pool_id"]))
        if plan_line is None or pool is None:
            raise ValueError("Cost Allocation line target or pool is missing")
        expected = semantic_sha256_hash_ref(
            {
                "domain": "EOS-COST-ALLOCATION-LINE-V1",
                "batch_id": command.batch_id,
                "pool_id": str(pool["pool_id"]),
                "source_hash": str(pool["source_hash"]),
                "plan_hash": str(plan["plan_hash"]),
                "plan_line_hash": str(plan_line["line_hash"]),
                "allocated_amount_functional": _amount_text(
                    line["allocated_amount_functional"]
                ),
                "rounding_delta": _amount_text(line["rounding_delta"]),
            }
        )
        if (
            line["status"] != "ALLOCATED"
            or line["allocation_mode"] != "MANAGEMENT_ALLOCATION"
            or str(line["basis_source_ref"]) != str(plan["basis_source_ref"])
            or str(line["basis_source_hash"]) != str(plan["basis_source_hash"])
            or str(line["evidence_hash"]) != expected
        ):
            raise ValueError("Cost Allocation line evidence has drifted")


def _require_transaction_lineage(
    *,
    operation: Mapping[str, Any],
    idempotency: Mapping[str, Any],
    outbox: Mapping[str, Any],
    batch: Mapping[str, Any],
    source_set_hash: str,
    reconciliation_hash: str,
) -> None:
    result = operation.get("result_json")
    if not isinstance(result, Mapping):
        raise TypeError("Cost Allocation result is missing")
    if (
        idempotency["idempotency_state"] != "COMPLETED"
        or idempotency["payload_hash"] != operation["payload_hash"]
        or idempotency["result_json"] != result
        or outbox["event_type"] != COST_ALLOCATION_EVENT_TYPE
        or batch["state"] != "COMMITTED"
        or str(batch["source_set_hash"]) != source_set_hash
        or str(batch["reconciliation_hash"]) != reconciliation_hash
        or result.get("batch_id") != str(batch["batch_id"])
        or result.get("source_set_hash") != source_set_hash
        or result.get("reconciliation_hash") != reconciliation_hash
    ):
        raise ValueError("Cost Allocation transaction lineage has drifted")


def _one(session: Session, statement) -> Mapping[str, Any] | None:
    return session.execute(statement).mappings().one_or_none()


def _base_projection(
    operation: Mapping[str, Any],
    *,
    reconciliation_status: str,
    verification_status: str,
    retry_disposition: str,
) -> dict[str, Any]:
    return {
        "schema_version": COST_ALLOCATION_RECONCILIATION_SCHEMA,
        "operation": COST_ALLOCATION_VERIFY_OPERATION,
        "tenant_id": str(operation["tenant_id"]),
        "business_operation_id": str(operation["business_operation_id"]),
        "commit_state": str(operation["commit_state"]),
        "reconciliation_status": reconciliation_status,
        "verification_status": verification_status,
        "retry_disposition": retry_disposition,
    }


def _pending_projection(operation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_base_projection(
            operation,
            reconciliation_status="RECONCILIATION_REQUIRED",
            verification_status="NOT_APPLICABLE",
            retry_disposition="RECONCILE_SAME_IDENTITY",
        ),
        "batch": None,
        "conservation": [],
        "reversed_pool_ids": [],
        "outbox": None,
    }


def _not_committed_projection(operation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_base_projection(
            operation,
            reconciliation_status="NOT_COMMITTED_CONFIRMED",
            verification_status="NOT_APPLICABLE",
            retry_disposition="MAY_RETRY_SAME_IDENTITY",
        ),
        "batch": None,
        "conservation": [],
        "reversed_pool_ids": [],
        "outbox": None,
    }


def _failed_projection(operation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_base_projection(
            operation,
            reconciliation_status="COMMITTED_CONFIRMED",
            verification_status="FAILED",
            retry_disposition="DO_NOT_RERUN",
        ),
        "batch": None,
        "conservation": [],
        "reversed_pool_ids": [],
        "outbox": None,
    }


def _batch_projection(
    batch: Mapping[str, Any], line_count: int, pool_count: int
) -> dict[str, Any]:
    return {
        "company_id": str(batch["company_id"]),
        "batch_id": str(batch["batch_id"]),
        "plan_id": str(batch["plan_id"]),
        "plan_revision": int(batch["plan_revision"]),
        "period_id": str(batch["period_id"]),
        "source_set_hash": str(batch["source_set_hash"]),
        "functional_currency": str(batch["functional_currency"]),
        "state": str(batch["state"]),
        "allocated_total": _amount_text(batch["allocated_total"]),
        "unallocated_total": _amount_text(batch["unallocated_total"]),
        "reconciliation_hash": str(batch["reconciliation_hash"]),
        "line_count": line_count,
        "pool_count": pool_count,
        "committed_at": _wire_time(batch["committed_at"]),
    }


def _outbox_projection(outbox: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "outbox_id": str(outbox["outbox_id"]),
        "event_id": str(outbox["event_id"]),
        "event_type": str(outbox["event_type"]),
        "event_payload_hash": str(outbox["event_payload_hash"]),
        "delivery_state": str(outbox["delivery_state"]),
        "attempt_count": int(outbox["attempt_count"]),
    }


def _amount_text(value: object) -> str:
    return format(Decimal(str(value)).quantize(Decimal("0.0001")), "f")


def _wire_time(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("Cost Allocation timestamp is missing")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _tenant(value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise EosAllocationReconciliationError(
            "EOS_COST_ALLOCATION_RECONCILIATION_INVALID",
            "tenant_id has an invalid format",
            status_code=422,
        )
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise EosAllocationReconciliationError(
            "EOS_COST_ALLOCATION_RECONCILIATION_INVALID",
            f"{field_name} must be a UUID",
            status_code=422,
        ) from exc
