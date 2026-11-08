from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, Literal, Mapping, Any, Iterable

DeliveryState = Literal[
    "PENDING","SENDING","ACKNOWLEDGED","RETRY_PENDING","UNKNOWN_DELIVERY","FAILED","CANCELLED"
]
PublicationOutcomeStatus = Literal[
    "CONFIRMED_ACKNOWLEDGED","CONFIRMED_NOT_DELIVERED","STILL_UNKNOWN","CONFLICT"
]
PublicationNextAction = Literal[
    "MARK_ACKNOWLEDGED","RETRY_SAME_IDENTITY","CHECK_LATER","ESCALATE"
]

@dataclass(frozen=True)
class PublicationIdentityV21:
    publication_operation_id: str
    idempotency_key_ref: str

@dataclass(frozen=True)
class PublicationReconciliationOutcomeV21:
    publication_reconciliation_id: str
    status: PublicationOutcomeStatus
    authoritative_query_ref: str
    next_action: PublicationNextAction
    evidence_refs: tuple[str, ...]
    external_delivery_ref: str | None = None

class ResultPublicationAuthorizationPortV21(Protocol):
    def preflight(self, *, tenant_id: str, agent_execution_id: str, result_id: str,
                  delivery_id: str, target_type: str, target_ref: str) -> Mapping[str, Any]: ...

class ResultDeliveryRepositoryV21(Protocol):
    def persist_result_and_deliveries_atomically(self, *, result: Mapping[str, Any],
                                                  deliveries: Iterable[Mapping[str, Any]]) -> None: ...
    def mark_acknowledged(self, *, tenant_id: str, delivery_id: str,
                          external_delivery_ref: str | None) -> None: ...

class ResultPublicationAdapterV21(Protocol):
    def publish(self, *, target_type: str, target_ref: str, result: Mapping[str, Any],
                publication_operation_id: str, idempotency_key_ref: str) -> Mapping[str, Any]: ...

class PublicationReconciliationAdapterV21(Protocol):
    def reconcile(self, *, target_type: str, target_ref: str,
                  publication_operation_id: str, idempotency_key_ref: str,
                  external_delivery_ref: str | None) -> PublicationReconciliationOutcomeV21: ...

def derive_publication_identity(*, result_id: str, target_type: str,
                                target_ref: str, result_hash: str) -> PublicationIdentityV21:
    semantic = "|".join((result_id, target_type, target_ref, result_hash)).encode("utf-8")
    digest = sha256(semantic).hexdigest()
    return PublicationIdentityV21(
        publication_operation_id=f"PUBOP:{digest}",
        idempotency_key_ref=f"PUBIDEMP:{digest}",
    )

def publication_retry_action(*, state: DeliveryState) -> str:
    if state == "UNKNOWN_DELIVERY":
        return "RECONCILE_FIRST"
    if state in ("PENDING", "RETRY_PENDING"):
        return "PUBLISH_SAME_IDENTITY"
    if state == "ACKNOWLEDGED":
        return "NO_ACTION"
    return "POLICY_OR_ESCALATE"

def can_finalize_success(deliveries: Iterable[Mapping[str, Any]]) -> bool:
    for d in deliveries:
        if bool(d.get("required")) and d.get("state") != "ACKNOWLEDGED":
            return False
    return True


BACKGROUND_AGENT_TYPES = {"CA", "PA", "EA"}

def validate_background_result_lineage(result: Mapping[str, Any]) -> bool:
    if result.get("agent_type") not in BACKGROUND_AGENT_TYPES:
        return True
    required = ("source_work_item_ref", "source_claim_ref", "source_claim_generation",
                "source_claimant_agent_id", "source_assignment_ref")
    return all(result.get(k) not in (None, "") for k in required)

def validate_delivery_plan(*, result: Mapping[str, Any], deliveries: Iterable[Mapping[str, Any]]) -> bool:
    rows = list(deliveries)
    if result.get("agent_type") in BACKGROUND_AGENT_TYPES:
        wc = [d for d in rows if d.get("target_type") == "WC_WORK_RESULT"]
        if len(wc) != 1 or wc[0].get("required") is not True:
            return False
        if not validate_background_result_lineage(result):
            return False
    return True

def wc_work_result_preflight_allows(preflight: Mapping[str, Any]) -> bool:
    if preflight.get("target_type") != "WC_WORK_RESULT":
        return preflight.get("decision") == "ALLOW"
    required_true = ("claim_status_checked", "claim_generation_current", "claimant_matches",
                     "assignment_matches", "execution_matches")
    return (preflight.get("decision") == "ALLOW" and
            bool(preflight.get("work_claim_lineage_ref")) and
            all(preflight.get(k) is True for k in required_true))
