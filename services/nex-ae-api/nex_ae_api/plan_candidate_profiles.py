from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.plan_candidate_generation import LivePlanCandidateService
from nex_ae_api.project_delegation_planning import (
    M1_PROJECT_DELEGATION_CAPABILITY_ID,
    M1_PROJECT_DELEGATION_PROFILE_VERSION,
)
from nex_ae_api.prompts import (
    AE_PLAN_BUILDER_BINDING,
    AE_PROJECT_DELEGATION_PLAN_BUILDER_BINDING,
)

PLAN_PROFILE_COMPATIBILITY_CAPABILITY_ID = "AE.COMPATIBILITY.DEFAULT"
PLANNING_SOURCE_TYPES = frozenset({"IA_PROMPT", "CLAIMED_WORKITEM"})
PLANNING_AGENT_TYPES = frozenset({"IA", "CA", "PA", "EA"})
PLANNING_PURPOSES = frozenset(
    {
        "INTERACTION_RESPONSE",
        "DELEGATION",
        "CLAIMED_WORK_EXECUTION",
        "PRODUCT_PREPARATION",
        "RESULT_SYNTHESIS",
    }
)


@dataclass(frozen=True)
class PlanCandidateProfileError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class PlanCandidateProfileRegistration:
    capability_id: str
    planning_source_type: str
    agent_type: str
    planning_purpose: str
    profile_version: str
    prompt_binding_key: str
    source_identity: str
    compatibility: bool = False

    def __post_init__(self) -> None:
        for field_name, value, maximum in (
            ("capability_id", self.capability_id, 160),
            ("planning_source_type", self.planning_source_type, 64),
            ("agent_type", self.agent_type, 16),
            ("planning_purpose", self.planning_purpose, 64),
            ("profile_version", self.profile_version, 128),
            ("prompt_binding_key", self.prompt_binding_key, 200),
            ("source_identity", self.source_identity, 256),
        ):
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > maximum
            ):
                raise PlanCandidateProfileError(
                    "PLAN_PROFILE_INVALID", f"{field_name} is invalid."
                )
        if self.planning_source_type not in PLANNING_SOURCE_TYPES:
            raise PlanCandidateProfileError(
                "PLAN_PROFILE_INVALID", "planning_source_type is unsupported."
            )
        if self.agent_type not in PLANNING_AGENT_TYPES:
            raise PlanCandidateProfileError(
                "PLAN_PROFILE_INVALID", "agent_type is unsupported."
            )
        if self.planning_purpose not in PLANNING_PURPOSES:
            raise PlanCandidateProfileError(
                "PLAN_PROFILE_INVALID", "planning_purpose is unsupported."
            )
        if not isinstance(self.compatibility, bool) or (
            self.compatibility
            != (self.capability_id == PLAN_PROFILE_COMPATIBILITY_CAPABILITY_ID)
        ):
            raise PlanCandidateProfileError(
                "PLAN_PROFILE_INVALID",
                "Compatibility profile identity is inconsistent.",
            )

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.capability_id,
            self.planning_source_type,
            self.agent_type,
            self.planning_purpose,
        )

    @property
    def scope_key(self) -> tuple[str, str, str]:
        return (
            self.planning_source_type,
            self.agent_type,
            self.planning_purpose,
        )

    def to_projection(self) -> dict[str, Any]:
        value = {
            "schema_version": "ae.plan_candidate_profile_registration.v2",
            "capability_id": self.capability_id,
            "planning_source_type": self.planning_source_type,
            "agent_type": self.agent_type,
            "planning_purpose": self.planning_purpose,
            "profile_version": self.profile_version,
            "prompt_binding_key": self.prompt_binding_key,
            "source_identity": self.source_identity,
            "compatibility": self.compatibility,
        }
        value["registration_hash"] = semantic_sha256_hash_ref(value)
        return value


@dataclass(frozen=True)
class PlanCandidateProfileRegistry:
    registrations: tuple[PlanCandidateProfileRegistration, ...] = ()
    _by_key: Mapping[
        tuple[str, str, str, str], PlanCandidateProfileRegistration
    ] = field(
        init=False, repr=False, compare=False
    )
    _compatibility_by_scope: Mapping[
        tuple[str, str, str], PlanCandidateProfileRegistration
    ] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        normalized = tuple(self.registrations)
        if any(
            not isinstance(item, PlanCandidateProfileRegistration)
            for item in normalized
        ):
            raise PlanCandidateProfileError(
                "PLAN_PROFILE_INVALID", "Plan profile registration is invalid."
            )
        ordered = tuple(sorted(normalized, key=lambda item: item.key))
        by_key: dict[
            tuple[str, str, str, str], PlanCandidateProfileRegistration
        ] = {}
        compatibility_by_scope: dict[
            tuple[str, str, str], PlanCandidateProfileRegistration
        ] = {}
        for registration in ordered:
            if registration.key in by_key:
                raise PlanCandidateProfileError(
                    "PLAN_PROFILE_DUPLICATE",
                    "Plan profile registration key must be unique.",
                )
            by_key[registration.key] = registration
            if registration.compatibility:
                compatibility_by_scope[registration.scope_key] = registration
        object.__setattr__(self, "registrations", ordered)
        object.__setattr__(self, "_by_key", MappingProxyType(by_key))
        object.__setattr__(
            self,
            "_compatibility_by_scope",
            MappingProxyType(compatibility_by_scope),
        )

    def resolve(
        self,
        capability_id: str,
        *,
        planning_source_type: str,
        agent_type: str,
        planning_purpose: str,
        allow_compatibility: bool = True,
        required: bool = False,
    ) -> PlanCandidateProfileRegistration | None:
        scope = (planning_source_type, agent_type, planning_purpose)
        registration = self._by_key.get((capability_id, *scope))
        if registration is None and allow_compatibility:
            registration = self._compatibility_by_scope.get(scope)
        if registration is None and required:
            raise PlanCandidateProfileError(
                "PLAN_PROFILE_NOT_REGISTERED",
                "No exact or explicit compatibility plan profile is registered.",
            )
        return registration

    def has_exact(
        self,
        capability_id: str,
        *,
        planning_source_type: str,
        agent_type: str,
        planning_purpose: str,
    ) -> bool:
        return (
            capability_id,
            planning_source_type,
            agent_type,
            planning_purpose,
        ) in self._by_key

    def to_projection(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": "ae.plan_candidate_profile_registry.v2",
            "registrations": [item.to_projection() for item in self.registrations],
        }
        value["registry_hash"] = semantic_sha256_hash_ref(value)
        return value


