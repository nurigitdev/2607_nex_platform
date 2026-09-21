from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5


VECTOR_INDEX_SCHEMA_VERSION = "cx_vector_index.v1"
EMBEDDING_PROFILE_SCHEMA_VERSION = "cx_embedding_profile.v1"
VECTOR_INDEX_STATUSES = frozenset(
    {"BUILDING", "READY", "STALE", "REBUILD_REQUIRED", "FAILED"}
)
VECTOR_INDEX_STALE_REASONS = frozenset(
    {
        "CHUNK_SET_CHANGED",
        "CHUNK_POLICY_CHANGED",
        "SOURCE_CHANGED",
        "CHUNK_CONTENT_CHANGED",
        "PROVIDER_ALIAS_CHANGED",
        "MODEL_PROFILE_CHANGED",
        "MODEL_REVISION_CHANGED",
        "DEPLOYMENT_CHANGED",
        "VECTOR_DIMENSION_CHANGED",
        "PAYLOAD_COUNT_MISMATCH",
        "PAYLOAD_FINGERPRINT_MISMATCH",
    }
)
VECTOR_INDEX_TRANSITIONS = frozenset(
    {
        ("BUILDING", "READY"),
        ("BUILDING", "FAILED"),
        ("READY", "STALE"),
        ("STALE", "REBUILD_REQUIRED"),
        ("FAILED", "REBUILD_REQUIRED"),
        ("REBUILD_REQUIRED", "BUILDING"),
    }
)
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,159}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_KEYS = frozenset(
    {"embedding", "vector", "payload", "source_text", "chunk_text", "prompt"}
)


@dataclass(frozen=True)
class VectorIndexContractError(ValueError):
    error_code: str
    detail: str


def build_embedding_profile(
    *,
    provider_alias: str,
    model_profile_id: str,
    model_revision: str,
    deployment_id: str,
    vector_dimension: int,
) -> dict[str, Any]:
    profile = {
        "profile_schema_version": EMBEDDING_PROFILE_SCHEMA_VERSION,
        "provider_alias": _identifier(provider_alias, "provider_alias"),
        "model_profile_id": _identifier(model_profile_id, "model_profile_id"),
        "model_revision": _identifier(model_revision, "model_revision"),
        "deployment_id": _identifier(deployment_id, "deployment_id"),
        "vector_dimension": _positive_int(vector_dimension, "vector_dimension"),
    }
    return {**profile, "profile_fingerprint": _sha256_json(profile)}


def build_source_snapshot(
    *,
    chunk_set_id: str,
    chunk_policy_id: str,
    source_markdown_sha256: str,
    chunks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes)):
        raise VectorIndexContractError(
            "cx.vector_index.chunks_invalid",
            "Chunks must be an ordered metadata sequence.",
        )
    chunk_refs = [_chunk_ref(chunk) for chunk in chunks]
    chunk_refs.sort(key=lambda item: item["ordinal"])
    if [item["ordinal"] for item in chunk_refs] != list(range(len(chunk_refs))):
        raise VectorIndexContractError(
            "cx.vector_index.chunk_ordinals_invalid",
            "Chunk ordinals must be unique and contiguous from zero.",
        )
    if len({item["chunk_id"] for item in chunk_refs}) != len(chunk_refs):
        raise VectorIndexContractError(
            "cx.vector_index.chunk_ids_invalid",
            "Chunk identifiers must be unique.",
        )
    snapshot = {
        "chunk_set_id": _identifier(chunk_set_id, "chunk_set_id"),
        "chunk_policy_id": _identifier(chunk_policy_id, "chunk_policy_id"),
        "source_markdown_sha256": _sha256(
            source_markdown_sha256, "source_markdown_sha256"
        ),
        "chunk_count": len(chunk_refs),
        "chunk_refs": chunk_refs,
    }
    return {**snapshot, "source_fingerprint": _sha256_json(snapshot)}


