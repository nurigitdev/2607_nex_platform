from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from nex_runtime.semantic_handoff import (
    SemanticHandoffError,
    validate_semantic_handoff_projection,
)
from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
    validate_sha256_digest,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.business_request_context import (
    BUSINESS_TRANSACTION_INTENT_LABEL,
    BusinessRequestContextError,
    admit_business_request_context,
    validate_business_request_context,
)

PLANNING_MODE_ENV = "NEX_AE_PLANNING_MODE"
PLANNING_MODES = frozenset({"disabled", "shadow", "required"})
WORK_INTENT_SCHEMA_VERSION = "1.1"
BUSINESS_WORK_INTENT_SCHEMA_VERSION = "1.2"

_MODE_PROFILE = {
    "GENERAL_ANSWER": (
        "Answer the admitted user request.",
        "QUERY",
        "A direct response is returned.",
        "contract://nex/ae/general-answer/v1",
    ),
    "GROUNDED_ANSWER": (
        "Answer the admitted user request using authorized evidence.",
        "QUERY",
        "A grounded response is returned.",
        "contract://nex/ae/grounded-answer/v1",
    ),
    "DOCUMENT_SUMMARY": (
        "Summarize the authorized source material.",
        "ANALYSIS",
        "A source-traceable summary is returned.",
        "contract://nex/ae/document-summary/v1",
    ),
    "DOCUMENT_GENERATION": (
        "Create the requested document from authorized context.",
        "DOCUMENT",
        "A structured document result is returned.",
        "contract://nex/ae/document-generation/v1",
    ),
}


