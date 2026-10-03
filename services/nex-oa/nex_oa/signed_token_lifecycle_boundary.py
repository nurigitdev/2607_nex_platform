from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


SIGNED_RUNTIME_TABLES = ("oa_signing_keys", "oa_token_revocations")
PREDECESSOR_TABLES = ("oa_service_principals", "oa_service_creds")
S127_SLICE_ORDER = tuple(str(number) for number in range(1262, 1272))


@dataclass(frozen=True)
class SignedTokenLifecycleBoundary:
    owner: str
    requirement: str
    token_profile: str
    grant_type: str
    algorithm: str
    minimum_rsa_bits: int
    maximum_token_ttl_seconds: int
    owned_tables: tuple[str, ...]
    predecessor_tables: tuple[str, ...]
    private_key_custody: str
    private_key_database_storage_allowed: bool
    raw_token_persistence_allowed: bool
    raw_token_logging_allowed: bool
    revocation_identifier_storage: str
    cross_service_database_reads_allowed: bool
    remote_model_provider_required: bool
    actual_postgres_smoke_slice: str
    checkpoint_slice: str
    full_gate_slice: str
    slice_order: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


S127_SIGNED_TOKEN_BOUNDARY = SignedTokenLifecycleBoundary(
    owner="nex-oa",
    requirement="S127",
    token_profile="service_access",
    grant_type="client_credentials",
    algorithm="RS256",
    minimum_rsa_bits=3072,
    maximum_token_ttl_seconds=300,
    owned_tables=SIGNED_RUNTIME_TABLES,
    predecessor_tables=PREDECESSOR_TABLES,
    private_key_custody="external_reference_only",
    private_key_database_storage_allowed=False,
    raw_token_persistence_allowed=False,
    raw_token_logging_allowed=False,
    revocation_identifier_storage="sha256_jti_digest",
    cross_service_database_reads_allowed=False,
    remote_model_provider_required=False,
    actual_postgres_smoke_slice="1270",
    checkpoint_slice="1266",
    full_gate_slice="1271",
    slice_order=S127_SLICE_ORDER,
)


def validate_signed_token_boundary(plan: Mapping[str, Any]) -> tuple[str, ...]:
    required = tuple(SignedTokenLifecycleBoundary.__dataclass_fields__)
    errors = [f"field_missing:{name}" for name in required if name not in plan]
    expected = S127_SIGNED_TOKEN_BOUNDARY.to_wire()
    for name in (
        "owner",
        "requirement",
        "token_profile",
        "grant_type",
        "algorithm",
        "minimum_rsa_bits",
        "maximum_token_ttl_seconds",
        "private_key_custody",
        "revocation_identifier_storage",
        "actual_postgres_smoke_slice",
        "checkpoint_slice",
        "full_gate_slice",
    ):
        if plan.get(name) != expected[name]:
            errors.append(f"{name}_invalid")
    for name in (
        "private_key_database_storage_allowed",
        "raw_token_persistence_allowed",
        "raw_token_logging_allowed",
        "cross_service_database_reads_allowed",
        "remote_model_provider_required",
    ):
        if plan.get(name) is not False:
            errors.append(f"{name}_must_be_false")
    if tuple(plan.get("owned_tables") or ()) != SIGNED_RUNTIME_TABLES:
        errors.append("owned_tables_invalid")
    if tuple(plan.get("predecessor_tables") or ()) != PREDECESSOR_TABLES:
        errors.append("predecessor_tables_invalid")
    if set(plan.get("owned_tables") or ()) & set(plan.get("predecessor_tables") or ()):
        errors.append("table_ownership_overlap")
    if tuple(plan.get("slice_order") or ()) != S127_SLICE_ORDER:
        errors.append("slice_order_invalid")
    return tuple(errors)


def implementation_owner_for_table(table_name: str) -> str | None:
    if table_name in PREDECESSOR_TABLES:
        return "S126"
    if table_name in SIGNED_RUNTIME_TABLES:
        return "S127"
    return None
