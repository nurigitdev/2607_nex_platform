from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .cost_allocations import (
    EOS_COST_ALLOCATION_BATCH_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
)
from .cost_source_pools import EOS_COST_SOURCE_POOL_TABLE
from .project_pnl import (
    ProjectPnlComponentDraft,
    ProjectPnlProjectionDraft,
    SqlAlchemyEosProjectPnlRepository,
)

PROJECT_PNL_REBUILD_SCHEMA = "eos_project_pnl_rebuild.v1"
_PROJECTION_NAMESPACE = uuid.UUID("f49bdff2-292c-5efc-9ab3-68d427281795")
_MONEY = Decimal("0.0001")


class EosProjectPnlProjectorError(RuntimeError):
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
class ProjectPnlRebuildRequest:
    tenant_id: str
    company_id: str
    project_id: str
    project_code: str
    period_id: str
    projection_version: int
    functional_currency: str
    as_of: datetime
    evaluated_at: datetime
    stale_after_seconds: int = 120


@dataclass(frozen=True)
class ProjectPnlSourcePoolFact:
    pool_id: str
    journal_id: str
    journal_line_no: int
    source_project_id: str
    source_project_code: str
    source_kind: str
    allocation_mode: str
    eligible_amount_functional: Decimal
    functional_currency: str
    account_id: str
    account_category: str
    source_record_ref: str
    source_hash: str
    source_journal_hash: str
    pool_state: str
    recognized_at: datetime


@dataclass(frozen=True)
class ProjectPnlAllocationFact:
    batch_id: str
    line_no: int
    pool_id: str
    project_id: str
    project_code: str
    work_code: str | None
    allocated_amount_functional: Decimal
    allocation_mode: str
    evidence_hash: str
    reconciliation_hash: str
    committed_at: datetime


@dataclass(frozen=True)
class ProjectPnlSourceSnapshot:
    pools: tuple[ProjectPnlSourcePoolFact, ...]
    allocations: tuple[ProjectPnlAllocationFact, ...]


class ProjectPnlProjectionSource(Protocol):
    def load(self, request: ProjectPnlRebuildRequest) -> ProjectPnlSourceSnapshot: ...


class ProjectPnlProjectionSink(Protocol):
    def append(
        self,
        draft: ProjectPnlProjectionDraft,
        components: Sequence[ProjectPnlComponentDraft],
    ) -> dict[str, Any]: ...


