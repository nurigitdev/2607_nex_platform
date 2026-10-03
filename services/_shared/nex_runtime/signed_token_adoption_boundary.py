from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


S128_CONSUMER_SERVICES = ("nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
S128_ROLLOUT_UNITS = ("shared_verifier_and_oa_issuer", *S128_CONSUMER_SERVICES)
S128_ROLLOUT_PROFILES = ("TEST_MOCK", "DUAL_READ", "SIGNED_ONLY")
S128_SLICE_ORDER = tuple(str(number) for number in range(1272, 1282))


@dataclass(frozen=True)
class PlatformSignedTokenAdoptionBoundary:
    owner: str
    issuer_service: str
    requirement: str
    token_profile: str
    issuer: str
    algorithm: str
    consumer_services: tuple[str, ...]
    rollout_units: tuple[str, ...]
    rollout_profiles: tuple[str, ...]
    primary_verification: str
    sensitive_route_check: str
    silent_mock_fallback_allowed: bool
    cross_service_database_reads_allowed: bool
    new_database_tables_required: bool
    remote_model_provider_required: bool
    deferred_token_profiles: tuple[str, ...]
    actual_postgres_smoke_slice: str
    checkpoint_slice: str
    full_gate_slice: str
    slice_order: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


S128_SIGNED_TOKEN_ADOPTION_BOUNDARY = PlatformSignedTokenAdoptionBoundary(
    owner="nex-runtime",
    issuer_service="nex-oa",
    requirement="S128",
    token_profile="service_access",
    issuer="urn:nex-platform:oa",
    algorithm="RS256",
    consumer_services=S128_CONSUMER_SERVICES,
    rollout_units=S128_ROLLOUT_UNITS,
    rollout_profiles=S128_ROLLOUT_PROFILES,
    primary_verification="local_jwks_signature_and_claim_validation",
    sensitive_route_check="oa_introspection",
    silent_mock_fallback_allowed=False,
    cross_service_database_reads_allowed=False,
    new_database_tables_required=False,
    remote_model_provider_required=False,
    deferred_token_profiles=("delegated_user_access",),
    actual_postgres_smoke_slice="1280",
    checkpoint_slice="1276",
    full_gate_slice="1281",
    slice_order=S128_SLICE_ORDER,
)


def validate_signed_token_adoption_boundary(
    plan: Mapping[str, Any],
) -> tuple[str, ...]:
    required = tuple(PlatformSignedTokenAdoptionBoundary.__dataclass_fields__)
    errors = [f"field_missing:{name}" for name in required if name not in plan]
    expected = S128_SIGNED_TOKEN_ADOPTION_BOUNDARY.to_wire()
    for name in (
        "owner",
        "issuer_service",
        "requirement",
        "token_profile",
        "issuer",
        "algorithm",
        "primary_verification",
        "sensitive_route_check",
        "actual_postgres_smoke_slice",
        "checkpoint_slice",
        "full_gate_slice",
    ):
        if plan.get(name) != expected[name]:
            errors.append(f"{name}_invalid")
    for name in (
        "silent_mock_fallback_allowed",
        "cross_service_database_reads_allowed",
        "new_database_tables_required",
        "remote_model_provider_required",
    ):
        if plan.get(name) is not False:
            errors.append(f"{name}_must_be_false")
    if tuple(plan.get("consumer_services") or ()) != S128_CONSUMER_SERVICES:
        errors.append("consumer_services_invalid")
    if tuple(plan.get("rollout_units") or ()) != S128_ROLLOUT_UNITS:
        errors.append("rollout_units_invalid")
    if tuple(plan.get("rollout_profiles") or ()) != S128_ROLLOUT_PROFILES:
        errors.append("rollout_profiles_invalid")
    if tuple(plan.get("deferred_token_profiles") or ()) != (
        "delegated_user_access",
    ):
        errors.append("deferred_token_profiles_invalid")
    if tuple(plan.get("slice_order") or ()) != S128_SLICE_ORDER:
        errors.append("slice_order_invalid")
    return tuple(errors)


def adoption_owner_for_service(service_id: str) -> str | None:
    if service_id == "nex-oa":
        return "issuer"
    if service_id in S128_CONSUMER_SERVICES:
        return "consumer"
    return None
