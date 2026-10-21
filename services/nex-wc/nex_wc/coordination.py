from __future__ import annotations

import copy
import json
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_wc.authorization import (
    AuthorizationSource,
    AuthorizationSubjectDenied,
    require_active_scope,
)
from nex_wc.work_items import InMemoryWorkItemRepository

DEFAULT_ROUTING_POLICY_VERSION = "p7-routing-policy.v1"
DEFAULT_CAPABILITY_PROFILES = {
    "FINANCE.PROJECT_BUDGET_CHECK": frozenset(
        {"agent-profile://pa/project-budget-read/v1"}
    )
}


@dataclass(frozen=True)
class CoordinationError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class AgentCandidateSource(Protocol):
    def list_agents(
        self, *, tenant_id: str, agent_type: str, project_id: str
    ) -> Sequence[Mapping[str, Any]]: ...

    def get_agent(self, *, tenant_id: str, agent_id: str) -> Mapping[str, Any] | None: ...


class CoordinationRepository(Protocol):
    def get_work_item(
        self, *, tenant_id: str, work_item_id: str
    ) -> dict[str, Any] | None: ...

    def save_routing_decision(
        self,
        *,
        tenant_id: str,
        work_item_id: str,
        expected_version: int,
        decision: Mapping[str, Any],
    ) -> dict[str, Any]: ...

    def commit_claim(
        self,
        *,
        tenant_id: str,
        work_item_id: str,
        expected_version: int,
        selected_agent: Mapping[str, Any],
        authorization: Mapping[str, Any],
        identifiers: Mapping[str, str],
        lease_verifier: str,
        lease_expires_at: str,
        now: str,
    ) -> dict[str, Any]: ...


class RoutingPolicy:
    def __init__(
        self,
        capability_profiles: Mapping[str, Sequence[str]] | None = None,
        *,
        version: str = DEFAULT_ROUTING_POLICY_VERSION,
    ) -> None:
        self.version = _required("policy version", version)
        source = (
            DEFAULT_CAPABILITY_PROFILES
            if capability_profiles is None
            else capability_profiles
        )
        self._capability_profiles = {
            str(capability): frozenset(str(profile) for profile in profiles)
            for capability, profiles in source.items()
        }

    def decide(
        self,
        *,
        work_item: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        routing_decision_id: str,
        decided_at: str,
    ) -> dict[str, Any]:
        target = work_item["routing_target"]
        required_type = target["required_agent_type"]
        project_id = target["project_scope_ref"]
        capability = target["required_capability"]
        admitted_profiles = self._capability_profiles.get(capability)
        candidate_set: list[dict[str, Any]] = []
        eligible: list[Mapping[str, Any]] = []
        for candidate in sorted(candidates, key=lambda item: str(item.get("agent_id"))):
            reasons: list[str] = []
            if candidate.get("status") != "ACTIVE":
                reasons.append("AGENT_INACTIVE")
            if candidate.get("agent_type") != required_type:
                reasons.append("AGENT_TYPE_MISMATCH")
            if candidate.get("project_id") != project_id:
                reasons.append("PROJECT_SCOPE_MISMATCH")
            if admitted_profiles is None:
                reasons.append("CAPABILITY_POLICY_MISSING")
            elif candidate.get("profile_ref") not in admitted_profiles:
                reasons.append("PROFILE_NOT_ADMITTED")
            is_eligible = not reasons
            if is_eligible:
                eligible.append(candidate)
            candidate_set.append(
                {
                    "candidate_type": "AGENT",
                    "candidate_ref": str(candidate.get("agent_id")),
                    "eligible": is_eligible,
                    "reason_codes": reasons,
                    "load_score": None,
                    "availability": candidate.get("status"),
                    "agent_type": candidate.get("agent_type"),
                }
            )
        selected = eligible[0] if eligible else None
        return {
            "schema_version": "2.1",
            "routing_decision_id": routing_decision_id,
            "work_item_id": work_item["work_item_id"],
            "tenant_id": work_item["tenant_id"],
            "required_capability": capability,
            "organization_scope_ref": target.get("organization_scope_ref"),
            "project_scope_ref": project_id,
            "candidate_set": candidate_set,
            "target_type": "CAPABILITY_POOL",
            "target_ref": None if selected is None else str(selected["agent_id"]),
            "decision": "UNROUTABLE" if selected is None else "ROUTED",
            "reason_codes": ["NO_ELIGIBLE_AGENT"] if selected is None else [],
            "policy_version": self.version,
            "decided_at": decided_at,
            "required_agent_type": required_type,
        }

    def profile_is_admitted(self, capability: str, profile_ref: str) -> bool:
        return profile_ref in self._capability_profiles.get(capability, frozenset())


