from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol
from uuid import UUID, uuid4

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
APPROVAL_INBOX_SCAN_LIMIT = 1000

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


@dataclass(frozen=True)
class ApprovalDecisionError(Exception):
    error_code: str
    detail: str
    status_code: int = 400
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ApprovalInboxError(Exception):
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

    def list_pending_work_items(
        self, *, tenant_id: str, limit: int
    ) -> Sequence[Mapping[str, Any]]: ...

    def commit_decision(
        self,
        *,
        decision: Mapping[str, Any],
        outbox: Mapping[str, Any],
        expected_version: int,
    ) -> tuple[dict[str, Any], bool]: ...

    def get_decision(
        self, *, tenant_id: str, approval_work_item_id: str
    ) -> dict[str, Any] | None: ...

    def list_pending_approval_events(
        self, *, limit: int
    ) -> Sequence[Mapping[str, Any]]: ...


class InMemoryApprovalWorkItemRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self._source_keys: set[tuple[str, str, str]] = set()
        self._decisions: dict[tuple[str, str], dict[str, Any]] = {}
        self._outbox: dict[tuple[str, str], dict[str, Any]] = {}
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

    def list_pending_work_items(
        self, *, tenant_id: str, limit: int
    ) -> Sequence[Mapping[str, Any]]:
        admitted_limit = _approval_inbox_scan_limit(limit)
        with self._lock:
            rows = sorted(
                (
                    copy.deepcopy(record)
                    for record in self._records.values()
                    if record["tenant_id"] == tenant_id
                    and record["state"] == "PENDING"
                ),
                key=lambda record: (
                    record["created_at"],
                    record["approval_work_item_id"],
                ),
            )
            return rows[:admitted_limit]

    def commit_decision(
        self,
        *,
        decision: Mapping[str, Any],
        outbox: Mapping[str, Any],
        expected_version: int,
    ) -> tuple[dict[str, Any], bool]:
        record = validate_approval_decision(decision)
        event_record = validate_approval_outbox(outbox, decision=record)
        key = (record["tenant_id"], record["approval_work_item_id"])
        with self._lock:
            item = self._records.get(key)
            if item is None:
                raise _decision_not_found()
            existing = self._decisions.get(key)
            if existing is not None:
                _require_same_decision(existing, record)
                return copy.deepcopy(existing), False
            _require_pending_version(item, expected_version=expected_version)
            outbox_key = (record["tenant_id"], event_record["outbox_id"])
            if outbox_key in self._outbox or any(
                existing_event["event_id"] == event_record["event_id"]
                and existing_event["tenant_id"] == record["tenant_id"]
                for existing_event in self._outbox.values()
            ):
                raise _decision_conflict(
                    "Approval outbox identity already exists."
                )
            self._decisions[key] = copy.deepcopy(record)
            self._outbox[outbox_key] = copy.deepcopy(event_record)
            item["state"] = _terminal_state(record["decision"])
            item["version"] = expected_version + 1
            return copy.deepcopy(record), True

    def get_decision(
        self, *, tenant_id: str, approval_work_item_id: str
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self._decisions.get((tenant_id, approval_work_item_id))
            return None if record is None else copy.deepcopy(record)

    def list_pending_approval_events(
        self, *, limit: int
    ) -> Sequence[Mapping[str, Any]]:
        admitted_limit = _outbox_limit(limit)
        with self._lock:
            rows = sorted(
                (
                    copy.deepcopy(record)
                    for record in self._outbox.values()
                    if record["delivery_state"] == "PENDING"
                ),
                key=lambda record: (record["created_at"], record["outbox_id"]),
            )
            return rows[:admitted_limit]


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

    def list_pending_work_items(
        self, *, tenant_id: str, limit: int
    ) -> Sequence[Mapping[str, Any]]:
        admitted_tenant = _scoped("tenant_id", tenant_id)
        admitted_limit = _approval_inbox_scan_limit(limit)
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(_SELECT_PENDING_WORK_ITEMS_SQL),
                        {
                            "tenant_id": admitted_tenant,
                            "limit": admitted_limit,
                        },
                    )
                    .mappings()
                    .all()
                )
                return [_work_item_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def commit_decision(
        self,
        *,
        decision: Mapping[str, Any],
        outbox: Mapping[str, Any],
        expected_version: int,
    ) -> tuple[dict[str, Any], bool]:
        record = validate_approval_decision(decision)
        event_record = validate_approval_outbox(outbox, decision=record)
        try:
            with self._session_factory() as session:
                item = _load_for_decision(
                    session,
                    tenant_id=record["tenant_id"],
                    approval_work_item_id=record["approval_work_item_id"],
                )
                if item is None:
                    raise _decision_not_found()
                existing = _load_decision(
                    session,
                    tenant_id=record["tenant_id"],
                    approval_work_item_id=record["approval_work_item_id"],
                )
                if existing is not None:
                    _require_same_decision(existing, record)
                    session.commit()
                    return existing, False
                _require_pending_version(item, expected_version=expected_version)
                session.execute(text(_DECISION_INSERT_SQL), record)
                params = {
                    **event_record,
                    "event_payload": json.dumps(
                        event_record["event_payload"],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
                session.execute(text(_APPROVAL_OUTBOX_INSERT_SQL), params)
                updated = session.execute(
                    text(_WORK_ITEM_DECISION_UPDATE_SQL),
                    {
                        "tenant_id": record["tenant_id"],
                        "approval_work_item_id": record["approval_work_item_id"],
                        "expected_version": expected_version,
                        "next_version": expected_version + 1,
                        "terminal_state": _terminal_state(record["decision"]),
                    },
                )
                if int(updated.rowcount or 0) != 1:
                    raise _decision_conflict(
                        "ApprovalWorkItem changed before decision commit."
                    )
                session.commit()
                return record, True
        except ApprovalDecisionError:
            raise
        except IntegrityError as exc:
            raise _decision_conflict(
                "Approval decision identity or version already exists."
            ) from exc
        except SQLAlchemyError as exc:
            raise _decision_unavailable() from exc

    def get_decision(
        self, *, tenant_id: str, approval_work_item_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_decision(
                    session,
                    tenant_id=tenant_id,
                    approval_work_item_id=approval_work_item_id,
                )
        except SQLAlchemyError as exc:
            raise _decision_unavailable() from exc

    def list_pending_approval_events(
        self, *, limit: int
    ) -> Sequence[Mapping[str, Any]]:
        admitted_limit = _outbox_limit(limit)
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(_APPROVAL_OUTBOX_PENDING_SQL),
                        {"limit": admitted_limit},
                    )
                    .mappings()
                    .all()
                )
                return [_outbox_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _decision_unavailable() from exc


class ApprovalWorkItemService:
    def __init__(self, repository: ApprovalWorkItemRepository) -> None:
        self._repository = repository

    def create_or_get(self, work_item: Mapping[str, Any]) -> dict[str, Any]:
        saved, created = self._repository.create_or_get(work_item)
        return {"work_item": saved, "created": created}


class ApprovalInboxService:
    def __init__(
        self,
        repository: ApprovalWorkItemRepository,
        *,
        authorization_source: AuthorizationSource,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source
        self._clock = clock or (lambda: datetime.now(UTC))

    def list_pending(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        try:
            admitted_tenant = _scoped("tenant_id", tenant_id)
            admitted_subject = _scoped("subject_id", subject_id)
            admitted_limit = _approval_inbox_limit(limit)
        except ApprovalWorkItemError as exc:
            raise _inbox_invalid(exc.detail) from exc

        try:
            authorization = self._authorization_source.effective_authorization(
                tenant_id=admitted_tenant,
                subject_id=admitted_subject,
            )
        except AuthorizationSubjectDenied as exc:
            raise _inbox_denied("OA denied the approval inbox principal.") from exc
        except Exception as exc:
            raise _inbox_unavailable("OA effective authorization is unavailable.") from exc

        try:
            require_active_scope(authorization, required_scope="approval:read")
            _require_authorization_identity(
                authorization,
                tenant_id=admitted_tenant,
                principal=admitted_subject,
            )
        except AuthorizationSubjectDenied as exc:
            raise _inbox_denied(str(exc)) from exc

        try:
            candidates = self._repository.list_pending_work_items(
                tenant_id=admitted_tenant,
                limit=APPROVAL_INBOX_SCAN_LIMIT,
            )
        except ApprovalWorkItemError as exc:
            if exc.status_code == 503:
                raise _inbox_unavailable(
                    "WC approval persistence is unavailable."
                ) from exc
            raise

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise _inbox_unavailable("WC approval inbox clock is invalid.")
        effective_now = now.astimezone(UTC)
        gates: list[dict[str, Any]] = []
        for candidate in candidates:
            item = validate_approval_work_item(candidate)
            if item.get("expires_at") is not None and _as_datetime(
                item["expires_at"]
            ) <= effective_now:
                continue
            try:
                _require_target_compatibility(
                    item,
                    authorization,
                    principal=admitted_subject,
                )
            except AuthorizationSubjectDenied:
                continue
            gates.append(_human_gate_view(item))
            if len(gates) == admitted_limit:
                break

        return {
            "schema_version": "wc_approval_inbox.v1",
            "tenant_id": admitted_tenant,
            "subject_ref": {"type": "oa.user", "id": admitted_subject},
            "gates": gates,
            "returned_count": len(gates),
            "limit": admitted_limit,
            "scan_truncated": len(candidates) == APPROVAL_INBOX_SCAN_LIMIT,
        }


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


class ApprovalDecisionService:
    def __init__(
        self,
        repository: ApprovalWorkItemRepository,
        *,
        authorizer: ApprovalDecisionAuthorizer,
        id_factory: Callable[[], str] | None = None,
        event_id_factory: Callable[[], str] | None = None,
        outbox_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._authorizer = authorizer
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._event_id_factory = event_id_factory or (lambda: str(uuid4()))
        self._outbox_id_factory = outbox_id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    def decide(
        self,
        *,
        tenant_id: str,
        approval_work_item_id: str,
        decision: str,
        decided_by: str,
        decision_comment: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> dict[str, Any]:
        item = self._repository.get(
            tenant_id=tenant_id,
            approval_work_item_id=approval_work_item_id,
        )
        if item is None:
            raise _decision_not_found()
        decision_value = _decision_value(decision)
        comment = _decision_comment(decision_comment)
        decision_id = _decision_uuid("decision_id", self._id_factory())
        decided_at = _timestamp("decided_at", self._clock())
        evidence = self._authorizer.authorize(
            work_item=item,
            decided_by=decided_by,
        )
        record = {
            "schema_version": "wc_approval_decision.v1",
            "tenant_id": item["tenant_id"],
            "decision_id": decision_id,
            "approval_work_item_id": item["approval_work_item_id"],
            "decision": decision_value,
            "decided_by": evidence["decided_by"],
            "decision_comment": comment,
            "decision_version": 1,
            "authorized_by_oa": True,
            "oa_decision_ref": evidence["oa_decision_ref"],
            "authorization_revision_hash": evidence[
                "authorization_revision_hash"
            ],
            "authorization_checked_at": evidence["authorization_checked_at"],
            "decided_at": decided_at,
        }
        event = _approval_event(
            work_item=item,
            decision=record,
            event_id=_decision_uuid("event_id", self._event_id_factory()),
            correlation_id=_decision_scoped(
                "correlation_id", correlation_id or item["approval_work_item_id"]
            ),
            causation_id=_decision_scoped(
                "causation_id", causation_id or item["approval_work_item_id"]
            ),
        )
        outbox = {
            "tenant_id": item["tenant_id"],
            "outbox_id": _decision_uuid("outbox_id", self._outbox_id_factory()),
            "event_id": event["event_id"],
            "approval_work_item_id": item["approval_work_item_id"],
            "decision_id": record["decision_id"],
            "event_type": event["event_type"],
            "event_payload": event,
            "delivery_state": "PENDING",
            "enqueued_job_id": None,
            "created_at": decided_at,
            "updated_at": decided_at,
        }
        saved, created = self._repository.commit_decision(
            decision=record,
            outbox=outbox,
            expected_version=item["version"],
        )
        return {"decision": saved, "created": created}


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


def validate_approval_decision(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version",
        "tenant_id",
        "decision_id",
        "approval_work_item_id",
        "decision",
        "decided_by",
        "decision_comment",
        "decision_version",
        "authorized_by_oa",
        "oa_decision_ref",
        "authorization_revision_hash",
        "authorization_checked_at",
        "decided_at",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _decision_invalid("ApprovalDecision fields are invalid.")
    record = copy.deepcopy(dict(value))
    if record["schema_version"] != "wc_approval_decision.v1":
        raise _decision_invalid("ApprovalDecision schema_version is invalid.")
    record["tenant_id"] = _decision_scoped("tenant_id", record["tenant_id"])
    record["decision_id"] = _decision_uuid("decision_id", record["decision_id"])
    record["approval_work_item_id"] = _decision_uuid(
        "approval_work_item_id", record["approval_work_item_id"]
    )
    record["decision"] = _decision_value(record["decision"])
    record["decided_by"] = _decision_scoped("decided_by", record["decided_by"])
    record["decision_comment"] = _decision_comment(record["decision_comment"])
    version = record["decision_version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _decision_invalid("ApprovalDecision decision_version is invalid.")
    if record["authorized_by_oa"] is not True:
        raise _decision_invalid("ApprovalDecision must be authorized by OA.")
    record["oa_decision_ref"] = _decision_scoped(
        "oa_decision_ref", record["oa_decision_ref"]
    )
    hash_ref = record["authorization_revision_hash"]
    if not isinstance(hash_ref, str) or not _HASH_REF.fullmatch(hash_ref):
        raise _decision_invalid("ApprovalDecision authorization hash is invalid.")
    record["authorization_checked_at"] = _decision_timestamp(
        "authorization_checked_at", record["authorization_checked_at"]
    )
    record["decided_at"] = _decision_timestamp("decided_at", record["decided_at"])
    return record


def validate_approval_event(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version",
        "tenant_id",
        "event_id",
        "event_type",
        "approval_work_item_id",
        "decision_id",
        "approval_domain",
        "decision",
        "decided_by",
        "oa_decision_ref",
        "occurred_at",
        "correlation_id",
        "causation_id",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _decision_invalid("ApprovalEvent fields are invalid.")
    record = copy.deepcopy(dict(value))
    if record["schema_version"] != "wc_approval_event.v1":
        raise _decision_invalid("ApprovalEvent schema_version is invalid.")
    record["tenant_id"] = _decision_scoped("tenant_id", record["tenant_id"])
    for field in ("event_id", "approval_work_item_id", "decision_id"):
        record[field] = _decision_uuid(field, record[field])
    domain = str(record["approval_domain"])
    expected_type = _event_type(domain)
    if record["event_type"] != expected_type:
        raise _decision_invalid("ApprovalEvent type does not match approval domain.")
    record["approval_domain"] = domain
    record["decision"] = _decision_value(record["decision"])
    for field in ("decided_by", "oa_decision_ref", "correlation_id", "causation_id"):
        record[field] = _decision_scoped(field, record[field])
    record["occurred_at"] = _decision_timestamp("occurred_at", record["occurred_at"])
    return record


def validate_approval_outbox(
    value: Mapping[str, Any], *, decision: Mapping[str, Any]
) -> dict[str, Any]:
    fields = {
        "tenant_id",
        "outbox_id",
        "event_id",
        "approval_work_item_id",
        "decision_id",
        "event_type",
        "event_payload",
        "delivery_state",
        "enqueued_job_id",
        "created_at",
        "updated_at",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _decision_invalid("Approval outbox fields are invalid.")
    record = copy.deepcopy(dict(value))
    event = validate_approval_event(record["event_payload"])
    for field in ("tenant_id", "approval_work_item_id", "decision_id"):
        if record[field] != decision[field] or event[field] != decision[field]:
            raise _decision_invalid(f"Approval outbox {field} binding is invalid.")
    record["tenant_id"] = _decision_scoped("tenant_id", record["tenant_id"])
    for field in ("outbox_id", "event_id", "approval_work_item_id", "decision_id"):
        record[field] = _decision_uuid(field, record[field])
    if record["event_id"] != event["event_id"]:
        raise _decision_invalid("Approval outbox event_id binding is invalid.")
    if record["event_type"] != event["event_type"]:
        raise _decision_invalid("Approval outbox event_type binding is invalid.")
    if record["delivery_state"] not in {"PENDING", "ENQUEUED", "DELIVERED", "FAILED"}:
        raise _decision_invalid("Approval outbox delivery_state is invalid.")
    if record["enqueued_job_id"] is not None:
        record["enqueued_job_id"] = _decision_scoped(
            "enqueued_job_id", record["enqueued_job_id"]
        )
    record["created_at"] = _decision_timestamp("created_at", record["created_at"])
    record["updated_at"] = _decision_timestamp("updated_at", record["updated_at"])
    record["event_payload"] = event
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
    return None if row is None else _work_item_from_row(row)


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
    return None if row is None else _work_item_from_row(row)


def _work_item_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
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


def _human_gate_view(work_item: Mapping[str, Any]) -> dict[str, Any]:
    item = validate_approval_work_item(work_item)
    return {
        "schema_version": "human_gate_view.p8.v1",
        "gate_id": item["approval_work_item_id"],
        "approval_domain": item["approval_domain"],
        "state": item["state"],
        "title": item["title"],
        "summary": item["display_safe_summary"],
        "action_ref": (
            "/api/v1/approval-gates/"
            f"{item['approval_work_item_id']}"
        ),
        "approval_provider_type": item["approval_provider_type"],
        "approval_target_ref": item["approval_target_ref"],
        "business_operation_id": item.get("business_operation_id"),
        "expires_at": item.get("expires_at"),
    }


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


def _require_same_decision(
    existing: Mapping[str, Any], candidate: Mapping[str, Any]
) -> None:
    semantic_fields = (
        "tenant_id",
        "approval_work_item_id",
        "decision",
        "decided_by",
        "decision_comment",
    )
    if any(existing[field] != candidate[field] for field in semantic_fields):
        raise _decision_conflict(
            "ApprovalWorkItem already has a different terminal decision."
        )


def _require_pending_version(
    work_item: Mapping[str, Any], *, expected_version: int
) -> None:
    if (
        work_item.get("state") != "PENDING"
        or work_item.get("version") != expected_version
    ):
        raise _decision_conflict(
            "ApprovalWorkItem is not at the expected PENDING version."
        )


def _terminal_state(decision: str) -> str:
    return "APPROVED" if decision == "APPROVE" else "REJECTED"


def _event_type(approval_domain: str) -> str:
    event_types = {
        "NSL_WRITE": "NSL_APPROVAL_DECIDED",
        "BUSINESS_FORMAL": "BUSINESS_FORMAL_APPROVAL_DECIDED",
        "AGENT_FORMAL": "AGENT_FORMAL_APPROVAL_DECIDED",
    }
    try:
        return event_types[approval_domain]
    except KeyError as exc:
        raise _decision_invalid("ApprovalEvent approval_domain is invalid.") from exc


def _approval_event(
    *,
    work_item: Mapping[str, Any],
    decision: Mapping[str, Any],
    event_id: str,
    correlation_id: str,
    causation_id: str,
) -> dict[str, Any]:
    return validate_approval_event(
        {
            "schema_version": "wc_approval_event.v1",
            "tenant_id": decision["tenant_id"],
            "event_id": event_id,
            "event_type": _event_type(work_item["approval_domain"]),
            "approval_work_item_id": decision["approval_work_item_id"],
            "decision_id": decision["decision_id"],
            "approval_domain": work_item["approval_domain"],
            "decision": decision["decision"],
            "decided_by": decision["decided_by"],
            "oa_decision_ref": decision["oa_decision_ref"],
            "occurred_at": decision["decided_at"],
            "correlation_id": correlation_id,
            "causation_id": causation_id,
        }
    )


def _decision_value(value: Any) -> str:
    normalized = str(value).strip().upper()
    if normalized not in {"APPROVE", "REJECT"}:
        raise _decision_invalid("ApprovalDecision decision is invalid.")
    return normalized


def _decision_comment(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2000:
        raise _decision_invalid("ApprovalDecision comment is invalid.")
    return value


def _decision_uuid(field: str, value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _decision_invalid(f"ApprovalDecision {field} must be a UUID.") from exc


def _decision_scoped(field: str, value: Any) -> str:
    normalized = str(value).strip()
    if not _SCOPED_ID.fullmatch(normalized):
        raise _decision_invalid(f"ApprovalDecision {field} is invalid.")
    return normalized


def _decision_timestamp(field: str, value: Any) -> str:
    try:
        return _timestamp(field, value)
    except ApprovalWorkItemError as exc:
        raise _decision_invalid(f"ApprovalDecision {field} is invalid.") from exc


def _decision_invalid(detail: str) -> ApprovalDecisionError:
    return ApprovalDecisionError("wc.approval_decision_invalid", detail)


def _decision_not_found() -> ApprovalDecisionError:
    return ApprovalDecisionError(
        "wc.approval_work_item_not_found",
        "ApprovalWorkItem was not found.",
        404,
    )


def _decision_conflict(detail: str) -> ApprovalDecisionError:
    return ApprovalDecisionError(
        "wc.approval_decision_conflict",
        detail,
        409,
    )


def _decision_unavailable() -> ApprovalDecisionError:
    return ApprovalDecisionError(
        "wc.approval_decision_store_unavailable",
        "WC approval decision persistence is unavailable.",
        503,
        True,
    )


def _outbox_limit(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1000:
        raise _decision_invalid("Approval outbox limit must be between 1 and 1000.")
    return value


def _approval_inbox_limit(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
        raise _invalid("Approval inbox limit must be between 1 and 100.")
    return value


def _approval_inbox_scan_limit(value: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= APPROVAL_INBOX_SCAN_LIMIT
    ):
        raise _invalid(
            f"Approval inbox scan limit must be between 1 and {APPROVAL_INBOX_SCAN_LIMIT}."
        )
    return value


def _inbox_invalid(detail: str) -> ApprovalInboxError:
    return ApprovalInboxError("wc.approval_inbox_invalid", detail, 422)


def _inbox_denied(detail: str) -> ApprovalInboxError:
    return ApprovalInboxError("wc.approval_inbox_authorization_denied", detail, 403)


def _inbox_unavailable(detail: str) -> ApprovalInboxError:
    return ApprovalInboxError(
        "wc.approval_inbox_unavailable", detail, 503, True
    )


def _load_for_decision(
    session: Session, *, tenant_id: str, approval_work_item_id: str
) -> dict[str, Any] | None:
    suffix = ""
    bind = session.get_bind()
    if bind.dialect.name != "sqlite":
        suffix = " FOR UPDATE"
    row = (
        session.execute(
            text(_WORK_ITEM_STATE_SQL + suffix),
            {
                "tenant_id": tenant_id,
                "approval_work_item_id": approval_work_item_id,
            },
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def _load_decision(
    session: Session, *, tenant_id: str, approval_work_item_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_DECISION_SELECT_SQL),
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
    record = dict(row)
    for field in ("decision_id", "approval_work_item_id"):
        record[field] = str(record[field])
    for field in ("authorization_checked_at", "decided_at"):
        record[field] = _decision_timestamp(field, record[field])
    record["authorized_by_oa"] = bool(record["authorized_by_oa"])
    record["schema_version"] = "wc_approval_decision.v1"
    return validate_approval_decision(record)


def _outbox_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row["event_payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise _decision_invalid("Approval outbox payload is malformed.") from exc
    record = dict(row)
    for field in ("outbox_id", "event_id", "approval_work_item_id", "decision_id"):
        record[field] = str(record[field])
    for field in ("created_at", "updated_at"):
        record[field] = _decision_timestamp(field, record[field])
    record["event_payload"] = payload
    decision = {
        "tenant_id": record["tenant_id"],
        "approval_work_item_id": record["approval_work_item_id"],
        "decision_id": record["decision_id"],
    }
    return validate_approval_outbox(record, decision=decision)


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

_SELECT_PENDING_WORK_ITEMS_SQL = """
SELECT tenant_id, approval_work_item_id, approval_domain, source_ref,
       semantic_hash, title, display_safe_summary, approval_provider_type,
       approval_target_ref, target_approver_ref, target_role_ref,
       target_org_scope_ref, target_project_scope_ref, agent_execution_id,
       executable_step_id, nsl_execution_id, business_operation_id,
       approval_request_id, protected_request_ref, resume_target_ref, state,
       created_at, expires_at, version
FROM wc_approval_work_item
WHERE tenant_id = :tenant_id
  AND state = 'PENDING'
ORDER BY created_at, approval_work_item_id
LIMIT :limit
"""

_WORK_ITEM_STATE_SQL = """
SELECT tenant_id, approval_work_item_id, state, version
FROM wc_approval_work_item
WHERE tenant_id = :tenant_id
  AND approval_work_item_id = :approval_work_item_id
"""

_DECISION_INSERT_SQL = """
INSERT INTO wc_approval_decision (
    tenant_id, decision_id, approval_work_item_id, decision, decided_by,
    decision_comment, decision_version, authorized_by_oa, oa_decision_ref,
    authorization_revision_hash, authorization_checked_at, decided_at
) VALUES (
    :tenant_id, :decision_id, :approval_work_item_id, :decision, :decided_by,
    :decision_comment, :decision_version, :authorized_by_oa, :oa_decision_ref,
    :authorization_revision_hash, :authorization_checked_at, :decided_at
)
"""

_WORK_ITEM_DECISION_UPDATE_SQL = """
UPDATE wc_approval_work_item
SET state = :terminal_state, version = :next_version
WHERE tenant_id = :tenant_id
  AND approval_work_item_id = :approval_work_item_id
  AND state = 'PENDING'
  AND version = :expected_version
"""

_DECISION_SELECT_SQL = """
SELECT tenant_id, decision_id, approval_work_item_id, decision, decided_by,
       decision_comment, decision_version, authorized_by_oa, oa_decision_ref,
       authorization_revision_hash, authorization_checked_at, decided_at
FROM wc_approval_decision
WHERE tenant_id = :tenant_id
  AND approval_work_item_id = :approval_work_item_id
ORDER BY decision_version DESC
LIMIT 1
"""

_APPROVAL_OUTBOX_INSERT_SQL = """
INSERT INTO wc_approval_outbox (
    tenant_id, outbox_id, event_id, approval_work_item_id, decision_id,
    event_type, event_payload, delivery_state, enqueued_job_id,
    created_at, updated_at
) VALUES (
    :tenant_id, :outbox_id, :event_id, :approval_work_item_id, :decision_id,
    :event_type, :event_payload, :delivery_state, :enqueued_job_id,
    :created_at, :updated_at
)
"""

_APPROVAL_OUTBOX_PENDING_SQL = """
SELECT tenant_id, outbox_id, event_id, approval_work_item_id, decision_id,
       event_type, event_payload, delivery_state, enqueued_job_id,
       created_at, updated_at
FROM wc_approval_outbox
WHERE delivery_state = 'PENDING'
ORDER BY created_at, outbox_id
LIMIT :limit
"""
