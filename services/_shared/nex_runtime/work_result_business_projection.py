from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .semantic_hashes import canonical_json, semantic_sha256_hash_ref, validate_hash_ref

WORK_RESULT_BUSINESS_PROJECTION_SCHEMA_VERSION = (
    "nex_work_result_business_projection.v1"
)
_FIELDS = frozenset(
    {
        "schema_version",
        "source_agent_result_hash",
        "business_object_refs",
        "external_refs",
        "business_summary",
        "projection_hash",
    }
)


class WorkResultBusinessProjectionError(ValueError):
    pass


def build_work_result_business_projection(
    *,
    source_agent_result_hash: object,
    business_object_refs: object,
    external_refs: object,
    business_summary: object,
) -> dict[str, Any]:
    projection = {
        "schema_version": WORK_RESULT_BUSINESS_PROJECTION_SCHEMA_VERSION,
        "source_agent_result_hash": source_agent_result_hash,
        "business_object_refs": business_object_refs,
        "external_refs": external_refs,
        "business_summary": business_summary,
    }
    normalized = _normalize(projection, require_hash=False)
    normalized["projection_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def validate_work_result_business_projection(value: object) -> dict[str, Any]:
    normalized = _normalize(value, require_hash=True)
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in normalized.items() if key != "projection_hash"}
    )
    if normalized["projection_hash"] != expected_hash:
        raise WorkResultBusinessProjectionError(
            "WorkResult business projection hash does not match its content."
        )
    return normalized


def _normalize(value: object, *, require_hash: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkResultBusinessProjectionError(
            "WorkResult business projection must be an object."
        )
    projection = copy.deepcopy(dict(value))
    expected_fields = _FIELDS if require_hash else _FIELDS - {"projection_hash"}
    if set(projection) != expected_fields:
        raise WorkResultBusinessProjectionError(
            "WorkResult business projection fields are invalid."
        )
    if (
        projection.get("schema_version")
        != WORK_RESULT_BUSINESS_PROJECTION_SCHEMA_VERSION
    ):
        raise WorkResultBusinessProjectionError(
            "WorkResult business projection schema version is invalid."
        )
    try:
        projection["source_agent_result_hash"] = validate_hash_ref(
            projection.get("source_agent_result_hash")
        )
        if require_hash:
            projection["projection_hash"] = validate_hash_ref(
                projection.get("projection_hash")
            )
    except ValueError as exc:
        raise WorkResultBusinessProjectionError(str(exc)) from exc
    projection["business_object_refs"] = _entity_refs(
        projection.get("business_object_refs")
    )
    projection["external_refs"] = _text_refs(projection.get("external_refs"))
    summary = projection.get("business_summary")
    if summary is not None and not isinstance(summary, Mapping):
        raise WorkResultBusinessProjectionError(
            "WorkResult business summary must be an object or null."
        )
    projection["business_summary"] = (
        None if summary is None else copy.deepcopy(dict(summary))
    )
    try:
        encoded = canonical_json(projection["business_summary"])
    except (TypeError, ValueError) as exc:
        raise WorkResultBusinessProjectionError(
            "WorkResult business summary must be canonical JSON."
        ) from exc
    if len(encoded.encode("utf-8")) > 32_768:
        raise WorkResultBusinessProjectionError(
            "WorkResult business summary exceeds the 32768-byte bound."
        )
    return projection


def _entity_refs(value: object) -> list[dict[str, str]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise WorkResultBusinessProjectionError(
            "business_object_refs must be an array."
        )
    if len(value) > 32:
        raise WorkResultBusinessProjectionError(
            "business_object_refs exceeds the 32-item bound."
        )
    refs: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"entity_type", "entity_id"}:
            raise WorkResultBusinessProjectionError(
                "business_object_refs contains an invalid entity reference."
            )
        entity_type = _text(item.get("entity_type"), maximum=80)
        entity_id = _text(item.get("entity_id"), maximum=256)
        refs.append({"entity_type": entity_type, "entity_id": entity_id})
    refs.sort(key=lambda item: (item["entity_type"], item["entity_id"]))
    if len({(item["entity_type"], item["entity_id"]) for item in refs}) != len(refs):
        raise WorkResultBusinessProjectionError(
            "business_object_refs contains duplicate references."
        )
    return refs


def _text_refs(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise WorkResultBusinessProjectionError("external_refs must be an array.")
    if len(value) > 64:
        raise WorkResultBusinessProjectionError(
            "external_refs exceeds the 64-item bound."
        )
    refs = sorted({_text(item, maximum=256) for item in value})
    return refs


def _text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise WorkResultBusinessProjectionError(
            "WorkResult business projection text value is invalid."
        )
    return value.strip()
