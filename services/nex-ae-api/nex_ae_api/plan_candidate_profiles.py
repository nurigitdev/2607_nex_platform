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
from nex_ae_api.prompts import AE_PROJECT_DELEGATION_PLAN_BUILDER_BINDING


@dataclass(frozen=True)
class PlanCandidateProfileError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class PlanCandidateProfileRegistration:
    capability_id: str
    profile_version: str
    prompt_binding_key: str
    source_identity: str

    def __post_init__(self) -> None:
        for field_name, value, maximum in (
            ("capability_id", self.capability_id, 160),
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

    def to_projection(self) -> dict[str, str]:
        value = {
            "schema_version": "ae.plan_candidate_profile_registration.v1",
            "capability_id": self.capability_id,
            "profile_version": self.profile_version,
            "prompt_binding_key": self.prompt_binding_key,
            "source_identity": self.source_identity,
        }
        value["registration_hash"] = semantic_sha256_hash_ref(value)
        return value


@dataclass(frozen=True)
class PlanCandidateProfileRegistry:
    registrations: tuple[PlanCandidateProfileRegistration, ...] = ()
    _by_capability: Mapping[str, PlanCandidateProfileRegistration] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.registrations, key=lambda item: item.capability_id))
        by_capability: dict[str, PlanCandidateProfileRegistration] = {}
        for registration in ordered:
            if not isinstance(registration, PlanCandidateProfileRegistration):
                raise PlanCandidateProfileError(
                    "PLAN_PROFILE_INVALID", "Plan profile registration is invalid."
                )
            if registration.capability_id in by_capability:
                raise PlanCandidateProfileError(
                    "PLAN_PROFILE_DUPLICATE",
                    "Plan profile capability registration must be unique.",
                )
            by_capability[registration.capability_id] = registration
        object.__setattr__(self, "registrations", ordered)
        object.__setattr__(self, "_by_capability", MappingProxyType(by_capability))

    def resolve(self, capability_id: str) -> PlanCandidateProfileRegistration | None:
        return self._by_capability.get(capability_id)

    def to_projection(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": "ae.plan_candidate_profile_registry.v1",
            "registrations": [item.to_projection() for item in self.registrations],
        }
        value["registry_hash"] = semantic_sha256_hash_ref(value)
        return value


@dataclass(frozen=True)
class ProfileAwarePlanCandidateService:
    default_service: LivePlanCandidateService = field(repr=False)
    registry: PlanCandidateProfileRegistry

    def generate_and_bind(self, **kwargs: Any) -> Any:
        work_intent = kwargs.get("work_intent")
        capability_id = (
            str(work_intent.get("intent_label"))
            if isinstance(work_intent, Mapping)
            else ""
        )
        registration = self.registry.resolve(capability_id)
        service = self.default_service
        if registration is not None:
            service = replace(
                service, prompt_binding_key=registration.prompt_binding_key
            )
        return service.generate_and_bind(**kwargs)


def build_m1_plan_candidate_profile_registry(
    product_capability_registry: Any,
) -> PlanCandidateProfileRegistry:
    capability = product_capability_registry.resolve(
        M1_PROJECT_DELEGATION_CAPABILITY_ID, required=False
    )
    if capability is None:
        return PlanCandidateProfileRegistry()
    return PlanCandidateProfileRegistry(
        (
            PlanCandidateProfileRegistration(
                capability_id=M1_PROJECT_DELEGATION_CAPABILITY_ID,
                profile_version=M1_PROJECT_DELEGATION_PROFILE_VERSION,
                prompt_binding_key=AE_PROJECT_DELEGATION_PLAN_BUILDER_BINDING,
                source_identity=capability.source_identity,
            ),
        )
    )
