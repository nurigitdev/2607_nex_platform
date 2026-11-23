from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_runtime.semantic_handoff import validate_semantic_handoff_projection
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref

from nex_ae_api.context_candidate_generation import (
    ContextCandidateStageError,
    parse_context_candidate_set,
)
from nex_ae_api.intent_candidate_generation import (
    IntentCandidateStageError,
    parse_intent_candidate,
)
from nex_ae_api.semantic_candidate_evidence import (
    SemanticCandidateStorage,
    SqlAlchemySemanticCandidateEvidenceRepository,
    candidate_payload_metadata_from_evidence,
)
from nex_ae_api.work_intent import SqlAlchemyWorkIntentRepository

SEMANTIC_REUSE_DECISION_SCHEMA_VERSION = "ae.semantic_reuse_decision.v1"

REUSE_DECISIONS = frozenset(
    {
        "REUSE_INTENT_REBUILD_CONTEXT",
        "REUSE_INTENT_AUGMENT_CONTEXT",
        "FULL_SEMANTIC_REPLAN",
        "RETURN_FOR_CLARIFICATION",
        "DENY_AUTHORITY_CHANGE",
        "DENY_CONFLICT",
    }
)
REUSE_REASON_CODES = frozenset(
    {
        "MISSING",
        "STALE",
        "LOW_CONFIDENCE",
        "AUTHORITY_CHANGED",
        "SCHEMA_DRIFT",
        "CONFLICT",
        "SUPERSEDED",
        "SCOPE_MISMATCH",
        "CAPABILITY_MISMATCH",
        "HASH_MISMATCH",
        "UNSUPPORTED_AGENT_ROLE",
    }
)


class SemanticHandoffReuseError(ValueError):
    pass


class WorkIntentSource(Protocol):
    def get(self, *, tenant_id: str, work_intent_id: str) -> dict[str, Any] | None: ...

    def get_latest_for_execution(
        self, *, tenant_id: str, execution_id: str
    ) -> dict[str, Any] | None: ...


