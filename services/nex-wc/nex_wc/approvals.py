from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_wc.authorization import (
    AuthorizationSource,
    AuthorizationSubjectDenied,
    require_active_scope,
)

APPROVAL_DOMAINS = frozenset({"AGENT_FORMAL", "NSL_WRITE", "BUSINESS_FORMAL"})
APPROVAL_STATES = frozenset(
    {"PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED"}
)
APPROVAL_PROVIDERS = {
    "AGENT_FORMAL": "AGENT",
    "NSL_WRITE": "NSL",
    "BUSINESS_FORMAL": "EOS",
}

_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "approval_work_item_id",
        "approval_domain",
        "source_ref",
        "semantic_hash",
        "title",
        "display_safe_summary",
        "approval_provider_type",
        "approval_target_ref",
        "resume_target_ref",
        "state",
        "created_at",
        "version",
    }
)
_OPTIONAL_FIELDS = frozenset(
    {
        "target_approver_ref",
        "target_role_ref",
        "target_org_scope_ref",
        "target_project_scope_ref",
        "agent_execution_id",
        "executable_step_id",
        "nsl_execution_id",
        "business_operation_id",
        "approval_request_id",
        "protected_request_ref",
        "expires_at",
    }
)
_DOMAIN_BINDINGS = {
    "NSL_WRITE": frozenset(
        {
            "agent_execution_id",
            "executable_step_id",
            "nsl_execution_id",
            "business_operation_id",
            "approval_request_id",
            "protected_request_ref",
        }
    ),
    "AGENT_FORMAL": frozenset(
        {
            "agent_execution_id",
            "executable_step_id",
            "business_operation_id",
            "protected_request_ref",
        }
    ),
    "BUSINESS_FORMAL": frozenset(
        {"business_operation_id", "protected_request_ref"}
    ),
}


@dataclass(frozen=True)
class ApprovalWorkItemError(Exception):
    error_code: str
    detail: str
    status_code: int = 400
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ApprovalDecisionAuthorizationError(Exception):
    error_code: str
    detail: str
    status_code: int
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class ApprovalWorkItemRepository(Protocol):
    def insert(self, work_item: Mapping[str, Any]) -> dict[str, Any]: ...

    def create_or_get(
        self, work_item: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]: ...

    def get(
        self, *, tenant_id: str, approval_work_item_id: str
    ) -> dict[str, Any] | None: ...

    def get_by_source(
        self, *, tenant_id: str, approval_domain: str, source_ref: str
    ) -> dict[str, Any] | None: ...


class InMemoryApprovalWorkItemRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self._source_keys: set[tuple[str, str, str]] = set()
        self._lock = RLock()

    def insert(self, work_item: Mapping[str, Any]) -> dict[str, Any]:
        record = validate_approval_work_item(work_item)
        key = (record["tenant_id"], record["approval_work_item_id"])
        source_key = (
            record["tenant_id"],
            record["approval_domain"],
            record["source_ref"],
        )
        with self._lock:
            if key in self._records or source_key in self._source_keys:
                raise _conflict()
            self._records[key] = copy.deepcopy(record)
            self._source_keys.add(source_key)
            return copy.deepcopy(record)

    def create_or_get(
        self, work_item: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        record = validate_approval_work_item(work_item)
        key = (record["tenant_id"], record["approval_work_item_id"])
        source_key = (
            record["tenant_id"],
            record["approval_domain"],
            record["source_ref"],
        )
        with self._lock:
            for existing in self._records.values():
                if (
                    existing["tenant_id"],
                    existing["approval_domain"],
                    existing["source_ref"],
                ) == source_key:
                    _require_same_semantics(existing, record)
                    return copy.deepcopy(existing), False
            if key in self._records:
                raise _conflict()
            self._records[key] = copy.deepcopy(record)
            self._source_keys.add(source_key)
            return copy.deepcopy(record), True

    def get(
        self, *, tenant_id: str, approval_work_item_id: str
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get((tenant_id, approval_work_item_id))
            return None if record is None else copy.deepcopy(record)

    def get_by_source(
        self, *, tenant_id: str, approval_domain: str, source_ref: str
    ) -> dict[str, Any] | None:
        with self._lock:
            for record in self._records.values():
                if (
                    record["tenant_id"] == tenant_id
                    and record["approval_domain"] == approval_domain
                    and record["source_ref"] == source_ref
                ):
                    return copy.deepcopy(record)
            return None


class SqlAlchemyApprovalWorkItemRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def insert(self, work_item: Mapping[str, Any]) -> dict[str, Any]:
        record = validate_approval_work_item(work_item)
        params = {field: record.get(field) for field in _REQUIRED_FIELDS | _OPTIONAL_FIELDS}
        try:
            with self._session_factory() as session:
                session.execute(text(_INSERT_SQL), params)
                saved = _load(
                    session,
                    tenant_id=record["tenant_id"],
                    approval_work_item_id=record["approval_work_item_id"],
                )
                if saved is None:
                    raise ApprovalWorkItemError(
                        "wc.approval_work_item_write_conflict",
                        "ApprovalWorkItem could not be reloaded after insertion.",
                        409,
                        True,
                    )
                session.commit()
                return saved
        except ApprovalWorkItemError:
            raise
        except IntegrityError as exc:
            raise _conflict() from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def create_or_get(
        self, work_item: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        record = validate_approval_work_item(work_item)
        params = {field: record.get(field) for field in _REQUIRED_FIELDS | _OPTIONAL_FIELDS}
        try:
            with self._session_factory() as session:
                inserted = session.execute(text(_INSERT_BY_SOURCE_SQL), params)
                saved = _load_by_source(
                    session,
                    tenant_id=record["tenant_id"],
                    approval_domain=record["approval_domain"],
                    source_ref=record["source_ref"],
                )
                if saved is None:
                    raise ApprovalWorkItemError(
                        "wc.approval_work_item_write_conflict",
                        "ApprovalWorkItem could not be resolved after creation.",
                        409,
                        True,
                    )
                created = int(inserted.rowcount or 0) == 1
                if not created:
                    _require_same_semantics(saved, record)
                session.commit()
                return saved, created
        except ApprovalWorkItemError:
            raise
        except IntegrityError as exc:
            raise _conflict() from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(
        self, *, tenant_id: str, approval_work_item_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load(
                    session,
                    tenant_id=tenant_id,
                    approval_work_item_id=approval_work_item_id,
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_by_source(
        self, *, tenant_id: str, approval_domain: str, source_ref: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_by_source(
                    session,
                    tenant_id=tenant_id,
                    approval_domain=approval_domain,
                    source_ref=source_ref,
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


class ApprovalWorkItemService:
    def __init__(self, repository: ApprovalWorkItemRepository) -> None:
        self._repository = repository

    def create_or_get(self, work_item: Mapping[str, Any]) -> dict[str, Any]:
        saved, created = self._repository.create_or_get(work_item)
        return {"work_item": saved, "created": created}


class ApprovalDecisionAuthorizer:
    def __init__(
        self,
        authorization_source: AuthorizationSource,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._authorization_source = authorization_source
        self._clock = clock or (lambda: datetime.now(UTC))

    def authorize(
        self, *, work_item: Mapping[str, Any], decided_by: str
    ) -> dict[str, Any]:
        item = validate_approval_work_item(work_item)
        principal = _scoped("decided_by", decided_by)
        try:
            authorization = self._authorization_source.effective_authorization(
                tenant_id=item["tenant_id"], subject_id=principal
            )
        except AuthorizationSubjectDenied as exc:
            raise _authorization_denied(
                "OA denied the approval decision principal."
            ) from exc
        except Exception as exc:
            raise ApprovalDecisionAuthorizationError(
                "wc.approval_authorization_unavailable",
                "OA effective authorization is unavailable.",
                503,
                True,
            ) from exc
        try:
            revision_hash = require_active_scope(
                authorization, required_scope="approval:decide"
            )
            _require_authorization_identity(
                authorization,
                tenant_id=item["tenant_id"],
                principal=principal,
            )
            _require_target_compatibility(item, authorization, principal=principal)
            revision_hash_ref = _authorization_hash_ref(revision_hash)
            decision_ref = _authorization_decision_ref(
                authorization, revision_hash_ref=revision_hash_ref
            )
        except AuthorizationSubjectDenied as exc:
            raise _authorization_denied(str(exc)) from exc
        return {
            "authorized_by_oa": True,
            "decided_by": principal,
            "oa_decision_ref": decision_ref,
            "authorization_revision_hash": revision_hash_ref,
            "authorization_checked_at": _timestamp(
                "authorization_checked_at", self._clock()
            ),
        }


def validate_approval_work_item(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("ApprovalWorkItem must be an object.")
    record = copy.deepcopy(dict(value))
    fields = set(record)
    missing = _REQUIRED_FIELDS - fields
    unknown = fields - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
    if missing:
        raise _invalid(f"Missing ApprovalWorkItem field: {min(missing)}.")
    if unknown:
        raise _invalid(f"Unsupported ApprovalWorkItem field: {min(unknown)}.")
    if record["schema_version"] != "wc_approval_work_item.v1":
        raise _invalid("ApprovalWorkItem schema_version is invalid.")

    record["tenant_id"] = _scoped("tenant_id", record["tenant_id"])
    record["approval_work_item_id"] = _uuid(
        "approval_work_item_id", record["approval_work_item_id"]
    )
    domain = str(record["approval_domain"])
    if domain not in APPROVAL_DOMAINS:
        raise _invalid("ApprovalWorkItem approval_domain is invalid.")
    record["approval_domain"] = domain
    if record["approval_provider_type"] != APPROVAL_PROVIDERS[domain]:
        raise _invalid("ApprovalWorkItem provider does not match approval_domain.")

    record["source_ref"] = _bounded("source_ref", record["source_ref"], 256)
    record["approval_target_ref"] = _bounded(
        "approval_target_ref", record["approval_target_ref"], 256
    )
    record["resume_target_ref"] = _bounded(
        "resume_target_ref", record["resume_target_ref"], 256
    )
    record["title"] = _bounded("title", record["title"], 300)
    record["display_safe_summary"] = _bounded(
        "display_safe_summary", record["display_safe_summary"], 2000
    )
    if not isinstance(record["semantic_hash"], str) or not _HASH_REF.fullmatch(
        record["semantic_hash"]
    ):
        raise _invalid("ApprovalWorkItem semantic_hash is invalid.")

    for field in _OPTIONAL_FIELDS - {"expires_at"}:
        if record.get(field) is not None:
            record[field] = _scoped(field, record[field])
    for field in _DOMAIN_BINDINGS[domain]:
        if record.get(field) is None:
            raise _invalid(f"{domain} requires {field}.")

    state = str(record["state"])
    if state not in APPROVAL_STATES:
        raise _invalid("ApprovalWorkItem state is invalid.")
    record["state"] = state
    record["created_at"] = _timestamp("created_at", record["created_at"])
    if record.get("expires_at") is not None:
        record["expires_at"] = _timestamp("expires_at", record["expires_at"])
        if _as_datetime(record["expires_at"]) <= _as_datetime(record["created_at"]):
            raise _invalid("ApprovalWorkItem expires_at must follow created_at.")
    version = record["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _invalid("ApprovalWorkItem version is invalid.")
    return record


def _load(
    session: Session, *, tenant_id: str, approval_work_item_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_SELECT_SQL),
            {
                "tenant_id": tenant_id,
                "approval_work_item_id": approval_work_item_id,
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    stored_fields = (_REQUIRED_FIELDS - {"schema_version"}) | _OPTIONAL_FIELDS
    record = {field: row[field] for field in stored_fields}
    record["schema_version"] = "wc_approval_work_item.v1"
    record["approval_work_item_id"] = str(record["approval_work_item_id"])
    record["created_at"] = _timestamp("created_at", record["created_at"])
    if record["expires_at"] is not None:
        record["expires_at"] = _timestamp("expires_at", record["expires_at"])
    return validate_approval_work_item(record)


def _load_by_source(
    session: Session, *, tenant_id: str, approval_domain: str, source_ref: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_SELECT_BY_SOURCE_SQL),
            {
                "tenant_id": tenant_id,
                "approval_domain": approval_domain,
                "source_ref": source_ref,
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    stored_fields = (_REQUIRED_FIELDS - {"schema_version"}) | _OPTIONAL_FIELDS
    record = {field: row[field] for field in stored_fields}
    record["schema_version"] = "wc_approval_work_item.v1"
    record["approval_work_item_id"] = str(record["approval_work_item_id"])
    record["created_at"] = _timestamp("created_at", record["created_at"])
    if record["expires_at"] is not None:
        record["expires_at"] = _timestamp("expires_at", record["expires_at"])
    return validate_approval_work_item(record)


def _require_same_semantics(
    existing: Mapping[str, Any], candidate: Mapping[str, Any]
) -> None:
    ignored = {"approval_work_item_id", "created_at", "state", "version"}
    existing_projection = {
        field: value for field, value in existing.items() if field not in ignored
    }
    candidate_projection = {
        field: value for field, value in candidate.items() if field not in ignored
    }
    if existing_projection != candidate_projection:
        raise ApprovalWorkItemError(
            "wc.approval_work_item_idempotency_conflict",
            "Approval source identity already exists with different semantics.",
            409,
        )


def _require_authorization_identity(
    authorization: Mapping[str, Any], *, tenant_id: str, principal: str
) -> None:
    if (
        authorization.get("tenant_id") != tenant_id
        or authorization.get("subject_id") != principal
    ):
        raise AuthorizationSubjectDenied(
            "OA authorization identity does not match the decision principal."
        )


def _require_target_compatibility(
    work_item: Mapping[str, Any],
    authorization: Mapping[str, Any],
    *,
    principal: str,
) -> None:
    target_principal = work_item.get("target_approver_ref")
    if target_principal is not None:
        if target_principal != principal:
            raise AuthorizationSubjectDenied(
                "Decision principal does not match target_approver_ref."
            )
        return

    target_sets = (
        ("target_role_ref", "roles"),
        ("target_org_scope_ref", "org_scope_refs"),
        ("target_project_scope_ref", "project_scope_refs"),
    )
    configured = False
    for target_field, authorization_field in target_sets:
        target = work_item.get(target_field)
        if target is None:
            continue
        configured = True
        granted = authorization.get(authorization_field)
        if (
            not isinstance(granted, (list, tuple))
            or target not in granted
        ):
            raise AuthorizationSubjectDenied(
                f"Decision principal does not match {target_field}."
            )
    if not configured:
        raise AuthorizationSubjectDenied(
            "ApprovalWorkItem has no decision target."
        )


def _authorization_hash_ref(revision_hash: str) -> str:
    value = revision_hash.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return f"sha256:{value}"
    if _HASH_REF.fullmatch(value):
        return value
    raise AuthorizationSubjectDenied("OA authorization revision hash is malformed.")


def _authorization_decision_ref(
    authorization: Mapping[str, Any], *, revision_hash_ref: str
) -> str:
    supplied = authorization.get("decision_ref")
    if supplied is not None:
        try:
            return _scoped("oa_decision_ref", supplied)
        except ApprovalWorkItemError as exc:
            raise AuthorizationSubjectDenied(
                "OA authorization decision reference is malformed."
            ) from exc
    return f"oa-authz:{revision_hash_ref.removeprefix('sha256:')}"


def _authorization_denied(detail: str) -> ApprovalDecisionAuthorizationError:
    return ApprovalDecisionAuthorizationError(
        "wc.approval_authorization_denied",
        detail,
        403,
    )


def _invalid(detail: str) -> ApprovalWorkItemError:
    return ApprovalWorkItemError("wc.approval_work_item_invalid", detail)


def _conflict() -> ApprovalWorkItemError:
    return ApprovalWorkItemError(
        "wc.approval_work_item_conflict",
        "ApprovalWorkItem identity or source identity already exists.",
        409,
    )


def _unavailable() -> ApprovalWorkItemError:
    return ApprovalWorkItemError(
        "wc.approval_work_item_store_unavailable",
        "WC approval persistence is unavailable.",
        503,
        True,
    )


def _bounded(field: str, value: Any, maximum: int) -> str:
    text_value = str(value).strip()
    if not text_value or len(text_value) > maximum:
        raise _invalid(f"ApprovalWorkItem {field} is invalid.")
    return text_value


def _scoped(field: str, value: Any) -> str:
    text_value = str(value).strip()
    if not _SCOPED_ID.fullmatch(text_value):
        raise _invalid(f"ApprovalWorkItem {field} is invalid.")
    return text_value


def _uuid(field: str, value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"ApprovalWorkItem {field} must be a UUID.") from exc


def _timestamp(field: str, value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise _invalid(f"ApprovalWorkItem {field} must include a timezone.")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    text_value = str(value).strip()
    try:
        parsed = _as_datetime(text_value)
    except ValueError as exc:
        raise _invalid(f"ApprovalWorkItem {field} is invalid.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"ApprovalWorkItem {field} must include a timezone.")
    return text_value


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


_INSERT_SQL = """
INSERT INTO wc_approval_work_item (
    tenant_id, approval_work_item_id, approval_domain, source_ref,
    semantic_hash, title, display_safe_summary, approval_provider_type,
    approval_target_ref, target_approver_ref, target_role_ref,
    target_org_scope_ref, target_project_scope_ref, agent_execution_id,
    executable_step_id, nsl_execution_id, business_operation_id,
    approval_request_id, protected_request_ref, resume_target_ref, state,
    created_at, expires_at, version
) VALUES (
    :tenant_id, :approval_work_item_id, :approval_domain, :source_ref,
    :semantic_hash, :title, :display_safe_summary, :approval_provider_type,
    :approval_target_ref, :target_approver_ref, :target_role_ref,
    :target_org_scope_ref, :target_project_scope_ref, :agent_execution_id,
    :executable_step_id, :nsl_execution_id, :business_operation_id,
    :approval_request_id, :protected_request_ref, :resume_target_ref, :state,
    :created_at, :expires_at, :version
)
"""

_INSERT_BY_SOURCE_SQL = _INSERT_SQL + """
ON CONFLICT (tenant_id, approval_domain, source_ref) DO NOTHING
"""

_SELECT_SQL = """
SELECT tenant_id, approval_work_item_id, approval_domain, source_ref,
       semantic_hash, title, display_safe_summary, approval_provider_type,
       approval_target_ref, target_approver_ref, target_role_ref,
       target_org_scope_ref, target_project_scope_ref, agent_execution_id,
       executable_step_id, nsl_execution_id, business_operation_id,
       approval_request_id, protected_request_ref, resume_target_ref, state,
       created_at, expires_at, version
FROM wc_approval_work_item
WHERE tenant_id = :tenant_id
  AND approval_work_item_id = :approval_work_item_id
"""

_SELECT_BY_SOURCE_SQL = """
SELECT tenant_id, approval_work_item_id, approval_domain, source_ref,
       semantic_hash, title, display_safe_summary, approval_provider_type,
       approval_target_ref, target_approver_ref, target_role_ref,
       target_org_scope_ref, target_project_scope_ref, agent_execution_id,
       executable_step_id, nsl_execution_id, business_operation_id,
       approval_request_id, protected_request_ref, resume_target_ref, state,
       created_at, expires_at, version
FROM wc_approval_work_item
WHERE tenant_id = :tenant_id
  AND approval_domain = :approval_domain
  AND source_ref = :source_ref
"""
