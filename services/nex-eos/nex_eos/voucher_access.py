from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .project_memberships import EOS_PROJECT_MEMBER_TABLE
from .projects import EOS_PROJECT_TABLE
from .vouchers import EOS_VOUCHER_DRAFT_LINE_TABLE, EOS_VOUCHER_DRAFT_TABLE

EOS_VOUCHER_READ_SCOPE = "finance:voucher-draft:read"
EOS_VOUCHER_AUDIT_SCOPE = "finance:voucher-draft:audit"
EOS_VOUCHER_CREATE_ROLES = frozenset({"OWNER", "MANAGER", "MEMBER"})
EOS_VOUCHER_GET_OPERATION = "FINANCE.VOUCHER_DRAFT.GET"
EOS_VOUCHER_LIST_OPERATION = "FINANCE.VOUCHER_DRAFT.LIST"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")


class EosVoucherAccessError(RuntimeError):
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


class EosVoucherAccessService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        authorization_source: AuthorizationSource,
    ) -> None:
        self._session_factory = session_factory
        self._authorization_source = authorization_source

    def require_create_membership(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
    ) -> str:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        subject_id = _scoped_id("subject_id", subject_id)
        row = (
            session.execute(
                select(
                    EOS_PROJECT_TABLE.c.status.label("project_status"),
                    EOS_PROJECT_MEMBER_TABLE.c.member_role,
                    EOS_PROJECT_MEMBER_TABLE.c.status.label("membership_status"),
                )
                .select_from(EOS_PROJECT_TABLE)
                .join(
                    EOS_PROJECT_MEMBER_TABLE,
                    (EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id)
                    & (
                        EOS_PROJECT_MEMBER_TABLE.c.project_id
                        == EOS_PROJECT_TABLE.c.project_id
                    )
                    & (EOS_PROJECT_MEMBER_TABLE.c.subject_id == subject_id),
                )
                .where(
                    EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_TABLE.c.project_id == project_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or row["project_status"] != "ACTIVE"
            or row["membership_status"] != "ACTIVE"
            or row["member_role"] not in EOS_VOUCHER_CREATE_ROLES
        ):
            raise _membership_denied()
        return str(row["member_role"])

    def get_draft(
        self,
        *,
        tenant_id: str,
        voucher_id: str,
        requester_subject_id: str,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        voucher_id = _uuid("voucher_id", voucher_id)
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        authorization = self._authorize_read(
            tenant_id=tenant_id,
            subject_id=requester,
        )
        statement = self._read_statement(
            tenant_id=tenant_id,
            subject_id=requester,
            auditor=EOS_VOUCHER_AUDIT_SCOPE in authorization["scopes"],
        ).where(EOS_VOUCHER_DRAFT_TABLE.c.voucher_id == voucher_id)
        try:
            with self._session_factory() as session:
                row = session.execute(statement).mappings().one_or_none()
                if row is None:
                    raise _not_found()
                lines = (
                    session.execute(
                        select(EOS_VOUCHER_DRAFT_LINE_TABLE)
                        .where(
                            EOS_VOUCHER_DRAFT_LINE_TABLE.c.tenant_id == tenant_id,
                            EOS_VOUCHER_DRAFT_LINE_TABLE.c.voucher_id == voucher_id,
                        )
                        .order_by(EOS_VOUCHER_DRAFT_LINE_TABLE.c.line_no)
                    )
                    .mappings()
                    .all()
                )
        except EosVoucherAccessError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return {
            "schema_version": "eos_voucher_draft_get.v1",
            "operation_id": EOS_VOUCHER_GET_OPERATION,
            "voucher": _wire_draft(row, lines=lines),
            "authorization_revision_hash": authorization["revision_hash"],
        }

    def list_drafts(
        self,
        *,
        tenant_id: str,
        project_id: str,
        requester_subject_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        limit = _limit(limit)
        offset = _offset(offset)
        authorization = self._authorize_read(
            tenant_id=tenant_id,
            subject_id=requester,
            project_id=project_id,
        )
        statement = (
            self._read_statement(
                tenant_id=tenant_id,
                subject_id=requester,
                auditor=EOS_VOUCHER_AUDIT_SCOPE in authorization["scopes"],
            )
            .where(EOS_VOUCHER_DRAFT_TABLE.c.project_id == project_id)
            .order_by(
                EOS_VOUCHER_DRAFT_TABLE.c.transaction_date.desc(),
                EOS_VOUCHER_DRAFT_TABLE.c.created_at.desc(),
                EOS_VOUCHER_DRAFT_TABLE.c.voucher_id,
            )
            .limit(limit)
            .offset(offset)
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(statement).mappings().all()
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return {
            "schema_version": "eos_voucher_draft_list.v1",
            "operation_id": EOS_VOUCHER_LIST_OPERATION,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "items": [_wire_draft(row) for row in rows],
            "limit": limit,
            "offset": offset,
            "authorization_revision_hash": authorization["revision_hash"],
        }

    @staticmethod
    def _read_statement(*, tenant_id: str, subject_id: str, auditor: bool):
        statement = (
            select(EOS_VOUCHER_DRAFT_TABLE)
            .select_from(EOS_VOUCHER_DRAFT_TABLE)
            .join(
                EOS_PROJECT_TABLE,
                (EOS_PROJECT_TABLE.c.tenant_id == tenant_id)
                & (
                    EOS_PROJECT_TABLE.c.project_id
                    == EOS_VOUCHER_DRAFT_TABLE.c.project_id
                )
                & (EOS_PROJECT_TABLE.c.status == "ACTIVE"),
            )
            .where(EOS_VOUCHER_DRAFT_TABLE.c.tenant_id == tenant_id)
        )
        if not auditor:
            statement = statement.join(
                EOS_PROJECT_MEMBER_TABLE,
                (EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id)
                & (
                    EOS_PROJECT_MEMBER_TABLE.c.project_id
                    == EOS_VOUCHER_DRAFT_TABLE.c.project_id
                )
                & (EOS_PROJECT_MEMBER_TABLE.c.subject_id == subject_id)
                & (EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE"),
            )
        return statement

    def _authorize_read(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _authorization_denied() from exc
        except Exception as exc:
            raise EosVoucherAccessError(
                "EOS_VOUCHER_AUTHORIZATION_UNAVAILABLE",
                "OA effective authorization is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        if (
            not isinstance(value, Mapping)
            or value.get("active") is not True
            or value.get("tenant_id") != tenant_id
            or value.get("subject_id") != subject_id
        ):
            raise _authorization_denied()
        scopes = _string_set(value.get("scopes"))
        if EOS_VOUCHER_READ_SCOPE not in scopes:
            raise _authorization_denied()
        revision_hash = value.get("revision_hash")
        if (
            not isinstance(revision_hash, str)
            or _REVISION_HASH.fullmatch(revision_hash) is None
        ):
            raise _authorization_denied()
        project_ids = value.get("project_ids")
        if (
            project_id is not None
            and project_ids is not None
            and project_id not in _string_set(project_ids)
        ):
            raise _authorization_denied()
        return {"scopes": scopes, "revision_hash": revision_hash}


def _wire_draft(row: Mapping[str, Any], *, lines=()) -> dict[str, Any]:
    value = {
        key: _wire_value(item)
        for key, item in dict(row).items()
        if key
        not in {"requester_ref_type", "requester_id", "source_ref_type", "source_id"}
    }
    value["requester_ref"] = {
        "type": str(row["requester_ref_type"]),
        "id": str(row["requester_id"]),
    }
    if lines:
        value["lines"] = [
            {key: _wire_value(item) for key, item in dict(line).items()}
            for line in lines
        ]
    return value


def _wire_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, ".2f")
    return value


def _string_set(value: object) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _authorization_denied()
    normalized = {item for item in value if isinstance(item, str) and item}
    if len(normalized) != len(value):
        raise _authorization_denied()
    return normalized


def _scoped_id(field: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid(f"{field} has an invalid format")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 100:
        raise _invalid("limit must be between 1 and 100")
    return value


def _offset(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _invalid("offset must be a non-negative integer")
    return value


def _authorization_denied() -> EosVoucherAccessError:
    return EosVoucherAccessError(
        "EOS_VOUCHER_AUTHORIZATION_DENIED",
        "Current Voucher read authorization was denied",
        status_code=403,
    )


def _membership_denied() -> EosVoucherAccessError:
    return EosVoucherAccessError(
        "EOS_VOUCHER_PROJECT_MEMBERSHIP_REQUIRED",
        "An admitted active Project membership is required",
        status_code=403,
    )


def _not_found() -> EosVoucherAccessError:
    return EosVoucherAccessError(
        "EOS_VOUCHER_NOT_FOUND",
        "Voucher Draft was not found in the admitted tenant and Project scope",
        status_code=404,
    )


def _invalid(detail: str) -> EosVoucherAccessError:
    return EosVoucherAccessError("EOS_VOUCHER_ACCESS_INVALID", detail, status_code=422)


def _unavailable() -> EosVoucherAccessError:
    return EosVoucherAccessError(
        "EOS_VOUCHER_QUERY_UNAVAILABLE",
        "Voucher Draft query persistence is unavailable",
        status_code=503,
        retryable=True,
    )
