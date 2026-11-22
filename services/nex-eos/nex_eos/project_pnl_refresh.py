from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .allocation_reconciliation import (
    EosAllocationReconciliationError,
    EosAllocationReconciliationService,
)
from .cost_allocations import (
    EOS_COST_ALLOCATION_BATCH_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
)
from .cost_source_pools import EOS_COST_SOURCE_POOL_TABLE
from .project_pnl import (
    EosProjectPnlPersistenceError,
    SqlAlchemyEosProjectPnlRepository,
    build_project_pnl_records,
)
from .project_pnl_projector import (
    EosProjectPnlProjector,
    EosProjectPnlProjectorError,
    ProjectPnlRebuildRequest,
)
from .projects import EOS_PROJECT_TABLE

PROJECT_PNL_REFRESH_OPERATION = "FINANCE.PROJECT_PNL.REFRESH_FROM_ALLOCATION"
PROJECT_PNL_REFRESH_SCHEMA = "eos_project_pnl_refresh_from_allocation.v1"
PROJECT_PNL_REFRESH_SOURCE_SCHEMA = "eos_project_pnl_refresh_source.v1"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PROJECT_ROLES = ("ALLOCATION_TARGET", "SOURCE_PROJECT")


class EosProjectPnlRefreshError(RuntimeError):
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
class ProjectPnlRefreshProject:
    project_id: str
    project_code: str
    project_status: str
    roles: tuple[str, ...]

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_code": self.project_code,
            "project_status": self.project_status,
            "roles": list(self.roles),
        }


@dataclass(frozen=True)
class ProjectPnlRefreshSource:
    tenant_id: str
    company_id: str
    business_operation_id: str
    batch_id: str
    plan_id: str
    plan_revision: int
    period_id: str
    functional_currency: str
    allocation_reconciliation_hash: str
    source_set_hash: str
    committed_at: datetime
    pool_ids: tuple[str, ...]
    affected_projects: tuple[ProjectPnlRefreshProject, ...]
    source_resolution_hash: str

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROJECT_PNL_REFRESH_SOURCE_SCHEMA,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "business_operation_id": self.business_operation_id,
            "batch_id": self.batch_id,
            "plan_id": self.plan_id,
            "plan_revision": self.plan_revision,
            "period_id": self.period_id,
            "functional_currency": self.functional_currency,
            "allocation_reconciliation_hash": self.allocation_reconciliation_hash,
            "source_set_hash": self.source_set_hash,
            "committed_at": _wire_time(self.committed_at),
            "pool_ids": list(self.pool_ids),
            "affected_projects": [
                project.semantic_payload() for project in self.affected_projects
            ],
        }


@dataclass(frozen=True)
class _ProjectRefreshPlan:
    request: ProjectPnlRebuildRequest
    expected_projection_id: str
    expected_projection_hash: str
    existing: Mapping[str, Any] | None


