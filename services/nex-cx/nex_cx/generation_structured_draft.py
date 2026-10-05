from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CxPrivateContentError,
    CxPrivateTextStore,
    build_private_payload_key,
    sha256_private_text,
)


GENERATION_STRUCTURED_DRAFT_PRIVATE_SCHEMA_VERSION = (
    "cx_generation_structured_draft_private.v1"
)
GENERATION_STRUCTURED_DRAFT_PAYLOAD_KIND = "structured_draft"
STRUCTURED_DRAFT_PRIVATE_METADATA_FIELDS = frozenset(
    {
        "structured_draft_private_schema_version",
        "structured_draft_storage_backend",
        "structured_draft_storage_uri",
        "structured_draft_sha256",
        "structured_draft_size_bytes",
    }
)


def persist_generation_structured_draft(
    *,
    private_text_store: CxPrivateTextStore,
    access_context: CxAccessContext,
    cx_generation_id: str,
    structured_draft: Mapping[str, Any],
) -> dict[str, Any]:
    draft = _validated_draft_identity(structured_draft, cx_generation_id)
    serialized = json.dumps(
        draft,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = sha256_private_text(serialized)
    key = build_private_payload_key(
        access_context,
        payload_kind=GENERATION_STRUCTURED_DRAFT_PAYLOAD_KIND,
        content_id=cx_generation_id,
    )
    receipt = private_text_store.put_text(
        access_context=access_context,
        key=key,
        text=serialized,
        expected_sha256=digest,
    )
    return {
        "structured_draft_private_schema_version": (
            GENERATION_STRUCTURED_DRAFT_PRIVATE_SCHEMA_VERSION
        ),
        "structured_draft_storage_backend": receipt.storage_backend,
        "structured_draft_storage_uri": receipt.storage_uri,
        "structured_draft_sha256": receipt.sha256,
        "structured_draft_size_bytes": receipt.size_bytes,
    }


def load_generation_structured_draft(
    *,
    private_text_store: CxPrivateTextStore,
    access_context: CxAccessContext,
    cx_generation_id: str,
    metadata: Mapping[str, Any],
    expected_structured_draft_id: str | None,
) -> dict[str, Any] | None:
    validated = validate_generation_structured_draft_metadata(metadata)
    key = build_private_payload_key(
        access_context,
        payload_kind=GENERATION_STRUCTURED_DRAFT_PAYLOAD_KIND,
        content_id=cx_generation_id,
    )
    serialized = private_text_store.get_text(
        access_context=access_context,
        key=key,
        expected_sha256=validated["structured_draft_sha256"],
    )
    if serialized is None:
        return None
    if len(serialized.encode("utf-8")) != validated[
        "structured_draft_size_bytes"
    ]:
        raise _invalid("Structured draft size does not match its metadata.")
    try:
        draft = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise _invalid("Structured draft payload is not valid JSON.") from exc
    normalized = _validated_draft_identity(draft, cx_generation_id)
    if (
        expected_structured_draft_id is not None
        and normalized["structured_draft_id"] != expected_structured_draft_id
    ):
        raise _invalid("Structured draft identity does not match generation metadata.")
    return normalized


def validate_generation_structured_draft_metadata(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    if metadata.get("structured_draft_private_schema_version") != (
        GENERATION_STRUCTURED_DRAFT_PRIVATE_SCHEMA_VERSION
    ):
        raise _invalid("Structured draft private schema version is invalid.")
    backend = _required_text(
        metadata.get("structured_draft_storage_backend"),
        "structured draft storage backend",
    )
    storage_uri = _required_text(
        metadata.get("structured_draft_storage_uri"),
        "structured draft storage URI",
    )
    if not storage_uri.startswith("cx-private://"):
        raise _invalid("Structured draft storage URI is invalid.")
    digest = _sha256(metadata.get("structured_draft_sha256"))
    size_bytes = metadata.get("structured_draft_size_bytes")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 1
    ):
        raise _invalid("Structured draft size is invalid.")
    return {
        "structured_draft_private_schema_version": (
            GENERATION_STRUCTURED_DRAFT_PRIVATE_SCHEMA_VERSION
        ),
        "structured_draft_storage_backend": backend,
        "structured_draft_storage_uri": storage_uri,
        "structured_draft_sha256": digest,
        "structured_draft_size_bytes": size_bytes,
    }


def _validated_draft_identity(
    value: object,
    cx_generation_id: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Structured draft must be an object.")
    draft = dict(value)
    if draft.get("structured_draft_schema_version") != "cx_structured_draft.v1":
        raise _invalid("Structured draft schema version is invalid.")
    draft_id = _required_text(draft.get("structured_draft_id"), "structured draft ID")
    generation_id = _required_text(
        draft.get("cx_generation_id"), "structured draft generation ID"
    )
    if generation_id != _required_text(cx_generation_id, "generation ID"):
        raise _invalid("Structured draft generation identity is inconsistent.")
    draft["structured_draft_id"] = draft_id
    draft["cx_generation_id"] = generation_id
    return draft


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
        raise _invalid(f"{field} is invalid.")
    return value.strip()


def _sha256(value: object) -> str:
    normalized = _required_text(value, "structured draft SHA-256").lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise _invalid("Structured draft SHA-256 is invalid.")
    return normalized


def _invalid(detail: str) -> CxPrivateContentError:
    return CxPrivateContentError(
        status_code=409,
        error_code="CX_GENERATION_STRUCTURED_DRAFT_INVALID",
        detail=detail,
    )
