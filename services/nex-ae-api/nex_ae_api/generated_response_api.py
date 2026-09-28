from __future__ import annotations

import hashlib
from typing import Any, Mapping

from nex_ae_api.generated_response_lineage import (
    validate_generated_response_lineage,
)


AE_GENERATED_RESPONSE_SCHEMA_VERSION = "ae_generated_response.v1"


def build_generated_response_owner_view(
    record: Mapping[str, Any],
    lineage: Mapping[str, Any],
    content: str,
) -> dict[str, Any]:
    normalized = validate_generated_response_lineage(lineage)
    if (
        normalized["interaction_id"] != record.get("interaction_id")
        or normalized["chat_document_id"] != record.get("chat_document_id")
        or normalized["cx_generation_id"] != record.get("cx_generation_id")
    ):
        raise ValueError("Generated response owner view lineage is inconsistent.")
    if not isinstance(content, str):
        raise ValueError("Generated response owner view content is invalid.")
    encoded = content.encode("utf-8")
    if (
        len(encoded) != normalized["size_bytes"]
        or hashlib.sha256(encoded).hexdigest() != normalized["content_sha256"]
    ):
        raise ValueError("Generated response owner view integrity check failed.")
    return {
        "response_schema_version": AE_GENERATED_RESPONSE_SCHEMA_VERSION,
        "interaction_id": normalized["interaction_id"],
        "chat_document_id": normalized["chat_document_id"],
        "response_id": normalized["response_id"],
        "cx_generation_id": normalized["cx_generation_id"],
        "content_type": normalized["content_type"],
        "content": content,
        "content_sha256": normalized["content_sha256"],
        "size_bytes": normalized["size_bytes"],
        "lineage": normalized,
        "owner_scope_enforced": True,
    }