class EosProjectPnlRefreshService:
    """Activate deterministic P&L projections from verified allocation state."""

    def __init__(
        self,
        *,
        resolver: EosAllocationPnlRefreshSourceResolver,
        projector: EosProjectPnlProjector,
        repository: SqlAlchemyEosProjectPnlRepository,
    ) -> None:
        self._resolver = resolver
        self._projector = projector
        self._repository = repository

    def refresh(
        self, *, tenant_id: str, company_id: str, batch_id: str
    ) -> dict[str, Any]:
        source = self._resolver.resolve(
            tenant_id=tenant_id,
            company_id=company_id,
            batch_id=batch_id,
        )
        plans = tuple(
            self._plan(source, project) for project in source.affected_projects
        )
        projections: list[dict[str, Any]] = []
        created = False
        for plan in plans:
            if plan.existing is not None:
                projection = dict(plan.existing)
            else:
                projection, was_created = self._append_or_converge(source, plan)
                created = created or was_created
            self._require_expected_projection(plan, projection)
            projections.append(projection)
        return _refresh_response(
            source,
            projections=tuple(projections),
            disposition="CREATED" if created else "EXACT_REPLAY",
        )

    def _plan(
        self,
        source: ProjectPnlRefreshSource,
        project: ProjectPnlRefreshProject,
    ) -> _ProjectRefreshPlan:
        try:
            boundary = self._repository.list_at_boundary(
                tenant_id=source.tenant_id,
                company_id=source.company_id,
                project_id=project.project_id,
                period_id=source.period_id,
                as_of=source.committed_at,
                limit=2,
            )
            if len(boundary) > 1:
                raise _ordering_conflict(
                    "Multiple Project P&L projections exist at the allocation boundary"
                )
            latest = self._repository.get(
                tenant_id=source.tenant_id,
                company_id=source.company_id,
                project_id=project.project_id,
                period_id=source.period_id,
            )
        except EosProjectPnlPersistenceError as exc:
            raise _map_persistence_error(exc) from exc

        existing = boundary[0] if boundary else None
        if existing is not None:
            version = int(existing["projection_version"])
        else:
            version = 1
            if latest is not None:
                latest_boundary = _parse_wire_time(latest.get("as_of"))
                if latest_boundary >= source.committed_at:
                    raise _ordering_conflict(
                        "A Project P&L projection already occupies or follows the "
                        "allocation boundary"
                    )
                version = int(latest["projection_version"]) + 1

        request = ProjectPnlRebuildRequest(
            tenant_id=source.tenant_id,
            company_id=source.company_id,
            project_id=project.project_id,
            project_code=project.project_code,
            period_id=source.period_id,
            projection_version=version,
            functional_currency=source.functional_currency,
            as_of=source.committed_at,
            evaluated_at=source.committed_at,
        )
        try:
            draft, components = self._projector.preview(request)
            if (
                draft.reconciliation_status != "VERIFIED"
                or draft.freshness_status != "CURRENT"
            ):
                raise _projection_not_ready(draft.reconciliation_status)
            header, _lines = build_project_pnl_records(draft, components)
        except EosProjectPnlRefreshError:
            raise
        except EosProjectPnlProjectorError as exc:
            raise _map_projector_error(exc) from exc
        except EosProjectPnlPersistenceError as exc:
            raise _map_persistence_error(exc) from exc
        plan = _ProjectRefreshPlan(
            request=request,
            expected_projection_id=str(header["projection_id"]),
            expected_projection_hash=str(header["projection_hash"]),
            existing=existing,
        )
        if existing is not None:
            self._require_expected_projection(plan, existing)
        return plan

    def _append_or_converge(
        self,
        source: ProjectPnlRefreshSource,
        plan: _ProjectRefreshPlan,
    ) -> tuple[dict[str, Any], bool]:
        try:
            return self._projector.rebuild(plan.request), True
        except EosProjectPnlProjectorError as exc:
            raise _map_projector_error(exc) from exc
        except EosProjectPnlPersistenceError as exc:
            if exc.status_code != 409:
                raise _map_persistence_error(exc) from exc
        try:
            converged = self._repository.list_at_boundary(
                tenant_id=source.tenant_id,
                company_id=source.company_id,
                project_id=plan.request.project_id,
                period_id=source.period_id,
                as_of=source.committed_at,
                limit=2,
            )
        except EosProjectPnlPersistenceError as exc:
            raise _map_persistence_error(exc) from exc
        if len(converged) != 1:
            raise _ordering_conflict(
                "Concurrent Project P&L refresh did not converge to one result"
            )
        projection = dict(converged[0])
        self._require_expected_projection(plan, projection)
        return projection, False

    @staticmethod
    def _require_expected_projection(
        plan: _ProjectRefreshPlan, projection: Mapping[str, Any]
    ) -> None:
        if (
            projection.get("projection_hash") != plan.expected_projection_hash
            or projection.get("projection_id") != plan.expected_projection_id
            or projection.get("reconciliation_status") != "VERIFIED"
            or projection.get("freshness_status") != "CURRENT"
        ):
            raise _projection_drift(
                "Persisted Project P&L projection differs from the verified "
                "allocation boundary"
            )


