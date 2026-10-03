from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


SERVICE_PRINCIPAL_STATUSES = ("ACTIVE", "DISABLED")
SERVICE_CREDENTIAL_STATUSES = ("ACTIVE", "ROTATING", "REVOKED", "EXPIRED")
KNOWN_SERVICE_IDS = frozenset(
    {"nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo"}
)
MAX_CREDENTIAL_LIFETIME_DAYS = 90
MAX_ROTATION_GRACE_SECONDS = 86_400
MAX_SIMULTANEOUS_ACTIVE_CREDENTIALS = 2
PROPOSED_TABLES = (
    "oa_service_principals",
    "oa_service_creds",
    "oa_signing_keys",
    "oa_token_revocations",
)


@dataclass(frozen=True)
class ServicePrincipalHandoff:
    owner: str
    implementation_requirement: str
    proposed_tables: tuple[str, ...]
    credential_hash_algorithm: str
    credential_secret_display: str
    maximum_credential_lifetime_days: int
    maximum_rotation_grace_seconds: int
    maximum_simultaneous_active_credentials: int
    token_ttl_seconds: int
    database_plaintext_secret_allowed: bool
    silent_default_audience_or_scope_allowed: bool
    cross_service_database_reads_allowed: bool

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


S126_SERVICE_PRINCIPAL_HANDOFF = ServicePrincipalHandoff(
    owner="nex-oa",
    implementation_requirement="S126",
    proposed_tables=PROPOSED_TABLES,
    credential_hash_algorithm="argon2id",
    credential_secret_display="once_at_creation_or_rotation",
    maximum_credential_lifetime_days=MAX_CREDENTIAL_LIFETIME_DAYS,
    maximum_rotation_grace_seconds=MAX_ROTATION_GRACE_SECONDS,
    maximum_simultaneous_active_credentials=MAX_SIMULTANEOUS_ACTIVE_CREDENTIALS,
    token_ttl_seconds=300,
    database_plaintext_secret_allowed=False,
    silent_default_audience_or_scope_allowed=False,
    cross_service_database_reads_allowed=False,
)


def validate_service_principal_spec(spec: Mapping[str, Any]) -> tuple[str, ...]:
    required = (
        "principal_id",
        "service_id",
        "display_name",
        "status",
        "allowed_audiences",
        "allowed_scopes",
        "revision",
    )
    errors = _missing(spec, required)
    for name in ("principal_id", "service_id", "display_name", "status"):
        if name in spec and not _nonempty_string(spec[name]):
            errors.append(f"principal_invalid:{name}")
    if "service_id" in spec and spec.get("service_id") not in KNOWN_SERVICE_IDS:
        errors.append("principal_service_id_unknown")
    if "status" in spec and spec.get("status") not in SERVICE_PRINCIPAL_STATUSES:
        errors.append("principal_status_invalid")
    _validate_allowlist(
        spec.get("allowed_audiences"),
        name="audiences",
        known_values=KNOWN_SERVICE_IDS,
        errors=errors,
    )
    _validate_allowlist(
        spec.get("allowed_scopes"),
        name="scopes",
        known_values=None,
        errors=errors,
    )
    if "revision" in spec and not _positive_integer(spec["revision"]):
        errors.append("principal_revision_invalid")
    return tuple(errors)


def validate_service_credential_record(
    record: Mapping[str, Any],
) -> tuple[str, ...]:
    required = (
        "credential_id",
        "principal_id",
        "secret_hash",
        "secret_hint",
        "status",
        "issued_at",
        "expires_at",
        "grace_until",
        "revision",
    )
    errors = _missing(record, required)
    for name in (
        "credential_id",
        "principal_id",
        "secret_hash",
        "secret_hint",
        "status",
    ):
        if name in record and not _nonempty_string(record[name]):
            errors.append(f"credential_invalid:{name}")
    secret_hash = record.get("secret_hash")
    if _nonempty_string(secret_hash) and not secret_hash.startswith("$argon2id$"):
        errors.append("credential_hash_algorithm_invalid")
    if "secret_hint" in record and _nonempty_string(record.get("secret_hint")):
        if len(record["secret_hint"]) > 8:
            errors.append("credential_secret_hint_too_long")
    if "status" in record and record.get("status") not in SERVICE_CREDENTIAL_STATUSES:
        errors.append("credential_status_invalid")
    for name in ("issued_at", "expires_at", "grace_until"):
        if name in record and not _integer(record[name]):
            errors.append(f"credential_invalid:{name}")
    if all(_integer(record.get(name)) for name in ("issued_at", "expires_at")):
        if record["expires_at"] <= record["issued_at"]:
            errors.append("credential_expiry_invalid")
        if record["expires_at"] - record["issued_at"] > (
            MAX_CREDENTIAL_LIFETIME_DAYS * 86_400
        ):
            errors.append("credential_lifetime_exceeded")
    if all(_integer(record.get(name)) for name in ("issued_at", "grace_until")):
        grace = record["grace_until"]
        if grace < record["issued_at"]:
            errors.append("credential_rotation_grace_invalid")
        if grace - record["issued_at"] > MAX_ROTATION_GRACE_SECONDS:
            errors.append("credential_rotation_grace_exceeded")
    if "revision" in record and not _positive_integer(record["revision"]):
        errors.append("credential_revision_invalid")
    for forbidden in ("secret", "client_secret", "access_token"):
        if forbidden in record:
            errors.append(f"credential_field_forbidden:{forbidden}")
    return tuple(errors)


def _validate_allowlist(
    value: Any,
    *,
    name: str,
    known_values: frozenset[str] | None,
    errors: list[str],
) -> None:
    if value is None:
        return
    if not isinstance(value, (list, tuple)) or not value:
        errors.append(f"principal_{name}_invalid")
        return
    if not all(_nonempty_string(item) for item in value):
        errors.append(f"principal_{name}_invalid")
        return
    if len(value) != len(set(value)):
        errors.append(f"principal_{name}_duplicate")
    if known_values is not None and not set(value).issubset(known_values):
        errors.append(f"principal_{name}_unknown")


def _missing(values: Mapping[str, Any], names: tuple[str, ...]) -> list[str]:
    return [f"field_missing:{name}" for name in names if name not in values]


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_integer(value: Any) -> bool:
    return _integer(value) and value > 0
