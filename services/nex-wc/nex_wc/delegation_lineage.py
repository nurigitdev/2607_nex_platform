from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol
from uuid import UUID

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

POLICY_REF = "wc.delegation.guard.initial-v1"
MAX_DELEGATION_DEPTH = 10
MAX_CHILDREN_PER_WORK_ITEM = 5
MAX_DESCENDANTS_PER_ROOT = 50

_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_AGENT_TYPES = frozenset({"IA", "CA", "PA", "EA"})
_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "work_item_id",
        "root_work_item_id",
        "parent_work_item_id",
        "parent_claim_ref",
        "parent_claim_generation",
        "delegating_agent_ref",
        "parent_agent_execution_id",
        "delegation_depth",
        "policy_ref",
        "policy_hash",
        "created_at",
    }
)


@dataclass(frozen=True)
class DelegationLineageError(Exception):
    error_code: str
    detail: str
    status_code: int = 400
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class DelegationLineageRepository(Protocol):
    def create(self, lineage: Mapping[str, Any]) -> tuple[dict[str, Any], bool]: ...

    def get(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any] | None: ...


def initial_delegation_policy() -> dict[str, Any]:
    policy = {
        "schema_version": "wc_delegation_policy.v1",
        "policy_ref": POLICY_REF,
        "max_delegation_depth": MAX_DELEGATION_DEPTH,
        "max_children_per_work_item": MAX_CHILDREN_PER_WORK_ITEM,
        "max_descendants_per_root": MAX_DESCENDANTS_PER_ROOT,
        "cycle_detection": True,
        "governance_controlled": True,
        "llm_overridable": False,
    }
    return {**policy, "policy_hash": semantic_sha256_hash_ref(policy)}


class InMemoryDelegationLineageRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def create(self, lineage: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        record = validate_delegation_lineage(lineage)
        key = (record["tenant_id"], record["work_item_id"])
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                _require_same_lineage(existing, record)
                return copy.deepcopy(existing), False
            self._records[key] = copy.deepcopy(record)
            return copy.deepcopy(record), True

    def get(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get((tenant_id, work_item_id))
            return None if record is None else copy.deepcopy(record)


class SqlAlchemyDelegationLineageRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, lineage: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        record = validate_delegation_lineage(lineage)
        agent = record["delegating_agent_ref"]
        params = {
            **record,
            "delegating_agent_id": agent["agent_id"],
            "delegating_agent_type": agent["agent_type"],
        }
        try:
            with self._session_factory() as session:
                inserted = session.execute(text(_INSERT_SQL), params)
                saved = _load(
                    session,
                    tenant_id=record["tenant_id"],
                    work_item_id=record["work_item_id"],
                )
                if saved is None:
                    raise DelegationLineageError(
                        "wc.delegation_lineage_write_conflict",
                        "Delegation lineage could not be reloaded after creation.",
                        409,
                        True,
                    )
                created = int(inserted.rowcount or 0) == 1
                if not created:
                    _require_same_lineage(saved, record)
                session.commit()
                return saved, created
        except DelegationLineageError:
            raise
        except SQLAlchemyError as exc:
            raise DelegationLineageError(
                "wc.delegation_lineage_store_unavailable",
                "WC delegation lineage persistence is unavailable.",
                503,
                True,
            ) from exc

    def get(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load(session, tenant_id=tenant_id, work_item_id=work_item_id)
        except SQLAlchemyError as exc:
            raise DelegationLineageError(
                "wc.delegation_lineage_store_unavailable",
                "WC delegation lineage persistence is unavailable.",
                503,
                True,
            ) from exc


def validate_delegation_lineage(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("delegation lineage must be an object")
    record = copy.deepcopy(dict(value))
    unknown = set(record) - _FIELDS
    missing = _FIELDS - set(record)
    if unknown:
        raise _invalid(f"unsupported lineage field: {min(unknown)}")
    if missing:
        raise _invalid(f"missing lineage field: {min(missing)}")
    if record["schema_version"] != "wc_delegation_lineage.v1":
        raise _invalid("lineage schema_version is invalid")

    for field in ("work_item_id", "root_work_item_id"):
        record[field] = _uuid(field, record[field])
    for field in ("parent_work_item_id", "parent_claim_ref"):
        if record[field] is not None:
            record[field] = _uuid(field, record[field])

    tenant_id = str(record["tenant_id"]).strip()
    execution_id = str(record["parent_agent_execution_id"]).strip()
    if not tenant_id or len(tenant_id) > 128:
        raise _invalid("tenant_id is invalid")
    if not execution_id or len(execution_id) > 128:
        raise _invalid("parent_agent_execution_id is invalid")
    record["tenant_id"] = tenant_id
    record["parent_agent_execution_id"] = execution_id

    agent = record["delegating_agent_ref"]
    if not isinstance(agent, Mapping) or set(agent) != {"agent_id", "agent_type"}:
        raise _invalid("delegating_agent_ref is invalid")
    agent_type = str(agent["agent_type"])
    if agent_type not in _AGENT_TYPES:
        raise _invalid("delegating agent type is invalid")
    record["delegating_agent_ref"] = {
        "agent_id": _uuid("delegating_agent_ref.agent_id", agent["agent_id"]),
        "agent_type": agent_type,
    }

    depth = record["delegation_depth"]
    generation = record["parent_claim_generation"]
    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= 10:
        raise _invalid("delegation_depth is invalid")
    parent_id = record["parent_work_item_id"]
    claim_ref = record["parent_claim_ref"]
    if parent_id is None:
        if claim_ref is not None or generation is not None or depth != 1:
            raise _invalid("first-level lineage parent authority is invalid")
        if record["root_work_item_id"] != record["work_item_id"]:
            raise _invalid("first-level lineage root must equal work_item_id")
    else:
        if claim_ref is None or not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise _invalid("nested lineage requires current parent Claim authority")
        if depth < 2 or record["root_work_item_id"] == record["work_item_id"]:
            raise _invalid("nested lineage root or depth is invalid")

    if record["policy_ref"] != POLICY_REF:
        raise _invalid("delegation policy_ref is not admitted")
    if not isinstance(record["policy_hash"], str) or not _HASH_REF.fullmatch(record["policy_hash"]):
        raise _invalid("delegation policy_hash is invalid")
    created_at = str(record["created_at"]).strip()
    if not created_at:
        raise _invalid("created_at is invalid")
    record["created_at"] = created_at
    return record


def _require_same_lineage(existing: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    if dict(existing) != dict(candidate):
        raise DelegationLineageError(
            "wc.delegation_lineage_conflict",
            "Delegation lineage is immutable and already exists with different semantics.",
            409,
        )


def _invalid(detail: str) -> DelegationLineageError:
    return DelegationLineageError("wc.delegation_lineage_invalid", detail)


def _uuid(field: str, value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _load(session: Session, *, tenant_id: str, work_item_id: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_SELECT_SQL),
            {"tenant_id": tenant_id, "work_item_id": work_item_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        "schema_version": "wc_delegation_lineage.v1",
        "tenant_id": row["tenant_id"],
        "work_item_id": str(row["work_item_id"]),
        "root_work_item_id": str(row["root_work_item_id"]),
        "parent_work_item_id": None if row["parent_work_item_id"] is None else str(row["parent_work_item_id"]),
        "parent_claim_ref": None if row["parent_claim_ref"] is None else str(row["parent_claim_ref"]),
        "parent_claim_generation": row["parent_claim_generation"],
        "delegating_agent_ref": {
            "agent_id": str(row["delegating_agent_id"]),
            "agent_type": row["delegating_agent_type"],
        },
        "parent_agent_execution_id": row["parent_agent_execution_id"],
        "delegation_depth": row["delegation_depth"],
        "policy_ref": row["policy_ref"],
        "policy_hash": row["policy_hash"],
        "created_at": str(row["created_at"]),
    }


_INSERT_SQL = """
INSERT INTO wc_delegation_lineage (
    tenant_id, work_item_id, root_work_item_id, parent_work_item_id,
    parent_claim_ref, parent_claim_generation, delegating_agent_id,
    delegating_agent_type, parent_agent_execution_id, delegation_depth,
    policy_ref, policy_hash, created_at
) VALUES (
    :tenant_id, :work_item_id, :root_work_item_id, :parent_work_item_id,
    :parent_claim_ref, :parent_claim_generation, :delegating_agent_id,
    :delegating_agent_type, :parent_agent_execution_id, :delegation_depth,
    :policy_ref, :policy_hash, :created_at
)
ON CONFLICT (tenant_id, work_item_id) DO NOTHING
"""

_SELECT_SQL = """
SELECT tenant_id, work_item_id, root_work_item_id, parent_work_item_id,
       parent_claim_ref, parent_claim_generation, delegating_agent_id,
       delegating_agent_type, parent_agent_execution_id, delegation_depth,
       policy_ref, policy_hash, created_at
FROM wc_delegation_lineage
WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
"""
