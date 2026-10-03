from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from nex_oa.service_principal_boundary import (
    KNOWN_SERVICE_IDS,
    MAX_CREDENTIAL_LIFETIME_DAYS,
    MAX_ROTATION_GRACE_SECONDS,
    MAX_SIMULTANEOUS_ACTIVE_CREDENTIALS,
    SERVICE_CREDENTIAL_STATUSES,
    SERVICE_PRINCIPAL_STATUSES,
)


OA_SERVICE_PRINCIPAL_SCHEMA_VERSION = "oa_service_principal.v1"
OA_SERVICE_CREDENTIAL_SCHEMA_VERSION = "oa_service_credential.v1"

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,63}:[a-z][a-z0-9._-]{0,63}$")
_CREDENTIAL_TRANSITIONS = {
    "ACTIVE": frozenset(("ROTATING", "REVOKED", "EXPIRED")),
    "ROTATING": frozenset(("REVOKED", "EXPIRED")),
    "REVOKED": frozenset(),
    "EXPIRED": frozenset(),
}


@dataclass(frozen=True)
class OaServicePrincipalError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def plan_service_principal_upsert(
    payload: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    principal_id = normalize_service_principal_id(payload.get("principal_id"))
    service_id = normalize_service_id(payload.get("service_id"))
    revision = _next_revision(payload.get("expected_revision"), current=current)
    if current is not None and (
        current.get("principal_id") != principal_id
        or current.get("service_id") != service_id
    ):
        raise _error(
            409,
            "oa.service_principal_identity_immutable",
            "principal_id and service_id are immutable.",
        )
    return {
        "principal_schema_version": OA_SERVICE_PRINCIPAL_SCHEMA_VERSION,
        "principal_id": principal_id,
        "service_id": service_id,
        "display_name": normalize_display_name(payload.get("display_name")),
        "status": normalize_principal_status(payload.get("status", "ACTIVE")),
        "allowed_audiences": normalize_audiences(payload.get("allowed_audiences")),
        "allowed_scopes": normalize_scopes(payload.get("allowed_scopes")),
        "previous_revision": revision - 1,
        "revision": revision,
    }


def plan_credential_issue(
    payload: Mapping[str, Any],
    *,
    principal: Mapping[str, Any],
    active_credential_count: object,
    now_epoch: object,
) -> dict[str, Any]:
    if normalize_principal_status(principal.get("status")) != "ACTIVE":
        raise _error(
            409,
            "oa.service_principal_disabled",
            "credentials cannot be issued for a disabled service principal.",
        )
    principal_id = normalize_service_principal_id(principal.get("principal_id"))
    count = _integer(active_credential_count, field_name="active_credential_count", minimum=0)
    if count >= MAX_SIMULTANEOUS_ACTIVE_CREDENTIALS:
        raise _error(
            409,
            "oa.service_credential_active_limit",
            "the service principal already has the maximum active credentials.",
        )
    issued_at = _integer(now_epoch, field_name="now_epoch", minimum=0)
    lifetime_days = _integer(
        payload.get("lifetime_days"),
        field_name="lifetime_days",
        minimum=1,
        maximum=MAX_CREDENTIAL_LIFETIME_DAYS,
    )
    return {
        "credential_schema_version": OA_SERVICE_CREDENTIAL_SCHEMA_VERSION,
        "credential_id": normalize_credential_id(payload.get("credential_id")),
        "principal_id": principal_id,
        "status": "ACTIVE",
        "issued_at": issued_at,
        "expires_at": issued_at + lifetime_days * 86_400,
        "grace_until": None,
        "previous_revision": 0,
        "revision": 1,
    }


def plan_credential_status_transition(
    credential: Mapping[str, Any],
    *,
    target_status: object,
    expected_revision: object,
    now_epoch: object,
    grace_seconds: object | None = None,
) -> dict[str, Any]:
    current_status = normalize_credential_status(credential.get("status"))
    target = normalize_credential_status(target_status)
    current_revision = _integer(
        credential.get("revision"), field_name="revision", minimum=1
    )
    expected = _integer(
        expected_revision, field_name="expected_revision", minimum=1
    )
    if expected != current_revision:
        raise _error(
            409,
            "oa.service_credential_revision_conflict",
            "expected_revision does not match the current credential revision.",
        )
    changed = target != current_status
    if changed and target not in _CREDENTIAL_TRANSITIONS[current_status]:
        raise _error(
            409,
            "oa.service_credential_transition_invalid",
            f"credential status cannot transition from {current_status} to {target}.",
        )
    now = _integer(now_epoch, field_name="now_epoch", minimum=0)
    if target == "ROTATING":
        grace = _integer(
            grace_seconds,
            field_name="grace_seconds",
            minimum=1,
            maximum=MAX_ROTATION_GRACE_SECONDS,
        )
        grace_until = now + grace
    else:
        if grace_seconds is not None:
            raise _invalid(
                "grace_seconds",
                "grace_seconds is accepted only when target_status is ROTATING.",
            )
        grace_until = credential.get("grace_until") if not changed else None
    return {
        "credential_schema_version": OA_SERVICE_CREDENTIAL_SCHEMA_VERSION,
        "credential_id": normalize_credential_id(credential.get("credential_id")),
        "principal_id": normalize_service_principal_id(credential.get("principal_id")),
        "previous_status": current_status,
        "status": target,
        "changed": changed,
        "changed_at": now if changed else None,
        "grace_until": grace_until,
        "previous_revision": current_revision,
        "revision": current_revision + 1 if changed else current_revision,
    }


def normalize_service_principal_id(value: object) -> str:
    return _normalized_id(value, field_name="principal_id")


def normalize_credential_id(value: object) -> str:
    return _normalized_id(value, field_name="credential_id")


def normalize_service_id(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("service_id", "service_id must be a known service name.")
    normalized = value.strip().lower()
    if normalized not in KNOWN_SERVICE_IDS:
        raise _invalid("service_id", "service_id must be a known service name.")
    return normalized


def normalize_display_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise _invalid("display_name", "display_name must contain 1-128 characters.")
    return value.strip()


def normalize_principal_status(value: object) -> str:
    return _normalized_status(
        value,
        field_name="status",
        allowed=SERVICE_PRINCIPAL_STATUSES,
    )


def normalize_credential_status(value: object) -> str:
    return _normalized_status(
        value,
        field_name="status",
        allowed=SERVICE_CREDENTIAL_STATUSES,
    )


def normalize_audiences(value: object) -> tuple[str, ...]:
    values = _sequence(value, field_name="allowed_audiences")
    normalized = {normalize_service_id(item) for item in values}
    if not normalized:
        raise _invalid(
            "allowed_audiences", "at least one allowed audience is required."
        )
    return tuple(sorted(normalized))


def normalize_scopes(value: object) -> tuple[str, ...]:
    values = _sequence(value, field_name="allowed_scopes")
    normalized: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not _SCOPE_PATTERN.fullmatch(item.strip().lower()):
            raise _invalid(
                "allowed_scopes", "each scope must use the resource:action form."
            )
        normalized.add(item.strip().lower())
    if not normalized:
        raise _invalid("allowed_scopes", "at least one allowed scope is required.")
    return tuple(sorted(normalized))


def _normalized_id(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise _invalid(field_name, f"{field_name} must be a string.")
    normalized = value.strip().lower()
    if not _ID_PATTERN.fullmatch(normalized):
        raise _invalid(
            field_name,
            f"{field_name} must contain 2-64 lowercase letters, digits, '.', '_' or '-'.",
        )
    return normalized


def _normalized_status(
    value: object,
    *,
    field_name: str,
    allowed: tuple[str, ...],
) -> str:
    if not isinstance(value, str) or value.strip().upper() not in allowed:
        raise _invalid(field_name, f"{field_name} is invalid.")
    return value.strip().upper()


def _sequence(value: object, *, field_name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _invalid(field_name, f"{field_name} must be an array.")
    return value


def _next_revision(
    expected: object,
    *,
    current: Mapping[str, Any] | None,
) -> int:
    expected_revision = _integer(
        expected if expected is not None else 0,
        field_name="expected_revision",
        minimum=0,
    )
    current_revision = (
        _integer(current.get("revision"), field_name="revision", minimum=1)
        if current is not None
        else 0
    )
    if expected_revision != current_revision:
        raise _error(
            409,
            "oa.service_principal_revision_conflict",
            "expected_revision does not match the current principal revision.",
        )
    return current_revision + 1


def _integer(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool):
        raise _invalid(field_name, f"{field_name} must be an integer.")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(field_name, f"{field_name} must be an integer.") from exc
    if str(value) != str(normalized) or normalized < minimum:
        raise _invalid(field_name, f"{field_name} is outside the allowed range.")
    if maximum is not None and normalized > maximum:
        raise _invalid(field_name, f"{field_name} is outside the allowed range.")
    return normalized


def _invalid(field_name: str, detail: str) -> OaServicePrincipalError:
    return _error(400, f"oa.service_principal_{field_name}_invalid", detail)


def _error(status_code: int, error_code: str, detail: str) -> OaServicePrincipalError:
    return OaServicePrincipalError(
        status_code=status_code,
        error_code=error_code,
        detail=detail,
    )
