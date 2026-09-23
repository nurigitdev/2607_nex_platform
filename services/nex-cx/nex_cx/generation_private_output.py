from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CxPrivateContentError,
    CxPrivateTextStore,
    build_private_payload_key,
    sha256_private_text,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore


GENERATION_PRIVATE_OUTPUT_SCHEMA_VERSION = "cx_generation_private_output.v1"
GENERATION_OUTPUT_PAYLOAD_KIND = "generation_output"
GENERATION_OUTPUT_STORAGE_ROOT_ENV = "NEX_CX_GENERATION_OUTPUT_STORAGE_ROOT"
DEFAULT_GENERATION_OUTPUT_STORAGE_ROOT = Path(
    "/data/nex-platform/cx/generated-outputs"
)


def persist_generation_output(
    *,
    private_text_store: CxPrivateTextStore,
    access_context: CxAccessContext,
    cx_generation_id: str,
    output_text: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Persist full generated text and return raw-safe public metadata."""
    if not isinstance(output_text, str) or not output_text.strip():
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_GENERATION_OUTPUT_INVALID",
            detail="Generated output must be a non-empty string.",
        )
    if sha256_private_text(output_text) != expected_sha256:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_GENERATION_OUTPUT_HASH_MISMATCH",
            detail="Generated output does not match its metadata SHA-256 value.",
        )
    key = build_private_payload_key(
        access_context,
        payload_kind=GENERATION_OUTPUT_PAYLOAD_KIND,
        content_id=cx_generation_id,
    )
    receipt = private_text_store.put_text(
        access_context=access_context,
        key=key,
        text=output_text,
        expected_sha256=expected_sha256,
    )
    return {
        "private_output_schema_version": GENERATION_PRIVATE_OUTPUT_SCHEMA_VERSION,
        "output_storage_backend": receipt.storage_backend,
        "output_storage_uri": receipt.storage_uri,
        "output_sha256": receipt.sha256,
        "output_size_bytes": receipt.size_bytes,
    }


def load_generation_output(
    *,
    private_text_store: CxPrivateTextStore,
    access_context: CxAccessContext,
    cx_generation_id: str,
    metadata: Mapping[str, Any],
) -> str | None:
    """Reload owner-private generated text and verify its metadata binding."""
    _validate_metadata(metadata)
    key = build_private_payload_key(
        access_context,
        payload_kind=GENERATION_OUTPUT_PAYLOAD_KIND,
        content_id=cx_generation_id,
    )
    text = private_text_store.get_text(
        access_context=access_context,
        key=key,
        expected_sha256=str(metadata["output_sha256"]),
    )
    if text is None:
        return None
    if len(text.encode("utf-8")) != metadata["output_size_bytes"]:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_GENERATION_OUTPUT_SIZE_MISMATCH",
            detail="Generated output size does not match its metadata.",
        )
    return text


def build_generation_output_store(
    environ: Mapping[str, str] | None = None,
) -> FileSystemCxPrivateTextStore:
    env = os.environ if environ is None else environ
    root = env.get(
        GENERATION_OUTPUT_STORAGE_ROOT_ENV,
        str(DEFAULT_GENERATION_OUTPUT_STORAGE_ROOT),
    )
    return FileSystemCxPrivateTextStore(root)


def _validate_metadata(metadata: Mapping[str, Any]) -> None:
    if metadata.get("private_output_schema_version") != (
        GENERATION_PRIVATE_OUTPUT_SCHEMA_VERSION
    ):
        raise _metadata_invalid("private output schema version is invalid.")
    backend = metadata.get("output_storage_backend")
    if not isinstance(backend, str) or not backend.strip():
        raise _metadata_invalid("output storage backend is invalid.")
    storage_uri = metadata.get("output_storage_uri")
    if not isinstance(storage_uri, str) or not storage_uri.startswith("cx-private://"):
        raise _metadata_invalid("output storage URI is invalid.")
    output_sha256 = metadata.get("output_sha256")
    if (
        not isinstance(output_sha256, str)
        or len(output_sha256) != 64
        or any(character not in "0123456789abcdef" for character in output_sha256)
    ):
        raise _metadata_invalid("output SHA-256 is invalid.")
    size_bytes = metadata.get("output_size_bytes")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 1:
        raise _metadata_invalid("output size is invalid.")


def _metadata_invalid(detail: str) -> CxPrivateContentError:
    return CxPrivateContentError(
        status_code=409,
        error_code="CX_GENERATION_OUTPUT_METADATA_INVALID",
        detail=detail,
    )