class EosAllocationPnlRefreshSourceResolver:
    """Resolve an immutable, verified AllocationBatch into P&L refresh inputs."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        reconciliation: EosAllocationReconciliationService,
    ) -> None:
        self._session_factory = session_factory
        self._reconciliation = reconciliation

    def resolve(
        self, *, tenant_id: str, company_id: str, batch_id: str
    ) -> ProjectPnlRefreshSource:
        tenant_id = _tenant(tenant_id)
        company_id = _uuid("company_id", company_id)
        batch_id = _uuid("batch_id", batch_id)
        verification = self._verify_batch(
            tenant_id=tenant_id,
            company_id=company_id,
            batch_id=batch_id,
        )
        verified_batch = _require_verified_batch(
            verification,
            tenant_id=tenant_id,
            company_id=company_id,
            batch_id=batch_id,
        )
        try:
            with self._session_factory() as session:
                return _resolve_source(
                    session,
                    tenant_id=tenant_id,
                    company_id=company_id,
                    batch_id=batch_id,
                    verification=verification,
                    verified_batch=verified_batch,
                )
        except EosProjectPnlRefreshError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def _verify_batch(
        self, *, tenant_id: str, company_id: str, batch_id: str
    ) -> Mapping[str, Any]:
        try:
            verification = self._reconciliation.verify_batch(
                tenant_id=tenant_id,
                company_id=company_id,
                batch_id=batch_id,
            )
        except EosAllocationReconciliationError as exc:
            if exc.status_code == 404:
                raise _not_found() from exc
            if exc.status_code == 422:
                raise _invalid(exc.detail) from exc
            if exc.status_code >= 500:
                raise _unavailable() from exc
            raise _not_verified() from exc
        if not isinstance(verification, Mapping):
            raise _source_drift("Allocation verification response is malformed")
        return verification


def _resolve_source(
    session: Session,
    *,
    tenant_id: str,
    company_id: str,
    batch_id: str,
    verification: Mapping[str, Any],
    verified_batch: Mapping[str, Any],
) -> ProjectPnlRefreshSource:
    batch = _one(
        session,
        select(EOS_COST_ALLOCATION_BATCH_TABLE).where(
            EOS_COST_ALLOCATION_BATCH_TABLE.c.tenant_id == tenant_id,
            EOS_COST_ALLOCATION_BATCH_TABLE.c.company_id == company_id,
            EOS_COST_ALLOCATION_BATCH_TABLE.c.batch_id == batch_id,
        ),
    )
    if batch is None:
        raise _not_found()
    lines = list(
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
    pool_ids = tuple(sorted({str(line["pool_id"]) for line in lines}))
    pools = list(
        session.execute(
            select(EOS_COST_SOURCE_POOL_TABLE)
            .where(
                EOS_COST_SOURCE_POOL_TABLE.c.tenant_id == tenant_id,
                EOS_COST_SOURCE_POOL_TABLE.c.company_id == company_id,
                EOS_COST_SOURCE_POOL_TABLE.c.pool_id.in_(pool_ids),
            )
            .order_by(EOS_COST_SOURCE_POOL_TABLE.c.pool_id)
        ).mappings()
    )
    _require_batch_lineage(
        batch=batch,
        lines=lines,
        pools=pools,
        pool_ids=pool_ids,
        verification=verification,
        verified_batch=verified_batch,
    )

    roles_by_project: dict[str, set[str]] = defaultdict(set)
    codes_by_project: dict[str, set[str]] = defaultdict(set)
    for line in lines:
        project_id = str(line["project_id"])
        roles_by_project[project_id].add("ALLOCATION_TARGET")
        codes_by_project[project_id].add(str(line["project_code"]))
    for pool in pools:
        project_id = str(pool["source_project_id"])
        roles_by_project[project_id].add("SOURCE_PROJECT")
        codes_by_project[project_id].add(str(pool["source_project_code"]))

    project_ids = tuple(sorted(roles_by_project))
    projects = list(
        session.execute(
            select(EOS_PROJECT_TABLE)
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_TABLE.c.project_id.in_(project_ids),
            )
            .order_by(EOS_PROJECT_TABLE.c.project_id)
        ).mappings()
    )
    if tuple(str(project["project_id"]) for project in projects) != project_ids:
        raise _source_drift("Affected Project authority is incomplete")

    affected_projects: list[ProjectPnlRefreshProject] = []
    for project in projects:
        project_id = str(project["project_id"])
        project_code = str(project["project_code"])
        if codes_by_project[project_id] != {project_code}:
            raise _source_drift("Affected Project code lineage has drifted")
        roles = tuple(
            role for role in _PROJECT_ROLES if role in roles_by_project[project_id]
        )
        affected_projects.append(
            ProjectPnlRefreshProject(
                project_id=project_id,
                project_code=project_code,
                project_status=str(project["status"]),
                roles=roles,
            )
        )

    source = ProjectPnlRefreshSource(
        tenant_id=tenant_id,
        company_id=company_id,
        business_operation_id=str(verification["business_operation_id"]),
        batch_id=batch_id,
        plan_id=str(batch["plan_id"]),
        plan_revision=int(batch["plan_revision"]),
        period_id=str(batch["period_id"]),
        functional_currency=str(batch["functional_currency"]),
        allocation_reconciliation_hash=str(batch["reconciliation_hash"]),
        source_set_hash=str(batch["source_set_hash"]),
        committed_at=_aware_time(batch["committed_at"]),
        pool_ids=pool_ids,
        affected_projects=tuple(affected_projects),
        source_resolution_hash="",
    )
    return replace(
        source,
        source_resolution_hash=semantic_sha256_hash_ref(
            {
                "domain": "EOS-PROJECT-PNL-REFRESH-SOURCE-V1",
                **source.semantic_payload(),
            }
        ),
    )


def _require_verified_batch(
    verification: Mapping[str, Any],
    *,
    tenant_id: str,
    company_id: str,
    batch_id: str,
) -> Mapping[str, Any]:
    batch = verification.get("batch")
    if (
        verification.get("tenant_id") != tenant_id
        or verification.get("commit_state") != "COMMITTED"
        or verification.get("reconciliation_status") != "COMMITTED_CONFIRMED"
        or verification.get("verification_status") != "VERIFIED"
        or verification.get("retry_disposition") != "DO_NOT_RERUN"
        or verification.get("reversed_pool_ids") != []
        or not isinstance(batch, Mapping)
    ):
        raise _not_verified()
    if batch.get("company_id") != company_id or batch.get("batch_id") != batch_id:
        raise _source_drift("Verified AllocationBatch scope has drifted")
    return batch


def _require_batch_lineage(
    *,
    batch: Mapping[str, Any],
    lines: list[Mapping[str, Any]],
    pools: list[Mapping[str, Any]],
    pool_ids: tuple[str, ...],
    verification: Mapping[str, Any],
    verified_batch: Mapping[str, Any],
) -> None:
    if (
        batch["state"] != "COMMITTED"
        or batch["committed_at"] is None
        or not lines
        or int(verified_batch.get("line_count", -1)) != len(lines)
        or int(verified_batch.get("pool_count", -1)) != len(pools)
        or tuple(str(pool["pool_id"]) for pool in pools) != pool_ids
    ):
        raise _source_drift("Verified AllocationBatch lineage is incomplete")
    expected = {
        "plan_id": str(batch["plan_id"]),
        "plan_revision": int(batch["plan_revision"]),
        "period_id": str(batch["period_id"]),
        "source_set_hash": str(batch["source_set_hash"]),
        "functional_currency": str(batch["functional_currency"]),
        "reconciliation_hash": str(batch["reconciliation_hash"]),
        "state": str(batch["state"]),
    }
    if any(verified_batch.get(key) != value for key, value in expected.items()):
        raise _source_drift("Verified AllocationBatch evidence has drifted")
    if str(batch["business_operation_id"]) != str(
        verification["business_operation_id"]
    ):
        raise _source_drift("Allocation BusinessOperation lineage has drifted")
    period_id = str(batch["period_id"])
    currency = str(batch["functional_currency"])
    if any(
        line["status"] != "ALLOCATED"
        or line["allocation_mode"] != "MANAGEMENT_ALLOCATION"
        for line in lines
    ):
        raise _source_drift("AllocationLine state has drifted")
    if any(
        pool["pool_state"] != "ALLOCATED"
        or str(pool["period_id"]) != period_id
        or str(pool["functional_currency"]) != currency
        for pool in pools
    ):
        raise _source_drift("SourcePool refresh authority has drifted")


def _one(session: Session, statement) -> Mapping[str, Any] | None:
    return session.execute(statement).mappings().one_or_none()


def _tenant(value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid("tenant_id has an invalid format")
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _aware_time(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise _source_drift("AllocationBatch committed_at is missing")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _wire_time(value: datetime) -> str:
    return _aware_time(value).isoformat().replace("+00:00", "Z")


def _parse_wire_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise _ordering_conflict("Project P&L projection boundary is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _ordering_conflict(
            "Project P&L projection boundary is malformed"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _refresh_response(
    source: ProjectPnlRefreshSource,
    *,
    projections: tuple[Mapping[str, Any], ...],
    disposition: str,
) -> dict[str, Any]:
    references = [
        {
            "project_id": str(projection["project_id"]),
            "project_code": str(projection["project_code"]),
            "projection_id": str(projection["projection_id"]),
            "projection_version": int(projection["projection_version"]),
            "projection_hash": str(projection["projection_hash"]),
            "reconciliation_status": str(projection["reconciliation_status"]),
            "freshness_status": str(projection["freshness_status"]),
        }
        for projection in sorted(projections, key=lambda item: str(item["project_id"]))
    ]
    semantics = {
        "schema_version": PROJECT_PNL_REFRESH_SCHEMA,
        "operation": PROJECT_PNL_REFRESH_OPERATION,
        "tenant_id": source.tenant_id,
        "company_id": source.company_id,
        "batch_id": source.batch_id,
        "period_id": source.period_id,
        "allocation_reconciliation_hash": source.allocation_reconciliation_hash,
        "projections": references,
    }
    return {
        **semantics,
        "disposition": disposition,
        "refresh_hash": semantic_sha256_hash_ref(
            {"domain": "EOS-PROJECT-PNL-REFRESH-V1", **semantics}
        ),
    }


def _invalid(detail: str) -> EosProjectPnlRefreshError:
    return EosProjectPnlRefreshError(
        "EOS_PROJECT_PNL_REFRESH_INVALID",
        detail,
        status_code=422,
    )


def _not_found() -> EosProjectPnlRefreshError:
    return EosProjectPnlRefreshError(
        "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_FOUND",
        "AllocationBatch was not found in tenant and company scope",
        status_code=404,
    )


def _not_verified() -> EosProjectPnlRefreshError:
    return EosProjectPnlRefreshError(
        "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_VERIFIED",
        "AllocationBatch is not committed, verified, and eligible for refresh",
        status_code=409,
    )


def _source_drift(detail: str) -> EosProjectPnlRefreshError:
    return EosProjectPnlRefreshError(
        "EOS_PROJECT_PNL_REFRESH_SOURCE_DRIFT",
        detail,
        status_code=409,
    )


def _unavailable() -> EosProjectPnlRefreshError:
    return EosProjectPnlRefreshError(
        "EOS_PROJECT_PNL_REFRESH_SOURCE_UNAVAILABLE",
        "Allocation-to-P&L refresh source persistence is unavailable",
        status_code=503,
        retryable=True,
    )


def _ordering_conflict(detail: str) -> EosProjectPnlRefreshError:
    return EosProjectPnlRefreshError(
        "EOS_PROJECT_PNL_REFRESH_ORDERING_CONFLICT",
        detail,
        status_code=409,
    )


def _projection_not_ready(status: str) -> EosProjectPnlRefreshError:
    return EosProjectPnlRefreshError(
        "EOS_PROJECT_PNL_REFRESH_PROJECTION_NOT_READY",
        f"Project P&L projection is not VERIFIED: {status}",
        status_code=409,
    )


def _projection_drift(detail: str) -> EosProjectPnlRefreshError:
    return EosProjectPnlRefreshError(
        "EOS_PROJECT_PNL_REFRESH_PROJECTION_DRIFT",
        detail,
        status_code=409,
    )


def _map_projector_error(
    exc: EosProjectPnlProjectorError,
) -> EosProjectPnlRefreshError:
    if exc.status_code >= 500:
        return EosProjectPnlRefreshError(
            "EOS_PROJECT_PNL_REFRESH_PROJECTOR_UNAVAILABLE",
            "Project P&L projector is unavailable",
            status_code=503,
            retryable=True,
        )
    return _projection_drift(exc.detail)


def _map_persistence_error(
    exc: EosProjectPnlPersistenceError,
) -> EosProjectPnlRefreshError:
    if exc.status_code >= 500:
        return EosProjectPnlRefreshError(
            "EOS_PROJECT_PNL_REFRESH_PROJECTION_UNAVAILABLE",
            "Project P&L projection persistence is unavailable",
            status_code=503,
            retryable=True,
        )
    return _ordering_conflict(exc.detail)