class SemanticEvidenceSource(Protocol):
    def get(self, *, tenant_id: str, candidate_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class SemanticReusePolicy:
    policy_ref: str
    target_agent_type: str
    work_class: str
    minimum_intent_confidence: float
    minimum_context_confidence: float
    maximum_age_seconds: int

    def __post_init__(self) -> None:
        if not self.policy_ref.strip():
            raise SemanticHandoffReuseError("Semantic reuse policy_ref is required.")
        if self.target_agent_type not in {"IA", "CA", "PA", "EA"}:
            raise SemanticHandoffReuseError(
                "Semantic reuse target Agent type is invalid."
            )
        if not self.work_class.strip():
            raise SemanticHandoffReuseError("Semantic reuse work_class is required.")
        for value in (
            self.minimum_intent_confidence,
            self.minimum_context_confidence,
        ):
            if isinstance(value, bool) or not 0.0 <= float(value) <= 1.0:
                raise SemanticHandoffReuseError(
                    "Semantic reuse confidence threshold is invalid."
                )
        if isinstance(self.maximum_age_seconds, bool) or self.maximum_age_seconds < 1:
            raise SemanticHandoffReuseError("Semantic reuse maximum age is invalid.")


class SemanticReusePolicyRegistry:
    def __init__(self, policies: Sequence[SemanticReusePolicy]) -> None:
        self._policies: dict[tuple[str, str], SemanticReusePolicy] = {}
        for policy in policies:
            key = (policy.target_agent_type, policy.work_class)
            if key in self._policies:
                raise SemanticHandoffReuseError(
                    "Semantic reuse policy identity is duplicated."
                )
            self._policies[key] = policy

    def resolve(
        self, *, target_agent_type: str, work_class: str
    ) -> SemanticReusePolicy | None:
        return self._policies.get((target_agent_type, work_class))


@dataclass(frozen=True)
class ResolvedSemanticHandoff:
    work_intent: Mapping[str, Any] | None
    latest_work_intent: Mapping[str, Any] | None
    intent_evidence: Mapping[str, Any] | None
    context_evidence: Mapping[str, Any] | None
    intent_candidate: Mapping[str, Any] | None
    context_candidate: Mapping[str, Any] | None


class SemanticHandoffAuthoritySource:
    def __init__(
        self,
        *,
        work_intents: WorkIntentSource,
        evidence: SemanticEvidenceSource,
        candidate_storage: SemanticCandidateStorage,
    ) -> None:
        self._work_intents = work_intents
        self._evidence = evidence
        self._candidate_storage = candidate_storage

    @classmethod
    def from_sqlalchemy(
        cls,
        *,
        work_intents: SqlAlchemyWorkIntentRepository,
        evidence: SqlAlchemySemanticCandidateEvidenceRepository,
        candidate_storage: SemanticCandidateStorage,
    ) -> SemanticHandoffAuthoritySource:
        return cls(
            work_intents=work_intents,
            evidence=evidence,
            candidate_storage=candidate_storage,
        )

    def resolve(self, handoff: Mapping[str, Any]) -> ResolvedSemanticHandoff:
        projection = validate_semantic_handoff_projection(handoff)
        tenant_id = projection["tenant_id"]
        owner_subject_id = projection["owner_subject_id"]
        work_intent = self._work_intents.get(
            tenant_id=tenant_id,
            work_intent_id=projection["parent_work_intent_id"],
        )
        latest = self._work_intents.get_latest_for_execution(
            tenant_id=tenant_id,
            execution_id=projection["parent_execution_id"],
        )
        intent_evidence = self._evidence.get(
            tenant_id=tenant_id,
            candidate_id=projection["intent_candidate_id"],
        )
        context_evidence = self._evidence.get(
            tenant_id=tenant_id,
            candidate_id=projection["context_candidate_id"],
        )
        return ResolvedSemanticHandoff(
            work_intent=work_intent,
            latest_work_intent=latest,
            intent_evidence=intent_evidence,
            context_evidence=context_evidence,
            intent_candidate=self._load_candidate(
                intent_evidence,
                tenant_id=tenant_id,
                owner_subject_id=owner_subject_id,
            ),
            context_candidate=self._load_candidate(
                context_evidence,
                tenant_id=tenant_id,
                owner_subject_id=owner_subject_id,
            ),
        )

    def _load_candidate(
        self,
        evidence: Mapping[str, Any] | None,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        if evidence is None:
            return None
        metadata = candidate_payload_metadata_from_evidence(evidence)
        return self._candidate_storage.load(
            metadata,
            tenant_id=tenant_id,
            owner_subject_id=owner_subject_id,
        )


class SemanticHandoffReuseEvaluator:
    def __init__(self, policies: SemanticReusePolicyRegistry) -> None:
        self._policies = policies

    def evaluate(
        self,
        *,
        handoff: Mapping[str, Any],
        planning_source: Mapping[str, Any],
        target_agent_type: str,
        resolved: ResolvedSemanticHandoff,
        evaluated_at: str,
        authority_changed: bool = False,
    ) -> dict[str, Any]:
        projection = validate_semantic_handoff_projection(handoff)
        now = _datetime(evaluated_at)
        capability = _text(
            "required_capability", planning_source.get("required_capability")
        )
        work_class = _text("work_class", planning_source.get("work_class"))
        project_ref = planning_source.get("project_ref")
        project_scope = (
            project_ref.get("entity_id") if isinstance(project_ref, Mapping) else None
        )
        if not isinstance(project_scope, str) or not project_scope.strip():
            raise SemanticHandoffReuseError("project_ref.entity_id is required.")
        policy = self._policies.resolve(
            target_agent_type=target_agent_type, work_class=work_class
        )
        if authority_changed:
            return _decision(
                projection,
                decision="DENY_AUTHORITY_CHANGE",
                reasons=("AUTHORITY_CHANGED",),
                policy_ref=None if policy is None else policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )
        if policy is None:
            return _decision(
                projection,
                decision="DENY_CONFLICT",
                reasons=("UNSUPPORTED_AGENT_ROLE",),
                policy_ref=None,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )

        security_reasons = _security_reasons(
            projection,
            planning_source=planning_source,
            capability=capability,
            project_scope=project_scope,
            resolved=resolved,
        )
        if security_reasons:
            return _decision(
                projection,
                decision="DENY_CONFLICT",
                reasons=security_reasons,
                policy_ref=policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )

        missing = tuple(
            name
            for name, value in (
                ("work_intent", resolved.work_intent),
                ("latest_work_intent", resolved.latest_work_intent),
                ("intent_evidence", resolved.intent_evidence),
                ("context_evidence", resolved.context_evidence),
                ("intent_candidate", resolved.intent_candidate),
                ("context_candidate", resolved.context_candidate),
            )
            if value is None
        )
        if missing:
            return _decision(
                projection,
                decision="FULL_SEMANTIC_REPLAN",
                reasons=("MISSING",),
                policy_ref=policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )

        work_intent = dict(resolved.work_intent or {})
        if resolved.latest_work_intent is not None and resolved.latest_work_intent.get(
            "work_intent_id"
        ) != work_intent.get("work_intent_id"):
            return _decision(
                projection,
                decision="FULL_SEMANTIC_REPLAN",
                reasons=("SUPERSEDED",),
                policy_ref=policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )
        age = (now - _datetime(projection["created_at"])).total_seconds()
        if age < 0 or age > policy.maximum_age_seconds:
            return _decision(
                projection,
                decision="FULL_SEMANTIC_REPLAN",
                reasons=("STALE",),
                policy_ref=policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )
        try:
            intent_candidate = parse_intent_candidate(
                _canonical_text(resolved.intent_candidate or {})
            )
            context_candidate = parse_context_candidate_set(
                _canonical_text(resolved.context_candidate or {})
            )
        except (IntentCandidateStageError, ContextCandidateStageError):
            return _decision(
                projection,
                decision="FULL_SEMANTIC_REPLAN",
                reasons=("SCHEMA_DRIFT",),
                policy_ref=policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )
        if (
            semantic_sha256_hash_ref(intent_candidate)
            != projection["intent_candidate_hash"]
            or semantic_sha256_hash_ref(context_candidate)
            != projection["context_candidate_hash"]
        ):
            return _decision(
                projection,
                decision="DENY_CONFLICT",
                reasons=("HASH_MISMATCH",),
                policy_ref=policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )
        if intent_candidate["clarification"]["required"]:
            return _decision(
                projection,
                decision="RETURN_FOR_CLARIFICATION",
                reasons=("CONFLICT",),
                policy_ref=policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )
        intent_confidence = float(intent_candidate["confidence"])
        context_confidence = float(context_candidate["confidence"])
        if intent_confidence < policy.minimum_intent_confidence:
            return _decision(
                projection,
                decision="FULL_SEMANTIC_REPLAN",
                reasons=("LOW_CONFIDENCE",),
                policy_ref=policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )
        if context_confidence < policy.minimum_context_confidence:
            return _decision(
                projection,
                decision="REUSE_INTENT_AUGMENT_CONTEXT",
                reasons=("LOW_CONFIDENCE",),
                policy_ref=policy.policy_ref,
                target_agent_type=target_agent_type,
                capability=capability,
                project_scope=project_scope,
                evaluated_at=evaluated_at,
            )
        return _decision(
            projection,
            decision="REUSE_INTENT_REBUILD_CONTEXT",
            reasons=(),
            policy_ref=policy.policy_ref,
            target_agent_type=target_agent_type,
            capability=capability,
            project_scope=project_scope,
            evaluated_at=evaluated_at,
        )


def _security_reasons(
    projection: Mapping[str, Any],
    *,
    planning_source: Mapping[str, Any],
    capability: str,
    project_scope: object,
    resolved: ResolvedSemanticHandoff,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    identity = planning_source.get("delegation_identity")
    if (
        not isinstance(identity, Mapping)
        or identity.get("parent_agent_execution_id")
        != projection["parent_execution_id"]
        or identity.get("requester_ref") != projection["owner_subject_id"]
    ):
        reasons.add("SCOPE_MISMATCH")
    work_intent = resolved.work_intent
    if work_intent is not None:
        if (
            work_intent.get("work_intent_id") != projection["parent_work_intent_id"]
            or work_intent.get("execution_id") != projection["parent_execution_id"]
            or work_intent.get("intent_revision")
            != projection["parent_intent_revision"]
            or work_intent.get("intent_hash") != projection["parent_work_intent_hash"]
            or semantic_sha256_hash_ref(
                {
                    key: value
                    for key, value in work_intent.items()
                    if key != "intent_hash"
                }
            )
            != projection["parent_work_intent_hash"]
        ):
            reasons.add("HASH_MISMATCH")
        hints = work_intent.get("required_capability_hints")
        if capability != work_intent.get("intent_label") and (
            not isinstance(hints, list) or capability not in hints
        ):
            reasons.add("CAPABILITY_MISMATCH")
        intent_project = work_intent.get("project_ref")
        if (
            not isinstance(intent_project, Mapping)
            or intent_project.get("resource_id") != project_scope
        ):
            reasons.add("SCOPE_MISMATCH")
    for stage, evidence, candidate_id, candidate_hash, evidence_hash in (
        (
            "INTENT",
            resolved.intent_evidence,
            projection["intent_candidate_id"],
            projection["intent_candidate_hash"],
            projection["intent_evidence_hash"],
        ),
        (
            "CONTEXT",
            resolved.context_evidence,
            projection["context_candidate_id"],
            projection["context_candidate_hash"],
            projection["context_evidence_hash"],
        ),
    ):
        if evidence is None:
            continue
        if (
            evidence.get("semantic_stage") != stage
            or evidence.get("candidate_id") != candidate_id
            or evidence.get("candidate_hash") != candidate_hash
            or evidence.get("execution_id") != projection["parent_execution_id"]
            or evidence.get("tenant_id") != projection["tenant_id"]
            or evidence.get("owner_subject_id") != projection["owner_subject_id"]
            or semantic_sha256_hash_ref(evidence) != evidence_hash
        ):
            reasons.add("HASH_MISMATCH")
    return tuple(sorted(reasons))


def _decision(
    projection: Mapping[str, Any],
    *,
    decision: str,
    reasons: Sequence[str],
    policy_ref: str | None,
    target_agent_type: str,
    capability: str,
    project_scope: object,
    evaluated_at: str,
) -> dict[str, Any]:
    if decision not in REUSE_DECISIONS or any(
        reason not in REUSE_REASON_CODES for reason in reasons
    ):
        raise SemanticHandoffReuseError("Semantic reuse decision is invalid.")
    record: dict[str, Any] = {
        "schema_version": SEMANTIC_REUSE_DECISION_SCHEMA_VERSION,
        "handoff_hash": projection["handoff_hash"],
        "parent_execution_id": projection["parent_execution_id"],
        "target_agent_type": target_agent_type,
        "delegated_capability": capability,
        "project_scope_ref": project_scope,
        "policy_ref": policy_ref,
        "decision": decision,
        "reason_codes": sorted(set(reasons)),
        "evaluated_at": _datetime(evaluated_at).isoformat().replace("+00:00", "Z"),
    }
    record["decision_hash"] = semantic_sha256_hash_ref(record)
    return record


def _canonical_text(value: Mapping[str, Any]) -> str:
    return canonical_json(dict(value))


def _text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticHandoffReuseError(f"{field} is required.")
    return value.strip()


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise SemanticHandoffReuseError("Semantic reuse timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SemanticHandoffReuseError("Semantic reuse timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise SemanticHandoffReuseError("Semantic reuse timestamp is invalid.")
    return parsed.astimezone(UTC)