@dataclass(frozen=True)
class WorkIntentError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def planning_mode(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    mode = str(env.get(PLANNING_MODE_ENV, "disabled")).strip().lower()
    if mode not in PLANNING_MODES:
        raise _invalid("AE planning mode must be disabled, shadow, or required.")
    return mode


def validate_work_intent(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a persisted WorkIntent without exposing mutable internals."""

    return _validate_work_intent(value)


def build_work_intent_from_decision(
    *,
    execution_id: str,
    source_ref: str,
    actor_ref: str,
    received_at: str,
    intent_decision: Mapping[str, Any],
    input_context_hash: str,
    work_intent_id: str | None = None,
    intent_revision: int = 1,
    supersedes_work_intent_id: str | None = None,
    prompt_provenance: Mapping[str, Any] | None = None,
    intent_candidate: Mapping[str, Any] | None = None,
    intent_candidate_hash: str | None = None,
    attachment_manifest_hash: str | None = None,
    id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    _require_uuid("execution_id", execution_id)
    _require_text("source_ref", source_ref, maximum=200)
    _require_text("actor_ref", actor_ref, maximum=200)
    _require_datetime("received_at", received_at)
    validate_hash_ref(input_context_hash)
    _validate_revision(intent_revision, supersedes_work_intent_id)

    schema_version = intent_decision.get("intent_decision_schema_version")
    if schema_version != "ae_intent_decision.v1":
        raise _invalid("IntentDecision schema version is unsupported.")
    if intent_decision.get("raw_prompt_included") is not False:
        raise _invalid("IntentDecision must not include the raw prompt.")
    mode = intent_decision.get("execution_mode")
    if mode not in _MODE_PROFILE:
        raise _invalid("IntentDecision execution_mode is unsupported.")
    decision_hash = validate_sha256_digest(intent_decision.get("decision_hash"))
    intent_label = _require_text(
        "intent_label", intent_decision.get("intent_label"), maximum=160
    )
    confidence = intent_decision.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise _invalid("IntentDecision confidence must be numeric.")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise _invalid("IntentDecision confidence must be between zero and one.")

    resolved_id = work_intent_id or (id_factory or (lambda: str(uuid4())))()
    _require_uuid("work_intent_id", resolved_id)
    if supersedes_work_intent_id is not None:
        _require_uuid("supersedes_work_intent_id", supersedes_work_intent_id)
    goal, work_class, criterion, result_contract_ref = _MODE_PROFILE[str(mode)]
    provenance = _build_provenance(
        schema_version=str(schema_version),
        decision_hash=decision_hash,
        input_context_hash=input_context_hash,
        prompt_provenance=prompt_provenance,
    )
    if intent_label == BUSINESS_TRANSACTION_INTENT_LABEL:
        if intent_candidate is None or intent_candidate_hash is None:
            raise _invalid(
                "M1 business WorkIntent requires its admitted IntentCandidate and hash."
            )
        try:
            admitted_business = admit_business_request_context(
                candidate=intent_candidate,
                candidate_hash=intent_candidate_hash,
                source_prompt_ref=source_ref,
                input_context_hash=input_context_hash,
                model_profile=provenance["model_profile"],
                model_ref=provenance["model_ref"],
                attachment_manifest_hash=attachment_manifest_hash,
            )
        except BusinessRequestContextError as exc:
            raise WorkIntentError(exc.error_code, exc.detail) from exc
        parameter_confidences = [
            float(item["confidence"])
            for item in admitted_business.parameter_candidates
        ]
        entity_confidences = [
            float(item["confidence"]) for item in admitted_business.entity_selectors
        ]
        work_intent = {
            "schema_version": BUSINESS_WORK_INTENT_SCHEMA_VERSION,
            "work_intent_id": resolved_id,
            "intent_revision": intent_revision,
            "supersedes_work_intent_id": supersedes_work_intent_id,
            "execution_id": execution_id,
            "source": {
                "source_type": "PROMPT",
                "source_ref": source_ref,
                "actor_ref": actor_ref,
                "received_at": received_at,
            },
            "execution_mode": "INTERACTIVE",
            "compatibility_execution_mode": mode,
            "project_ref": None,
            "intent_label": intent_label,
            "goal": (
                "Prepare and post the admitted Project-attributed business "
                "transaction."
            ),
            "work_class": "BUSINESS_TRANSACTION",
            "required_capability_hints": [BUSINESS_TRANSACTION_INTENT_LABEL],
            "entity_selectors": list(admitted_business.entity_selectors),
            "parameter_candidates": list(admitted_business.parameter_candidates),
            "constraints": [
                {
                    "constraint_type": "BUSINESS_CONTEXT_AUTHORITY",
                    "description": (
                        "The business request context is input, not accounting "
                        "authority."
                    ),
                }
            ],
            "completion_criteria": [
                {
                    "criterion_id": "C1",
                    "description": (
                        "The active Project Agent returns the governed accounting "
                        "result."
                    ),
                    "required": True,
                    "result_contract_ref": (
                        "contract://nex/mybee/finance/journal-posting-result/v1"
                    ),
                }
            ],
            "clarification": {
                "status": "NOT_REQUIRED",
                "reasons": [],
                "questions": [],
            },
            "confidence": {
                "overall": confidence,
                "intent": confidence,
                "entities": min(entity_confidences),
                "parameters": min(parameter_confidences),
            },
            "provenance": provenance,
            "business_request_context": dict(admitted_business.context),
            "business_context_hash": admitted_business.context["context_hash"],
        }
        work_intent["intent_hash"] = semantic_sha256_hash_ref(work_intent)
        return _validate_work_intent(work_intent)

    work_intent: dict[str, Any] = {
        "schema_version": WORK_INTENT_SCHEMA_VERSION,
        "work_intent_id": resolved_id,
        "intent_revision": intent_revision,
        "supersedes_work_intent_id": supersedes_work_intent_id,
        "execution_id": execution_id,
        "source": {
            "source_type": "PROMPT",
            "source_ref": source_ref,
            "actor_ref": actor_ref,
            "received_at": received_at,
        },
        "execution_mode": "INTERACTIVE",
        "compatibility_execution_mode": mode,
        "project_ref": None,
        "intent_label": intent_label,
        "goal": goal,
        "work_class": work_class,
        "required_capability_hints": ["AE.CHAT.COMPATIBILITY"],
        "entity_selectors": [],
        "parameter_candidates": [],
        "constraints": [],
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": criterion,
                "required": True,
                "result_contract_ref": result_contract_ref,
            }
        ],
        "clarification": {
            "status": "NOT_REQUIRED",
            "reasons": [],
            "questions": [],
        },
        "confidence": {
            "overall": confidence,
            "intent": confidence,
            "entities": None,
            "parameters": None,
        },
        "provenance": provenance,
    }
    work_intent["intent_hash"] = semantic_sha256_hash_ref(work_intent)
    return work_intent


def build_work_intent_from_claimed_work(
    *,
    execution_id: str,
    actor_ref: str,
    received_at: str,
    planning_source: Mapping[str, Any],
    intent_decision: Mapping[str, Any],
    input_context_hash: str,
    work_intent_id: str,
    prompt_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _require_uuid("execution_id", execution_id)
    _require_uuid("work_intent_id", work_intent_id)
    _require_text("actor_ref", actor_ref, maximum=200)
    _require_datetime("received_at", received_at)
    validate_hash_ref(input_context_hash)
    source = _claimed_planning_source(planning_source)
    if intent_decision.get("intent_decision_schema_version") != "ae_intent_decision.v1":
        raise _invalid("IntentDecision schema version is unsupported.")
    if intent_decision.get("raw_prompt_included") is not False:
        raise _invalid("IntentDecision must not include the raw prompt.")
    compatibility_mode = intent_decision.get("execution_mode")
    if compatibility_mode not in _MODE_PROFILE:
        raise _invalid("IntentDecision execution_mode is unsupported.")
    _require_text("intent_label", intent_decision.get("intent_label"), maximum=160)
    confidence = intent_decision.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise _invalid("IntentDecision confidence must be numeric.")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise _invalid("IntentDecision confidence must be between zero and one.")
    decision_hash = validate_sha256_digest(intent_decision.get("decision_hash"))
    provenance = _build_provenance(
        schema_version="ae_intent_decision.v1",
        decision_hash=decision_hash,
        input_context_hash=input_context_hash,
        prompt_provenance=prompt_provenance,
    )
    result: dict[str, Any] = {
        "schema_version": (
            BUSINESS_WORK_INTENT_SCHEMA_VERSION
            if _claimed_source_has_business_context(source)
            else WORK_INTENT_SCHEMA_VERSION
        ),
        "work_intent_id": work_intent_id,
        "intent_revision": 1,
        "supersedes_work_intent_id": None,
        "execution_id": execution_id,
        "source": {
            "source_type": "CLAIMED_WORKITEM",
            "source_ref": source["source_ref"],
            "actor_ref": actor_ref,
            "received_at": received_at,
        },
        "execution_mode": "BACKGROUND",
        "compatibility_execution_mode": compatibility_mode,
        "project_ref": {
            "system": "nex-wc",
            "resource_type": "PROJECT",
            "resource_id": source["project_ref"]["entity_id"],
        },
        "intent_label": source["required_capability"],
        "goal": source["goal"],
        "work_class": source["work_class"],
        "required_capability_hints": [source["required_capability"]],
        "entity_selectors": [],
        "parameter_candidates": [],
        "constraints": [
            f"completion_policy={source['completion_policy']}",
            f"result_contract_ref={source['result_contract_ref']}",
        ],
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": "Submit the claimed WorkItem result contract.",
                "required": True,
                "result_contract_ref": source["result_contract_ref"],
            }
        ],
        "clarification": {
            "status": "NOT_REQUIRED",
            "reasons": [],
            "questions": [],
        },
        "confidence": {
            "overall": confidence,
            "intent": confidence,
            "entities": None,
            "parameters": None,
        },
        "provenance": provenance,
    }
    if _claimed_source_has_business_context(source):
        result.update(
            {
                "constraints": [
                    {
                        "constraint_type": "BUSINESS_CONTEXT_AUTHORITY",
                        "description": (
                            "The delegated business request context is input, not "
                            "accounting authority."
                        ),
                    },
                    {
                        "constraint_type": "CLAIMED_WORK_AUTHORITY",
                        "description": (
                            "WC claim lineage and owner-service facts remain "
                            "authoritative."
                        ),
                    },
                ],
                "business_request_context": source["business_request_context"],
                "business_context_hash": source["business_context_hash"],
            }
        )
    result["intent_hash"] = semantic_sha256_hash_ref(result)
    return _validate_work_intent(result)


class SqlAlchemyWorkIntentRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(
        self,
        *,
        tenant_id: str,
        work_intent: Mapping[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        tenant_id = _require_text("tenant_id", tenant_id, maximum=200)
        _require_datetime("created_at", created_at)
        normalized = _validate_work_intent(work_intent)
        params = {
            "tenant_id": tenant_id,
            "work_intent_id": normalized["work_intent_id"],
            "intent_revision": normalized["intent_revision"],
            "agent_execution_id": normalized["execution_id"],
            "supersedes_work_intent_id": normalized.get(
                "supersedes_work_intent_id"
            ),
            "source_ref": normalized["source"]["source_ref"],
            "actor_ref": normalized["source"]["actor_ref"],
            "compatibility_execution_mode": normalized[
                "compatibility_execution_mode"
            ],
            "work_class": normalized["work_class"],
            "intent_hash": normalized["intent_hash"],
            "intent_json": canonical_json(normalized),
            "created_at": created_at,
        }
        try:
            with self._session_factory() as session:
                _require_superseded_revision(session, params)
                session.execute(
                    text(_intent_insert_sql(_dialect_name(session))), params
                )
                saved = _load_work_intent(
                    session, tenant_id, str(normalized["work_intent_id"])
                )
                if saved is None:
                    conflict = _load_work_intent_by_revision(
                        session,
                        tenant_id,
                        str(normalized["execution_id"]),
                        int(normalized["intent_revision"]),
                    )
                    if conflict is not None:
                        raise WorkIntentError(
                            "ae.work_intent_revision_conflict",
                            "A different WorkIntent already owns this execution revision.",
                        )
                    raise WorkIntentError(
                        "ae.work_intent_write_conflict",
                        "WorkIntent could not be reloaded after persistence.",
                        True,
                    )
                if saved != normalized:
                    raise WorkIntentError(
                        "ae.work_intent_immutable_conflict",
                        "WorkIntent identity already exists with different content.",
                    )
                session.commit()
                return saved
        except WorkIntentError:
            raise
        except SQLAlchemyError as exc:
            raise WorkIntentError(
                "ae.work_intent_store_unavailable",
                "AE WorkIntent store is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, work_intent_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _require_text("tenant_id", tenant_id, maximum=200)
        _require_uuid("work_intent_id", work_intent_id)
        try:
            with self._session_factory() as session:
                return _load_work_intent(session, tenant_id, work_intent_id)
        except SQLAlchemyError as exc:
            raise WorkIntentError(
                "ae.work_intent_store_unavailable",
                "AE WorkIntent store is unavailable.",
                True,
            ) from exc

    def get_latest_for_execution(
        self, *, tenant_id: str, execution_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _require_text("tenant_id", tenant_id, maximum=200)
        _require_uuid("execution_id", execution_id)
        try:
            with self._session_factory() as session:
                return _load_latest_work_intent(session, tenant_id, execution_id)
        except SQLAlchemyError as exc:
            raise WorkIntentError(
                "ae.work_intent_store_unavailable",
                "AE WorkIntent store is unavailable.",
                True,
            ) from exc


def _build_provenance(
    *,
    schema_version: str,
    decision_hash: str,
    input_context_hash: str,
    prompt_provenance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    values = dict(prompt_provenance or {})
    prompt_fields = (
        "prompt_binding_key",
        "prompt_template_version_id",
        "prompt_content_sha256",
        "rendered_prompt_hash",
    )
    present = [values.get(field) is not None for field in prompt_fields]
    if any(present) and not all(present):
        raise _invalid("Prompt provenance must capture one exact complete version.")
    if all(present):
        _require_text("prompt_binding_key", values["prompt_binding_key"], maximum=200)
        _require_uuid(
            "prompt_template_version_id", values["prompt_template_version_id"]
        )
        validate_sha256_digest(values["prompt_content_sha256"])
        validate_sha256_digest(values["rendered_prompt_hash"])
    for field, maximum in (("model_profile", 128), ("model_ref", 256)):
        if values.get(field) is not None:
            _require_text(field, values[field], maximum=maximum)
    return {
        "resolver_type": (
            "LLM_CANDIDATE" if all(present) else "DETERMINISTIC_POLICY"
        ),
        "intent_decision_schema_version": schema_version,
        "intent_decision_hash": decision_hash,
        "input_context_hash": input_context_hash,
        "prompt_binding_key": values.get("prompt_binding_key"),
        "prompt_template_version_id": values.get("prompt_template_version_id"),
        "prompt_content_sha256": values.get("prompt_content_sha256"),
        "rendered_prompt_hash": values.get("rendered_prompt_hash"),
        "model_profile": values.get("model_profile"),
        "model_ref": values.get("model_ref"),
    }


def _validate_work_intent(value: Mapping[str, Any]) -> dict[str, Any]:
    record = json.loads(canonical_json(dict(value)))
    schema_version = record.get("schema_version")
    if schema_version not in {
        WORK_INTENT_SCHEMA_VERSION,
        BUSINESS_WORK_INTENT_SCHEMA_VERSION,
    }:
        raise _invalid("WorkIntent schema_version must be 1.1 or 1.2.")
    _require_uuid("work_intent_id", record.get("work_intent_id"))
    _require_uuid("execution_id", record.get("execution_id"))
    _validate_revision(
        record.get("intent_revision"), record.get("supersedes_work_intent_id")
    )
    source = record.get("source")
    if not isinstance(source, dict) or source.get("source_type") not in {
        "PROMPT",
        "CLAIMED_WORKITEM",
    }:
        raise _invalid("WorkIntent source is unsupported.")
    expected_mode = (
        "INTERACTIVE" if source.get("source_type") == "PROMPT" else "BACKGROUND"
    )
    if record.get("execution_mode") != expected_mode:
        raise _invalid("WorkIntent execution_mode does not match its source.")
    if record.get("compatibility_execution_mode") not in _MODE_PROFILE:
        raise _invalid("WorkIntent compatibility execution mode is unsupported.")
    if schema_version == BUSINESS_WORK_INTENT_SCHEMA_VERSION:
        _validate_business_work_intent(record)
    validate_hash_ref(record.get("intent_hash"))
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "intent_hash"}
    )
    if record["intent_hash"] != expected_hash:
        raise _invalid("WorkIntent intent_hash does not match its semantic content.")
    return record


def _validate_business_work_intent(record: Mapping[str, Any]) -> None:
    if (
        record.get("intent_label") != BUSINESS_TRANSACTION_INTENT_LABEL
        or record.get("work_class") != "BUSINESS_TRANSACTION"
        or BUSINESS_TRANSACTION_INTENT_LABEL
        not in record.get("required_capability_hints", ())
    ):
        raise _invalid("WorkIntent v1.2 is reserved for the admitted M1 business path.")
    try:
        context = validate_business_request_context(
            record.get("business_request_context")
        )
    except BusinessRequestContextError as exc:
        raise WorkIntentError(exc.error_code, exc.detail) from exc
    if record.get("business_context_hash") != context["context_hash"]:
        raise _invalid("WorkIntent business_context_hash does not match its context.")
    source = record.get("source")
    provenance = record.get("provenance")
    if not isinstance(source, Mapping) or not isinstance(provenance, Mapping):
        raise _invalid("WorkIntent business context provenance does not match.")
    if source.get("source_type") == "PROMPT" and (
        source.get("source_ref") != context["source_prompt_ref"]
        or provenance.get("input_context_hash")
        != context["candidate_provenance"]["input_context_hash"]
        or provenance.get("model_profile")
        != context["candidate_provenance"]["model_profile"]
        or provenance.get("model_ref")
        != context["candidate_provenance"]["model_ref"]
    ):
        raise _invalid("WorkIntent business context provenance does not match.")
    if source.get("source_type") == "CLAIMED_WORKITEM" and not record.get(
        "project_ref"
    ):
        raise _invalid("Claimed business WorkIntent requires Project authority.")


def _claimed_planning_source(value: Mapping[str, Any]) -> dict[str, Any]:
    base_fields = {
        "schema_version",
        "source_type",
        "source_ref",
        "goal",
        "work_class",
        "required_capability",
        "project_ref",
        "artifact_refs",
        "evidence_refs",
        "completion_policy",
        "result_contract_ref",
    }
    v2_fields = base_fields | {
        "delegation_identity",
        "business_request_context",
        "business_context_hash",
    }
    v3_fields = base_fields | {"delegation_identity", "semantic_handoff"}
    v3_business_fields = v3_fields | {
        "business_request_context",
        "business_context_hash",
    }
    if not isinstance(value, Mapping):
        raise _invalid("Claimed planning source fields are invalid.")
    result = dict(value)
    schema_version = result.get("schema_version")
    expected_fields = base_fields
    if schema_version == "p7.claimed_work_planning_source.v2":
        expected_fields = v2_fields
    elif schema_version == "p7.claimed_work_planning_source.v3":
        expected_fields = (
            v3_business_fields
            if "business_request_context" in result
            else v3_fields
        )
    if (
        set(result) != expected_fields
        or schema_version
        not in {
            "p7.claimed_work_planning_source.v1",
            "p7.claimed_work_planning_source.v2",
            "p7.claimed_work_planning_source.v3",
        }
        or result.get("source_type") != "CLAIMED_WORKITEM"
    ):
        raise _invalid("Claimed planning source version or type is invalid.")
    _require_text("source_ref", result.get("source_ref"), maximum=200)
    _require_text("goal", result.get("goal"), maximum=4000)
    _require_text("work_class", result.get("work_class"), maximum=64)
    _require_text(
        "required_capability", result.get("required_capability"), maximum=160
    )
    _require_text(
        "result_contract_ref", result.get("result_contract_ref"), maximum=512
    )
    project = result.get("project_ref")
    if (
        not isinstance(project, Mapping)
        or project.get("entity_type") != "PROJECT"
        or not isinstance(project.get("entity_id"), str)
        or not project["entity_id"].strip()
    ):
        raise _invalid("Claimed planning source project_ref is invalid.")
    if (
        schema_version == "p7.claimed_work_planning_source.v1"
        and result.get("required_capability") == BUSINESS_TRANSACTION_INTENT_LABEL
    ):
        raise _invalid("M1 claimed work requires business planning source v2.")
    if _claimed_source_has_business_context(result):
        if (
            result.get("work_class") != "BUSINESS_TRANSACTION"
            or result.get("required_capability")
            != BUSINESS_TRANSACTION_INTENT_LABEL
        ):
            raise _invalid("Claimed business planning source profile is invalid.")
        try:
            context = validate_business_request_context(
                result.get("business_request_context")
            )
        except BusinessRequestContextError as exc:
            raise WorkIntentError(exc.error_code, exc.detail) from exc
        if result.get("business_context_hash") != context["context_hash"]:
            raise _invalid("Claimed planning business context hash is invalid.")
        identity = result.get("delegation_identity")
        if not isinstance(identity, Mapping) or set(identity) != {
            "delegation_id",
            "delegation_revision",
            "requester_ref",
            "parent_agent_execution_id",
        }:
            raise _invalid("Claimed planning delegation identity is invalid.")
        result["business_request_context"] = context
    if schema_version == "p7.claimed_work_planning_source.v3":
        identity = result.get("delegation_identity")
        if not isinstance(identity, Mapping) or set(identity) != {
            "delegation_id",
            "delegation_revision",
            "requester_ref",
            "parent_agent_execution_id",
        }:
            raise _invalid("Claimed planning delegation identity is invalid.")
        for field in (
            "delegation_id",
            "requester_ref",
            "parent_agent_execution_id",
        ):
            _require_text(
                f"delegation_identity.{field}", identity.get(field), maximum=200
            )
        revision = identity.get("delegation_revision")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
        ):
            raise _invalid("Claimed planning delegation revision is invalid.")
        try:
            handoff = validate_semantic_handoff_projection(
                result.get("semantic_handoff")
            )
        except SemanticHandoffError as exc:
            raise _invalid(str(exc)) from exc
        if (
            handoff["parent_execution_id"]
            != identity["parent_agent_execution_id"]
            or handoff["owner_subject_id"] != identity["requester_ref"]
        ):
            raise _invalid("Claimed planning semantic handoff lineage is invalid.")
        result["delegation_identity"] = dict(identity)
        result["semantic_handoff"] = handoff
    return result


def _claimed_source_has_business_context(value: Mapping[str, Any]) -> bool:
    return (
        "business_request_context" in value or "business_context_hash" in value
    )


def _validate_revision(revision: object, supersedes: object) -> None:
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or not 1 <= revision <= 99
    ):
        raise _invalid("intent_revision must be between 1 and 99.")
    if revision == 1 and supersedes is not None:
        raise _invalid("The first WorkIntent revision cannot supersede another revision.")
    if revision > 1 and supersedes is None:
        raise _invalid("A revised WorkIntent must identify the superseded revision.")


def _require_superseded_revision(session: Session, params: Mapping[str, Any]) -> None:
    if int(params["intent_revision"]) == 1:
        return
    previous = _load_work_intent(
        session,
        str(params["tenant_id"]),
        str(params["supersedes_work_intent_id"]),
    )
    if (
        previous is None
        or previous["execution_id"] != params["agent_execution_id"]
        or int(previous["intent_revision"]) != int(params["intent_revision"]) - 1
    ):
        raise WorkIntentError(
            "ae.work_intent_revision_chain_invalid",
            "WorkIntent revision must supersede the preceding execution revision.",
        )


def _intent_insert_sql(dialect_name: str) -> str:
    intent_json = (
        "CAST(:intent_json AS jsonb)" if dialect_name == "postgresql" else ":intent_json"
    )
    return f"""
        INSERT INTO ae_work_intent (
            tenant_id, work_intent_id, intent_revision, agent_execution_id,
            supersedes_work_intent_id, source_ref, actor_ref,
            compatibility_execution_mode, work_class, intent_hash,
            intent_json, created_at
        ) VALUES (
            :tenant_id, :work_intent_id, :intent_revision, :agent_execution_id,
            :supersedes_work_intent_id, :source_ref, :actor_ref,
            :compatibility_execution_mode, :work_class, :intent_hash,
            {intent_json}, :created_at
        ) ON CONFLICT DO NOTHING
    """


def _load_work_intent(
    session: Session, tenant_id: str, work_intent_id: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT intent_json FROM ae_work_intent
            WHERE tenant_id = :tenant_id AND work_intent_id = :work_intent_id
            """
        ),
        {"tenant_id": tenant_id, "work_intent_id": work_intent_id},
    ).mappings().first()
    return None if row is None else _json_value(row["intent_json"])


def _load_work_intent_by_revision(
    session: Session, tenant_id: str, execution_id: str, revision: int
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT intent_json FROM ae_work_intent
            WHERE tenant_id = :tenant_id
              AND agent_execution_id = :execution_id
              AND intent_revision = :revision
            """
        ),
        {
            "tenant_id": tenant_id,
            "execution_id": execution_id,
            "revision": revision,
        },
    ).mappings().first()
    return None if row is None else _json_value(row["intent_json"])


def _load_latest_work_intent(
    session: Session, tenant_id: str, execution_id: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT intent_json FROM ae_work_intent
            WHERE tenant_id = :tenant_id
              AND agent_execution_id = :execution_id
            ORDER BY intent_revision DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "execution_id": execution_id},
    ).mappings().first()
    return None if row is None else _json_value(row["intent_json"])


def _json_value(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value)


def _require_uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID string.")
    try:
        UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID string.") from exc
    return value


def _require_text(field: str, value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(f"{field} must be a non-empty string up to {maximum} characters.")
    return value.strip()


def _require_datetime(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an RFC 3339 date-time string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 date-time string.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone offset.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> WorkIntentError:
    return WorkIntentError("ae.work_intent_invalid", detail)
