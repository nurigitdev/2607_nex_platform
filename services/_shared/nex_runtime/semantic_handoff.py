from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref

SEMANTIC_HANDOFF_SCHEMA_VERSION = "ae.semantic_handoff.v1"

_AGENT_TYPES = frozenset({"IA", "CA", "PA", "EA"})
_SOURCE_TYPES = frozenset({"PROMPT", "CLAIMED_WORKITEM"})
_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "owner_subject_id",
        "parent_execution_id",
        "parent_agent_type",
        "parent_work_intent_id",
        "parent_work_intent_hash",
        "parent_intent_revision",
        "intent_candidate_id",
        "intent_candidate_hash",
        "intent_evidence_hash",
        "context_candidate_id",
        "context_candidate_hash",
        "context_evidence_hash",
        "source_type",
        "source_ref",
        "source_interaction_id",
        "source_revision",
        "created_at",
        "handoff_hash",
    }
)


class SemanticHandoffError(ValueError):
    pass


def build_semantic_handoff_projection(
    *,
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    intent_evidence: Mapping[str, Any],
    context_evidence: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    intent = _canonical_mapping("work_intent", work_intent)
    context = _canonical_mapping("agent_context", agent_context)
    intent_stage = _admitted_evidence("INTENT", intent_evidence)
    context_stage = _admitted_evidence("CONTEXT", context_evidence)

    execution_id = _uuid("parent_execution_id", intent.get("execution_id"))
    if (
        context.get("execution_id") != execution_id
        or intent_stage.get("execution_id") != execution_id
        or context_stage.get("execution_id") != execution_id
    ):
        raise _invalid("Semantic handoff execution lineage does not match.")

    identity = context.get("identity")
    if not isinstance(identity, Mapping):
        raise _invalid("Semantic handoff AgentContext identity is invalid.")
    tenant_id = _text("tenant_id", identity.get("tenant_id"), 128)
    owner_subject_id = _text(
        "owner_subject_id", identity.get("principal_id"), 200
    )
    parent_agent_type = identity.get("agent_type")
    if parent_agent_type not in _AGENT_TYPES:
        raise _invalid("Semantic handoff parent Agent type is invalid.")
    for evidence in (intent_stage, context_stage):
        if (
            evidence.get("tenant_id") != tenant_id
            or evidence.get("owner_subject_id") != owner_subject_id
        ):
            raise _invalid("Semantic handoff evidence ownership does not match.")

    work_intent_id = _uuid(
        "parent_work_intent_id", intent.get("work_intent_id")
    )
    work_intent_hash = _hash(
        "parent_work_intent_hash", intent.get("intent_hash")
    )
    expected_intent_hash = semantic_sha256_hash_ref(
        {key: value for key, value in intent.items() if key != "intent_hash"}
    )
    if work_intent_hash != expected_intent_hash:
        raise _invalid("Semantic handoff WorkIntent hash does not match.")
    revision = _positive_int(
        "parent_intent_revision", intent.get("intent_revision")
    )

    work_ref = context.get("work_intent_ref")
    if not isinstance(work_ref, Mapping) or (
        work_ref.get("id") != work_intent_id
        or work_ref.get("version") != revision
        or work_ref.get("hash") != work_intent_hash
    ):
        raise _invalid("Semantic handoff AgentContext WorkIntent ref does not match.")

    context_hash = _hash("context_hash", context.get("context_hash"))
    expected_context_hash = semantic_sha256_hash_ref(
        {key: value for key, value in context.items() if key != "context_hash"}
    )
    if context_hash != expected_context_hash:
        raise _invalid("Semantic handoff AgentContext hash does not match.")

    source = intent.get("source")
    if not isinstance(source, Mapping):
        raise _invalid("Semantic handoff WorkIntent source is invalid.")
    source_type = source.get("source_type")
    if source_type not in _SOURCE_TYPES:
        raise _invalid("Semantic handoff WorkIntent source type is invalid.")
    source_ref = _text("source_ref", source.get("source_ref"), 200)
    interaction = context.get("interaction")
    source_interaction_id = None
    if interaction is not None:
        if not isinstance(interaction, Mapping):
            raise _invalid("Semantic handoff interaction lineage is invalid.")
        source_interaction_id = _uuid(
            "source_interaction_id", interaction.get("interaction_id")
        )

    projection: dict[str, Any] = {
        "schema_version": SEMANTIC_HANDOFF_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "owner_subject_id": owner_subject_id,
        "parent_execution_id": execution_id,
        "parent_agent_type": parent_agent_type,
        "parent_work_intent_id": work_intent_id,
        "parent_work_intent_hash": work_intent_hash,
        "parent_intent_revision": revision,
        "intent_candidate_id": _uuid(
            "intent_candidate_id", intent_stage.get("candidate_id")
        ),
        "intent_candidate_hash": _hash(
            "intent_candidate_hash", intent_stage.get("candidate_hash")
        ),
        "intent_evidence_hash": semantic_sha256_hash_ref(intent_stage),
        "context_candidate_id": _uuid(
            "context_candidate_id", context_stage.get("candidate_id")
        ),
        "context_candidate_hash": _hash(
            "context_candidate_hash", context_stage.get("candidate_hash")
        ),
        "context_evidence_hash": semantic_sha256_hash_ref(context_stage),
        "source_type": source_type,
        "source_ref": source_ref,
        "source_interaction_id": source_interaction_id,
        "source_revision": revision,
        "created_at": _datetime("created_at", created_at),
    }
    projection["handoff_hash"] = semantic_sha256_hash_ref(projection)
    return validate_semantic_handoff_projection(projection)


def validate_semantic_handoff_projection(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    record = _canonical_mapping("semantic_handoff", value)
    if set(record) != _FIELDS or (
        record.get("schema_version") != SEMANTIC_HANDOFF_SCHEMA_VERSION
    ):
        raise _invalid("Semantic handoff fields or schema version are invalid.")
    _text("tenant_id", record.get("tenant_id"), 128)
    _text("owner_subject_id", record.get("owner_subject_id"), 200)
    _uuid("parent_execution_id", record.get("parent_execution_id"))
    if record.get("parent_agent_type") not in _AGENT_TYPES:
        raise _invalid("Semantic handoff parent Agent type is invalid.")
    for field in (
        "parent_work_intent_id",
        "intent_candidate_id",
        "context_candidate_id",
    ):
        _uuid(field, record.get(field))
    for field in (
        "parent_work_intent_hash",
        "intent_candidate_hash",
        "intent_evidence_hash",
        "context_candidate_hash",
        "context_evidence_hash",
        "handoff_hash",
    ):
        _hash(field, record.get(field))
    _positive_int("parent_intent_revision", record.get("parent_intent_revision"))
    _positive_int("source_revision", record.get("source_revision"))
    if record.get("source_type") not in _SOURCE_TYPES:
        raise _invalid("Semantic handoff source type is invalid.")
    _text("source_ref", record.get("source_ref"), 200)
    interaction_id = record.get("source_interaction_id")
    if interaction_id is not None:
        _uuid("source_interaction_id", interaction_id)
    _datetime("created_at", record.get("created_at"))
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "handoff_hash"}
    )
    if record["handoff_hash"] != expected_hash:
        raise _invalid("Semantic handoff hash does not match its content.")
    return record


def _admitted_evidence(stage: str, value: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _canonical_mapping(f"{stage.lower()}_evidence", value)
    if (
        evidence.get("semantic_stage") != stage
        or evidence.get("validation_outcome") != "ADMITTED"
        or evidence.get("directive") != "CONTINUE"
    ):
        raise _invalid(f"Semantic handoff requires admitted {stage} evidence.")
    _uuid("candidate_id", evidence.get("candidate_id"))
    _uuid("execution_id", evidence.get("execution_id"))
    _hash("candidate_hash", evidence.get("candidate_hash"))
    return evidence


def _canonical_mapping(field: str, value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object.")
    try:
        return json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be canonical JSON.") from exc


def _text(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
    ):
        raise _invalid(f"{field} is invalid.")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID.") from exc


def _hash(field: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise _invalid(f"{field} must be a SHA-256 hash reference.")
    return value


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer.")
    return value


def _datetime(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _invalid(f"{field} is invalid.")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an ISO-8601 timestamp.") from exc
    return value


def _invalid(detail: str) -> SemanticHandoffError:
    return SemanticHandoffError(detail)
