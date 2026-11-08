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

    def count_children(self, *, tenant_id: str, parent_work_item_id: str) -> int: ...

    def count_descendants(self, *, tenant_id: str, root_work_item_id: str) -> int: ...

    def ancestor_agent_refs(
        self, *, tenant_id: str, work_item_id: str
    ) -> list[dict[str, str]]: ...


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

    def count_children(self, *, tenant_id: str, parent_work_item_id: str) -> int:
        with self._lock:
            return sum(
                1
                for record in self._records.values()
                if record["tenant_id"] == tenant_id
                and record["parent_work_item_id"] == parent_work_item_id
            )

    def count_descendants(self, *, tenant_id: str, root_work_item_id: str) -> int:
        with self._lock:
            return sum(
                1
                for record in self._records.values()
                if record["tenant_id"] == tenant_id
                and record["root_work_item_id"] == root_work_item_id
                and record["work_item_id"] != root_work_item_id
            )

    def ancestor_agent_refs(
        self, *, tenant_id: str, work_item_id: str
    ) -> list[dict[str, str]]:
        with self._lock:
            rows: list[dict[str, Any]] = []
            current = self._records.get((tenant_id, work_item_id))
            while current is not None and len(rows) <= MAX_DELEGATION_DEPTH:
                rows.append(copy.deepcopy(current))
                parent_work_item_id = current["parent_work_item_id"]
                current = (
                    None
                    if parent_work_item_id is None
                    else self._records.get((tenant_id, parent_work_item_id))
                )
            return _validate_ancestor_chain(rows, work_item_id=work_item_id)


class SqlAlchemyDelegationLineageRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, lineage: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        try:
            with self._session_factory() as session:
                saved, created = create_delegation_lineage_in_session(
                    session, lineage
                )
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
                return load_delegation_lineage_in_session(
                    session, tenant_id=tenant_id, work_item_id=work_item_id
                )
        except SQLAlchemyError as exc:
            raise DelegationLineageError(
                "wc.delegation_lineage_store_unavailable",
                "WC delegation lineage persistence is unavailable.",
                503,
                True,
            ) from exc

    def count_children(self, *, tenant_id: str, parent_work_item_id: str) -> int:
        try:
            with self._session_factory() as session:
                return count_delegation_children_in_session(
                    session,
                    tenant_id=tenant_id,
                    parent_work_item_id=parent_work_item_id,
                )
        except SQLAlchemyError as exc:
            raise DelegationLineageError(
                "wc.delegation_lineage_store_unavailable",
                "WC delegation lineage persistence is unavailable.",
                503,
                True,
            ) from exc

    def count_descendants(self, *, tenant_id: str, root_work_item_id: str) -> int:
        try:
            with self._session_factory() as session:
                return count_delegation_descendants_in_session(
                    session,
                    tenant_id=tenant_id,
                    root_work_item_id=root_work_item_id,
                )
        except SQLAlchemyError as exc:
            raise DelegationLineageError(
                "wc.delegation_lineage_store_unavailable",
                "WC delegation lineage persistence is unavailable.",
                503,
                True,
            ) from exc

    def ancestor_agent_refs(
        self, *, tenant_id: str, work_item_id: str
    ) -> list[dict[str, str]]:
        try:
            with self._session_factory() as session:
                return load_delegation_ancestor_agents_in_session(
                    session, tenant_id=tenant_id, work_item_id=work_item_id
                )
        except DelegationLineageError:
            raise
        except SQLAlchemyError as exc:
            raise DelegationLineageError(
                "wc.delegation_lineage_store_unavailable",
                "WC delegation lineage persistence is unavailable.",
                503,
                True,
            ) from exc