def build_vector_index_manifest(
    *,
    content_object_id: str,
    tenant_ref: Mapping[str, Any],
    owner_subject_ref: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    embedding_profile: Mapping[str, Any],
    trace_id: str,
    request_id: str,
    observed_at: str,
) -> dict[str, Any]:
    source = _source_snapshot(source_snapshot)
    profile = _embedding_profile(embedding_profile)
    tenant = _typed_ref(tenant_ref, expected_type="oa.tenant", field="tenant_ref")
    owner = _typed_ref(
        owner_subject_ref,
        expected_type="oa.user",
        field="owner_subject_ref",
    )
    identity = ":".join(
        (
            tenant["id"],
            owner["id"],
            _identifier(content_object_id, "content_object_id"),
            source["source_fingerprint"],
            profile["profile_fingerprint"],
        )
    )
    manifest = {
        "vector_index_schema_version": VECTOR_INDEX_SCHEMA_VERSION,
        "vector_index_id": str(uuid5(NAMESPACE_URL, f"nex-cx-vector-index:{identity}")),
        "content_object_id": _identifier(content_object_id, "content_object_id"),
        "tenant_ref": tenant,
        "owner_subject_ref": owner,
        "source_snapshot": source,
        "embedding_profile": profile,
        "status": "BUILDING",
        "status_reason": None,
        "payload_count": 0,
        "payload_fingerprint": None,
        "checkpoint_version": 0,
        "trace_id": _identifier(trace_id, "trace_id"),
        "request_id": _identifier(request_id, "request_id"),
        "created_at": _timestamp(observed_at, "observed_at"),
        "updated_at": _timestamp(observed_at, "observed_at"),
        "ready_at": None,
    }
    validate_vector_index_manifest(manifest)
    return manifest


def mark_vector_index_ready(
    manifest: Mapping[str, Any],
    *,
    payload_receipts: Sequence[Mapping[str, Any]],
    observed_at: str,
) -> dict[str, Any]:
    current = validate_vector_index_manifest(manifest)
    _assert_transition(current["status"], "READY")
    receipts = [_payload_receipt(item) for item in payload_receipts]
    expected_refs = current["source_snapshot"]["chunk_refs"]
    expected_ids = [item["chunk_id"] for item in expected_refs]
    receipt_ids = [item["chunk_id"] for item in receipts]
    if sorted(receipt_ids) != sorted(expected_ids) or len(receipt_ids) != len(
        set(receipt_ids)
    ):
        raise VectorIndexContractError(
            "cx.vector_index.payload_set_mismatch",
            "Payload receipts must cover each source chunk exactly once.",
        )
    dimension = current["embedding_profile"]["vector_dimension"]
    if any(item["vector_dimension"] != dimension for item in receipts):
        raise VectorIndexContractError(
            "cx.vector_index.payload_dimension_mismatch",
            "Payload receipt dimensions must match the embedding profile.",
        )
    receipts.sort(key=lambda item: expected_ids.index(item["chunk_id"]))
    updated = {
        **current,
        "status": "READY",
        "status_reason": None,
        "payload_count": len(receipts),
        "payload_fingerprint": _sha256_json(receipts),
        "checkpoint_version": current["checkpoint_version"] + 1,
        "updated_at": _timestamp(observed_at, "observed_at"),
        "ready_at": _timestamp(observed_at, "observed_at"),
    }
    return validate_vector_index_manifest(updated)


def transition_vector_index_state(
    manifest: Mapping[str, Any],
    *,
    target_status: str,
    reason: str | None,
    observed_at: str,
) -> dict[str, Any]:
    current = validate_vector_index_manifest(manifest)
    if target_status == "READY":
        raise VectorIndexContractError(
            "cx.vector_index.ready_requires_receipts",
            "READY transition requires payload receipt verification.",
        )
    _assert_transition(current["status"], target_status)
    normalized_reason = _transition_reason(target_status, reason)
    updated = {
        **current,
        "status": target_status,
        "status_reason": normalized_reason,
        "checkpoint_version": current["checkpoint_version"] + 1,
        "updated_at": _timestamp(observed_at, "observed_at"),
    }
    if target_status == "BUILDING":
        updated.update(
            {
                "payload_count": 0,
                "payload_fingerprint": None,
                "ready_at": None,
            }
        )
    return validate_vector_index_manifest(updated)


def assess_vector_index_freshness(
    manifest: Mapping[str, Any] | None,
    *,
    source_snapshot: Mapping[str, Any],
    embedding_profile: Mapping[str, Any],
    payload_count: int,
    payload_fingerprint: str | None,
) -> dict[str, Any]:
    source = _source_snapshot(source_snapshot)
    profile = _embedding_profile(embedding_profile)
    count = _non_negative_int(payload_count, "payload_count")
    if manifest is None:
        return _freshness_result("MISSING", "INDEX_MISSING", usable=False)
    current = validate_vector_index_manifest(manifest)
    if current["status"] != "READY":
        return _freshness_result(
            current["status"], current["status_reason"], usable=False
        )
    reason = _freshness_mismatch_reason(current, source, profile, count)
    if reason is None and current["payload_fingerprint"] != payload_fingerprint:
        reason = "PAYLOAD_FINGERPRINT_MISMATCH"
    if reason is not None:
        return _freshness_result("STALE", reason, usable=False)
    return _freshness_result("READY", None, usable=True)


