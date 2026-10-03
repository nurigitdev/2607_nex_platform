from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


S129_PROTOCOLS = ("OIDC_AUTHORIZATION_CODE_PKCE",)
S129_ID_TOKEN_ALGORITHMS = ("RS256",)
S129_AG_SAFE_CLAIMS = (
    "tenant_id",
    "subject_id",
    "roles",
    "scopes",
    "auth_method",
    "session_id_digest",
)
S129_SLICE_ORDER = tuple(str(number) for number in range(1282, 1292))
S129_OA_TABLES = ("oa_fed_providers", "oa_fed_identities")


@dataclass(frozen=True)
class OaFederatedAuthAgBoundary:
    owner: str
    consumer_service: str
    requirement: str
    protocols: tuple[str, ...]
    id_token_algorithms: tuple[str, ...]
    external_identity_linking: str
    automatic_email_linking_allowed: bool
    automatic_employee_id_linking_allowed: bool
    external_token_forwarding_allowed: bool
    ag_direct_idp_validation_allowed: bool
    cross_service_database_reads_allowed: bool
    provider_secrets_persisted: bool
    oa_session_issuance_required: bool
    ag_admin_role_required: bool
    ag_safe_claims: tuple[str, ...]
    oa_tables: tuple[str, ...]
    live_external_idp_required: bool
    protected_loopback_smoke_required: bool
    actual_postgres_smoke_slice: str
    checkpoint_slice: str
    full_gate_slice: str
    deferred_protocols: tuple[str, ...]
    slice_order: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


S129_FEDERATED_AUTH_AG_BOUNDARY = OaFederatedAuthAgBoundary(
    owner="nex-oa",
    consumer_service="nex-ag",
    requirement="S129",
    protocols=S129_PROTOCOLS,
    id_token_algorithms=S129_ID_TOKEN_ALGORITHMS,
    external_identity_linking="PREPROVISIONED_EXACT_SUBJECT",
    automatic_email_linking_allowed=False,
    automatic_employee_id_linking_allowed=False,
    external_token_forwarding_allowed=False,
    ag_direct_idp_validation_allowed=False,
    cross_service_database_reads_allowed=False,
    provider_secrets_persisted=False,
    oa_session_issuance_required=True,
    ag_admin_role_required=True,
    ag_safe_claims=S129_AG_SAFE_CLAIMS,
    oa_tables=S129_OA_TABLES,
    live_external_idp_required=False,
    protected_loopback_smoke_required=True,
    actual_postgres_smoke_slice="1290",
    checkpoint_slice="1286",
    full_gate_slice="1291",
    deferred_protocols=("SAML_2_0",),
    slice_order=S129_SLICE_ORDER,
)


def validate_federated_auth_ag_boundary(
    plan: Mapping[str, Any],
) -> tuple[str, ...]:
    required = tuple(OaFederatedAuthAgBoundary.__dataclass_fields__)
    errors = [f"field_missing:{name}" for name in required if name not in plan]
    expected = S129_FEDERATED_AUTH_AG_BOUNDARY.to_wire()
    for name in (
        "owner",
        "consumer_service",
        "requirement",
        "external_identity_linking",
        "actual_postgres_smoke_slice",
        "checkpoint_slice",
        "full_gate_slice",
    ):
        if plan.get(name) != expected[name]:
            errors.append(f"{name}_invalid")
    for name in (
        "automatic_email_linking_allowed",
        "automatic_employee_id_linking_allowed",
        "external_token_forwarding_allowed",
        "ag_direct_idp_validation_allowed",
        "cross_service_database_reads_allowed",
        "provider_secrets_persisted",
        "live_external_idp_required",
    ):
        if plan.get(name) is not False:
            errors.append(f"{name}_must_be_false")
    for name in (
        "oa_session_issuance_required",
        "ag_admin_role_required",
        "protected_loopback_smoke_required",
    ):
        if plan.get(name) is not True:
            errors.append(f"{name}_must_be_true")
    for name, value in (
        ("protocols", S129_PROTOCOLS),
        ("id_token_algorithms", S129_ID_TOKEN_ALGORITHMS),
        ("ag_safe_claims", S129_AG_SAFE_CLAIMS),
        ("oa_tables", S129_OA_TABLES),
        ("deferred_protocols", ("SAML_2_0",)),
        ("slice_order", S129_SLICE_ORDER),
    ):
        if tuple(plan.get(name) or ()) != value:
            errors.append(f"{name}_invalid")
    return tuple(errors)


def federation_responsibility(component: str) -> str | None:
    return {
        "nex-oa": "identity_provider_trust_and_internal_session_authority",
        "nex-ag": "oa_normalized_operator_context_consumer",
        "external-idp": "primary_user_authentication",
    }.get(component)
