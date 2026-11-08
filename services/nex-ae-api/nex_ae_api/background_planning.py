from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.agent_context import TrustedContextResolution
from nex_ae_api.agent_execution import (
    AgentExecutionError,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.semantic_candidate_admission import (
    DeterministicCandidateAdmissionService,
    SemanticCandidateAdmissionError,
    SemanticCandidateAdmissionRequest,
    SemanticCandidateAdmissionResult,
)


@dataclass(frozen=True)
class BackgroundPlanningError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class BackgroundAgentPlanningService:
    semantic_admission: DeterministicCandidateAdmissionService = field(repr=False)
    executions: SqlAlchemyAgentExecutionRepository = field(repr=False)

    def plan_claimed_execution(
        self,
        *,
        tenant_id: str,
        execution_id: str,
        runtime_policy_ref: Mapping[str, Any],
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> SemanticCandidateAdmissionResult:
        try:
            execution = self.executions.get(tenant_id, execution_id)
            planning_source = self.executions.get_claimed_planning_source(
                tenant_id, execution_id
            )
        except AgentExecutionError as exc:
            raise BackgroundPlanningError(
                exc.error_code, exc.detail, exc.retryable
            ) from exc
        if execution is None or planning_source is None:
            raise BackgroundPlanningError(
                "ae.background_planning_source_missing",
                "Background planning requires an admitted execution and durable source.",
            )
        _require_execution_source(execution, planning_source)
        snapshot = self.semantic_admission.capabilities.get_latest(
            tenant_id=tenant_id
        )
        if snapshot is None:
            raise BackgroundPlanningError(
                "ae.background_planning_capability_snapshot_missing",
                "Background planning requires an active capability snapshot.",
            )
        resolver = _ClaimedWorkContextResolver(
            tenant_id=tenant_id,
            principal_id=str(execution["requester_ref"]),
            agent_id=str(execution["agent_id"]),
            execution_id=execution_id,
            planning_source=planning_source,
            as_of=str(execution["received_at"]),
        )
        compatibility_ids = {
            name: str(
                uuid5(
                    NAMESPACE_URL,
                    f"nex:p7:background-planning:{execution_id}:{name}",
                )
            )
            for name in ("workspace", "conversation", "interaction")
        }
        prompt = str(planning_source["goal"])
        labels = [
            str(item["entity_id"])
            for field_name in ("artifact_refs", "evidence_refs")
            for item in planning_source[field_name]
        ][:32]
        trusted_mode, retrieval_enabled = _trusted_execution_profile(
            planning_source
        )
        try:
            return self.semantic_admission.admit_and_compile(
                SemanticCandidateAdmissionRequest(
                    tenant_id=tenant_id,
                    owner_subject_id=str(execution["requester_ref"]),
                    profile_ref=f"urn:nex:agent-profile:{str(execution['agent_type']).lower()}:background:v1",
                    interaction_id=compatibility_ids["interaction"],
                    workspace_id=compatibility_ids["workspace"],
                    conversation_id=compatibility_ids["conversation"],
                    correlation_id=str(execution["correlation_id"]),
                    causation_id=execution.get("causation_id"),
                    request_id=request_id or f"p7-background:{execution_id}",
                    trace_id=trace_id or _trace_id(execution),
                    user_prompt=prompt,
                    base_context={
                        "interaction_text": prompt,
                        "conversation_summary": None,
                        "resource_label_hints": labels,
                    },
                    runtime_policy_ref=runtime_policy_ref,
                    context_resolver=resolver,
                    capability_snapshot=snapshot,
                    retrieval_enabled=retrieval_enabled,
                    authorized_resource_context_available=(
                        bool(labels) or retrieval_enabled
                    ),
                    trusted_execution_mode=trusted_mode,
                    planning_source_type="CLAIMED_WORKITEM",
                    existing_execution_id=execution_id,
                    agent_type=str(execution["agent_type"]),
                    project_id=str(execution["project_id"]),
                    source_ref=str(execution["work_item_ref"]),
                    planning_source=planning_source,
                )
            )
        except SemanticCandidateAdmissionError as exc:
            raise BackgroundPlanningError(
                exc.error_code, exc.detail, exc.retryable
            ) from exc


@dataclass(frozen=True)
class _ClaimedWorkContextResolver:
    tenant_id: str
    principal_id: str
    agent_id: str
    execution_id: str
    planning_source: Mapping[str, Any] = field(repr=False)
    as_of: str

    def resolve(self, request: Any) -> TrustedContextResolution:
        if (
            request.tenant_id != self.tenant_id
            or request.principal_id != self.principal_id
            or request.agent_id != self.agent_id
            or request.execution_id != self.execution_id
            or request.agent_type not in {"CA", "PA", "EA"}
            or request.source_type != "CLAIMED_WORKITEM"
            or request.source_ref != self.planning_source["source_ref"]
        ):
            raise BackgroundPlanningError(
                "ae.background_context_scope_mismatch",
                "Claimed WorkItem context resolver scope does not match execution.",
            )
        resources = tuple(
            _resource_ref(item)
            for field_name in ("artifact_refs", "evidence_refs")
            for item in self.planning_source[field_name]
        )
        source_hash = semantic_sha256_hash_ref(self.planning_source)
        return TrustedContextResolution(
            project_ref={
                "system": "nex-wc",
                "resource_type": "PROJECT",
                "resource_id": self.planning_source["project_ref"]["entity_id"],
            },
            authority_ref=f"WC:WORK_ITEM:{self.planning_source['source_ref']}",
            resolved_entities=(),
            retrieval_refs=resources,
            evidence_refs=resources,
            conflicts=(),
            degradations=(),
            context_manifest=(
                {
                    "kind": "CLAIMED_WORKITEM_REF",
                    "source_ref": f"WC:WORK_ITEM:{self.planning_source['source_ref']}",
                    "source_version": source_hash,
                    "content_hash": source_hash,
                    "as_of": self.as_of,
                },
            ),
            budget_tokens=4096,
            estimated_used_tokens=min(1024, 256 + 64 * len(resources)),
        )


def _require_execution_source(
    execution: Mapping[str, Any], planning_source: Mapping[str, Any]
) -> None:
    if (
        execution.get("source_type") != "CLAIMED_WORKITEM"
        or execution.get("agent_type") not in {"CA", "PA", "EA"}
        or execution.get("work_item_ref") != planning_source.get("source_ref")
        or execution.get("project_id")
        != planning_source.get("project_ref", {}).get("entity_id")
    ):
        raise BackgroundPlanningError(
            "ae.background_planning_lineage_conflict",
            "Durable planning source does not match claimed execution lineage.",
        )


def _resource_ref(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "system": "nex-wc",
        "resource_type": str(value["entity_type"]),
        "resource_id": str(value["entity_id"]),
        **({"version": str(value["version"])} if value.get("version") is not None else {}),
    }


def _trace_id(execution: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        f"{execution['tenant_id']}|{execution['agent_execution_id']}|{execution['correlation_id']}".encode(
            "utf-8"
        )
    ).hexdigest()[:32]


def _trusted_execution_profile(
    planning_source: Mapping[str, Any],
) -> tuple[str, bool]:
    work_class = str(planning_source.get("work_class") or "").upper()
    if work_class == "DOCUMENT":
        return "DOCUMENT_GENERATION", True
    if work_class == "ANALYSIS":
        return "DOCUMENT_SUMMARY", True
    has_authorized_resources = any(
        planning_source.get(field_name)
        for field_name in ("artifact_refs", "evidence_refs")
    )
    if has_authorized_resources:
        return "GROUNDED_ANSWER", True
    return "GENERAL_ANSWER", False
