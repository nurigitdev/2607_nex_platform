from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol
from uuid import UUID, uuid4

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_wc.authorization import (
    AuthorizationSource,
    AuthorizationSubjectDenied,
    require_active_scope,
)
from nex_wc.delegation_lineage import (
    DelegationLineageRepository,
    InMemoryDelegationLineageRepository,
    count_delegation_children_in_session,
    create_delegation_lineage_in_session,
    initial_delegation_policy,
    load_delegation_lineage_in_session,
    validate_delegation_lineage,
)

WORK_CLASSES = frozenset(
    {
        "QUERY",
        "ANALYSIS",
        "DOCUMENT",
        "BUSINESS_TRANSACTION",
        "COORDINATION",
        "EXPERT_REVIEW",
        "REPORTING",
        "OPERATIONAL",
    }
)
AGENT_TYPES = frozenset({"CA", "PA", "EA"})
COMPLETION_POLICIES = frozenset(
    {
        "OWNER_SUBMITS",
        "ALL_ASSIGNEES_SUBMIT",
        "ANY_ASSIGNEE_SUBMITS",
        "ALL_REQUIRED_CHILDREN",
        "MANUAL",
    }
)
BASE_DELEGATION_FIELDS = frozenset(
    {
        "schema_version",
        "delegation_id",
        "tenant_id",
        "parent_agent_execution_id",
        "parent_executable_plan_id",
        "parent_executable_step_id",
        "delegation_revision",
        "goal",
        "work_class",
        "required_agent_type",
        "required_capability",
        "project_ref",
        "project_scope_ref",
        "result_contract_ref",
        "completion_policy",
        "correlation_id",
        "causation_id",
    }
)
NESTED_DELEGATION_FIELDS = frozenset(
    {
        "parent_work_item_id",
        "parent_claim_ref",
        "parent_claim_generation",
        "delegating_agent_ref",
    }
)
DELEGATION_FIELDS = BASE_DELEGATION_FIELDS | NESTED_DELEGATION_FIELDS
REQUIRED_DELEGATION_FIELDS = BASE_DELEGATION_FIELDS - {"causation_id"}


@dataclass(frozen=True)
class WorkItemError(Exception):
    error_code: str
    detail: str
    status_code: int = 400
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class WorkItemRepository(Protocol):
    def create(
        self,
        record: Mapping[str, Any],
        *,
        lineage: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]: ...

    def get(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any] | None: ...

    def get_lineage(
        self, *, tenant_id: str, work_item_id: str
    ) -> dict[str, Any] | None: ...


class ParentClaimAuthoritySource(Protocol):
    def get_parent_claim_authority(
        self, *, tenant_id: str, claim_id: str
    ) -> Mapping[str, Any] | None: ...