class WorkCoordinationService:
    def __init__(
        self,
        repository: CoordinationRepository,
        *,
        candidate_source: AgentCandidateSource,
        authorization_source: AuthorizationSource,
        policy: RoutingPolicy | None = None,
        id_factory: Callable[[], str] | None = None,
        token_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        lease_seconds: int = 300,
    ) -> None:
        if lease_seconds < 30 or lease_seconds > 3600:
            raise CoordinationError(
                "wc.claim_lease_policy_invalid",
                "claim lease_seconds must be between 30 and 3600.",
                400,
            )
        self._repository = repository
        self._candidate_source = candidate_source
        self._authorization_source = authorization_source
        self._policy = policy or RoutingPolicy()
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lease_seconds = lease_seconds

    def route(
        self, *, tenant_id: str, work_item_id: str, expected_version: int
    ) -> dict[str, Any]:
        record = self._required_work_item(tenant_id, work_item_id)
        item = record["work_item"]
        if item["version"] != expected_version or item["state"] != "CREATED":
            raise CoordinationError(
                "wc.work_item_route_conflict",
                "WorkItem is not at the expected CREATED version.",
            )
        target = item["routing_target"]
        try:
            candidates = self._candidate_source.list_agents(
                tenant_id=tenant_id,
                agent_type=target["required_agent_type"],
                project_id=target["project_scope_ref"],
            )
        except Exception as exc:
            raise CoordinationError(
                "wc.agent_registry_unavailable",
                "AE Agent Registry is unavailable.",
                503,
                True,
            ) from exc
        now = _time(self._clock())
        decision = self._policy.decide(
            work_item=item,
            candidates=candidates,
            routing_decision_id=self._id_factory(),
            decided_at=now,
        )
        return self._repository.save_routing_decision(
            tenant_id=tenant_id,
            work_item_id=work_item_id,
            expected_version=expected_version,
            decision=decision,
        )

    def claim(
        self, *, tenant_id: str, work_item_id: str, expected_version: int
    ) -> dict[str, Any]:
        record = self._required_work_item(tenant_id, work_item_id)
        item = record["work_item"]
        route = record.get("latest_routing_decision")
        if item["version"] != expected_version or item["state"] not in {
            "ROUTED",
            "ASSIGNED",
        }:
            raise CoordinationError(
                "wc.work_item_claim_conflict",
                "WorkItem is not at an expected claimable version.",
            )
        if not isinstance(route, Mapping) or route.get("decision") != "ROUTED":
            raise CoordinationError(
                "wc.routing_decision_not_claimable",
                "A routed decision is required before claim.",
            )
        agent_id = str(route["target_ref"])
        try:
            candidate = self._candidate_source.get_agent(
                tenant_id=tenant_id, agent_id=agent_id
            )
        except Exception as exc:
            raise CoordinationError(
                "wc.agent_registry_unavailable",
                "AE Agent Registry is unavailable.",
                503,
                True,
            ) from exc
        self._require_current_candidate(item, candidate)
        subject_id = str(item["requester"]["entity_id"])
        try:
            authorization = self._authorization_source.effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )
            revision_hash = require_active_scope(
                authorization,
                required_scope="work:claim",
            )
        except AuthorizationSubjectDenied as exc:
            raise CoordinationError(
                "wc.claim_authorization_denied",
                "Requester lacks active work:claim authority.",
                403,
            ) from exc
        except Exception as exc:
            raise CoordinationError(
                "wc.oa_authorization_unavailable",
                "OA effective authorization is unavailable.",
                503,
                True,
            ) from exc
        now_dt = self._clock().astimezone(UTC)
        now = _time(now_dt)
        lease_token = self._token_factory()
        _required("lease token", lease_token)
        identifiers = {
            "assignment_id": self._id_factory(),
            "claim_id": self._id_factory(),
            "handoff_id": self._id_factory(),
            "outbox_id": self._id_factory(),
            "event_id": self._id_factory(),
        }
        result = self._repository.commit_claim(
            tenant_id=tenant_id,
            work_item_id=work_item_id,
            expected_version=expected_version,
            selected_agent=candidate or {},
            authorization={
                "subject_id": subject_id,
                "revision_hash": revision_hash,
                "checked_at": now,
            },
            identifiers=identifiers,
            lease_verifier=semantic_sha256_hash_ref(lease_token),
            lease_expires_at=_time(now_dt + timedelta(seconds=self._lease_seconds)),
            now=now,
        )
        return {**result, "lease_token": lease_token}

    def _required_work_item(self, tenant_id: str, work_item_id: str) -> dict[str, Any]:
        _required("tenant_id", tenant_id)
        _required("work_item_id", work_item_id)
        record = self._repository.get_work_item(
            tenant_id=tenant_id, work_item_id=work_item_id
        )
        if record is None:
            raise CoordinationError(
                "wc.work_item_not_found", "WorkItem was not found.", 404
            )
        return record

    def _require_current_candidate(
        self, work_item: Mapping[str, Any], candidate: Mapping[str, Any] | None
    ) -> None:
        target = work_item["routing_target"]
        if candidate is None or candidate.get("status") != "ACTIVE":
            raise CoordinationError(
                "wc.claim_candidate_ineligible", "Selected Agent is not active."
            )
        if candidate.get("agent_type") != target["required_agent_type"]:
            raise CoordinationError(
                "wc.claim_candidate_ineligible", "Selected Agent type changed."
            )
        if candidate.get("project_id") != target["project_scope_ref"]:
            raise CoordinationError(
                "wc.claim_candidate_ineligible", "Selected Agent project changed."
            )
        if not self._policy.profile_is_admitted(
            str(target["required_capability"]), str(candidate.get("profile_ref"))
        ):
            raise CoordinationError(
                "wc.claim_candidate_ineligible", "Selected Agent profile is not admitted."
            )


