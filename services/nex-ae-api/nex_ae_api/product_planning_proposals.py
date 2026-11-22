from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_ae_api.plan_candidate_generation import parse_plan_candidate
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCoordinatorRegistration,
)
from nex_ae_api.semantic_candidate_evidence import (
    validate_semantic_candidate_evidence,
)

PRODUCT_PLANNING_PROPOSAL_SCHEMA_VERSION = "ae.product_planning_proposal.v1"
PRODUCT_PLANNING_PROPOSAL_REF_SCHEMA_VERSION = "ae.product_planning_proposal_ref.v1"


class ProductPlanningProposalError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def build_product_planning_proposal(
    *,
    evidence: Mapping[str, Any],
    candidate: Mapping[str, Any],
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
    registration: ProductPlanningCoordinatorRegistration,
    admitted_capability_ids: Sequence[str],
) -> dict[str, Any]:
    normalized_evidence = validate_semantic_candidate_evidence(evidence)
    normalized_candidate = parse_plan_candidate(_canonical_candidate(candidate))
    if registration.planning_policy.mode == "DETERMINISTIC_ONLY":
        raise _invalid("Deterministic-only Product planning cannot build a proposal.")
    if (
        registration.planning_policy.proposal_schema_version
        != PRODUCT_PLANNING_PROPOSAL_SCHEMA_VERSION
    ):
        raise _invalid("Product proposal schema differs from its registration.")
    if (
        normalized_evidence["semantic_stage"] != "PLAN"
        or normalized_evidence["validation_outcome"] != "ADMITTED"
        or normalized_evidence["directive"] != "CONTINUE"
    ):
        raise _invalid("Product proposal requires admitted PLAN evidence.")
    if (
        normalized_evidence["prompt_binding_key"]
        != registration.planning_policy.prompt_binding_key
    ):
        raise _conflict("Product proposal policy binding has drifted.")
    candidate_hash = semantic_sha256_hash_ref(normalized_candidate)
    if normalized_evidence["candidate_hash"] != candidate_hash:
        raise _conflict("Product proposal candidate hash has drifted.")

    execution_id = _text(work_intent.get("execution_id"), "execution_id", 64)
    if (
        normalized_evidence["execution_id"] != execution_id
        or agent_context.get("execution_id") != execution_id
    ):
        raise _conflict("Product proposal execution lineage has drifted.")
    work_intent_id = _text(work_intent.get("work_intent_id"), "work_intent_id", 64)
    work_intent_hash = _hash(work_intent.get("intent_hash"), "work_intent_hash")
    context_id = _text(agent_context.get("context_id"), "context_id", 64)
    context_hash = _hash(agent_context.get("context_hash"), "context_hash")
    work_ref = agent_context.get("work_intent_ref")
    if not isinstance(work_ref, Mapping) or (
        work_ref.get("id") != work_intent_id or work_ref.get("hash") != work_intent_hash
    ):
        raise _conflict("Product proposal WorkIntent context has drifted.")

    admitted = _capability_ids(admitted_capability_ids)
    suggested = tuple(
        sorted(
            {
                _text(item.get("capability_hint"), "capability_hint", 160)
                for item in normalized_candidate["logical_steps"]
            }
        )
    )
    if any(item not in admitted for item in suggested):
        raise _invalid("Product proposal suggests an unadmitted capability.")

    proposal = {
        "schema_version": PRODUCT_PLANNING_PROPOSAL_SCHEMA_VERSION,
        "tenant_id": normalized_evidence["tenant_id"],
        "owner_subject_id": normalized_evidence["owner_subject_id"],
        "execution_id": execution_id,
        "work_intent_ref": {
            "work_intent_id": work_intent_id,
            "intent_hash": work_intent_hash,
        },
        "agent_context_ref": {
            "context_id": context_id,
            "context_hash": context_hash,
        },
        "coordinator_ref": {
            "coordinator_id": registration.coordinator_id,
            "coordinator_version": registration.coordinator_version,
            "coordinator_registration_hash": registration.registration_hash,
        },
        "planning_policy": registration.planning_policy.projection(),
        "candidate_ref": {
            "candidate_id": normalized_evidence["candidate_id"],
            "candidate_hash": candidate_hash,
            "storage_ref": normalized_evidence["candidate_payload_storage_ref"],
            "size_bytes": normalized_evidence["candidate_payload_size_bytes"],
        },
        "suggested_capability_ids": list(suggested),
        "provider_provenance": {
            field: normalized_evidence[field]
            for field in (
                "prompt_binding_key",
                "prompt_template_version_id",
                "prompt_template_version",
                "prompt_content_sha256",
                "rendered_prompt_hash",
                "model_profile",
                "model_ref",
                "deployment_id",
                "mo_generation_id",
                "request_id",
                "trace_id",
                "admission_policy_ref",
            )
        },
        "created_at": normalized_evidence["created_at"],
        "content_included": False,
        "provider_plan_authoritative": False,
    }
    proposal["proposal_hash"] = semantic_sha256_hash_ref(proposal)
    return validate_product_planning_proposal(proposal)


