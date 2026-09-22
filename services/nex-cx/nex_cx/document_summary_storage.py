from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CxPrivateContentError,
    CxPrivateTextStore,
    build_private_payload_key,
    sha256_private_text,
)


SUMMARY_TEXT_PAYLOAD_KIND = "summary_text"


def persist_document_summary_text(
    *,
    private_text_store: CxPrivateTextStore,
    access_context: CxAccessContext,
    summary: Mapping[str, Any],
    summary_text: str,
) -> dict[str, Any]:
    """Persist a summary payload and return metadata linked to its private URI."""
    summary_id = _required_text(summary, "document_summary_id")
    expected_sha256 = _required_sha256(summary, "summary_text_sha256")
    if sha256_private_text(summary_text) != expected_sha256:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_SUMMARY_TEXT_HASH_MISMATCH",
            detail="Summary text does not match its metadata SHA-256 value.",
        )
    key = build_private_payload_key(
        access_context,
        payload_kind=SUMMARY_TEXT_PAYLOAD_KIND,
        content_id=summary_id,
    )
    receipt = private_text_store.put_text(
        access_context=access_context,
        key=key,
        text=summary_text,
        expected_sha256=expected_sha256,
    )
    return {
        **dict(summary),
        "summary_storage_uri": receipt.storage_uri,
    }


def load_document_summary_text(
    *,
    private_text_store: CxPrivateTextStore,
    access_context: CxAccessContext,
    summary: Mapping[str, Any],
) -> str | None:
    """Reload a private summary payload and verify its metadata-bound hash."""
    storage_uri = _required_text(summary, "summary_storage_uri")
    if not storage_uri.startswith("cx-private://"):
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_SUMMARY_STORAGE_REFERENCE_INVALID",
            detail="Summary metadata does not reference private durable storage.",
        )
    key = build_private_payload_key(
        access_context,
        payload_kind=SUMMARY_TEXT_PAYLOAD_KIND,
        content_id=_required_text(summary, "document_summary_id"),
    )
    return private_text_store.get_text(
        access_context=access_context,
        key=key,
        expected_sha256=_required_sha256(summary, "summary_text_sha256"),
    )


def _required_text(summary: Mapping[str, Any], field: str) -> str:
    value = summary.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_SUMMARY_STORAGE_METADATA_INVALID",
            detail=f"Summary metadata field {field} is invalid.",
        )
    return value.strip()


def _required_sha256(summary: Mapping[str, Any], field: str) -> str:
    value = _required_text(summary, field).lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_SUMMARY_STORAGE_METADATA_INVALID",
            detail=f"Summary metadata field {field} is not a SHA-256 value.",
        )
    return value