def validate_vector_index_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        raise VectorIndexContractError(
            "cx.vector_index.manifest_invalid", "Vector index manifest must be an object."
        )
    value = deepcopy(dict(manifest))
    if _contains_forbidden_key(value):
        raise VectorIndexContractError(
            "cx.vector_index.private_payload_forbidden",
            "Vector index manifests cannot contain private payload fields.",
        )
    if value.get("vector_index_schema_version") != VECTOR_INDEX_SCHEMA_VERSION:
        raise VectorIndexContractError(
            "cx.vector_index.schema_version_invalid",
            "Vector index schema version is not supported.",
        )
    for field in ("vector_index_id", "content_object_id", "trace_id", "request_id"):
        value[field] = _identifier(value.get(field), field)
    value["tenant_ref"] = _typed_ref(
        value.get("tenant_ref"), expected_type="oa.tenant", field="tenant_ref"
    )
    value["owner_subject_ref"] = _typed_ref(
        value.get("owner_subject_ref"),
        expected_type="oa.user",
        field="owner_subject_ref",
    )
    value["source_snapshot"] = _source_snapshot(value.get("source_snapshot"))
    value["embedding_profile"] = _embedding_profile(value.get("embedding_profile"))
    status = value.get("status")
    if status not in VECTOR_INDEX_STATUSES:
        raise VectorIndexContractError(
            "cx.vector_index.status_invalid", "Vector index status is invalid."
        )
    reason = value.get("status_reason")
    if status in {"BUILDING", "READY"} and reason is not None:
        raise VectorIndexContractError(
            "cx.vector_index.status_reason_invalid",
            "BUILDING and READY indexes cannot carry a status reason.",
        )
    if status in {"STALE", "REBUILD_REQUIRED", "FAILED"}:
        _identifier(reason, "status_reason")
    value["payload_count"] = _non_negative_int(
        value.get("payload_count"), "payload_count"
    )
    payload_fingerprint = value.get("payload_fingerprint")
    if payload_fingerprint is not None:
        value["payload_fingerprint"] = _sha256(
            payload_fingerprint, "payload_fingerprint"
        )
    if status == "READY" and (
        value["payload_count"] != value["source_snapshot"]["chunk_count"]
        or payload_fingerprint is None
    ):
        raise VectorIndexContractError(
            "cx.vector_index.ready_payload_invalid",
            "READY indexes require a complete payload fingerprint.",
        )
    value["checkpoint_version"] = _non_negative_int(
        value.get("checkpoint_version"), "checkpoint_version"
    )
    for field in ("created_at", "updated_at"):
        value[field] = _timestamp(value.get(field), field)
    ready_at = value.get("ready_at")
    if status == "READY" and ready_at is None:
        raise VectorIndexContractError(
            "cx.vector_index.ready_at_missing", "READY indexes require ready_at."
        )
    if ready_at is not None:
        value["ready_at"] = _timestamp(ready_at, "ready_at")
    return value


def _freshness_mismatch_reason(
    manifest: Mapping[str, Any],
    source: Mapping[str, Any],
    profile: Mapping[str, Any],
    payload_count: int,
) -> str | None:
    stored_source = manifest["source_snapshot"]
    stored_profile = manifest["embedding_profile"]
    comparisons = (
        (stored_source["chunk_set_id"], source["chunk_set_id"], "CHUNK_SET_CHANGED"),
        (
            stored_source["chunk_policy_id"],
            source["chunk_policy_id"],
            "CHUNK_POLICY_CHANGED",
        ),
        (
            stored_source["source_markdown_sha256"],
            source["source_markdown_sha256"],
            "SOURCE_CHANGED",
        ),
        (
            stored_source["source_fingerprint"],
            source["source_fingerprint"],
            "CHUNK_CONTENT_CHANGED",
        ),
        (
            stored_profile["provider_alias"],
            profile["provider_alias"],
            "PROVIDER_ALIAS_CHANGED",
        ),
        (
            stored_profile["model_profile_id"],
            profile["model_profile_id"],
            "MODEL_PROFILE_CHANGED",
        ),
        (
            stored_profile["model_revision"],
            profile["model_revision"],
            "MODEL_REVISION_CHANGED",
        ),
        (
            stored_profile["deployment_id"],
            profile["deployment_id"],
            "DEPLOYMENT_CHANGED",
        ),
        (
            stored_profile["vector_dimension"],
            profile["vector_dimension"],
            "VECTOR_DIMENSION_CHANGED",
        ),
        (manifest["payload_count"], payload_count, "PAYLOAD_COUNT_MISMATCH"),
    )
    return next((reason for stored, current, reason in comparisons if stored != current), None)


def _freshness_result(status: str, reason: str | None, *, usable: bool) -> dict[str, Any]:
    return {
        "freshness_schema_version": "cx_vector_index_freshness.v1",
        "status": status,
        "reason": reason,
        "retrieval_usable": usable,
        "rebuild_required": status in {"MISSING", "STALE", "REBUILD_REQUIRED", "FAILED"},
    }


