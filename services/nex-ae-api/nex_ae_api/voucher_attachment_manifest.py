from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from nex_runtime.semantic_hashes import (
    nsl_write_payload_hash_ref,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

ATTACHMENT_MANIFEST_SCHEMA_VERSION = "ae_voucher_attachment_manifest.v1"
ATTACHMENT_MANIFEST_CONSTRAINT = "ATTACHMENT_MANIFEST"
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "attachment_batch_id",
        "owner_subject_ref",
        "conversation_id",
        "interaction_id",
        "attachment_count",
        "total_size_bytes",
        "items",
        "attachment_manifest_hash",
    }
)
_ITEM_FIELDS = frozenset(
    {
        "attachment_id",
        "object_ref",
        "object_version_ref",
        "display_name",
        "media_type",
        "size_bytes",
        "content_sha256",
        "evidence_ref",
    }
)


@dataclass(frozen=True)
class VoucherAttachmentManifestError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_attachment_manifest(batch: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(batch, Mapping) or batch.get("state") not in {"READY", "LOCKED"}:
        raise _invalid("Voucher attachment batch must be READY or LOCKED.")
    items = batch.get("items")
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise _invalid("Voucher attachment batch items are invalid.")
    if any(not isinstance(item, Mapping) for item in items):
        raise _invalid("Voucher attachment batch item is invalid.")
    active = [item for item in items if item.get("state") != "REMOVED"]
    expected_state = "LOCKED" if batch["state"] == "LOCKED" else "READY"
    if any(
        not isinstance(item, Mapping) or item.get("state") != expected_state
        for item in active
    ):
        raise _invalid("Voucher attachment manifest contains an incomplete item.")
    projected = sorted(
        (_manifest_item(item) for item in active),
        key=lambda item: item["attachment_id"],
    )
    if len(projected) != batch.get("attachment_count") or sum(
        item["size_bytes"] for item in projected
    ) != batch.get("total_size_bytes"):
        raise _invalid("Voucher attachment manifest totals are inconsistent.")
    manifest = {
        "schema_version": ATTACHMENT_MANIFEST_SCHEMA_VERSION,
        "tenant_id": _text("tenant_id", batch.get("tenant_id")),
        "attachment_batch_id": _text(
            "attachment_batch_id", batch.get("attachment_batch_id")
        ),
        "owner_subject_ref": _owner(batch.get("owner_subject_ref")),
        "conversation_id": _text("conversation_id", batch.get("conversation_id")),
        "interaction_id": _text("interaction_id", batch.get("interaction_id")),
        "attachment_count": len(projected),
        "total_size_bytes": sum(item["size_bytes"] for item in projected),
        "items": projected,
    }
    manifest["attachment_manifest_hash"] = semantic_sha256_hash_ref(manifest)
    persisted_hash = batch.get("attachment_manifest_hash")
    if (
        batch["state"] == "LOCKED"
        and persisted_hash != manifest["attachment_manifest_hash"]
    ):
        raise _invalid("Locked Voucher attachment manifest integrity failed.")
    return manifest


def validate_attachment_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Voucher attachment manifest must be an object.")
    supplied = dict(value)
    if set(supplied) != _MANIFEST_FIELDS:
        raise _invalid("Voucher attachment manifest fields are invalid.")
    if supplied.get("schema_version") != ATTACHMENT_MANIFEST_SCHEMA_VERSION:
        raise _invalid("Voucher attachment manifest schema is invalid.")
    try:
        supplied_hash = validate_hash_ref(supplied.get("attachment_manifest_hash"))
    except ValueError as exc:
        raise _invalid("Voucher attachment manifest hash is invalid.") from exc
    expected = semantic_sha256_hash_ref(
        {
            key: item
            for key, item in supplied.items()
            if key != "attachment_manifest_hash"
        }
    )
    if supplied_hash != expected:
        raise _invalid("Voucher attachment manifest hash does not match its content.")
    items = supplied.get("items")
    if not isinstance(items, list) or items != sorted(
        items, key=lambda item: str(item.get("attachment_id"))
    ):
        raise _invalid("Voucher attachment manifest items are not canonically sorted.")
    if len(items) != supplied.get("attachment_count") or sum(
        _size(item.get("size_bytes")) for item in items
    ) != supplied.get("total_size_bytes"):
        raise _invalid("Voucher attachment manifest totals are inconsistent.")
    for item in items:
        if not isinstance(item, Mapping) or set(item) != _ITEM_FIELDS:
            raise _invalid("Voucher attachment manifest item fields are invalid.")
        _manifest_item(item)
    _owner(supplied.get("owner_subject_ref"))
    for field in (
        "tenant_id",
        "attachment_batch_id",
        "conversation_id",
        "interaction_id",
    ):
        _text(field, supplied.get(field))
    return deepcopy(supplied)


def bind_manifest_to_work_intent(
    work_intent: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    bound = deepcopy(dict(work_intent))
    normalized = validate_attachment_manifest(manifest)
    constraints = bound.get("constraints")
    if not isinstance(constraints, list):
        raise _invalid("WorkIntent constraints are invalid.")
    identity = manifest_identity(normalized)
    existing = [
        item
        for item in constraints
        if isinstance(item, Mapping)
        and item.get("constraint_type") == ATTACHMENT_MANIFEST_CONSTRAINT
    ]
    constraint = {
        "constraint_type": ATTACHMENT_MANIFEST_CONSTRAINT,
        "description": "Use the exact approval-locked Voucher attachment manifest.",
        **identity,
    }
    if existing and existing != [constraint]:
        raise _invalid("WorkIntent is already bound to another attachment manifest.")
    if not existing:
        constraints.append(constraint)
    bound["intent_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in bound.items() if key != "intent_hash"}
    )
    return bound


def manifest_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_attachment_manifest(manifest)
    return {
        "attachment_batch_id": normalized["attachment_batch_id"],
        "attachment_manifest_hash": normalized["attachment_manifest_hash"],
        "attachment_count": normalized["attachment_count"],
        "total_size_bytes": normalized["total_size_bytes"],
    }


def work_intent_manifest_binding(
    work_intent: Mapping[str, Any],
) -> dict[str, Any] | None:
    constraints = work_intent.get("constraints")
    if not isinstance(constraints, list):
        return None
    matches = [
        item
        for item in constraints
        if isinstance(item, Mapping)
        and item.get("constraint_type") == ATTACHMENT_MANIFEST_CONSTRAINT
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise _invalid("WorkIntent has multiple attachment manifest bindings.")
    item = matches[0]
    identity = {
        "attachment_batch_id": _text(
            "attachment_batch_id", item.get("attachment_batch_id")
        ),
        "attachment_manifest_hash": _hash(
            "attachment_manifest_hash", item.get("attachment_manifest_hash")
        ),
        "attachment_count": _count(item.get("attachment_count")),
        "total_size_bytes": _size(item.get("total_size_bytes"), allow_zero=True),
    }
    return identity


def bind_manifest_to_governed_payload(
    payload: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = validate_attachment_manifest(manifest)
    result = deepcopy(dict(payload))
    attachments = [
        {
            key: item[key]
            for key in (
                "attachment_id",
                "object_ref",
                "display_name",
                "media_type",
                "size_bytes",
                "content_sha256",
                "evidence_ref",
            )
            if item.get(key) is not None
        }
        for item in normalized["items"]
    ]
    existing = result.get("attachments")
    if existing not in (None, []) and existing != attachments:
        raise _invalid("Governed payload is already bound to other attachments.")
    result.update(
        {
            "attachment_batch_id": normalized["attachment_batch_id"],
            "attachment_manifest_hash": normalized["attachment_manifest_hash"],
            "attachments": attachments,
        }
    )
    return result


def approval_display_summary(
    summary: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    result = deepcopy(dict(summary))
    identity = manifest_identity(manifest)
    for key, value in identity.items():
        existing = result.get(key)
        if existing is not None and existing != value:
            raise _invalid("Approval summary has another attachment manifest binding.")
        result[key] = value
    return result


def require_manifest_approval_binding(
    *,
    manifest: Mapping[str, Any],
    governed_payload: Mapping[str, Any],
    approval_request: object,
    approval_evidence: Mapping[str, Any] | None = None,
) -> str:
    normalized = validate_attachment_manifest(manifest)
    request = _approval_record(approval_request)
    expected_payload = bind_manifest_to_governed_payload(governed_payload, normalized)
    expected_hash = nsl_write_payload_hash_ref(expected_payload)
    summary = request.get("display_safe_summary")
    identity = manifest_identity(normalized)
    if (
        request.get("payload_hash") != expected_hash
        or not isinstance(summary, Mapping)
        or any(summary.get(key) != value for key, value in identity.items())
    ):
        raise _invalid("ApprovalRequest does not bind the exact attachment manifest.")
    if approval_evidence is not None and (
        approval_evidence.get("payload_hash") != expected_hash
        or approval_evidence.get("write_intent_hash")
        != request.get("write_intent_hash")
        or approval_evidence.get("approval_request_id")
        != request.get("approval_request_id")
    ):
        raise _invalid("Platform ApprovalEvidence has stale attachment lineage.")
    return expected_hash


def _manifest_item(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Voucher attachment manifest item is invalid.")
    result = {
        "attachment_id": _text("attachment_id", value.get("attachment_id")),
        "object_ref": _text("object_ref", value.get("object_ref")),
        "object_version_ref": _optional_text(value.get("object_version_ref")),
        "display_name": _text("display_name", value.get("display_name")),
        "media_type": _text("media_type", value.get("media_type")),
        "size_bytes": _size(value.get("size_bytes")),
        "content_sha256": _digest(value.get("content_sha256")),
        "evidence_ref": _optional_text(value.get("evidence_ref")),
    }
    return result


def _approval_record(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_data = getattr(value, "to_data", None)
    if callable(to_data):
        result = to_data()
        if isinstance(result, Mapping):
            return dict(result)
    raise _invalid("ApprovalRequest is invalid.")


def _owner(value: object) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"type", "id"}
        or value.get("type") != "oa.user"
    ):
        raise _invalid("Voucher attachment manifest owner is invalid.")
    return {"type": "oa.user", "id": _text("owner_subject_id", value.get("id"))}


def _text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text("optional manifest field", value)


def _digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise _invalid("content_sha256 is invalid.")
    try:
        int(value, 16)
    except ValueError as exc:
        raise _invalid("content_sha256 is invalid.") from exc
    if value.lower() != value:
        raise _invalid("content_sha256 is invalid.")
    return value


def _hash(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} is invalid.") from exc


def _size(value: object, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _invalid("Voucher attachment size is invalid.")
    return value


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 20:
        raise _invalid("Voucher attachment count is invalid.")
    return value


def _invalid(detail: str) -> VoucherAttachmentManifestError:
    return VoucherAttachmentManifestError(
        "ae.voucher_attachment_manifest_invalid", detail
    )
