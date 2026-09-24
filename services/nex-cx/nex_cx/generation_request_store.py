from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CxPrivateContentError,
    CxPrivateTextStore,
    build_private_payload_key,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore


GENERATION_REQUEST_ENVELOPE_SCHEMA_VERSION = "cx_generation_request_envelope.v1"
GENERATION_REQUEST_RECEIPT_SCHEMA_VERSION = "cx_generation_request_receipt.v1"
GENERATION_REQUEST_PAYLOAD_KIND = "generation_request"
GENERATION_REQUEST_STORAGE_ROOT_ENV = "NEX_CX_GENERATION_REQUEST_STORAGE_ROOT"
DEFAULT_GENERATION_REQUEST_STORAGE_ROOT = Path(
    "/data/nex-platform/cx/generation-requests"
)
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "api-key",
        "authorization",
        "password",
        "service_token",
        "service-token",
    }
)


def build_generation_request_envelope(
    *,
    access_context: CxAccessContext,
    cx_generation_id: str,
    admission_id: str,
    source_payload: Mapping[str, Any],
    mo_payload: Mapping[str, Any],
    compatibility_rule: Mapping[str, Any],
    retrieval_package: Mapping[str, Any] | None,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    envelope = {
        "envelope_schema_version": GENERATION_REQUEST_ENVELOPE_SCHEMA_VERSION,
        "cx_generation_id": _required_text(cx_generation_id, "cx_generation_id"),
        "admission_id": _required_text(admission_id, "admission_id"),
        "tenant_ref_id": _required_text(access_context.tenant_id, "tenant_ref_id"),
        "owner_subject_ref_id": _required_text(
            access_context.subject_id, "owner_subject_ref_id"
        ),
        "request_id": _required_text(request_id, "request_id"),
        "trace_id": _required_text(trace_id, "trace_id"),
        "source_payload": _mapping(source_payload, "source_payload"),
        "mo_payload": _mapping(mo_payload, "mo_payload"),
        "compatibility_rule": _mapping(
            compatibility_rule, "compatibility_rule"
        ),
        "retrieval_package": (
            _mapping(retrieval_package, "retrieval_package")
            if retrieval_package is not None
            else None
        ),
    }
    return validate_generation_request_envelope(
        envelope,
        access_context=access_context,
        cx_generation_id=cx_generation_id,
    )


def persist_generation_request_envelope(
    *,
    private_text_store: CxPrivateTextStore,
    access_context: CxAccessContext,
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_generation_request_envelope(
        envelope,
        access_context=access_context,
        cx_generation_id=envelope.get("cx_generation_id"),
    )
    serialized = _canonical_json(normalized)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    key = build_private_payload_key(
        access_context,
        payload_kind=GENERATION_REQUEST_PAYLOAD_KIND,
        content_id=normalized["cx_generation_id"],
    )
    receipt = private_text_store.put_text(
        access_context=access_context,
        key=key,
        text=serialized,
        expected_sha256=digest,
    )
    return {
        "request_receipt_schema_version": GENERATION_REQUEST_RECEIPT_SCHEMA_VERSION,
        "request_storage_backend": receipt.storage_backend,
        "request_storage_uri": receipt.storage_uri,
        "request_envelope_sha256": receipt.sha256,
        "request_envelope_size_bytes": receipt.size_bytes,
    }


def load_generation_request_envelope(
    *,
    private_text_store: CxPrivateTextStore,
    access_context: CxAccessContext,
    cx_generation_id: str,
    receipt: Mapping[str, Any],
) -> dict[str, Any] | None:
    metadata = validate_generation_request_receipt(receipt)
    generation_id = _required_text(cx_generation_id, "cx_generation_id")
    key = build_private_payload_key(
        access_context,
        payload_kind=GENERATION_REQUEST_PAYLOAD_KIND,
        content_id=generation_id,
    )
    serialized = private_text_store.get_text(
        access_context=access_context,
        key=key,
        expected_sha256=metadata["request_envelope_sha256"],
    )
    if serialized is None:
        return None
    if len(serialized.encode("utf-8")) != metadata["request_envelope_size_bytes"]:
        raise _invalid("Stored generation request size does not match its receipt.")
    try:
        decoded = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise _invalid("Stored generation request is not valid JSON.") from exc
    return validate_generation_request_envelope(
        decoded,
        access_context=access_context,
        cx_generation_id=generation_id,
    )


def validate_generation_request_envelope(
    value: object,
    *,
    access_context: CxAccessContext,
    cx_generation_id: object,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Generation request envelope must be an object.")
    if value.get("envelope_schema_version") != (
        GENERATION_REQUEST_ENVELOPE_SCHEMA_VERSION
    ):
        raise _invalid("Generation request envelope schema version is invalid.")
    generation_id = _required_text(cx_generation_id, "cx_generation_id")
    if _required_text(value.get("cx_generation_id"), "cx_generation_id") != generation_id:
        raise _not_found()
    if _required_text(value.get("tenant_ref_id"), "tenant_ref_id") != (
        access_context.tenant_id
    ) or _required_text(
        value.get("owner_subject_ref_id"), "owner_subject_ref_id"
    ) != access_context.subject_id:
        raise _not_found()
    normalized = {
        "envelope_schema_version": GENERATION_REQUEST_ENVELOPE_SCHEMA_VERSION,
        "cx_generation_id": generation_id,
        "admission_id": _required_text(value.get("admission_id"), "admission_id"),
        "tenant_ref_id": access_context.tenant_id,
        "owner_subject_ref_id": access_context.subject_id,
        "request_id": _required_text(value.get("request_id"), "request_id"),
        "trace_id": _required_text(value.get("trace_id"), "trace_id"),
        "source_payload": _mapping(value.get("source_payload"), "source_payload"),
        "mo_payload": _mapping(value.get("mo_payload"), "mo_payload"),
        "compatibility_rule": _mapping(
            value.get("compatibility_rule"), "compatibility_rule"
        ),
        "retrieval_package": (
            _mapping(value.get("retrieval_package"), "retrieval_package")
            if value.get("retrieval_package") is not None
            else None
        ),
    }
    if normalized["mo_payload"].get("cx_generation_id") != generation_id:
        raise _invalid("MO payload generation identity is invalid.")
    if _contains_secret(normalized):
        raise _invalid("Generation request envelope contains credential material.")
    return normalized


def validate_generation_request_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("request_receipt_schema_version") != (
        GENERATION_REQUEST_RECEIPT_SCHEMA_VERSION
    ):
        raise _invalid("Generation request receipt schema version is invalid.")
    backend = _required_text(value.get("request_storage_backend"), "request_storage_backend")
    uri = value.get("request_storage_uri")
    if not isinstance(uri, str) or not uri.startswith("cx-private://"):
        raise _invalid("Generation request storage URI is invalid.")
    digest = value.get("request_envelope_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise _invalid("Generation request SHA-256 is invalid.")
    size = value.get("request_envelope_size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise _invalid("Generation request size is invalid.")
    return {
        "request_receipt_schema_version": GENERATION_REQUEST_RECEIPT_SCHEMA_VERSION,
        "request_storage_backend": backend,
        "request_storage_uri": uri,
        "request_envelope_sha256": digest,
        "request_envelope_size_bytes": size,
    }


def build_generation_request_store(
    environ: Mapping[str, str] | None = None,
) -> FileSystemCxPrivateTextStore:
    env = os.environ if environ is None else environ
    root = env.get(
        GENERATION_REQUEST_STORAGE_ROOT_ENV,
        str(DEFAULT_GENERATION_REQUEST_STORAGE_ROOT),
    )
    return FileSystemCxPrivateTextStore(root)


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field_name} must be an object.")
    return json.loads(json.dumps(dict(value)))


def _contains_secret(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).strip().lower() in _SECRET_KEYS or _contains_secret(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be a non-empty string.")
    return value.strip()


def _not_found() -> CxPrivateContentError:
    return CxPrivateContentError(
        status_code=404,
        error_code="CX_GENERATION_REQUEST_NOT_FOUND",
        detail="Generation request envelope was not found for the owner scope.",
    )


def _invalid(detail: str) -> CxPrivateContentError:
    return CxPrivateContentError(
        status_code=409,
        error_code="CX_GENERATION_REQUEST_INVALID",
        detail=detail,
    )
