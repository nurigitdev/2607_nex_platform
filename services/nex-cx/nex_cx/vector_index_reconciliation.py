from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_cx.vector_index_freshness import (
    assess_vector_index_freshness,
    build_vector_index_manifest,
    transition_vector_index_state,
    validate_vector_index_manifest,
)
from nex_cx.vector_index_repository import VectorIndexRepository


def reconcile_vector_index(
    *,
    manifest: Mapping[str, Any] | None,
    source_snapshot: Mapping[str, Any],
    embedding_profile: Mapping[str, Any],
    payload_count: int,
    payload_fingerprint: str | None,
    repository: VectorIndexRepository,
    observed_at: str,
) -> dict[str, Any]:
    freshness = assess_vector_index_freshness(
        manifest,
        source_snapshot=source_snapshot,
        embedding_profile=embedding_profile,
        payload_count=payload_count,
        payload_fingerprint=payload_fingerprint,
    )
    if manifest is None:
        return _result("CREATE_INDEX", freshness, manifest=None)
    current = validate_vector_index_manifest(manifest)
    if freshness["retrieval_usable"]:
        return _result("NONE", freshness, manifest=current)
    if current["status"] == "BUILDING":
        return _result("WAIT_FOR_BUILD", freshness, manifest=current)
    if current["status"] == "REBUILD_REQUIRED":
        return _result("ADMIT_REBUILD", freshness, manifest=current)

    reason = freshness["reason"] or current["status_reason"] or "BUILD_FAILED"
    expected = current["checkpoint_version"]
    if current["status"] == "READY":
        current = transition_vector_index_state(
            current,
            target_status="STALE",
            reason=reason,
            observed_at=observed_at,
        )
        current = repository.save(current, expected_checkpoint_version=expected)
        expected = current["checkpoint_version"]
    rebuild_reason = (
        "BUILD_FAILED" if current["status"] == "FAILED" else current["status_reason"]
    )
    current = transition_vector_index_state(
        current,
        target_status="REBUILD_REQUIRED",
        reason=(rebuild_reason or reason),
        observed_at=observed_at,
    )
    current = repository.save(current, expected_checkpoint_version=expected)
    return _result("ADMIT_REBUILD", freshness, manifest=current)


def admit_vector_rebuild(
    *,
    manifest: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    embedding_profile: Mapping[str, Any],
    repository: VectorIndexRepository,
    trace_id: str,
    request_id: str,
    observed_at: str,
) -> dict[str, Any]:
    current = validate_vector_index_manifest(manifest)
    if current["status"] != "REBUILD_REQUIRED":
        raise ValueError("vector index rebuild admission requires REBUILD_REQUIRED")
    same_identity = (
        current["source_snapshot"]["source_fingerprint"]
        == source_snapshot.get("source_fingerprint")
        and current["embedding_profile"]["profile_fingerprint"]
        == embedding_profile.get("profile_fingerprint")
    )
    if same_identity:
        building = transition_vector_index_state(
            current,
            target_status="BUILDING",
            reason=None,
            observed_at=observed_at,
        )
        stored = repository.save(
            building,
            expected_checkpoint_version=current["checkpoint_version"],
        )
        return {
            "rebuild_schema_version": "cx_vector_rebuild_admission.v1",
            "action": "REBUILD_IN_PLACE",
            "supersedes_vector_index_id": None,
            "manifest": stored,
        }

    replacement = build_vector_index_manifest(
        content_object_id=current["content_object_id"],
        tenant_ref=current["tenant_ref"],
        owner_subject_ref=current["owner_subject_ref"],
        source_snapshot=source_snapshot,
        embedding_profile=embedding_profile,
        trace_id=trace_id,
        request_id=request_id,
        observed_at=observed_at,
    )
    stored = repository.create(replacement)
    return {
        "rebuild_schema_version": "cx_vector_rebuild_admission.v1",
        "action": "CREATE_REPLACEMENT",
        "supersedes_vector_index_id": current["vector_index_id"],
        "manifest": stored,
    }


def _result(
    action: str,
    freshness: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "reconciliation_schema_version": "cx_vector_index_reconciliation.v1",
        "action": action,
        "freshness": dict(freshness),
        "manifest": dict(manifest) if manifest is not None else None,
    }