class InMemoryCoordinationRepository:
    def __init__(self, work_items: InMemoryWorkItemRepository) -> None:
        self._work_items = work_items
        self._routes: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._claims: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._assignments: dict[tuple[str, str], dict[str, Any]] = {}
        self._outbox: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def get_work_item(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any] | None:
        record = self._work_items.get(tenant_id=tenant_id, work_item_id=work_item_id)
        if record is None:
            return None
        routes = self._routes.get((tenant_id, work_item_id), [])
        return {
            **record,
            "latest_routing_decision": copy.deepcopy(routes[-1]) if routes else None,
        }

    def save_routing_decision(
        self,
        *,
        tenant_id: str,
        work_item_id: str,
        expected_version: int,
        decision: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            key = (tenant_id, work_item_id)
            record = self._work_items._records.get(key)
            if record is None:
                raise CoordinationError("wc.work_item_not_found", "WorkItem was not found.", 404)
            if record["version"] != expected_version or record["state"] != "CREATED":
                raise CoordinationError("wc.work_item_route_conflict", "WorkItem route version conflict.")
            saved = copy.deepcopy(dict(decision))
            self._routes.setdefault(key, []).append(saved)
            if saved["decision"] == "ROUTED":
                _transition_record(record, state="ROUTED", updated_at=saved["decided_at"])
            return copy.deepcopy(saved)

    def commit_claim(
        self,
        *,
        tenant_id: str,
        work_item_id: str,
        expected_version: int,
        selected_agent: Mapping[str, Any],
        authorization: Mapping[str, Any],
        identifiers: Mapping[str, str],
        lease_verifier: str,
        lease_expires_at: str,
        now: str,
    ) -> dict[str, Any]:
        with self._lock:
            key = (tenant_id, work_item_id)
            record = self._work_items._records.get(key)
            routes = self._routes.get(key, [])
            if record is None or not routes:
                raise CoordinationError("wc.work_item_claim_conflict", "Claim source is missing.")
            if record["version"] != expected_version or record["state"] not in {
                "ROUTED",
                "ASSIGNED",
            }:
                raise CoordinationError("wc.work_item_claim_conflict", "WorkItem claim version conflict.")
            active = [
                claim
                for claim in self._claims.get(key, [])
                if claim["state"] == "ACTIVE"
            ]
            if record["state"] == "ASSIGNED":
                if len(active) != 1 or _parse_time(active[0]["lease_expires_at"]) > _parse_time(now):
                    raise CoordinationError(
                        "wc.active_claim_exists", "An unexpired active claim already exists."
                    )
                expired = active[0]
                expired["state"] = "EXPIRED"
                assignment = self._assignments.get(key)
                if assignment is None or assignment["assignment_id"] != expired["assignment_id"]:
                    raise CoordinationError(
                        "wc.claim_recovery_conflict", "Expired claim assignment is unavailable."
                    )
                assignment["status"] = "RELEASED"
                for outbox in self._outbox.values():
                    if (
                        outbox["work_item_id"] == work_item_id
                        and outbox["event_type"] == "CLAIM_EXECUTION_HANDOFF"
                        and outbox["event_payload"].get("claim_ref")
                        == expired["claim_id"]
                        and outbox["delivery_state"] in {"PENDING", "ENQUEUED"}
                    ):
                        outbox["delivery_state"] = "FAILED"
                        outbox["updated_at"] = now
                active = []
            if active:
                raise CoordinationError("wc.active_claim_exists", "An active claim already exists.")
            generation = max((claim["claim_generation"] for claim in self._claims.get(key, [])), default=0) + 1
            route = routes[-1]
            assignment = {
                "assignment_id": identifiers["assignment_id"],
                "work_item_id": work_item_id,
                "agent_id": str(selected_agent["agent_id"]),
                "agent_type": selected_agent["agent_type"],
                "project_id": selected_agent["project_id"],
                "claim_generation": generation,
                "status": "ACTIVE",
                "agent_execution_id": None,
            }
            claim = {
                "claim_id": identifiers["claim_id"],
                "work_item_id": work_item_id,
                "assignment_id": identifiers["assignment_id"],
                "claim_generation": generation,
                "state": "ACTIVE",
                "lease_verifier": lease_verifier,
                "lease_expires_at": lease_expires_at,
                "authorization_revision_hash": authorization["revision_hash"],
            }
            handoff = _handoff(
                record["work_item"],
                selected_agent,
                identifiers,
                generation,
                now,
            )
            planning_source = _planning_source(
                record["work_item"], record["delegation_spec"]
            )
            self._assignments[key] = assignment
            self._claims.setdefault(key, []).append(claim)
            self._outbox[(tenant_id, identifiers["outbox_id"])] = {
                "tenant_id": tenant_id,
                "outbox_id": identifiers["outbox_id"],
                "event_id": identifiers["event_id"],
                "work_item_id": work_item_id,
                "event_type": "CLAIM_EXECUTION_HANDOFF",
                "event_payload": handoff,
                "delivery_state": "PENDING",
                "enqueued_job_id": None,
                "created_at": now,
                "updated_at": now,
            }
            _transition_record(record, state="ASSIGNED", updated_at=now)
            return {
                "work_item": copy.deepcopy(record["work_item"]),
                "routing_decision": copy.deepcopy(route),
                "assignment": copy.deepcopy(assignment),
                "claim": copy.deepcopy(claim),
                "handoff": handoff,
                "planning_source": planning_source,
                "outbox_id": identifiers["outbox_id"],
                "event_id": identifiers["event_id"],
            }

    def list_pending_handoffs(self, *, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            pending = [
                copy.deepcopy(row)
                for row in self._outbox.values()
                if row["event_type"] == "CLAIM_EXECUTION_HANDOFF"
                and row["delivery_state"] == "PENDING"
            ]
        return sorted(pending, key=lambda row: (row["created_at"], row["outbox_id"]))[
            :limit
        ]

    def mark_handoff_enqueued(
        self, *, outbox_id: str, event_id: str, job_id: str, updated_at: str
    ) -> dict[str, Any]:
        with self._lock:
            row = next(
                (
                    value
                    for (_, stored_outbox_id), value in self._outbox.items()
                    if stored_outbox_id == outbox_id and value["event_id"] == event_id
                ),
                None,
            )
            if row is None or row["delivery_state"] not in {"PENDING", "ENQUEUED"}:
                raise CoordinationError(
                    "wc.handoff_outbox_conflict", "Handoff outbox enqueue state changed."
                )
            if row["enqueued_job_id"] not in {None, job_id}:
                raise CoordinationError(
                    "wc.handoff_outbox_conflict", "Handoff outbox job identity changed."
                )
            row["delivery_state"] = "ENQUEUED"
            row["enqueued_job_id"] = job_id
            row["updated_at"] = updated_at
            return copy.deepcopy(row)

    def load_handoff_event(self, *, outbox_id: str, event_id: str) -> dict[str, Any]:
        with self._lock:
            for (tenant_id, stored_outbox_id), row in self._outbox.items():
                if stored_outbox_id == outbox_id and row["event_id"] == event_id:
                    work = self._work_items._records[(tenant_id, row["work_item_id"])]
                    return {
                        **copy.deepcopy(row),
                        "requester_ref": work["work_item"]["requester"]["entity_id"],
                        "planning_source": _planning_source(
                            work["work_item"], work["delegation_spec"]
                        ),
                        **_in_memory_handoff_authority(
                            self,
                            tenant_id=tenant_id,
                            work_item_id=row["work_item_id"],
                            handoff=row["event_payload"],
                        ),
                    }
        raise CoordinationError("wc.handoff_outbox_not_found", "Handoff outbox was not found.", 404)

    def mark_handoff_delivered(
        self,
        *,
        outbox_id: str,
        event_id: str,
        job_id: str,
        updated_at: str,
        agent_execution_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            row = next(
                (
                    value
                    for (_, stored_outbox_id), value in self._outbox.items()
                    if stored_outbox_id == outbox_id and value["event_id"] == event_id
                ),
                None,
            )
            if row is None or row["delivery_state"] not in {"ENQUEUED", "DELIVERED"}:
                raise CoordinationError(
                    "wc.handoff_outbox_conflict", "Handoff outbox delivery state changed."
                )
            if row["enqueued_job_id"] != job_id:
                raise CoordinationError(
                    "wc.handoff_outbox_conflict", "Handoff outbox job identity changed."
                )
            if agent_execution_id is not None:
                assignment = self._assignments.get(
                    (row["tenant_id"], row["work_item_id"])
                )
                if (
                    assignment is None
                    or assignment["assignment_id"]
                    != row["event_payload"].get("assignment_ref")
                    or assignment.get("agent_execution_id")
                    not in {None, agent_execution_id}
                ):
                    raise CoordinationError(
                        "wc.handoff_execution_conflict",
                        "Handoff AgentExecution lineage changed.",
                    )
                assignment["agent_execution_id"] = agent_execution_id
            row["delivery_state"] = "DELIVERED"
            row["updated_at"] = updated_at
            return copy.deepcopy(row)

    def get_parent_claim_authority(
        self, *, tenant_id: str, claim_id: str
    ) -> dict[str, Any] | None:
        with self._lock:
            for key, claims in self._claims.items():
                if key[0] != tenant_id:
                    continue
                claim = next(
                    (item for item in claims if item["claim_id"] == claim_id), None
                )
                if claim is None:
                    continue
                assignment = self._assignments.get(key)
                if assignment is None:
                    return None
                return {
                    "work_item_id": claim["work_item_id"],
                    "claim_id": claim["claim_id"],
                    "claim_assignment_id": claim["assignment_id"],
                    "claim_generation": claim["claim_generation"],
                    "claim_state": claim["state"],
                    "lease_expires_at": claim["lease_expires_at"],
                    "assignment_id": assignment["assignment_id"],
                    "assignment_claim_generation": assignment["claim_generation"],
                    "assignment_status": assignment["status"],
                    "agent_id": assignment["agent_id"],
                    "agent_type": assignment["agent_type"],
                    "agent_execution_id": assignment.get("agent_execution_id"),
                }
        return None


class SqlAlchemyCoordinationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_work_item(self, *, tenant_id: str, work_item_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_work_item(session, tenant_id, work_item_id)
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc

    def save_routing_decision(
        self,
        *,
        tenant_id: str,
        work_item_id: str,
        expected_version: int,
        decision: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                record = _lock_work_item(session, tenant_id, work_item_id)
                if record is None:
                    raise CoordinationError("wc.work_item_not_found", "WorkItem was not found.", 404)
                if record["version"] != expected_version or record["state"] != "CREATED":
                    raise CoordinationError("wc.work_item_route_conflict", "WorkItem route version conflict.")
                route_version = int(
                    session.execute(
                        text("""
                            SELECT COALESCE(max(decision_version), 0) + 1
                            FROM wc_routing_decision
                            WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
                        """),
                        {"tenant_id": tenant_id, "work_item_id": work_item_id},
                    ).scalar_one()
                )
                session.execute(
                    text(_ROUTE_INSERT_SQL),
                    {
                        "tenant_id": tenant_id,
                        "work_item_id": work_item_id,
                        "routing_decision_id": decision["routing_decision_id"],
                        "decision_version": route_version,
                        "policy_version": decision["policy_version"],
                        "status": "SELECTED" if decision["decision"] == "ROUTED" else "NO_ELIGIBLE_AGENT",
                        "selected_agent_id": decision.get("target_ref"),
                        "decision": json.dumps(decision, sort_keys=True),
                        "created_at": decision["decided_at"],
                    },
                )
                if decision["decision"] == "ROUTED":
                    _update_work_item(session, record, "ROUTED", decision["decided_at"])
                session.commit()
                return dict(decision)
        except CoordinationError:
            raise
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc

    def commit_claim(
        self,
        *,
        tenant_id: str,
        work_item_id: str,
        expected_version: int,
        selected_agent: Mapping[str, Any],
        authorization: Mapping[str, Any],
        identifiers: Mapping[str, str],
        lease_verifier: str,
        lease_expires_at: str,
        now: str,
    ) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                record = _lock_work_item(session, tenant_id, work_item_id)
                if (
                    record is None
                    or record["version"] != expected_version
                    or record["state"] not in {"ROUTED", "ASSIGNED"}
                ):
                    raise CoordinationError("wc.work_item_claim_conflict", "WorkItem claim version conflict.")
                route = _load_latest_route(session, tenant_id, work_item_id, lock=True)
                if route is None or route["decision"] != "ROUTED" or route.get("target_ref") != selected_agent.get("agent_id"):
                    raise CoordinationError("wc.routing_decision_not_claimable", "Routing decision changed before claim.")
                if record["state"] == "ASSIGNED":
                    expired = session.execute(
                        text(
                            "UPDATE wc_claim SET state = 'EXPIRED', updated_at = :now "
                            "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id "
                            "AND state = 'ACTIVE' AND lease_expires_at <= :now "
                            "RETURNING claim_id, assignment_id"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "work_item_id": work_item_id,
                            "now": now,
                        },
                    ).mappings().first()
                    if expired is None:
                        raise CoordinationError(
                            "wc.active_claim_exists",
                            "An unexpired active claim already exists.",
                        )
                    assignment = session.execute(
                        text(
                            "UPDATE wc_assignment SET status = 'RELEASED', updated_at = :now "
                            "WHERE tenant_id = :tenant_id AND assignment_id = :assignment_id "
                            "AND status = 'ACTIVE'"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "assignment_id": expired["assignment_id"],
                            "now": now,
                        },
                    )
                    if int(assignment.rowcount or 0) != 1:
                        raise CoordinationError(
                            "wc.claim_recovery_conflict",
                            "Expired claim assignment changed before reclaim.",
                            retryable=True,
                        )
                    session.execute(
                        text(
                            "UPDATE wc_event_outbox SET delivery_state = 'FAILED', "
                            "updated_at = :now WHERE tenant_id = :tenant_id "
                            "AND work_item_id = :work_item_id "
                            "AND event_type = 'CLAIM_EXECUTION_HANDOFF' "
                            "AND event_payload ->> 'claim_ref' = :claim_id "
                            "AND delivery_state IN ('PENDING', 'ENQUEUED')"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "work_item_id": work_item_id,
                            "claim_id": str(expired["claim_id"]),
                            "now": now,
                        },
                    )
                generation = int(
                    session.execute(
                        text("""
                            SELECT COALESCE(max(claim_generation), 0) + 1
                            FROM wc_claim
                            WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
                        """),
                        {"tenant_id": tenant_id, "work_item_id": work_item_id},
                    ).scalar_one()
                )
                params = {
                    "tenant_id": tenant_id,
                    "work_item_id": work_item_id,
                    "routing_decision_id": route["routing_decision_id"],
                    "assignment_id": identifiers["assignment_id"],
                    "claim_id": identifiers["claim_id"],
                    "agent_id": selected_agent["agent_id"],
                    "agent_type": selected_agent["agent_type"],
                    "project_id": selected_agent["project_id"],
                    "claim_generation": generation,
                    "lease_verifier": lease_verifier,
                    "lease_expires_at": lease_expires_at,
                    "authorization_revision_hash": authorization["revision_hash"],
                    "authorized_subject_id": authorization["subject_id"],
                    "authorization_checked_at": authorization["checked_at"],
                    "now": now,
                }
                session.execute(text(_ASSIGNMENT_INSERT_SQL), params)
                session.execute(text(_CLAIM_INSERT_SQL), params)
                handoff = _handoff(
                    record["work_item"],
                    selected_agent,
                    identifiers,
                    generation,
                    now,
                )
                planning_source = _planning_source(
                    record["work_item"], record["delegation_spec"]
                )
                session.execute(
                    text(_OUTBOX_INSERT_SQL),
                    {
                        **params,
                        "outbox_id": identifiers["outbox_id"],
                        "event_id": identifiers["event_id"],
                        "event_payload": json.dumps(handoff, sort_keys=True),
                    },
                )
                _update_work_item(session, record, "ASSIGNED", now)
                session.commit()
                return {
                    "work_item": record["work_item"],
                    "routing_decision": route,
                    "assignment": {
                        "assignment_id": identifiers["assignment_id"],
                        "work_item_id": work_item_id,
                        "agent_id": selected_agent["agent_id"],
                        "agent_type": selected_agent["agent_type"],
                        "project_id": selected_agent["project_id"],
                        "claim_generation": generation,
                        "status": "ACTIVE",
                        "agent_execution_id": None,
                    },
                    "claim": {
                        "claim_id": identifiers["claim_id"],
                        "work_item_id": work_item_id,
                        "assignment_id": identifiers["assignment_id"],
                        "claim_generation": generation,
                        "state": "ACTIVE",
                        "lease_verifier": lease_verifier,
                        "lease_expires_at": lease_expires_at,
                        "authorization_revision_hash": authorization["revision_hash"],
                    },
                    "handoff": handoff,
                    "planning_source": planning_source,
                    "outbox_id": identifiers["outbox_id"],
                    "event_id": identifiers["event_id"],
                }
        except CoordinationError:
            raise
        except IntegrityError as exc:
            raise CoordinationError("wc.active_claim_exists", "An active claim already exists.") from exc
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc

    def list_pending_handoffs(self, *, limit: int) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        """
                        SELECT tenant_id, outbox_id, event_id, work_item_id,
                               event_type, event_payload, delivery_state,
                               enqueued_job_id, created_at, updated_at
                        FROM wc_event_outbox
                        WHERE event_type = 'CLAIM_EXECUTION_HANDOFF'
                          AND delivery_state = 'PENDING'
                        ORDER BY created_at, outbox_id
                        LIMIT :limit
                        """
                    ),
                    {"limit": limit},
                ).mappings().all()
                return [_outbox_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc

    def mark_handoff_enqueued(
        self, *, outbox_id: str, event_id: str, job_id: str, updated_at: str
    ) -> dict[str, Any]:
        return self._transition_handoff_outbox(
            outbox_id=outbox_id,
            event_id=event_id,
            job_id=job_id,
            source_states=("PENDING", "ENQUEUED"),
            target_state="ENQUEUED",
            updated_at=updated_at,
        )

    def load_handoff_event(self, *, outbox_id: str, event_id: str) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        """
                        SELECT o.tenant_id, o.outbox_id, o.event_id, o.work_item_id,
                               o.event_type, o.event_payload, o.delivery_state,
                               o.enqueued_job_id, o.created_at, o.updated_at,
                               w.delegation_spec, w.work_item,
                               claim.state AS claim_state,
                               claim.claim_generation,
                               claim.lease_expires_at,
                               assignment.status AS assignment_status,
                               active.claim_id AS active_claim_id,
                               w.work_item -> 'requester' ->> 'entity_id' AS requester_ref
                        FROM wc_event_outbox AS o
                        JOIN wc_work_item AS w
                         ON w.tenant_id = o.tenant_id
                         AND w.work_item_id = o.work_item_id
                        LEFT JOIN wc_claim AS claim
                          ON claim.tenant_id = o.tenant_id
                         AND claim.claim_id::text = o.event_payload ->> 'claim_ref'
                        LEFT JOIN wc_assignment AS assignment
                          ON assignment.tenant_id = claim.tenant_id
                         AND assignment.assignment_id = claim.assignment_id
                        LEFT JOIN wc_claim AS active
                          ON active.tenant_id = o.tenant_id
                         AND active.work_item_id = o.work_item_id
                         AND active.state = 'ACTIVE'
                        WHERE o.outbox_id = :outbox_id AND o.event_id = :event_id
                        """
                    ),
                    {"outbox_id": outbox_id, "event_id": event_id},
                ).mappings().first()
                if row is None:
                    raise CoordinationError(
                        "wc.handoff_outbox_not_found", "Handoff outbox was not found.", 404
                    )
                return {
                    **_outbox_from_row(row),
                    "requester_ref": row["requester_ref"],
                    "planning_source": _planning_source(
                        dict(row["work_item"]), dict(row["delegation_spec"])
                    ),
                    "claim_state": row["claim_state"],
                    "claim_generation": (
                        None
                        if row["claim_generation"] is None
                        else int(row["claim_generation"])
                    ),
                    "claim_lease_expires_at": (
                        None
                        if row["lease_expires_at"] is None
                        else _time(row["lease_expires_at"])
                    ),
                    "assignment_status": row["assignment_status"],
                    "active_claim_id": (
                        None
                        if row["active_claim_id"] is None
                        else str(row["active_claim_id"])
                    ),
                }
        except CoordinationError:
            raise
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc

    def mark_handoff_delivered(
        self,
        *,
        outbox_id: str,
        event_id: str,
        job_id: str,
        updated_at: str,
        agent_execution_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                row = _transition_handoff_outbox_in_session(
                    session,
                    outbox_id=outbox_id,
                    event_id=event_id,
                    job_id=job_id,
                    source_states=("ENQUEUED", "DELIVERED"),
                    target_state="DELIVERED",
                    updated_at=updated_at,
                )
                if agent_execution_id is not None:
                    assignment_ref = row["event_payload"].get("assignment_ref")
                    updated = session.execute(
                        text(
                            "UPDATE wc_assignment SET agent_execution_id = :execution_id, "
                            "updated_at = :updated_at WHERE tenant_id = :tenant_id "
                            "AND assignment_id = :assignment_id "
                            "AND (agent_execution_id IS NULL "
                            "OR agent_execution_id = :execution_id)"
                        ),
                        {
                            "tenant_id": row["tenant_id"],
                            "assignment_id": assignment_ref,
                            "execution_id": agent_execution_id,
                            "updated_at": updated_at,
                        },
                    )
                    if int(updated.rowcount or 0) != 1:
                        raise CoordinationError(
                            "wc.handoff_execution_conflict",
                            "Handoff AgentExecution lineage changed.",
                        )
                session.commit()
                return row
        except CoordinationError:
            raise
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc

    def _transition_handoff_outbox(
        self,
        *,
        outbox_id: str,
        event_id: str,
        job_id: str,
        source_states: tuple[str, str],
        target_state: str,
        updated_at: str,
    ) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                row = _transition_handoff_outbox_in_session(
                    session,
                    outbox_id=outbox_id,
                    event_id=event_id,
                    job_id=job_id,
                    source_states=source_states,
                    target_state=target_state,
                    updated_at=updated_at,
                )
                session.commit()
                return row
        except CoordinationError:
            raise
        except SQLAlchemyError as exc:
            raise _store_unavailable() from exc


def _transition_handoff_outbox_in_session(
    session: Session,
    *,
    outbox_id: str,
    event_id: str,
    job_id: str,
    source_states: tuple[str, str],
    target_state: str,
    updated_at: str,
) -> dict[str, Any]:
    row = session.execute(
        text(
            """
            UPDATE wc_event_outbox
            SET delivery_state = :target_state,
                enqueued_job_id = COALESCE(enqueued_job_id, :job_id),
                updated_at = :updated_at
            WHERE outbox_id = :outbox_id AND event_id = :event_id
              AND delivery_state IN (:source_state_1, :source_state_2)
              AND (enqueued_job_id IS NULL OR enqueued_job_id = :job_id)
            RETURNING tenant_id, outbox_id, event_id, work_item_id,
                      event_type, event_payload, delivery_state,
                      enqueued_job_id, created_at, updated_at
            """
        ),
        {
            "outbox_id": outbox_id,
            "event_id": event_id,
            "job_id": job_id,
            "source_state_1": source_states[0],
            "source_state_2": source_states[1],
            "target_state": target_state,
            "updated_at": updated_at,
        },
    ).mappings().first()
    if row is None:
        raise CoordinationError(
            "wc.handoff_outbox_conflict", "Handoff outbox state changed."
        )
    return _outbox_from_row(row)


def _load_work_item(session: Session, tenant_id: str, work_item_id: str) -> dict[str, Any] | None:
    row = session.execute(
        text("""
            SELECT tenant_id, work_item_id, delegation_spec, work_item, state, version
            FROM wc_work_item
            WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
        """),
        {"tenant_id": tenant_id, "work_item_id": work_item_id},
    ).mappings().first()
    if row is None:
        return None
    route = _load_latest_route(session, tenant_id, work_item_id)
    return {
        "tenant_id": row["tenant_id"],
        "work_item_id": str(row["work_item_id"]),
        "delegation_spec": dict(row["delegation_spec"]),
        "work_item": dict(row["work_item"]),
        "state": row["state"],
        "version": int(row["version"]),
        "latest_routing_decision": route,
    }


def _lock_work_item(session: Session, tenant_id: str, work_item_id: str) -> dict[str, Any] | None:
    row = session.execute(
        text("""
            SELECT tenant_id, work_item_id, delegation_spec, work_item, state, version
            FROM wc_work_item
            WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
            FOR UPDATE
        """),
        {"tenant_id": tenant_id, "work_item_id": work_item_id},
    ).mappings().first()
    if row is None:
        return None
    return {
        "tenant_id": row["tenant_id"],
        "work_item_id": str(row["work_item_id"]),
        "delegation_spec": dict(row["delegation_spec"]),
        "work_item": dict(row["work_item"]),
        "state": row["state"],
        "version": int(row["version"]),
    }


def _load_latest_route(
    session: Session, tenant_id: str, work_item_id: str, *, lock: bool = False
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    row = session.execute(
        text(f"""
            SELECT routing_decision_id, decision
            FROM wc_routing_decision
            WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
            ORDER BY decision_version DESC LIMIT 1{suffix}
        """),
        {"tenant_id": tenant_id, "work_item_id": work_item_id},
    ).mappings().first()
    if row is None:
        return None
    decision = dict(row["decision"])
    decision["routing_decision_id"] = str(row["routing_decision_id"])
    return decision


def _update_work_item(session: Session, record: dict[str, Any], state: str, now: str) -> None:
    item = record["work_item"]
    item["state"] = state
    item["version"] = int(record["version"]) + 1
    item["updated_at"] = now
    session.execute(
        text("""
            UPDATE wc_work_item
            SET work_item = CAST(:work_item AS JSONB), state = :state,
                version = :version, updated_at = :updated_at
            WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id
        """),
        {
            "tenant_id": record["tenant_id"],
            "work_item_id": record["work_item_id"],
            "work_item": json.dumps(item, sort_keys=True),
            "state": state,
            "version": item["version"],
            "updated_at": now,
        },
    )
    record["state"] = state
    record["version"] = item["version"]


def _transition_record(record: dict[str, Any], *, state: str, updated_at: str) -> None:
    record["state"] = state
    record["version"] += 1
    record["updated_at"] = updated_at
    record["work_item"]["state"] = state
    record["work_item"]["version"] = record["version"]
    record["work_item"]["updated_at"] = updated_at


def _in_memory_handoff_authority(
    repository: InMemoryCoordinationRepository,
    *,
    tenant_id: str,
    work_item_id: str,
    handoff: Mapping[str, Any],
) -> dict[str, Any]:
    key = (tenant_id, work_item_id)
    claim = next(
        (
            item
            for item in repository._claims.get(key, ())
            if item["claim_id"] == handoff.get("claim_ref")
        ),
        None,
    )
    active = next(
        (
            item
            for item in repository._claims.get(key, ())
            if item["state"] == "ACTIVE"
        ),
        None,
    )
    assignment = repository._assignments.get(key)
    return {
        "claim_state": None if claim is None else claim["state"],
        "claim_generation": (
            None if claim is None else int(claim["claim_generation"])
        ),
        "claim_lease_expires_at": (
            None if claim is None else claim["lease_expires_at"]
        ),
        "assignment_status": (
            None
            if assignment is None
            or claim is None
            or assignment["assignment_id"] != claim["assignment_id"]
            else assignment["status"]
        ),
        "active_claim_id": None if active is None else active["claim_id"],
    }


def _handoff(
    work_item: Mapping[str, Any],
    agent: Mapping[str, Any],
    identifiers: Mapping[str, str],
    generation: int,
    now: str,
) -> dict[str, Any]:
    return {
        "schema_version": "2.1",
        "handoff_id": identifiers["handoff_id"],
        "tenant_id": work_item["tenant_id"],
        "work_item_ref": work_item["work_item_id"],
        "claim_ref": identifiers["claim_id"],
        "claim_generation": generation,
        "claimant_agent_ref": str(agent["agent_id"]),
        "claimant_agent_type": agent["agent_type"],
        "project_id": agent["project_id"],
        "assignment_ref": identifiers["assignment_id"],
        "correlation_id": work_item["trace"]["correlation_id"],
        "causation_id": work_item["trace"].get("causation_id"),
        "occurred_at": now,
    }


def _planning_source(
    work_item: Mapping[str, Any], delegation_spec: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "p7.claimed_work_planning_source.v1",
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": work_item["work_item_id"],
        "goal": work_item["goal"],
        "work_class": work_item["work_class"],
        "required_capability": work_item["routing_target"]["required_capability"],
        "project_ref": work_item["project_ref"],
        "artifact_refs": work_item.get("artifact_refs", []),
        "evidence_refs": [],
        "completion_policy": work_item["completion_policy"],
        "result_contract_ref": delegation_spec["result_contract_ref"],
    }


def _outbox_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "outbox_id": str(row["outbox_id"]),
        "event_id": str(row["event_id"]),
        "work_item_id": str(row["work_item_id"]),
        "event_type": row["event_type"],
        "event_payload": dict(row["event_payload"]),
        "delivery_state": row["delivery_state"],
        "enqueued_job_id": row["enqueued_job_id"],
        "created_at": _time(row["created_at"]) if isinstance(row["created_at"], datetime) else str(row["created_at"]),
        "updated_at": _time(row["updated_at"]) if isinstance(row["updated_at"], datetime) else str(row["updated_at"]),
    }


def _required(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CoordinationError("wc.coordination_input_invalid", f"{field} is required.", 400)
    return value


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CoordinationError(
            "wc.coordination_store_invalid",
            "Stored claim lease timestamp is invalid.",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CoordinationError(
            "wc.coordination_store_invalid",
            "Stored claim lease timestamp is invalid.",
        ) from exc
    if parsed.tzinfo is None:
        raise CoordinationError(
            "wc.coordination_store_invalid",
            "Stored claim lease timestamp lacks a timezone.",
        )
    return parsed.astimezone(UTC)


def _store_unavailable() -> CoordinationError:
    return CoordinationError(
        "wc.coordination_store_unavailable",
        "WC coordination persistence is unavailable.",
        503,
        True,
    )


_ROUTE_INSERT_SQL = """
    INSERT INTO wc_routing_decision (
        tenant_id, routing_decision_id, work_item_id, decision_version,
        policy_version, status, selected_agent_id, decision, created_at
    ) VALUES (
        :tenant_id, :routing_decision_id, :work_item_id, :decision_version,
        :policy_version, :status, :selected_agent_id,
        CAST(:decision AS JSONB), :created_at
    )
"""

_ASSIGNMENT_INSERT_SQL = """
    INSERT INTO wc_assignment (
        tenant_id, assignment_id, work_item_id, routing_decision_id,
        agent_id, agent_type, project_id, claim_generation, status,
        created_at, updated_at
    ) VALUES (
        :tenant_id, :assignment_id, :work_item_id, :routing_decision_id,
        :agent_id, :agent_type, :project_id, :claim_generation, 'ACTIVE',
        :now, :now
    )
"""

_CLAIM_INSERT_SQL = """
    INSERT INTO wc_claim (
        tenant_id, claim_id, work_item_id, assignment_id, claim_generation,
        state, lease_verifier, lease_expires_at, authorization_revision_hash,
        authorized_subject_id, authorization_checked_at, created_at, updated_at
    ) VALUES (
        :tenant_id, :claim_id, :work_item_id, :assignment_id, :claim_generation,
        'ACTIVE', :lease_verifier, :lease_expires_at, :authorization_revision_hash,
        :authorized_subject_id, :authorization_checked_at, :now, :now
    )
"""

_OUTBOX_INSERT_SQL = """
    INSERT INTO wc_event_outbox (
        tenant_id, outbox_id, event_id, work_item_id, event_type,
        event_payload, delivery_state, created_at, updated_at
    ) VALUES (
        :tenant_id, :outbox_id, :event_id, :work_item_id,
        'CLAIM_EXECUTION_HANDOFF', CAST(:event_payload AS JSONB),
        'PENDING', :now, :now
    )
"""
