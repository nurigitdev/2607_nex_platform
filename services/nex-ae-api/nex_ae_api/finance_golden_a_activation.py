from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_ae_api.agent_context import TrustedContextResolution
from nex_ae_api.golden_a_planning import (
    GOLDEN_A_AUTHORITY_PROFILE_SCHEMA_VERSION,
    activate_golden_a_work_intent,
    bind_golden_a_product_candidate,
    validate_golden_a_product_authority_profile,
)

FINANCE_GOLDEN_A_PROFILE_PATH_ENV = "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH"


@dataclass(frozen=True)
class FinanceGoldenAActivationError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


class GoldenAFinanceAuthoritySource(Protocol):
    @property
    def source_identity(self) -> str: ...

    def resolve(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        resolved_at: str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class VersionedGoldenAFinanceAuthoritySource:
    profile: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        profile = dict(self.profile)
        validate_golden_a_finance_profile(profile)
        try:
            validate_golden_a_product_authority_profile(profile)
        except ValueError as exc:
            raise FinanceGoldenAActivationError(
                str(getattr(exc, "error_code", "FINANCE_AUTHORITY_PROFILE_INVALID")),
                str(exc),
            ) from exc
        object.__setattr__(self, "profile", profile)

    @classmethod
    def from_path(cls, path: Path) -> VersionedGoldenAFinanceAuthoritySource:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FinanceGoldenAActivationError(
                "FINANCE_AUTHORITY_SOURCE_UNAVAILABLE",
                "Golden A finance authority profile is unavailable.",
            ) from exc
        if not isinstance(payload, Mapping):
            raise FinanceGoldenAActivationError(
                "FINANCE_AUTHORITY_PROFILE_INVALID",
                "Golden A finance authority profile must be an object.",
            )
        return cls(payload)

    @property
    def source_identity(self) -> str:
        return (
            "nex-ae:finance-golden-a-authority:"
            f"{self.profile['profile_id']}:v{self.profile['profile_version']}:"
            f"{self.profile['profile_hash']}"
        )

    def resolve(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        resolved_at: str,
    ) -> Mapping[str, Any]:
        del resolved_at
        if tenant_id != self.profile.get("tenant_id"):
            raise FinanceGoldenAActivationError(
                "FINANCE_AUTHORITY_TENANT_MISMATCH",
                "No Golden A finance authority profile exists for this tenant.",
            )
        principals = self.profile.get("authorized_principal_ids")
        protected_input = self.profile.get("protected_input")
        if (
            not isinstance(principals, list)
            or principal_id not in principals
            or not isinstance(protected_input, Mapping)
            or protected_input.get("requester_subject_id") != principal_id
        ):
            raise FinanceGoldenAActivationError(
                "FINANCE_AUTHORITY_PRINCIPAL_MISMATCH",
                "The requester is not authorized by the Golden A finance profile.",
            )
        return self.profile


@dataclass(frozen=True)
class FinanceGoldenAActivationResult:
    work_intent: Mapping[str, Any] = field(repr=False)
    context_resolver: Any = field(repr=False)


@dataclass(frozen=True)
class GoldenAFinanceIntentActivator:
    authority_source: GoldenAFinanceAuthoritySource = field(repr=False)
    capability: Mapping[str, Any] = field(repr=False)

    def activate(
        self,
        *,
        candidate: Mapping[str, Any],
        work_intent: Mapping[str, Any],
        tenant_id: str,
        principal_id: str,
        resolved_at: str,
    ) -> FinanceGoldenAActivationResult:
        profile = self.authority_source.resolve(
            tenant_id=tenant_id,
            principal_id=principal_id,
            resolved_at=resolved_at,
        )
        activation = bind_golden_a_product_candidate(
            authority_profile=profile,
            candidate=candidate,
            capability=self.capability,
        )
        activated = activate_golden_a_work_intent(
            work_intent,
            candidate=candidate,
            activation=activation,
        )
        return FinanceGoldenAActivationResult(
            work_intent=activated,
            context_resolver=GoldenAFinanceContextResolver(
                activation=activation,
                authority_ref=f"OA:SUBJECT:{principal_id}",
                resolved_at=resolved_at,
            ),
        )


@dataclass(frozen=True)
class GoldenAFinanceContextResolver:
    activation: Mapping[str, Any] = field(repr=False)
    authority_ref: str
    resolved_at: str

    def resolve(self, _request: Any) -> TrustedContextResolution:
        binding = self.activation["authoritative_binding"]
        project_ref = dict(binding["project_ref"])
        profile_ref = self.activation["authority_ref"]
        return TrustedContextResolution(
            project_ref=None,
            authority_ref=self.authority_ref,
            resolved_entities=(
                {
                    "selector_id": "E1",
                    "resource_ref": project_ref,
                    "source_ref": (
                        "finance-authority-project:" + str(project_ref["resource_id"])
                    ),
                    "resolved_at": self.resolved_at,
                },
            ),
            retrieval_refs=(),
            evidence_refs=(),
            conflicts=(),
            degradations=(),
            context_manifest=(
                {
                    "kind": "FINANCE_AUTHORITY_PROFILE",
                    "source_ref": (
                        "finance-authority-profile:" + str(profile_ref["profile_id"])
                    ),
                    "source_version": str(profile_ref["profile_version"]),
                    "content_hash": profile_ref["profile_hash"],
                    "as_of": self.resolved_at,
                },
            ),
            budget_tokens=2048,
            estimated_used_tokens=256,
        )


def load_golden_a_finance_authority_source(
    environ: Mapping[str, str],
) -> VersionedGoldenAFinanceAuthoritySource | None:
    value = str(environ.get(FINANCE_GOLDEN_A_PROFILE_PATH_ENV) or "").strip()
    if not value:
        return None
    return VersionedGoldenAFinanceAuthoritySource.from_path(Path(value))


def validate_golden_a_finance_profile(profile: Mapping[str, Any]) -> None:
    if profile.get("schema_version") != GOLDEN_A_AUTHORITY_PROFILE_SCHEMA_VERSION:
        raise FinanceGoldenAActivationError(
            "FINANCE_AUTHORITY_PROFILE_INVALID",
            "Golden A finance authority profile version is unsupported.",
        )
    try:
        supplied = validate_hash_ref(profile.get("profile_hash"))
    except ValueError as exc:
        raise FinanceGoldenAActivationError(
            "FINANCE_AUTHORITY_PROFILE_INVALID",
            "Golden A finance authority profile hash is invalid.",
        ) from exc
    expected = semantic_sha256_hash_ref(
        {key: value for key, value in profile.items() if key != "profile_hash"}
    )
    if supplied != expected:
        raise FinanceGoldenAActivationError(
            "FINANCE_AUTHORITY_PROFILE_INVALID",
            "Golden A finance authority profile hash does not match its content.",
        )