class SqlAlchemyEosProjectPnlProjectionSource:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load(self, request: ProjectPnlRebuildRequest) -> ProjectPnlSourceSnapshot:
        as_of = _aware_time("as_of", request.as_of)
        try:
            with self._session_factory() as session:
                pools = self._load_pools(session, request=request, as_of=as_of)
                allocations = self._load_allocations(
                    session, request=request, as_of=as_of
                )
        except EosProjectPnlProjectorError:
            raise
        except SQLAlchemyError as exc:
            raise EosProjectPnlProjectorError(
                "PROJECT_PNL_SOURCE_UNAVAILABLE",
                "Project P&L source snapshot is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        return ProjectPnlSourceSnapshot(tuple(pools), tuple(allocations))

    @staticmethod
    def _load_pools(
        session: Session,
        *,
        request: ProjectPnlRebuildRequest,
        as_of: datetime,
    ) -> list[ProjectPnlSourcePoolFact]:
        rows = session.execute(
            select(EOS_COST_SOURCE_POOL_TABLE)
            .where(
                EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == request.tenant_id,
                EOS_COST_SOURCE_POOL_TABLE.c.company_id == request.company_id,
                EOS_COST_SOURCE_POOL_TABLE.c.period_id == request.period_id,
                EOS_COST_SOURCE_POOL_TABLE.c.recognized_at <= as_of,
                EOS_COST_SOURCE_POOL_TABLE.c.pool_state != "REVERSED",
            )
            .order_by(EOS_COST_SOURCE_POOL_TABLE.c.pool_id)
        ).mappings()
        return [_pool_fact(row) for row in rows]

    @staticmethod
    def _load_allocations(
        session: Session,
        *,
        request: ProjectPnlRebuildRequest,
        as_of: datetime,
    ) -> list[ProjectPnlAllocationFact]:
        rows = session.execute(
            select(
                EOS_COST_ALLOCATION_LINE_TABLE,
                EOS_COST_ALLOCATION_BATCH_TABLE.c.reconciliation_hash,
                EOS_COST_ALLOCATION_BATCH_TABLE.c.committed_at,
            )
            .join(
                EOS_COST_ALLOCATION_BATCH_TABLE,
                (
                    EOS_COST_ALLOCATION_BATCH_TABLE.c.tenant_id
                    == EOS_COST_ALLOCATION_LINE_TABLE.c.tenant_id
                )
                & (
                    EOS_COST_ALLOCATION_BATCH_TABLE.c.company_id
                    == EOS_COST_ALLOCATION_LINE_TABLE.c.company_id
                )
                & (
                    EOS_COST_ALLOCATION_BATCH_TABLE.c.batch_id
                    == EOS_COST_ALLOCATION_LINE_TABLE.c.batch_id
                ),
            )
            .where(
                EOS_COST_ALLOCATION_BATCH_TABLE.c.tenant_id == request.tenant_id,
                EOS_COST_ALLOCATION_BATCH_TABLE.c.company_id == request.company_id,
                EOS_COST_ALLOCATION_BATCH_TABLE.c.period_id == request.period_id,
                EOS_COST_ALLOCATION_BATCH_TABLE.c.state == "COMMITTED",
                EOS_COST_ALLOCATION_BATCH_TABLE.c.committed_at <= as_of,
                EOS_COST_ALLOCATION_LINE_TABLE.c.status == "ALLOCATED",
            )
            .order_by(
                EOS_COST_ALLOCATION_LINE_TABLE.c.batch_id,
                EOS_COST_ALLOCATION_LINE_TABLE.c.line_no,
            )
        ).mappings()
        return [_allocation_fact(row) for row in rows]


class EosProjectPnlProjector:
    def __init__(
        self,
        *,
        source: ProjectPnlProjectionSource,
        sink: ProjectPnlProjectionSink,
    ) -> None:
        self._source = source
        self._sink = sink

    def rebuild(self, request: ProjectPnlRebuildRequest) -> dict[str, Any]:
        snapshot = self._source.load(request)
        draft, components = build_direct_allocation_projection(request, snapshot)
        return self._sink.append(draft, components)


def build_direct_allocation_projection(
    request: ProjectPnlRebuildRequest,
    snapshot: ProjectPnlSourceSnapshot,
) -> tuple[ProjectPnlProjectionDraft, tuple[ProjectPnlComponentDraft, ...]]:
    as_of = _aware_time("as_of", request.as_of)
    evaluated_at = _aware_time("evaluated_at", request.evaluated_at)
    if evaluated_at < as_of:
        raise _invalid("evaluated_at must not precede as_of")
    projection_version = _positive_int("projection_version", request.projection_version)
    stale_after_seconds = _non_negative_int(
        "stale_after_seconds", request.stale_after_seconds
    )

    pools_by_id = {item.pool_id: item for item in snapshot.pools}
    if len(pools_by_id) != len(snapshot.pools):
        raise _source_drift("Source snapshot contains duplicate SourcePool identities")
    allocations_by_pool: dict[str, list[ProjectPnlAllocationFact]] = defaultdict(list)
    allocation_identities: set[tuple[str, int]] = set()
    for item in snapshot.allocations:
        identity = (item.batch_id, item.line_no)
        if identity in allocation_identities:
            raise _source_drift(
                "Source snapshot contains duplicate allocation identities"
            )
        allocation_identities.add(identity)
        pool = pools_by_id.get(item.pool_id)
        if pool is None:
            raise _source_drift("Committed allocation references an absent SourcePool")
        if pool.pool_state != "ALLOCATED":
            raise _source_drift(
                "Committed allocation is visible before its SourcePool state transition"
            )
        if item.allocation_mode != "MANAGEMENT_ALLOCATION":
            raise _blocked("Unsupported allocation mode entered the P&L projection")
        allocations_by_pool[item.pool_id].append(item)

    relevant_pool_ids = {
        item.pool_id
        for item in snapshot.pools
        if item.source_project_id == request.project_id
    }
    relevant_pool_ids.update(
        item.pool_id
        for item in snapshot.allocations
        if item.project_id == request.project_id
    )
    relevant_pools = tuple(
        item for item in snapshot.pools if item.pool_id in relevant_pool_ids
    )
    _validate_pool_snapshot(request, relevant_pools, allocations_by_pool)

    components: list[ProjectPnlComponentDraft] = []
    pending = False
    partial = False
    blocked = False
    for pool in relevant_pools:
        pool_allocations = allocations_by_pool.get(pool.pool_id, [])
        if pool.allocation_mode == "DIRECT":
            if pool.source_project_id == request.project_id:
                components.append(_direct_component(pool))
            continue
        if pool.allocation_mode != "MANAGEMENT_ALLOCATION":
            blocked = True
            continue
        for allocation in pool_allocations:
            if allocation.project_id == request.project_id:
                if allocation.project_code != request.project_code:
                    raise _source_drift(
                        "Allocation Project Code differs from requested Project authority"
                    )
                components.append(_allocation_component(pool, allocation))
        allocated_total = sum(
            (item.allocated_amount_functional for item in pool_allocations),
            Decimal(0),
        )
        residual = _money(pool.eligible_amount_functional - allocated_total)
        if residual != 0 and pool.source_project_id == request.project_id:
            components.append(_residual_component(pool, residual, allocated_total))
            if allocated_total == 0:
                pending = True
            else:
                partial = True
        if pool.pool_state == "ON_HOLD":
            blocked = True

    components.sort(key=_component_sort_key)
    reconciliation_status = (
        "BLOCKED"
        if blocked
        else "PARTIAL"
        if partial
        else "PENDING"
        if pending
        else "VERIFIED"
    )
    staleness_seconds = int((evaluated_at - as_of).total_seconds())
    freshness_status = (
        "CURRENT" if staleness_seconds <= stale_after_seconds else "STALE"
    )
    posting_watermark = _posting_watermark(request, relevant_pools)
    allocation_watermark = _allocation_watermark(
        request, relevant_pools, allocations_by_pool
    )
    projection_id = str(
        uuid.uuid5(
            _PROJECTION_NAMESPACE,
            "/".join(
                (
                    request.tenant_id,
                    request.company_id,
                    request.project_id,
                    request.period_id,
                    str(projection_version),
                )
            ),
        )
    )
    draft = ProjectPnlProjectionDraft(
        tenant_id=request.tenant_id,
        company_id=request.company_id,
        projection_id=projection_id,
        project_id=request.project_id,
        project_code=request.project_code,
        period_id=request.period_id,
        projection_version=projection_version,
        functional_currency=request.functional_currency,
        as_of=as_of,
        posting_watermark=posting_watermark,
        posting_watermark_at=as_of,
        allocation_watermark=allocation_watermark,
        allocation_watermark_at=as_of,
        reconciliation_status=reconciliation_status,
        freshness_status=freshness_status,
        staleness_seconds=staleness_seconds,
        data_classification="CONFIDENTIAL_FINANCIAL",
    )
    return draft, tuple(components)


def _validate_pool_snapshot(
    request: ProjectPnlRebuildRequest,
    pools: Sequence[ProjectPnlSourcePoolFact],
    allocations_by_pool: Mapping[str, Sequence[ProjectPnlAllocationFact]],
) -> None:
    for pool in pools:
        if pool.functional_currency != request.functional_currency:
            raise _blocked("SourcePool currency differs from projection currency")
        if (
            pool.source_project_id == request.project_id
            and pool.source_project_code != request.project_code
        ):
            raise _source_drift(
                "SourcePool Project Code differs from requested Project authority"
            )
        allocated = sum(
            (
                item.allocated_amount_functional
                for item in allocations_by_pool.get(pool.pool_id, ())
            ),
            Decimal(0),
        )
        eligible = _money(pool.eligible_amount_functional)
        if pool.allocation_mode == "DIRECT" and pool.pool_state != "ALLOCATED":
            raise _source_drift("DIRECT SourcePool must be in ALLOCATED state")
        if allocations_by_pool.get(pool.pool_id) and (
            pool.allocation_mode != "MANAGEMENT_ALLOCATION"
        ):
            raise _source_drift(
                "Committed allocation references a non-management SourcePool"
            )
        if eligible >= 0 and not (Decimal(0) <= allocated <= eligible):
            raise _source_drift("Allocation exceeds the positive SourcePool amount")
        if eligible < 0 and not (eligible <= allocated <= Decimal(0)):
            raise _source_drift("Allocation exceeds the negative SourcePool amount")
        if (
            pool.allocation_mode == "MANAGEMENT_ALLOCATION"
            and pool.pool_state == "ALLOCATED"
            and not allocations_by_pool.get(pool.pool_id)
        ):
            raise _source_drift(
                "Allocated SourcePool has no committed allocation evidence"
            )


def _direct_component(pool: ProjectPnlSourcePoolFact) -> ProjectPnlComponentDraft:
    return ProjectPnlComponentDraft(
        classification=_actual_classification(pool, allocated=False),
        source_kind=_source_kind(pool.source_kind),
        functional_amount=_actual_amount(pool, pool.eligible_amount_functional),
        source_ref=f"eos.cost-pool:{pool.pool_id}:direct",
        source_hash=pool.source_hash,
        account_id=pool.account_id,
        data_classification=_data_classification(pool.source_kind),
    )


def _allocation_component(
    pool: ProjectPnlSourcePoolFact,
    allocation: ProjectPnlAllocationFact,
) -> ProjectPnlComponentDraft:
    return ProjectPnlComponentDraft(
        classification=_actual_classification(pool, allocated=True),
        source_kind=_source_kind(pool.source_kind),
        functional_amount=_actual_amount(pool, allocation.allocated_amount_functional),
        source_ref=(
            f"eos.cost-allocation:{allocation.batch_id}:line:{allocation.line_no}"
        ),
        source_hash=allocation.evidence_hash,
        account_id=pool.account_id,
        work_code=allocation.work_code,
        data_classification=_data_classification(pool.source_kind),
    )


def _residual_component(
    pool: ProjectPnlSourcePoolFact,
    residual: Decimal,
    allocated_total: Decimal,
) -> ProjectPnlComponentDraft:
    return ProjectPnlComponentDraft(
        classification=(
            "POSTED_PAYROLL_UNALLOCATED"
            if pool.source_kind == "PAYROLL"
            else "UNALLOCATED"
        ),
        source_kind=_source_kind(pool.source_kind),
        functional_amount=_actual_amount(pool, residual),
        source_ref=f"eos.cost-pool:{pool.pool_id}:residual",
        source_hash=semantic_sha256_hash_ref(
            {
                "domain": "EOS-PROJECT-PNL-RESIDUAL-V1",
                "pool_id": pool.pool_id,
                "source_hash": pool.source_hash,
                "eligible_amount": _amount_text(pool.eligible_amount_functional),
                "allocated_total": _amount_text(allocated_total),
                "residual": _amount_text(residual),
            }
        ),
        account_id=pool.account_id,
        data_classification=_data_classification(pool.source_kind),
    )


def _actual_classification(pool: ProjectPnlSourcePoolFact, *, allocated: bool) -> str:
    if pool.source_kind == "FX_GAIN_LOSS":
        return "FX_REALIZED_GAIN_LOSS"
    if pool.account_category == "REVENUE":
        return "POSTED_REVENUE"
    if allocated and pool.source_kind == "PAYROLL":
        return "POSTED_LABOR_ALLOCATED"
    return "POSTED_ALLOCATED_COST" if allocated else "POSTED_DIRECT_COST"


def _actual_amount(pool: ProjectPnlSourcePoolFact, amount: Decimal) -> Decimal:
    normalized = _money(amount)
    if pool.source_kind == "FX_GAIN_LOSS" and pool.account_category == "EXPENSE":
        return -normalized
    return normalized


def _source_kind(value: str) -> str:
    return "MATERIAL" if value == "PURCHASE" else value


def _data_classification(source_kind: str) -> str:
    return "PAYROLL_SENSITIVE" if source_kind == "PAYROLL" else "CONFIDENTIAL_FINANCIAL"


def _posting_watermark(
    request: ProjectPnlRebuildRequest,
    pools: Sequence[ProjectPnlSourcePoolFact],
) -> str:
    return semantic_sha256_hash_ref(
        {
            "domain": "EOS-PROJECT-PNL-POSTING-WATERMARK-V1",
            "tenant_id": request.tenant_id,
            "company_id": request.company_id,
            "project_id": request.project_id,
            "period_id": request.period_id,
            "as_of": request.as_of.astimezone(UTC).isoformat(),
            "sources": [
                {
                    "pool_id": item.pool_id,
                    "journal_id": item.journal_id,
                    "journal_line_no": item.journal_line_no,
                    "source_hash": item.source_hash,
                    "source_journal_hash": item.source_journal_hash,
                    "pool_state": item.pool_state,
                }
                for item in sorted(pools, key=lambda value: value.pool_id)
            ],
        }
    )


def _allocation_watermark(
    request: ProjectPnlRebuildRequest,
    pools: Sequence[ProjectPnlSourcePoolFact],
    allocations_by_pool: Mapping[str, Sequence[ProjectPnlAllocationFact]],
) -> str:
    rows = [
        item for pool in pools for item in allocations_by_pool.get(pool.pool_id, ())
    ]
    return semantic_sha256_hash_ref(
        {
            "domain": "EOS-PROJECT-PNL-ALLOCATION-WATERMARK-V1",
            "tenant_id": request.tenant_id,
            "company_id": request.company_id,
            "project_id": request.project_id,
            "period_id": request.period_id,
            "as_of": request.as_of.astimezone(UTC).isoformat(),
            "allocations": [
                {
                    "batch_id": item.batch_id,
                    "line_no": item.line_no,
                    "pool_id": item.pool_id,
                    "project_id": item.project_id,
                    "amount": _amount_text(item.allocated_amount_functional),
                    "evidence_hash": item.evidence_hash,
                    "reconciliation_hash": item.reconciliation_hash,
                }
                for item in sorted(
                    rows, key=lambda value: (value.batch_id, value.line_no)
                )
            ],
        }
    )


def _component_sort_key(value: ProjectPnlComponentDraft) -> tuple[str, str, str]:
    return value.classification, value.source_ref, value.source_hash


def _pool_fact(row: Mapping[str, Any]) -> ProjectPnlSourcePoolFact:
    return ProjectPnlSourcePoolFact(
        pool_id=str(row["pool_id"]),
        journal_id=str(row["journal_id"]),
        journal_line_no=int(row["journal_line_no"]),
        source_project_id=str(row["source_project_id"]),
        source_project_code=str(row["source_project_code"]),
        source_kind=str(row["source_kind"]),
        allocation_mode=str(row["allocation_mode"]),
        eligible_amount_functional=_money(row["eligible_amount_functional"]),
        functional_currency=str(row["functional_currency"]),
        account_id=str(row["account_id"]),
        account_category=str(row["account_category"]),
        source_record_ref=str(row["source_record_ref"]),
        source_hash=str(row["source_hash"]),
        source_journal_hash=str(row["source_journal_hash"]),
        pool_state=str(row["pool_state"]),
        recognized_at=_stored_time("recognized_at", row["recognized_at"]),
    )


def _allocation_fact(row: Mapping[str, Any]) -> ProjectPnlAllocationFact:
    return ProjectPnlAllocationFact(
        batch_id=str(row["batch_id"]),
        line_no=int(row["line_no"]),
        pool_id=str(row["pool_id"]),
        project_id=str(row["project_id"]),
        project_code=str(row["project_code"]),
        work_code=str(row["work_code"]) if row["work_code"] is not None else None,
        allocated_amount_functional=_money(row["allocated_amount_functional"]),
        allocation_mode=str(row["allocation_mode"]),
        evidence_hash=str(row["evidence_hash"]),
        reconciliation_hash=str(row["reconciliation_hash"]),
        committed_at=_stored_time("committed_at", row["committed_at"]),
    )


def _aware_time(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _stored_time(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise _source_drift(f"{name} is not a persisted datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(_MONEY)


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise _invalid(f"{name} must be a positive integer")
    return parsed


def _non_negative_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{name} must be non-negative")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be non-negative") from exc
    if parsed < 0:
        raise _invalid(f"{name} must be non-negative")
    return parsed


def _amount_text(value: Any) -> str:
    return format(_money(value), ".4f")


def _invalid(detail: str) -> EosProjectPnlProjectorError:
    return EosProjectPnlProjectorError(
        "PROJECT_PNL_REBUILD_INVALID", detail, status_code=400
    )


def _blocked(detail: str) -> EosProjectPnlProjectorError:
    return EosProjectPnlProjectorError(
        "PROJECT_PNL_REBUILD_BLOCKED", detail, status_code=409
    )


def _source_drift(detail: str) -> EosProjectPnlProjectorError:
    return EosProjectPnlProjectorError(
        "PROJECT_PNL_SOURCE_DRIFT",
        detail,
        status_code=503,
        retryable=True,
    )


def build_eos_project_pnl_projector(
    session_factory: sessionmaker[Session],
    repository: SqlAlchemyEosProjectPnlRepository,
) -> EosProjectPnlProjector:
    return EosProjectPnlProjector(
        source=SqlAlchemyEosProjectPnlProjectionSource(session_factory),
        sink=repository,
    )