def product_planning_proposal_reference(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    proposal = validate_product_planning_proposal(value)
    candidate = proposal["candidate_ref"]
    return validate_product_planning_proposal_reference(
        {
            "schema_version": PRODUCT_PLANNING_PROPOSAL_REF_SCHEMA_VERSION,
            "proposal_hash": proposal["proposal_hash"],
            "candidate_id": candidate["candidate_id"],
            "candidate_hash": candidate["candidate_hash"],
            "candidate_payload_storage_ref": candidate["storage_ref"],
        }
    )


def validate_product_planning_proposal_reference(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Product planning proposal reference must be an object.")
    reference = dict(value)
    if set(reference) != {
        "schema_version",
        "proposal_hash",
        "candidate_id",
        "candidate_hash",
        "candidate_payload_storage_ref",
    } or reference.get("schema_version") != (
        PRODUCT_PLANNING_PROPOSAL_REF_SCHEMA_VERSION
    ):
        raise _invalid("Product planning proposal reference fields are invalid.")
    _hash(reference["proposal_hash"], "proposal_hash")
    _text(reference["candidate_id"], "candidate_id", 64)
    _hash(reference["candidate_hash"], "candidate_hash")
    _text(
        reference["candidate_payload_storage_ref"],
        "candidate_payload_storage_ref",
        512,
    )
    return reference


def validate_product_planning_proposal(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Product planning proposal must be an object.")
    proposal = dict(value)
    fields = {
        "schema_version",
        "tenant_id",
        "owner_subject_id",
        "execution_id",
        "work_intent_ref",
        "agent_context_ref",
        "coordinator_ref",
        "planning_policy",
        "candidate_ref",
        "suggested_capability_ids",
        "provider_provenance",
        "created_at",
        "content_included",
        "provider_plan_authoritative",
        "proposal_hash",
    }
    if set(proposal) != fields or proposal.get("schema_version") != (
        PRODUCT_PLANNING_PROPOSAL_SCHEMA_VERSION
    ):
        raise _invalid("Product planning proposal fields do not match v1.")
    for field, maximum in (
        ("tenant_id", 128),
        ("owner_subject_id", 200),
        ("execution_id", 64),
        ("created_at", 64),
    ):
        _text(proposal.get(field), field, maximum)
    _reference(
        proposal.get("work_intent_ref"),
        {"work_intent_id", "intent_hash"},
        "work_intent_ref",
    )
    _reference(
        proposal.get("agent_context_ref"),
        {"context_id", "context_hash"},
        "agent_context_ref",
    )
    coordinator = _mapping(proposal.get("coordinator_ref"), "coordinator_ref")
    if set(coordinator) != {
        "coordinator_id",
        "coordinator_version",
        "coordinator_registration_hash",
    }:
        raise _invalid("Product proposal coordinator reference is invalid.")
    _text(coordinator["coordinator_id"], "coordinator_id", 160)
    _text(coordinator["coordinator_version"], "coordinator_version", 64)
    _hash(
        coordinator["coordinator_registration_hash"],
        "coordinator_registration_hash",
    )
    policy = _mapping(proposal.get("planning_policy"), "planning_policy")
    if not policy:
        raise _invalid("Product proposal planning policy is unavailable.")
    candidate = _mapping(proposal.get("candidate_ref"), "candidate_ref")
    if set(candidate) != {
        "candidate_id",
        "candidate_hash",
        "storage_ref",
        "size_bytes",
    }:
        raise _invalid("Product proposal candidate reference is invalid.")
    _text(candidate["candidate_id"], "candidate_id", 64)
    _hash(candidate["candidate_hash"], "candidate_hash")
    _text(candidate["storage_ref"], "storage_ref", 512)
    if (
        not isinstance(candidate["size_bytes"], int)
        or isinstance(candidate["size_bytes"], bool)
        or candidate["size_bytes"] < 1
    ):
        raise _invalid("Product proposal candidate size is invalid.")
    _capability_ids(proposal.get("suggested_capability_ids"))
    provenance = _mapping(proposal.get("provider_provenance"), "provider_provenance")
    if not provenance:
        raise _invalid("Product proposal provider provenance is unavailable.")
    if (
        proposal.get("content_included") is not False
        or proposal.get("provider_plan_authoritative") is not False
    ):
        raise _invalid(
            "Product proposal cannot include content or execution authority."
        )
    supplied_hash = _hash(proposal.get("proposal_hash"), "proposal_hash")
    body = {key: item for key, item in proposal.items() if key != "proposal_hash"}
    if supplied_hash != semantic_sha256_hash_ref(body):
        raise _conflict("Product planning proposal hash has drifted.")
    return proposal


def _canonical_candidate(value: Mapping[str, Any]) -> str:
    from nex_runtime.semantic_hashes import canonical_json

    try:
        return canonical_json(dict(value))
    except (TypeError, ValueError) as exc:
        raise _invalid("Product proposal candidate is invalid.") from exc


def _reference(value: object, fields: set[str], label: str) -> None:
    reference = _mapping(value, label)
    if set(reference) != fields:
        raise _invalid(f"Product proposal {label} is invalid.")
    identity_field = next(field for field in fields if field.endswith("_id"))
    hash_field = next(field for field in fields if field.endswith("_hash"))
    _text(reference[identity_field], identity_field, 64)
    _hash(reference[hash_field], hash_field)


def _capability_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("Product proposal capability identities are invalid.")
    normalized = tuple(_text(item, "capability_id", 160) for item in value)
    if (
        not normalized
        or len(normalized) > 32
        or len(set(normalized)) != len(normalized)
    ):
        raise _invalid("Product proposal capability identities are invalid.")
    return normalized


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"Product proposal {label} is invalid.")
    return value


def _hash(value: object, label: str) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"Product proposal {label} is invalid.") from exc


def _text(value: object, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise _invalid(f"Product proposal {label} is invalid.")
    return value


def _invalid(detail: str) -> ProductPlanningProposalError:
    return ProductPlanningProposalError("PRODUCT_PLANNING_PROPOSAL_INVALID", detail)


def _conflict(detail: str) -> ProductPlanningProposalError:
    return ProductPlanningProposalError("PRODUCT_PLANNING_PROPOSAL_CONFLICT", detail)
