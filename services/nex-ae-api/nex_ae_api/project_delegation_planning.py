from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.agent_context import TrustedContextResolution
from nex_ae_api.project_agent_lifecycle import AE_PROJECT_AGENT_SYNC_TABLE
from nex_ae_api.service_auth import resolve_ae_outbound_service_token

M1_PROJECT_DELEGATION_CAPABILITY_ID = "FINANCE.VOUCHER.APPROVE_AND_POST"
M1_PROJECT_DELEGATION_PROFILE_VERSION = "mybee-m1-project-delegation.v1"
M1_PROJECT_DELEGATION_ACTION = "finance:voucher-candidate:create"
M1_PROJECT_DELEGATION_RESULT_CONTRACT = (
    "contract://nex/mybee/finance/journal-posting-result/v1"
)


@dataclass(frozen=True)
class ProjectDelegationPlanningError(ValueError):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class EosProjectResolutionSource(Protocol):
    def resolve_active_project(
        self, *, tenant_id: str, subject_id: str, project_code: str
    ) -> Mapping[str, Any]: ...


class OaProjectDecisionSource(Protocol):
    def decide(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        project_code: str,
        action: str,
        correlation_id: str,
        minimum_source_version: int,
    ) -> Mapping[str, Any]: ...


class ActiveProjectAgentSource(Protocol):
    def resolve_active(
        self, *, tenant_id: str, project_code: str
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class HttpEosProjectResolutionSource:
    base_url: str
    service_token: str = field(repr=False)
    client: httpx.Client | None = field(default=None, repr=False, compare=False)
    timeout_seconds: float = 15.0

    def resolve_active_project(
        self, *, tenant_id: str, subject_id: str, project_code: str
    ) -> Mapping[str, Any]:
        token = resolve_ae_outbound_service_token(
            self.service_token, audience="nex-eos"
        )
        request = self.client or httpx
        try:
            response = request.get(
                self.base_url.rstrip("/") + "/internal/v2/projects:resolve",
                params={"project_code": project_code, "active_only": "true"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Cache-Control": "no-store, max-age=0",
                    "X-NeX-Tenant-Id": tenant_id,
                    "X-NeX-Subject-Id": subject_id,
                    "X-Service-ID": "nex-ae-api",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProjectDelegationPlanningError(
                "PROJECT_RESOLUTION_UNAVAILABLE",
                "EOS Project resolution is unavailable or denied.",
                retryable=isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)),
            ) from exc
        if not isinstance(body, Mapping):
            raise _invalid("EOS Project resolution response is malformed.")
        return dict(body)


@dataclass(frozen=True)
class HttpOaProjectDecisionSource:
    base_url: str
    service_token: str = field(repr=False)
    client: httpx.Client | None = field(default=None, repr=False, compare=False)
    timeout_seconds: float = 15.0

    def decide(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        project_code: str,
        action: str,
        correlation_id: str,
        minimum_source_version: int,
    ) -> Mapping[str, Any]:
        token = resolve_ae_outbound_service_token(self.service_token, audience="nex-oa")
        request = self.client or httpx
        try:
            response = request.post(
                self.base_url.rstrip("/") + "/internal/v1/auth/project-decisions",
                json={
                    "tenant_id": tenant_id,
                    "subject_id": subject_id,
                    "project_code": project_code,
                    "action": action,
                    "correlation_id": correlation_id,
                    "minimum_source_version": minimum_source_version,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Cache-Control": "no-store, max-age=0",
                    "X-Service-ID": "nex-ae-api",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProjectDelegationPlanningError(
                "PROJECT_AUTHORIZATION_UNAVAILABLE",
                "OA Project authorization is unavailable.",
                retryable=isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)),
            ) from exc
        decision = body.get("decision") if isinstance(body, Mapping) else None
        if not isinstance(decision, Mapping):
            raise _invalid("OA Project authorization response is malformed.")
        return dict(decision)


@dataclass(frozen=True)
class SqlAlchemyActiveProjectAgentSource:
    session_factory: sessionmaker[Session] = field(repr=False)

    def resolve_active(self, *, tenant_id: str, project_code: str) -> Mapping[str, Any]:
        try:
            with self.session_factory() as session:
                rows = (
                    session.execute(
                        select(AE_PROJECT_AGENT_SYNC_TABLE).where(
                            AE_PROJECT_AGENT_SYNC_TABLE.c.tenant_id == tenant_id,
                            AE_PROJECT_AGENT_SYNC_TABLE.c.project_code == project_code,
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise ProjectDelegationPlanningError(
                "PROJECT_AGENT_SOURCE_UNAVAILABLE",
                "AE Project Agent projection is unavailable.",
                retryable=True,
            ) from exc
        if len(rows) != 1:
            raise ProjectDelegationPlanningError(
                "PROJECT_AGENT_NOT_UNIQUE",
                "Exactly one synchronized Project Agent is required.",
            )
        row = dict(rows[0])
        if (
            row.get("project_state") != "ACTIVE"
            or row.get("agent_status") != "ACTIVE"
            or row.get("capability_mode") != "ORDINARY"
        ):
            raise ProjectDelegationPlanningError(
                "PROJECT_AGENT_NOT_ACTIVE",
                "The synchronized Project Agent is not active for ordinary work.",
            )
        return row


@dataclass(frozen=True)
class ProjectDelegationPlanningProfile:
    capability_id: str = M1_PROJECT_DELEGATION_CAPABILITY_ID
    profile_version: str = M1_PROJECT_DELEGATION_PROFILE_VERSION
    oa_action: str = M1_PROJECT_DELEGATION_ACTION
    result_contract_ref: str = M1_PROJECT_DELEGATION_RESULT_CONTRACT

    @property
    def source_identity(self) -> str:
        return "nex-ae:project-delegation:" + semantic_sha256_hash_ref(
            {
                "capability_id": self.capability_id,
                "profile_version": self.profile_version,
                "oa_action": self.oa_action,
                "result_contract_ref": self.result_contract_ref,
            }
        )


@dataclass(frozen=True)
class ProjectDelegationActivationResult:
    work_intent: Mapping[str, Any] = field(repr=False)
    context_resolver: Any = field(repr=False)


@dataclass(frozen=True)
class ProjectDelegationIntentActivator:
    eos: EosProjectResolutionSource = field(repr=False)
    oa: OaProjectDecisionSource = field(repr=False)
    project_agents: ActiveProjectAgentSource = field(repr=False)
    profile: ProjectDelegationPlanningProfile = field(
        default_factory=ProjectDelegationPlanningProfile
    )

    def activate(
        self,
        *,
        candidate: Mapping[str, Any],
        work_intent: Mapping[str, Any],
        tenant_id: str,
        principal_id: str,
        resolved_at: str,
    ) -> ProjectDelegationActivationResult:
        if work_intent.get("intent_label") != self.profile.capability_id:
            raise _invalid("Project delegation capability does not match WorkIntent.")
        project_code, selector = _one_project_code(candidate)
        project = dict(
            self.eos.resolve_active_project(
                tenant_id=tenant_id,
                subject_id=principal_id,
                project_code=project_code,
            )
        )
        if (
            project.get("project_code") != project_code
            or project.get("status") != "ACTIVE"
        ):
            raise _invalid("EOS did not resolve one active canonical Project.")
        version = _positive_int("project version", project.get("version"))
        decision = dict(
            self.oa.decide(
                tenant_id=tenant_id,
                subject_id=principal_id,
                project_code=project_code,
                action=self.profile.oa_action,
                correlation_id=str(work_intent.get("execution_id")),
                minimum_source_version=version,
            )
        )
        _require_allow_decision(
            decision,
            tenant_id=tenant_id,
            subject_id=principal_id,
            project_code=project_code,
            action=self.profile.oa_action,
            minimum_source_version=version,
        )
        agent = dict(
            self.project_agents.resolve_active(
                tenant_id=tenant_id, project_code=project_code
            )
        )
        if str(agent.get("project_code")) != project_code:
            raise _invalid("AE Project Agent projection does not match EOS Project.")
        activated = _activate_work_intent(
            work_intent,
            profile=self.profile,
            project_code=project_code,
            selector=selector,
        )
        return ProjectDelegationActivationResult(
            work_intent=activated,
            context_resolver=ProjectDelegationContextResolver(
                tenant_id=tenant_id,
                principal_id=principal_id,
                project=project,
                decision=decision,
                project_agent=agent,
                profile=self.profile,
                resolved_at=resolved_at,
            ),
        )


@dataclass(frozen=True)
class ProjectDelegationContextResolver:
    tenant_id: str
    principal_id: str
    project: Mapping[str, Any] = field(repr=False)
    decision: Mapping[str, Any] = field(repr=False)
    project_agent: Mapping[str, Any] = field(repr=False)
    profile: ProjectDelegationPlanningProfile
    resolved_at: str

    def resolve(self, _request: Any) -> TrustedContextResolution:
        project_id = str(self.project_agent["project_id"])
        project_code = str(self.project["project_code"])
        version = str(self.project["version"])
        authority_ref = str(self.decision["decision_ref"])
        authority_hash = semantic_sha256_hash_ref(dict(self.decision))
        project_hash = semantic_sha256_hash_ref(dict(self.project))
        return TrustedContextResolution(
            project_ref=None,
            authority_ref=authority_ref,
            resolved_entities=(
                {
                    "selector_id": "E1",
                    "resource_ref": {
                        "system": "nex-eos",
                        "resource_type": "PROJECT",
                        "resource_id": project_id,
                        "version": version,
                    },
                    "source_ref": f"EOS:PROJECT_CODE:{project_code}",
                    "resolved_at": self.resolved_at,
                },
            ),
            retrieval_refs=(),
            evidence_refs=(),
            conflicts=(),
            degradations=(),
            context_manifest=(
                {
                    "kind": "EOS_PROJECT_RESOLUTION",
                    "source_ref": f"EOS:PROJECT_CODE:{project_code}",
                    "source_version": version,
                    "content_hash": project_hash,
                    "as_of": self.resolved_at,
                },
                {
                    "kind": "OA_PROJECT_AUTHORIZATION",
                    "source_ref": authority_ref,
                    "source_version": str(self.decision["source_version"]),
                    "content_hash": authority_hash,
                    "as_of": self.resolved_at,
                },
                {
                    "kind": "AE_PROJECT_AGENT_PROJECTION",
                    "source_ref": f"AE:PROJECT_AGENT:{self.project_agent['agent_id']}",
                    "source_version": str(self.project_agent["project_version"]),
                    "content_hash": semantic_sha256_hash_ref(
                        {
                            key: str(value)
                            for key, value in self.project_agent.items()
                            if key not in {"created_at", "updated_at"}
                        }
                    ),
                    "as_of": self.resolved_at,
                },
            ),
            budget_tokens=2048,
            estimated_used_tokens=320,
        )


def build_http_project_delegation_activator(
    environ: Mapping[str, str],
    *,
    session_factory: sessionmaker[Session],
) -> ProjectDelegationIntentActivator | None:
    eos_url = str(environ.get("NEX_EOS_BASE_URL") or "").strip()
    oa_url = str(environ.get("NEX_OA_BASE_URL") or "").strip()
    eos_token = str(environ.get("NEX_AE_TO_EOS_SERVICE_TOKEN") or "").strip()
    oa_token = str(environ.get("NEX_AE_TO_OA_SERVICE_TOKEN") or "").strip()
    if not any((eos_url, oa_url, eos_token, oa_token)):
        return None
    if not all((eos_url, oa_url, eos_token, oa_token)):
        raise ProjectDelegationPlanningError(
            "PROJECT_DELEGATION_CONFIGURATION_INCOMPLETE",
            "Project delegation requires EOS/OA URLs and AE service tokens.",
        )
    return ProjectDelegationIntentActivator(
        eos=HttpEosProjectResolutionSource(eos_url, eos_token),
        oa=HttpOaProjectDecisionSource(oa_url, oa_token),
        project_agents=SqlAlchemyActiveProjectAgentSource(session_factory),
    )


def _one_project_code(candidate: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    selectors = candidate.get("entity_selectors")
    if not isinstance(selectors, list):
        raise _invalid("Project delegation candidate selectors are malformed.")
    matches = [
        item
        for item in selectors
        if isinstance(item, Mapping)
        and isinstance(item.get("value"), str)
        and _is_project_code(str(item["value"]))
    ]
    if len(matches) != 1:
        raise ProjectDelegationPlanningError(
            "PROJECT_CODE_AMBIGUOUS",
            "Exactly one explicit Project Code is required for delegation.",
        )
    return str(matches[0]["value"]), matches[0]


def _activate_work_intent(
    work_intent: Mapping[str, Any],
    *,
    profile: ProjectDelegationPlanningProfile,
    project_code: str,
    selector: Mapping[str, Any],
) -> dict[str, Any]:
    record = deepcopy(dict(work_intent))
    expected = semantic_sha256_hash_ref(
        {key: value for key, value in record.items() if key != "intent_hash"}
    )
    if record.get("schema_version") not in {"1.1", "1.2"} or record.get(
        "intent_hash"
    ) != expected:
        raise _invalid("Project delegation requires an intact WorkIntent v1.1 or v1.2.")
    confidence = selector.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise _invalid("Project selector confidence is invalid.")
    record.update(
        {
            "intent_label": profile.capability_id,
            "goal": "Delegate governed Project accounting work to the active Project Agent.",
            "work_class": "BUSINESS_TRANSACTION",
            "required_capability_hints": [profile.capability_id],
            "entity_selectors": [
                {
                    "selector_id": "E1",
                    "entity_type": "PROJECT",
                    "raw_text": project_code,
                    "attributes": {"authority": "MODEL_CANDIDATE_ONLY"},
                    "required": True,
                    "confidence": float(confidence),
                }
            ],
            "constraints": [
                *(
                    list(record.get("constraints", ()))
                    if record.get("schema_version") == "1.2"
                    else []
                ),
                {
                    "constraint_type": "PROJECT_DELEGATION_AUTHORITY",
                    "description": "EOS, OA, and AE Project Agent state are authoritative.",
                }
            ],
            "completion_criteria": [
                {
                    "criterion_id": "C1",
                    "description": "The active Project Agent returns the governed accounting result.",
                    "required": True,
                    "result_contract_ref": profile.result_contract_ref,
                }
            ],
            "clarification": {"status": "NOT_REQUIRED", "reasons": [], "questions": []},
            "confidence": {
                **dict(record["confidence"]),
                "entities": float(confidence),
            },
        }
    )
    record["intent_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in record.items() if key != "intent_hash"}
    )
    return record


def _require_allow_decision(
    decision: Mapping[str, Any],
    *,
    tenant_id: str,
    subject_id: str,
    project_code: str,
    action: str,
    minimum_source_version: int,
) -> None:
    if (
        decision.get("tenant_id") != tenant_id
        or decision.get("subject_id") != subject_id
        or decision.get("project_code") != project_code
        or decision.get("action") != action
        or decision.get("allowed") is not True
        or decision.get("reason_code") != "ALLOW"
        or not isinstance(decision.get("decision_ref"), str)
        or _positive_int("OA source version", decision.get("source_version"))
        < minimum_source_version
    ):
        raise ProjectDelegationPlanningError(
            "PROJECT_AUTHORIZATION_DENIED",
            "OA denied or returned stale Project authority.",
        )


def _is_project_code(value: str) -> bool:
    return (
        len(value) == 11
        and value[:4].isalnum()
        and value[:4] == value[:4].upper()
        and value[4] in "DMSOIG"
        and value[5:].isdigit()
    )


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field_name} is invalid.")
    return value


def _invalid(detail: str) -> ProjectDelegationPlanningError:
    return ProjectDelegationPlanningError("PROJECT_DELEGATION_INVALID", detail)