def create_delegation_lineage_in_session(
    session: Session, lineage: Mapping[str, Any]
) -> tuple[dict[str, Any], bool]:
    record = validate_delegation_lineage(lineage)
    agent = record["delegating_agent_ref"]
    params = {
        **record,
        "delegating_agent_id": agent["agent_id"],
        "delegating_agent_type": agent["agent_type"],
    }
    inserted = session.execute(text(_INSERT_SQL), params)
    saved = load_delegation_lineage_in_session(
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
    return saved, created


def load_delegation_lineage_in_session(
    session: Session, *, tenant_id: str, work_item_id: str
) -> dict[str, Any] | None:
    return _load(session, tenant_id=tenant_id, work_item_id=work_item_id)


def count_delegation_children_in_session(
    session: Session, *, tenant_id: str, parent_work_item_id: str
) -> int:
    return int(
        session.execute(
            text(_COUNT_CHILDREN_SQL),
            {
                "tenant_id": tenant_id,
                "parent_work_item_id": parent_work_item_id,
            },
        ).scalar_one()
    )


def count_delegation_descendants_in_session(
    session: Session, *, tenant_id: str, root_work_item_id: str
) -> int:
    return int(
        session.execute(
            text(_COUNT_DESCENDANTS_SQL),
            {
                "tenant_id": tenant_id,
                "root_work_item_id": root_work_item_id,
            },
        ).scalar_one()
    )


def load_delegation_ancestor_agents_in_session(
    session: Session, *, tenant_id: str, work_item_id: str
) -> list[dict[str, str]]:
    rows = session.execute(
        text(_SELECT_ANCESTOR_CHAIN_SQL),
        {"tenant_id": tenant_id, "work_item_id": work_item_id},
    ).mappings().all()
    return _validate_ancestor_chain(rows, work_item_id=work_item_id)


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


def _validate_ancestor_chain(
    rows: list[Mapping[str, Any]], *, work_item_id: str
) -> list[dict[str, str]]:
    if not rows:
        return []
    expected_depth = int(rows[0]["delegation_depth"])
    if expected_depth != len(rows) or expected_depth > MAX_DELEGATION_DEPTH:
        raise _invalid("delegation ancestor chain depth is inconsistent")
    root_work_item_id = str(rows[0]["root_work_item_id"])
    seen: set[str] = set()
    agents: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        current_work_item_id = str(row["work_item_id"])
        expected_parent = (
            None if index + 1 == len(rows) else str(rows[index + 1]["work_item_id"])
        )
        parent_work_item_id = row["parent_work_item_id"]
        if (
            current_work_item_id in seen
            or str(row["root_work_item_id"]) != root_work_item_id
            or int(row["delegation_depth"]) != expected_depth - index
            or (
                None if parent_work_item_id is None else str(parent_work_item_id)
            )
            != expected_parent
        ):
            raise _invalid("delegation ancestor chain is inconsistent")
        seen.add(current_work_item_id)
        agents.append(
            {
                "agent_id": str(row["delegating_agent_id"]),
                "agent_type": str(row["delegating_agent_type"]),
            }
            if "delegating_agent_id" in row
            else copy.deepcopy(dict(row["delegating_agent_ref"]))
        )
    if str(rows[0]["work_item_id"]) != str(work_item_id) or str(
        rows[-1]["work_item_id"]
    ) != root_work_item_id:
        raise _invalid("delegation ancestor chain endpoints are inconsistent")
    return agents


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

_COUNT_CHILDREN_SQL = """
    SELECT count(*)
    FROM wc_delegation_lineage
    WHERE tenant_id = :tenant_id
      AND parent_work_item_id = :parent_work_item_id
"""

_COUNT_DESCENDANTS_SQL = """
    SELECT count(*)
    FROM wc_delegation_lineage
    WHERE tenant_id = :tenant_id
      AND root_work_item_id = :root_work_item_id
      AND work_item_id <> :root_work_item_id
"""

_SELECT_ANCESTOR_CHAIN_SQL = """
    WITH RECURSIVE ancestor AS (
        SELECT work_item_id, root_work_item_id, parent_work_item_id,
               delegating_agent_id, delegating_agent_type, delegation_depth,
               0 AS hop, ARRAY[work_item_id]::uuid[] AS path
        FROM wc_delegation_lineage
        WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
        UNION ALL
        SELECT parent.work_item_id, parent.root_work_item_id,
               parent.parent_work_item_id, parent.delegating_agent_id,
               parent.delegating_agent_type, parent.delegation_depth,
               child.hop + 1, child.path || parent.work_item_id
        FROM ancestor AS child
        JOIN wc_delegation_lineage AS parent
          ON parent.tenant_id = :tenant_id
         AND parent.work_item_id = child.parent_work_item_id
        WHERE child.parent_work_item_id IS NOT NULL
          AND child.hop < 9
          AND NOT parent.work_item_id = ANY(child.path)
    )
    SELECT work_item_id, root_work_item_id, parent_work_item_id,
           delegating_agent_id, delegating_agent_type, delegation_depth
    FROM ancestor
    ORDER BY hop
"""