class InMemoryWorkItemRepository:
    def __init__(
        self,
        lineage_repository: DelegationLineageRepository | None = None,
    ) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self._semantic_keys: dict[tuple[str, str], tuple[str, str]] = {}
        self._lineages = lineage_repository or InMemoryDelegationLineageRepository()
        self._parent_claim_authority_source: ParentClaimAuthoritySource | None = None
        self._lock = RLock()

    def bind_parent_claim_authority_source(
        self, source: ParentClaimAuthoritySource
    ) -> None:
        self._parent_claim_authority_source = source

    def create(
        self,
        record: Mapping[str, Any],
        *,
        lineage: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        item = copy.deepcopy(dict(record))
        admitted_lineage = (
            None if lineage is None else validate_delegation_lineage(lineage)
        )
        tenant_id = item["tenant_id"]
        semantic_key = (tenant_id, item["idempotency_key"])
        with self._lock:
            if (
                admitted_lineage is not None
                and admitted_lineage["parent_work_item_id"] is not None
            ):
                authority = (
                    None
                    if self._parent_claim_authority_source is None
                    else self._parent_claim_authority_source.get_parent_claim_authority(
                        tenant_id=str(tenant_id),
                        claim_id=str(admitted_lineage["parent_claim_ref"]),
                    )
                )
                _require_parent_claim_authority(
                    authority,
                    lineage=admitted_lineage,
                    observed_at=str(item["created_at"]),
                )
            existing_ref = self._semantic_keys.get(semantic_key)
            if existing_ref is not None:
                existing = self._records[existing_ref]
                _require_same_semantics(existing, item)
                return copy.deepcopy(existing), False
            record_key = (tenant_id, item["work_item_id"])
            if record_key in self._records:
                raise WorkItemError(
                    "wc.work_item_id_conflict",
                    "WorkItem identity already exists.",
                    409,
                )
            if admitted_lineage is not None:
                _require_lineage_matches_record(item, admitted_lineage)
                if admitted_lineage["parent_work_item_id"] is not None:
                    _require_child_budget(
                        self._lineages.count_children(
                            tenant_id=str(tenant_id),
                            parent_work_item_id=str(
                                admitted_lineage["parent_work_item_id"]
                            ),
                        )
                    )
                self._lineages.create(admitted_lineage)
            self._records[record_key] = item
            self._semantic_keys[semantic_key] = record_key
            return copy.deepcopy(item), True

    def get(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any] | None:
        with self._lock:
            found = self._records.get((tenant_id, work_item_id))
            return None if found is None else copy.deepcopy(found)

    def get_lineage(
        self, *, tenant_id: str, work_item_id: str
    ) -> dict[str, Any] | None:
        return self._lineages.get(tenant_id=tenant_id, work_item_id=work_item_id)


class SqlAlchemyWorkItemRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        record: Mapping[str, Any],
        *,
        lineage: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        params = dict(record)
        admitted_lineage = (
            None if lineage is None else validate_delegation_lineage(lineage)
        )
        if admitted_lineage is not None:
            _require_lineage_matches_record(record, admitted_lineage)
        params["delegation_spec"] = json.dumps(
            params["delegation_spec"], ensure_ascii=False, sort_keys=True
        )
        params["work_item"] = json.dumps(
            params["work_item"], ensure_ascii=False, sort_keys=True
        )
        try:
            with self._session_factory() as session:
                if (
                    admitted_lineage is not None
                    and admitted_lineage["parent_work_item_id"] is not None
                ):
                    authority = _load_parent_claim_authority_in_session(
                        session,
                        tenant_id=str(record["tenant_id"]),
                        claim_id=str(admitted_lineage["parent_claim_ref"]),
                    )
                    _require_parent_claim_authority(
                        authority,
                        lineage=admitted_lineage,
                        observed_at=str(record["created_at"]),
                    )
                    existing = _load_by_semantic_key(
                        session,
                        tenant_id=str(record["tenant_id"]),
                        idempotency_key=str(record["idempotency_key"]),
                    )
                    if existing is not None:
                        _require_same_semantics(existing, record)
                        return existing, False
                    _require_child_budget(
                        count_delegation_children_in_session(
                            session,
                            tenant_id=str(record["tenant_id"]),
                            parent_work_item_id=str(
                                admitted_lineage["parent_work_item_id"]
                            ),
                        )
                    )
                inserted = session.execute(text(_INSERT_SQL), params)
                saved = _load_by_semantic_key(
                    session,
                    tenant_id=str(record["tenant_id"]),
                    idempotency_key=str(record["idempotency_key"]),
                )
                if saved is None:
                    raise WorkItemError(
                        "wc.work_item_write_conflict",
                        "WorkItem could not be reloaded after creation.",
                        409,
                        True,
                    )
                created = int(inserted.rowcount or 0) == 1
                if not created:
                    _require_same_semantics(saved, record)
                elif admitted_lineage is not None:
                    create_delegation_lineage_in_session(session, admitted_lineage)
                session.commit()
                return saved, created
        except WorkItemError:
            raise
        except SQLAlchemyError as exc:
            raise WorkItemError(
                "wc.work_item_store_unavailable",
                "WC WorkItem persistence is unavailable.",
                503,
                True,
            ) from exc

    def get_lineage(
        self, *, tenant_id: str, work_item_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return load_delegation_lineage_in_session(
                    session, tenant_id=tenant_id, work_item_id=work_item_id
                )
        except SQLAlchemyError as exc:
            raise WorkItemError(
                "wc.work_item_store_unavailable",
                "WC WorkItem persistence is unavailable.",
                503,
                True,
            ) from exc

    def get(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_SELECT_BY_ID_SQL),
                        {"tenant_id": tenant_id, "work_item_id": work_item_id},
                    )
                    .mappings()
                    .first()
                )
                return None if row is None else _record_from_row(row)
        except SQLAlchemyError as exc:
            raise WorkItemError(
                "wc.work_item_store_unavailable",
                "WC WorkItem persistence is unavailable.",
                503,
                True,
            ) from exc


