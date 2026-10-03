from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


LIFECYCLE_TABLES = ("oa_service_principals", "oa_service_creds")
DEFERRED_SIGNED_RUNTIME_TABLES = ("oa_signing_keys", "oa_token_revocations")
S126_SLICE_ORDER = tuple(str(number) for number in range(1252, 1262))


@dataclass(frozen=True)
class ServicePrincipalLifecycleBoundary:
    owner: str
    requirement: str
    lifecycle_tables: tuple[str, ...]
    deferred_requirement: str
    deferred_tables: tuple[str, ...]
    credential_hash_algorithm: str
    credential_secret_display: str
    database_plaintext_secret_allowed: bool
    cross_service_database_reads_allowed: bool
    remote_model_provider_required: bool
    actual_postgres_smoke_slice: str
    checkpoint_slice: str
    full_gate_slice: str
    slice_order: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


S126_LIFECYCLE_BOUNDARY = ServicePrincipalLifecycleBoundary(
    owner="nex-oa",
    requirement="S126",
    lifecycle_tables=LIFECYCLE_TABLES,
    deferred_requirement="S127",
    deferred_tables=DEFERRED_SIGNED_RUNTIME_TABLES,
    credential_hash_algorithm="argon2id",
    credential_secret_display="once_at_creation_or_rotation",
    database_plaintext_secret_allowed=False,
    cross_service_database_reads_allowed=False,
    remote_model_provider_required=False,
    actual_postgres_smoke_slice="1260",
    checkpoint_slice="1256",
    full_gate_slice="1261",
    slice_order=S126_SLICE_ORDER,
)


def validate_lifecycle_boundary(plan: Mapping[str, Any]) -> tuple[str, ...]:
    required = (
        "owner",
        "requirement",
        "lifecycle_tables",
        "deferred_requirement",
        "deferred_tables",
        "actual_postgres_smoke_slice",
        "checkpoint_slice",
        "full_gate_slice",
        "slice_order",
    )
    errors = [f"field_missing:{name}" for name in required if name not in plan]
    if plan.get("owner") != "nex-oa":
        errors.append("owner_invalid")
    if plan.get("requirement") != "S126":
        errors.append("requirement_invalid")
    if tuple(plan.get("lifecycle_tables") or ()) != LIFECYCLE_TABLES:
        errors.append("lifecycle_tables_invalid")
    if plan.get("deferred_requirement") != "S127":
        errors.append("deferred_requirement_invalid")
    if tuple(plan.get("deferred_tables") or ()) != DEFERRED_SIGNED_RUNTIME_TABLES:
        errors.append("deferred_tables_invalid")
    if set(plan.get("lifecycle_tables") or ()) & set(plan.get("deferred_tables") or ()):
        errors.append("table_ownership_overlap")
    if tuple(plan.get("slice_order") or ()) != S126_SLICE_ORDER:
        errors.append("slice_order_invalid")
    if plan.get("actual_postgres_smoke_slice") != "1260":
        errors.append("postgres_smoke_slice_invalid")
    if plan.get("checkpoint_slice") != "1256":
        errors.append("checkpoint_slice_invalid")
    if plan.get("full_gate_slice") != "1261":
        errors.append("full_gate_slice_invalid")
    return tuple(errors)


def implementation_owner_for_table(table_name: str) -> str | None:
    if table_name in LIFECYCLE_TABLES:
        return "S126"
    if table_name in DEFERRED_SIGNED_RUNTIME_TABLES:
        return "S127"
    return None
