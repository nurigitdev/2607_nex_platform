from __future__ import annotations

import re
import uuid
from typing import Any

from .project_authorization import (
    EosProjectAuthorizationError,
    EosProjectAuthorizationGate,
)
from .project_pnl import (
    EosProjectPnlPersistenceError,
    SqlAlchemyEosProjectPnlRepository,
)

PROJECT_PNL_READ_ACTION = "finance:report:read"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")


class EosProjectPnlQueryError(RuntimeError):
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


class EosProjectPnlQueryService:
    """Reads immutable P&L projections behind a fresh Project decision."""

    def __init__(
        self,
        *,
        repository: SqlAlchemyEosProjectPnlRepository,
        project_authorizer: EosProjectAuthorizationGate,
    ) -> None:
        self._repository = repository
        self._project_authorizer = project_authorizer

    def get(
        self,
        *,
        tenant_id: str,
        company_id: str,
        project_id: str,
        period_id: str,
        requester_subject_id: str,
        correlation_id: str,
        projection_version: int | None = None,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id, limit=128)
        company_id = _uuid("company_id", company_id)
        project_id = _uuid("project_id", project_id)
        period_id = _uuid("period_id", period_id)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id, limit=128
        )
        correlation_id = _scoped_id("correlation_id", correlation_id, limit=128)
        if projection_version is not None:
            projection_version = _positive_int("projection_version", projection_version)
        try:
            evidence = self._project_authorizer.authorize(
                tenant_id=tenant_id,
                subject_id=requester_subject_id,
                project_id=project_id,
                action=PROJECT_PNL_READ_ACTION,
                correlation_id=correlation_id,
            )
        except EosProjectAuthorizationError as exc:
            raise EosProjectPnlQueryError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        try:
            projection = self._repository.get(
                tenant_id=tenant_id,
                company_id=company_id,
                project_id=project_id,
                period_id=period_id,
                projection_version=projection_version,
            )
        except EosProjectPnlPersistenceError as exc:
            raise EosProjectPnlQueryError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
            ) from exc
        if projection is None:
            raise EosProjectPnlQueryError(
                "PROJECT_PNL_QUERY_NOT_FOUND",
                "Project P&L projection was not found in the authorized scope",
                status_code=404,
            )
        if (
            projection.get("tenant_id") != tenant_id
            or projection.get("company_id") != company_id
            or projection.get("project_id") != project_id
            or projection.get("period_id") != period_id
            or projection.get("project_code") != evidence.project_code
        ):
            raise EosProjectPnlQueryError(
                "PROJECT_PNL_QUERY_BINDING_DRIFT",
                "Project P&L projection differs from the authorized query scope",
                status_code=503,
                retryable=True,
            )
        return projection


def _scoped_id(name: str, value: Any, *, limit: int) -> str:
    text = str(value).strip()
    if len(text) > limit or not _SCOPED_ID.fullmatch(text):
        raise _invalid(name, f"must contain 1..{limit} scoped characters")
    return text


def _uuid(name: str, value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(name, "must be a UUID") from exc


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _invalid(name, "must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(name, "must be a positive integer") from exc
    if parsed <= 0:
        raise _invalid(name, "must be a positive integer")
    return parsed


def _invalid(name: str, detail: str) -> EosProjectPnlQueryError:
    return EosProjectPnlQueryError(
        "PROJECT_PNL_QUERY_INVALID_ARGUMENT",
        f"{name} {detail}",
        status_code=400,
    )
