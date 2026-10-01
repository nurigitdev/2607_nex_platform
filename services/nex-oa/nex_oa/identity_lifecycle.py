from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

from nex_oa.subjects import normalize_registry_id, normalize_subject_status


OA_IDENTITY_LIFECYCLE_SCHEMA_VERSION = "oa_identity_lifecycle.v1"
OA_SUBJECT_LIFECYCLE_ENTITY = "SUBJECT"

_SUBJECT_TRANSITIONS = {
    "ACTIVE": frozenset(("DISABLED", "DELETED")),
    "DISABLED": frozenset(("ACTIVE", "DELETED")),
    "DELETED": frozenset(),
}
_REASON_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


@dataclass(frozen=True)
class OaIdentityLifecycleError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def plan_subject_status_transition(
    subject: Mapping[str, Any],
    *,
    target_status: object,
    expected_revision: object,
    reason_code: object | None = None,
) -> dict[str, Any]:
    record = _subject_record(subject)
    tenant_id = normalize_registry_id(record.get("tenant_id"), field_name="tenant_id")
    subject_id = normalize_registry_id(
        record.get("subject_id"), field_name="subject_id"
    )
    current_status = normalize_subject_status(record.get("status"))
    normalized_target = normalize_subject_status(target_status)
    current_revision = normalize_lifecycle_revision(record.get("revision", 1))
    normalized_expected = normalize_lifecycle_revision(expected_revision)
    if normalized_expected != current_revision:
        raise OaIdentityLifecycleError(
            status_code=409,
            error_code="oa.lifecycle_revision_conflict",
            detail="expected_revision does not match the current subject revision.",
        )

    changed = normalized_target != current_status
    if changed and normalized_target not in _SUBJECT_TRANSITIONS[current_status]:
        raise OaIdentityLifecycleError(
            status_code=409,
            error_code="oa.subject_transition_invalid",
            detail=f"subject status cannot transition from {current_status} to {normalized_target}.",
        )
    normalized_reason = normalize_lifecycle_reason(reason_code, required=changed)
    return {
        "lifecycle_schema_version": OA_IDENTITY_LIFECYCLE_SCHEMA_VERSION,
        "entity_type": OA_SUBJECT_LIFECYCLE_ENTITY,
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "previous_status": current_status,
        "target_status": normalized_target,
        "expected_revision": normalized_expected,
        "next_revision": current_revision + 1 if changed else current_revision,
        "changed": changed,
        "reason_code": normalized_reason,
        "terminal": normalized_target == "DELETED",
    }


def normalize_lifecycle_revision(value: object) -> int:
    if isinstance(value, bool):
        raise _revision_error()
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise _revision_error() from exc
    if revision < 1 or str(value) != str(revision):
        raise _revision_error()
    return revision


def normalize_lifecycle_reason(value: object | None, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise _reason_error("reason_code is required for a lifecycle change.")
        return None
    if not isinstance(value, str):
        raise _reason_error("reason_code must be a string.")
    reason = value.strip().lower()
    if not _REASON_CODE_PATTERN.fullmatch(reason):
        raise _reason_error(
            "reason_code must contain 2-64 lowercase letters, digits, '.', '_' or '-'."
        )
    return reason


def _subject_record(subject: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = subject.get("subject")
    if nested is None:
        return subject
    if not isinstance(nested, Mapping):
        raise OaIdentityLifecycleError(
            status_code=400,
            error_code="oa.subject_record_invalid",
            detail="subject must be an object.",
        )
    return nested


def _revision_error() -> OaIdentityLifecycleError:
    return OaIdentityLifecycleError(
        status_code=400,
        error_code="oa.lifecycle_revision_invalid",
        detail="revision must be a positive integer.",
    )


def _reason_error(detail: str) -> OaIdentityLifecycleError:
    return OaIdentityLifecycleError(
        status_code=400,
        error_code="oa.lifecycle_reason_invalid",
        detail=detail,
    )