class WorkItemService:
    def __init__(
        self,
        repository: WorkItemRepository,
        *,
        authorization_source: AuthorizationSource,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        delegation_guard_enabled: bool = False,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._delegation_guard_enabled = delegation_guard_enabled

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise _invalid("request body must be an object")
        unknown = set(payload) - {
            "work_item_id",
            "delegation_spec",
            "title",
            "description",
            "requester",
            "accountable_owner",
            "closure_policy",
            "priority",
            "due_at",
        }
        if unknown:
            raise _invalid(f"unsupported request field: {min(unknown)}")
        spec = validate_delegation_spec(payload.get("delegation_spec"))
        requester = _entity_ref(payload.get("requester"), "requester")
        owner = _entity_ref(payload.get("accountable_owner"), "accountable_owner")
        closure = _closure_policy(payload.get("closure_policy"))
        title_value = payload["title"] if "title" in payload else spec["goal"][:300]
        title = str(title_value).strip()
        if not title or len(title) > 300:
            raise _invalid("title must contain 1 to 300 characters")
        description = payload.get("description")
        if description is not None and (
            not isinstance(description, str) or len(description) > 12000
        ):
            raise _invalid("description must be null or at most 12000 characters")
        priority = str(payload.get("priority") or "NORMAL")
        if priority not in {"LOW", "NORMAL", "HIGH", "URGENT"}:
            raise _invalid("priority is invalid")
        work_item_id = _uuid(
            "work_item_id",
            payload.get("work_item_id") or self._id_factory(),
        )
        identity = delegation_identity(spec)
        idempotency_key = semantic_sha256_hash_ref(identity)
        delegation_hash = semantic_sha256_hash_ref(spec)
        subject_id = requester["entity_id"]
        try:
            authorization = self._authorization_source.effective_authorization(
                tenant_id=spec["tenant_id"], subject_id=subject_id
            )
            revision_hash = require_active_scope(
                authorization,
                required_scope="work:delegate",
            )
        except AuthorizationSubjectDenied as exc:
            raise WorkItemError(
                "wc.work_item_authorization_denied",
                "Requester lacks active work:delegate authority.",
                403,
            ) from exc
        except Exception as exc:
            raise WorkItemError(
                "wc.work_item_authorization_unavailable",
                "OA effective authorization is unavailable.",
                503,
                True,
            ) from exc
        now = self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
        work_item = {
            "schema_version": "2.1",
            "tenant_id": spec["tenant_id"],
            "work_item_id": work_item_id,
            "title": title,
            "goal": spec["goal"],
            "description": description,
            "work_class": spec["work_class"],
            "priority": priority,
            "state": "CREATED",
            "source": {
                "source_type": "AGENT_PLAN_STEP",
                "source_ref": spec["delegation_id"],
                "parent_work_item_id": spec.get("parent_work_item_id"),
                "parent_execution_id": spec["parent_agent_execution_id"],
                "parent_plan_step_id": spec["parent_executable_step_id"],
            },
            "requester": requester,
            "accountable_owner": owner,
            "routing_target": {
                "target_type": "COWORKER_AGENT",
                "target_ref": None,
                "required_capability": spec["required_capability"],
                "organization_scope_ref": None,
                "project_scope_ref": spec["project_scope_ref"],
                "required_agent_type": spec["required_agent_type"],
            },
            "project_ref": copy.deepcopy(spec["project_ref"]),
            "business_object_refs": [],
            "artifact_refs": [],
            "completion_policy": spec["completion_policy"],
            "closure_policy": closure,
            "due_at": payload.get("due_at"),
            "trace": {
                "correlation_id": spec["correlation_id"],
                "causation_id": spec.get("causation_id"),
                "execution_id": spec["parent_agent_execution_id"],
            },
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        record = {
            "tenant_id": spec["tenant_id"],
            "work_item_id": work_item_id,
            "idempotency_key": idempotency_key,
            "delegation_semantic_hash": delegation_hash,
            "delegation_spec": spec,
            "work_item": work_item,
            "state": "CREATED",
            "source_type": "AGENT_PLAN_STEP",
            "parent_execution_id": spec["parent_agent_execution_id"],
            "parent_plan_id": spec["parent_executable_plan_id"],
            "parent_step_id": spec["parent_executable_step_id"],
            "delegation_revision": spec["delegation_revision"],
            "project_id": spec["project_ref"]["entity_id"],
            "required_agent_type": spec["required_agent_type"],
            "create_authorization_revision_hash": revision_hash,
            "create_authorization_checked_at": now,
            "create_authorized_subject_id": subject_id,
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        lineage = None
        if self._delegation_guard_enabled:
            lineage = (
                _nested_lineage(
                    repository=self._repository,
                    record=record,
                    spec=spec,
                    requester=requester,
                    created_at=now,
                )
                if spec["schema_version"] == "1.1"
                else _first_level_lineage(
                    record=record,
                    requester=requester,
                    created_at=now,
                )
            )
        saved, created = self._repository.create(record, lineage=lineage)
        return {"work_item": saved["work_item"], "created": created}

    def get(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any]:
        _required_text("tenant_id", tenant_id, 128)
        _required_text("work_item_id", work_item_id, 128)
        found = self._repository.get(tenant_id=tenant_id, work_item_id=work_item_id)
        if found is None:
            raise WorkItemError(
                "wc.work_item_not_found", "WorkItem was not found.", 404
            )
        return found["work_item"]

    def status(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any]:
        item = self.get(tenant_id=tenant_id, work_item_id=work_item_id)
        return {
            "schema_version": "wc_work_item_status.v1",
            "tenant_id": item["tenant_id"],
            "work_item_id": item["work_item_id"],
            "state": item["state"],
            "version": item["version"],
            "updated_at": item["updated_at"],
        }


def delegation_identity(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": spec["tenant_id"],
        "delegation_id": spec["delegation_id"],
        "delegation_revision": spec["delegation_revision"],
    }


def validate_delegation_spec(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("delegation_spec must be an object")
    spec = copy.deepcopy(dict(value))
    unknown = set(spec) - DELEGATION_FIELDS
    missing = REQUIRED_DELEGATION_FIELDS - set(spec)
    if unknown:
        raise _invalid(f"unsupported DelegationSpec field: {min(unknown)}")
    if missing:
        raise _invalid(f"missing DelegationSpec field: {min(missing)}")
    schema_version = spec["schema_version"]
    nested_fields = NESTED_DELEGATION_FIELDS & set(spec)
    if schema_version == "1.0":
        if nested_fields:
            raise _invalid("DelegationSpec 1.0 cannot contain nested lineage fields")
    elif schema_version == "1.1":
        missing_nested = NESTED_DELEGATION_FIELDS - set(spec)
        if missing_nested:
            raise _invalid(
                f"missing nested DelegationSpec field: {min(missing_nested)}"
            )
    else:
        raise _invalid("DelegationSpec schema_version must be 1.0 or 1.1")
    for name, maximum in (
        ("delegation_id", 128),
        ("tenant_id", 128),
        ("parent_agent_execution_id", 128),
        ("parent_executable_plan_id", 128),
        ("parent_executable_step_id", 128),
        ("goal", 4000),
        ("required_capability", 160),
        ("project_scope_ref", 160),
        ("result_contract_ref", 512),
        ("correlation_id", 128),
    ):
        _required_text(name, spec[name], maximum)
    revision = spec["delegation_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise _invalid("delegation_revision must be an integer of at least 1")
    if spec["work_class"] not in WORK_CLASSES:
        raise _invalid("work_class is invalid")
    if spec["required_agent_type"] not in AGENT_TYPES:
        raise _invalid("required_agent_type is invalid")
    if spec["completion_policy"] not in COMPLETION_POLICIES:
        raise _invalid("completion_policy is invalid")
    project = _entity_ref(spec["project_ref"], "project_ref")
    if project["entity_type"] != "PROJECT":
        raise _invalid("project_ref.entity_type must be PROJECT")
    if project["entity_id"] != spec["project_scope_ref"]:
        raise _invalid(
            "project_ref and project_scope_ref must identify the same project"
        )
    spec["project_ref"] = project
    causation_id = spec.get("causation_id")
    if causation_id is not None:
        _required_text("causation_id", causation_id, 128)
    if schema_version == "1.1":
        spec["parent_work_item_id"] = _uuid(
            "parent_work_item_id", spec["parent_work_item_id"]
        )
        spec["parent_claim_ref"] = _uuid(
            "parent_claim_ref", spec["parent_claim_ref"]
        )
        generation = spec["parent_claim_generation"]
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 1
        ):
            raise _invalid("parent_claim_generation must be an integer of at least 1")
        agent = spec["delegating_agent_ref"]
        if not isinstance(agent, Mapping) or set(agent) != {"agent_id", "agent_type"}:
            raise _invalid(
                "delegating_agent_ref must contain agent_id and agent_type"
            )
        if agent["agent_type"] not in AGENT_TYPES:
            raise _invalid("delegating_agent_ref.agent_type must be CA, PA, or EA")
        spec["delegating_agent_ref"] = {
            "agent_id": _uuid("delegating_agent_ref.agent_id", agent["agent_id"]),
            "agent_type": agent["agent_type"],
        }
    return spec


def _entity_ref(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an entity reference")
    result = copy.deepcopy(dict(value))
    if set(result) - {"entity_type", "entity_id", "version", "status"}:
        raise _invalid(f"{field} contains unsupported fields")
    _required_text(f"{field}.entity_type", result.get("entity_type"), 80)
    _required_text(f"{field}.entity_id", result.get("entity_id"), 160)
    return result


def _closure_policy(value: object) -> dict[str, Any]:
    if value is None:
        return {
            "authority_type": "REQUESTER",
            "authority_ref": None,
            "required_review": False,
            "allow_agent_auto_close": False,
        }
    if not isinstance(value, Mapping):
        raise _invalid("closure_policy must be an object")
    result = dict(value)
    if set(result) - {
        "authority_type",
        "authority_ref",
        "required_review",
        "allow_agent_auto_close",
    }:
        raise _invalid("closure_policy contains unsupported fields")
    if result.get("authority_type") not in {
        "REQUESTER",
        "ACCOUNTABLE_OWNER",
        "DESIGNATED_REVIEWER",
        "POLICY_ROLE",
        "MANUAL",
    }:
        raise _invalid("closure_policy.authority_type is invalid")
    result.setdefault("authority_ref", None)
    result.setdefault("required_review", False)
    result.setdefault("allow_agent_auto_close", False)
    if not isinstance(result["required_review"], bool) or not isinstance(
        result["allow_agent_auto_close"], bool
    ):
        raise _invalid("closure_policy flags must be boolean")
    return result


def _required_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(f"{field} must contain 1 to {maximum} characters")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _invalid(detail: str) -> WorkItemError:
    return WorkItemError("wc.work_item_invalid", detail, 400)


def _require_same_semantics(
    existing: Mapping[str, Any], candidate: Mapping[str, Any]
) -> None:
    if existing["delegation_semantic_hash"] != candidate["delegation_semantic_hash"]:
        raise WorkItemError(
            "wc.work_item_idempotency_conflict",
            "The delegation identity already exists with different semantics.",
            409,
        )
    existing_requester = existing.get("work_item", {}).get("requester", {})
    candidate_requester = candidate.get("work_item", {}).get("requester", {})
    if existing_requester.get("entity_id") != candidate_requester.get("entity_id"):
        raise WorkItemError(
            "wc.work_item_idempotency_conflict",
            "The delegation identity belongs to a different requester.",
            409,
        )


def _first_level_lineage(
    *,
    record: Mapping[str, Any],
    requester: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    if requester.get("entity_type") != "AGENT":
        raise _invalid("delegation requester must be an Agent")
    policy = initial_delegation_policy()
    work_item_id = str(record["work_item_id"])
    return validate_delegation_lineage(
        {
            "schema_version": "wc_delegation_lineage.v1",
            "tenant_id": record["tenant_id"],
            "work_item_id": work_item_id,
            "root_work_item_id": work_item_id,
            "parent_work_item_id": None,
            "parent_claim_ref": None,
            "parent_claim_generation": None,
            "delegating_agent_ref": {
                "agent_id": _uuid("requester.entity_id", requester["entity_id"]),
                "agent_type": "IA",
            },
            "parent_agent_execution_id": record["parent_execution_id"],
            "delegation_depth": 1,
            "policy_ref": policy["policy_ref"],
            "policy_hash": policy["policy_hash"],
            "created_at": created_at,
        }
    )


def _nested_lineage(
    *,
    repository: WorkItemRepository,
    record: Mapping[str, Any],
    spec: Mapping[str, Any],
    requester: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    agent = spec["delegating_agent_ref"]
    if (
        requester.get("entity_type") != "AGENT"
        or requester.get("entity_id") != agent["agent_id"]
    ):
        raise WorkItemError(
            "wc.delegation_parent_authority_stale",
            "Nested delegation requester does not match its delegating Agent.",
            409,
        )
    parent = repository.get_lineage(
        tenant_id=str(record["tenant_id"]),
        work_item_id=str(spec["parent_work_item_id"]),
    )
    if parent is None:
        raise WorkItemError(
            "wc.delegation_parent_authority_stale",
            "Nested delegation parent lineage is unavailable.",
            409,
        )
    policy = initial_delegation_policy()
    prospective_depth = int(parent["delegation_depth"]) + 1
    if prospective_depth > int(policy["max_delegation_depth"]):
        raise WorkItemError(
            "wc.delegation_hop_limit_exceeded",
            "Nested delegation would exceed the admitted maximum depth.",
            409,
        )
    return validate_delegation_lineage(
        {
            "schema_version": "wc_delegation_lineage.v1",
            "tenant_id": record["tenant_id"],
            "work_item_id": record["work_item_id"],
            "root_work_item_id": parent["root_work_item_id"],
            "parent_work_item_id": spec["parent_work_item_id"],
            "parent_claim_ref": spec["parent_claim_ref"],
            "parent_claim_generation": spec["parent_claim_generation"],
            "delegating_agent_ref": agent,
            "parent_agent_execution_id": record["parent_execution_id"],
            "delegation_depth": prospective_depth,
            "policy_ref": policy["policy_ref"],
            "policy_hash": policy["policy_hash"],
            "created_at": created_at,
        }
    )


def _require_lineage_matches_record(
    record: Mapping[str, Any], lineage: Mapping[str, Any]
) -> None:
    source = record.get("work_item", {}).get("source", {})
    if (
        lineage["tenant_id"] != record["tenant_id"]
        or lineage["work_item_id"] != record["work_item_id"]
        or lineage["parent_agent_execution_id"] != record["parent_execution_id"]
        or lineage["parent_work_item_id"] != source.get("parent_work_item_id")
    ):
        raise WorkItemError(
            "wc.delegation_lineage_conflict",
            "Delegation lineage does not match its WorkItem admission.",
            409,
        )


def _require_parent_claim_authority(
    authority: Mapping[str, Any] | None,
    *,
    lineage: Mapping[str, Any],
    observed_at: str,
) -> None:
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        lease_expiry = datetime.fromisoformat(
            str(None if authority is None else authority.get("lease_expires_at")).replace(
                "Z", "+00:00"
            )
        )
    except (TypeError, ValueError) as exc:
        raise _stale_parent_authority() from exc
    agent = lineage["delegating_agent_ref"]
    expected = {
        "work_item_id": lineage["parent_work_item_id"],
        "claim_id": lineage["parent_claim_ref"],
        "claim_generation": lineage["parent_claim_generation"],
        "claim_state": "ACTIVE",
        "assignment_status": "ACTIVE",
        "agent_id": agent["agent_id"],
        "agent_type": agent["agent_type"],
        "agent_execution_id": lineage["parent_agent_execution_id"],
    }
    if authority is None or any(
        str(authority.get(field)) != str(value) for field, value in expected.items()
    ):
        raise _stale_parent_authority()
    if lease_expiry.tzinfo is None or observed.tzinfo is None or lease_expiry <= observed:
        raise _stale_parent_authority()
    if (
        authority.get("assignment_id") is None
        or authority.get("claim_assignment_id") != authority.get("assignment_id")
        or int(authority.get("assignment_claim_generation", 0))
        != int(lineage["parent_claim_generation"])
    ):
        raise _stale_parent_authority()


def _stale_parent_authority() -> WorkItemError:
    return WorkItemError(
        "wc.delegation_parent_authority_stale",
        "Nested delegation requires the current parent Claim, Assignment, and AgentExecution authority.",
        409,
    )


def _require_child_budget(current_children: int) -> None:
    maximum = int(initial_delegation_policy()["max_children_per_work_item"])
    if current_children >= maximum:
        raise WorkItemError(
            "wc.delegation_child_budget_exceeded",
            "Nested delegation would exceed the direct child budget.",
            409,
        )


def _load_parent_claim_authority_in_session(
    session: Session, *, tenant_id: str, claim_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_SELECT_PARENT_CLAIM_AUTHORITY_SQL),
            {"tenant_id": tenant_id, "claim_id": claim_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        "work_item_id": str(row["work_item_id"]),
        "claim_id": str(row["claim_id"]),
        "claim_assignment_id": str(row["claim_assignment_id"]),
        "claim_generation": int(row["claim_generation"]),
        "claim_state": row["claim_state"],
        "lease_expires_at": str(row["lease_expires_at"]),
        "assignment_id": str(row["assignment_id"]),
        "assignment_claim_generation": int(row["assignment_claim_generation"]),
        "assignment_status": row["assignment_status"],
        "agent_id": str(row["agent_id"]),
        "agent_type": row["agent_type"],
        "agent_execution_id": row["agent_execution_id"],
    }


def _load_by_semantic_key(
    session: Session, *, tenant_id: str, idempotency_key: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_SELECT_BY_SEMANTIC_KEY_SQL),
            {"tenant_id": tenant_id, "idempotency_key": idempotency_key},
        )
        .mappings()
        .first()
    )
    return None if row is None else _record_from_row(row)


def _record_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "work_item_id": str(row["work_item_id"]),
        "idempotency_key": row["idempotency_key"],
        "delegation_semantic_hash": row["delegation_semantic_hash"],
        "delegation_spec": dict(row["delegation_spec"]),
        "work_item": dict(row["work_item"]),
        "state": row["state"],
        "source_type": row["source_type"],
        "parent_execution_id": row["parent_execution_id"],
        "parent_plan_id": row["parent_plan_id"],
        "parent_step_id": row["parent_step_id"],
        "delegation_revision": int(row["delegation_revision"]),
        "project_id": row["project_id"],
        "required_agent_type": row["required_agent_type"],
        "create_authorization_revision_hash": row["create_authorization_revision_hash"],
        "create_authorization_checked_at": (
            None
            if row["create_authorization_checked_at"] is None
            else str(row["create_authorization_checked_at"])
        ),
        "create_authorized_subject_id": row["create_authorized_subject_id"],
        "version": int(row["version"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


_SELECT_COLUMNS = """
    tenant_id, work_item_id, idempotency_key, delegation_semantic_hash,
    delegation_spec, work_item, state, source_type, parent_execution_id,
    parent_plan_id, parent_step_id, delegation_revision, project_id,
    required_agent_type, create_authorization_revision_hash,
    create_authorization_checked_at, create_authorized_subject_id,
    version, created_at, updated_at
"""

_INSERT_SQL = """
    INSERT INTO wc_work_item (
        tenant_id, work_item_id, idempotency_key, delegation_semantic_hash,
        delegation_spec, work_item, state, source_type, parent_execution_id,
        parent_plan_id, parent_step_id, delegation_revision, project_id,
        required_agent_type, create_authorization_revision_hash,
        create_authorization_checked_at, create_authorized_subject_id,
        version, created_at, updated_at
    ) VALUES (
        :tenant_id, :work_item_id, :idempotency_key, :delegation_semantic_hash,
        CAST(:delegation_spec AS JSONB), CAST(:work_item AS JSONB), :state,
        :source_type, :parent_execution_id, :parent_plan_id, :parent_step_id,
        :delegation_revision, :project_id, :required_agent_type,
        :create_authorization_revision_hash, :create_authorization_checked_at,
        :create_authorized_subject_id, :version, :created_at, :updated_at
    ) ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
"""

_SELECT_BY_SEMANTIC_KEY_SQL = f"""
    SELECT {_SELECT_COLUMNS}
    FROM wc_work_item
    WHERE tenant_id = :tenant_id AND idempotency_key = :idempotency_key
"""

_SELECT_BY_ID_SQL = f"""
    SELECT {_SELECT_COLUMNS}
    FROM wc_work_item
    WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
"""

_SELECT_PARENT_CLAIM_AUTHORITY_SQL = """
    SELECT claim.work_item_id, claim.claim_id,
           claim.assignment_id AS claim_assignment_id,
           claim.claim_generation, claim.state AS claim_state,
           claim.lease_expires_at,
           assignment.assignment_id,
           assignment.claim_generation AS assignment_claim_generation,
           assignment.status AS assignment_status,
           assignment.agent_id, assignment.agent_type,
           assignment.agent_execution_id
    FROM wc_claim AS claim
    JOIN wc_assignment AS assignment
      ON assignment.tenant_id = claim.tenant_id
     AND assignment.assignment_id = claim.assignment_id
    WHERE claim.tenant_id = :tenant_id
      AND claim.claim_id = :claim_id
    FOR UPDATE OF claim, assignment
"""