def _assert_transition(current: str, target: str) -> None:
    if (current, target) not in VECTOR_INDEX_TRANSITIONS:
        raise VectorIndexContractError(
            "cx.vector_index.transition_invalid",
            f"Vector index transition is not allowed: {current}->{target}",
        )


def _transition_reason(target: str, reason: str | None) -> str | None:
    if target == "BUILDING":
        if reason is not None:
            raise VectorIndexContractError(
                "cx.vector_index.status_reason_invalid",
                "BUILDING transition cannot carry a reason.",
            )
        return None
    normalized = _identifier(reason, "status_reason")
    if target in {"STALE", "REBUILD_REQUIRED"} and normalized not in (
        VECTOR_INDEX_STALE_REASONS | {"BUILD_FAILED"}
    ):
        raise VectorIndexContractError(
            "cx.vector_index.stale_reason_invalid",
            "Vector index stale reason is not supported.",
        )
    return normalized


def _payload_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or _contains_forbidden_key(value):
        raise VectorIndexContractError(
            "cx.vector_index.payload_receipt_invalid",
            "Payload receipt must contain metadata only.",
        )
    return {
        "chunk_id": _identifier(value.get("chunk_id"), "chunk_id"),
        "embedding_sha256": _sha256(
            value.get("embedding_sha256"), "embedding_sha256"
        ),
        "vector_dimension": _positive_int(
            value.get("vector_dimension"), "vector_dimension"
        ),
        "storage_uri": _storage_uri(value.get("storage_uri")),
    }


def _source_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise VectorIndexContractError(
            "cx.vector_index.source_snapshot_invalid",
            "Source snapshot must be an object.",
        )
    rebuilt = build_source_snapshot(
        chunk_set_id=value.get("chunk_set_id"),
        chunk_policy_id=value.get("chunk_policy_id"),
        source_markdown_sha256=value.get("source_markdown_sha256"),
        chunks=value.get("chunk_refs", ()),
    )
    if rebuilt["source_fingerprint"] != value.get("source_fingerprint"):
        raise VectorIndexContractError(
            "cx.vector_index.source_fingerprint_invalid",
            "Source fingerprint verification failed.",
        )
    return rebuilt


def _embedding_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise VectorIndexContractError(
            "cx.vector_index.embedding_profile_invalid",
            "Embedding profile must be an object.",
        )
    rebuilt = build_embedding_profile(
        provider_alias=value.get("provider_alias"),
        model_profile_id=value.get("model_profile_id"),
        model_revision=value.get("model_revision"),
        deployment_id=value.get("deployment_id"),
        vector_dimension=value.get("vector_dimension"),
    )
    if rebuilt["profile_fingerprint"] != value.get("profile_fingerprint"):
        raise VectorIndexContractError(
            "cx.vector_index.profile_fingerprint_invalid",
            "Embedding profile fingerprint verification failed.",
        )
    return rebuilt


def _chunk_ref(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or _contains_forbidden_key(value):
        raise VectorIndexContractError(
            "cx.vector_index.chunk_ref_invalid",
            "Chunk references must contain metadata only.",
        )
    return {
        "chunk_id": _identifier(value.get("chunk_id"), "chunk_id"),
        "ordinal": _non_negative_int(value.get("ordinal"), "ordinal"),
        "text_sha256": _sha256(value.get("text_sha256"), "text_sha256"),
    }


def _typed_ref(value: Mapping[str, Any], *, expected_type: str, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"type", "id"}:
        raise VectorIndexContractError(
            "cx.vector_index.owner_ref_invalid", f"{field} must be a typed reference."
        )
    if value.get("type") != expected_type:
        raise VectorIndexContractError(
            "cx.vector_index.owner_ref_invalid", f"{field} type is invalid."
        )
    return {"type": expected_type, "id": _identifier(value.get("id"), field)}


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise VectorIndexContractError(
            "cx.vector_index.identifier_invalid", f"{field} is invalid."
        )
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise VectorIndexContractError(
            "cx.vector_index.sha256_invalid", f"{field} must be a SHA-256 value."
        )
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise VectorIndexContractError(
            "cx.vector_index.integer_invalid", f"{field} must be a positive integer."
        )
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VectorIndexContractError(
            "cx.vector_index.integer_invalid",
            f"{field} must be a non-negative integer.",
        )
    return value


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorIndexContractError(
            "cx.vector_index.timestamp_invalid", f"{field} must be a timestamp."
        )
    return value


def _storage_uri(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith(
        ("cx-private://", "cx-vector://")
    ):
        raise VectorIndexContractError(
            "cx.vector_index.storage_uri_invalid", "Vector storage URI is invalid."
        )
    return value


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in _FORBIDDEN_KEYS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