@dataclass(frozen=True)
class ProfileAwarePlanCandidateService:
    default_service: LivePlanCandidateService = field(repr=False)
    registry: PlanCandidateProfileRegistry

    def generate_and_bind(self, **kwargs: Any) -> Any:
        service, forwarded = self._service(kwargs)
        return service.generate_and_bind(**forwarded)

    def generate_proposal(self, **kwargs: Any) -> Any:
        service, forwarded = self._service(kwargs)
        return service.generate_proposal(**forwarded)

    def has_exact_profile(
        self,
        *,
        capability_id: str,
        planning_source_type: str,
        agent_type: str,
        planning_purpose: str,
    ) -> bool:
        return self.registry.has_exact(
            capability_id,
            planning_source_type=planning_source_type,
            agent_type=agent_type,
            planning_purpose=planning_purpose,
        )

    def _service(
        self, kwargs: Mapping[str, Any]
    ) -> tuple[LivePlanCandidateService, dict[str, Any]]:
        forwarded = dict(kwargs)
        work_intent = kwargs.get("work_intent")
        capability_id = (
            str(work_intent.get("intent_label"))
            if isinstance(work_intent, Mapping)
            else ""
        )
        planning_source_type = str(forwarded.pop("planning_source_type", ""))
        agent_type = str(forwarded.pop("agent_type", ""))
        planning_purpose = str(forwarded.pop("planning_purpose", ""))
        registration = self.registry.resolve(
            capability_id,
            planning_source_type=planning_source_type,
            agent_type=agent_type,
            planning_purpose=planning_purpose,
            required=True,
        )
        assert registration is not None
        return (
            replace(
                self.default_service,
                prompt_binding_key=registration.prompt_binding_key,
            ),
            forwarded,
        )


def build_m1_plan_candidate_profile_registry(
    product_capability_registry: Any,
) -> PlanCandidateProfileRegistry:
    capability = product_capability_registry.resolve(
        M1_PROJECT_DELEGATION_CAPABILITY_ID, required=False
    )
    registrations = [
        PlanCandidateProfileRegistration(
            capability_id=PLAN_PROFILE_COMPATIBILITY_CAPABILITY_ID,
            planning_source_type="IA_PROMPT",
            agent_type="IA",
            planning_purpose="INTERACTION_RESPONSE",
            profile_version="ae-plan-compatibility.v1",
            prompt_binding_key=AE_PLAN_BUILDER_BINDING,
            source_identity="nex-ae:plan-profile:compatibility:v1",
            compatibility=True,
        ),
        *(
            PlanCandidateProfileRegistration(
                capability_id=PLAN_PROFILE_COMPATIBILITY_CAPABILITY_ID,
                planning_source_type="CLAIMED_WORKITEM",
                agent_type=agent_type,
                planning_purpose="CLAIMED_WORK_EXECUTION",
                profile_version="ae-plan-compatibility.v1",
                prompt_binding_key=AE_PLAN_BUILDER_BINDING,
                source_identity="nex-ae:plan-profile:compatibility:v1",
                compatibility=True,
            )
            for agent_type in ("CA", "PA", "EA")
        ),
    ]
    if capability is not None:
        registrations.extend(
            (
                PlanCandidateProfileRegistration(
                    capability_id=M1_PROJECT_DELEGATION_CAPABILITY_ID,
                    planning_source_type="IA_PROMPT",
                    agent_type="IA",
                    planning_purpose="DELEGATION",
                    profile_version=M1_PROJECT_DELEGATION_PROFILE_VERSION,
                    prompt_binding_key=AE_PROJECT_DELEGATION_PLAN_BUILDER_BINDING,
                    source_identity=capability.source_identity,
                ),
                PlanCandidateProfileRegistration(
                    capability_id=M1_PROJECT_DELEGATION_CAPABILITY_ID,
                    planning_source_type="CLAIMED_WORKITEM",
                    agent_type="PA",
                    planning_purpose="PRODUCT_PREPARATION",
                    profile_version=M1_PROJECT_DELEGATION_PROFILE_VERSION,
                    prompt_binding_key=AE_PROJECT_DELEGATION_PLAN_BUILDER_BINDING,
                    source_identity=capability.source_identity,
                ),
            )
        )
    return PlanCandidateProfileRegistry(tuple(registrations))
