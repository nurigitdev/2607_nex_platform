from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from nex_cx.vector_index_freshness import (
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    mark_vector_index_ready,
    transition_vector_index_state,
)
from nex_cx.vector_index_reconciliation import (
    admit_vector_rebuild,
    reconcile_vector_index,
)
from nex_cx.vector_index_repository import InMemoryVectorIndexRepository


def _parts():
    source = build_source_snapshot(
        chunk_set_id=str(uuid4()),
        chunk_policy_id="1000_100",
        source_markdown_sha256="1" * 64,
        chunks=[{"chunk_id": str(uuid4()), "ordinal": 0, "text_sha256": "2" * 64}],
    )
    profile = build_embedding_profile(
        provider_alias="mock",
        model_profile_id="qwen-test",
        model_revision="test",
        deployment_id="local",
        vector_dimension=2,
    )
    manifest = build_vector_index_manifest(
        content_object_id=str(uuid4()),
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "owner-a"},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="trace-0936",
        request_id="request-0936",
        observed_at="2026-09-21T14:00:00Z",
    )
    ready = mark_vector_index_ready(
        manifest,
        payload_receipts=[{
            "chunk_id": source["chunk_refs"][0]["chunk_id"],
            "embedding_sha256": "3" * 64,
            "vector_dimension": 2,
            "storage_uri": f"cx-private://pgvector/{uuid4()}",
        }],
        observed_at="2026-09-21T14:01:00Z",
    )
    return source, profile, manifest, ready


def test_reconcile_missing_ready_and_building_actions():
    source, profile, building, ready = _parts()
    repository = InMemoryVectorIndexRepository()
    missing = reconcile_vector_index(
        manifest=None,
        source_snapshot=source,
        embedding_profile=profile,
        payload_count=0,
        payload_fingerprint=None,
        repository=repository,
        observed_at="2026-09-21T14:02:00Z",
    )
    repository.create(building)
    waiting = reconcile_vector_index(
        manifest=building,
        source_snapshot=source,
        embedding_profile=profile,
        payload_count=0,
        payload_fingerprint=None,
        repository=repository,
        observed_at="2026-09-21T14:02:00Z",
    )
    repository = InMemoryVectorIndexRepository()
    repository.create(ready)
    current = reconcile_vector_index(
        manifest=ready,
        source_snapshot=source,
        embedding_profile=profile,
        payload_count=1,
        payload_fingerprint=ready["payload_fingerprint"],
        repository=repository,
        observed_at="2026-09-21T14:02:00Z",
    )

    assert missing["action"] == "CREATE_INDEX"
    assert missing["manifest"] is None
    assert waiting["action"] == "WAIT_FOR_BUILD"
    assert current["action"] == "NONE"
    assert current["freshness"]["retrieval_usable"] is True


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("source", "SOURCE_CHANGED"),
        ("profile", "MODEL_REVISION_CHANGED"),
        ("count", "PAYLOAD_COUNT_MISMATCH"),
        ("fingerprint", "PAYLOAD_FINGERPRINT_MISMATCH"),
    ],
)
def test_reconcile_ready_drift_persists_rebuild_required(mutation, reason):
    source, profile, _building, ready = _parts()
    current_source = deepcopy(source)
    current_profile = deepcopy(profile)
    count = 1
    fingerprint = ready["payload_fingerprint"]
    if mutation == "source":
        current_source["source_markdown_sha256"] = "4" * 64
        current_source = build_source_snapshot(
            chunk_set_id=current_source["chunk_set_id"],
            chunk_policy_id=current_source["chunk_policy_id"],
            source_markdown_sha256=current_source["source_markdown_sha256"],
            chunks=current_source["chunk_refs"],
        )
    elif mutation == "profile":
        current_profile = build_embedding_profile(
            provider_alias=profile["provider_alias"],
            model_profile_id=profile["model_profile_id"],
            model_revision="changed",
            deployment_id=profile["deployment_id"],
            vector_dimension=2,
        )
    elif mutation == "count":
        count = 0
    else:
        fingerprint = "5" * 64
    repository = InMemoryVectorIndexRepository()
    repository.create(ready)

    result = reconcile_vector_index(
        manifest=ready,
        source_snapshot=current_source,
        embedding_profile=current_profile,
        payload_count=count,
        payload_fingerprint=fingerprint,
        repository=repository,
        observed_at="2026-09-21T14:02:00Z",
    )

    assert result["action"] == "ADMIT_REBUILD"
    assert result["freshness"]["reason"] == reason
    assert result["manifest"]["status"] == "REBUILD_REQUIRED"
    assert result["manifest"]["status_reason"] == reason
    assert result["manifest"]["checkpoint_version"] == 3


def test_reconcile_failed_stale_and_already_required_states():
    source, profile, building, ready = _parts()
    repository = InMemoryVectorIndexRepository()
    failed = transition_vector_index_state(
        building,
        target_status="FAILED",
        reason="PROVIDER_FAILED",
        observed_at="2026-09-21T14:01:00Z",
    )
    repository.create(failed)
    failed_result = reconcile_vector_index(
        manifest=failed,
        source_snapshot=source,
        embedding_profile=profile,
        payload_count=0,
        payload_fingerprint=None,
        repository=repository,
        observed_at="2026-09-21T14:02:00Z",
    )
    required = failed_result["manifest"]
    assert required["status"] == "REBUILD_REQUIRED"
    assert required["status_reason"] == "BUILD_FAILED"
    again = reconcile_vector_index(
        manifest=required,
        source_snapshot=source,
        embedding_profile=profile,
        payload_count=0,
        payload_fingerprint=None,
        repository=repository,
        observed_at="2026-09-21T14:03:00Z",
    )
    assert again["action"] == "ADMIT_REBUILD"

    stale = transition_vector_index_state(
        ready,
        target_status="STALE",
        reason="PAYLOAD_COUNT_MISMATCH",
        observed_at="2026-09-21T14:01:00Z",
    )
    repository = InMemoryVectorIndexRepository()
    repository.create(stale)
    stale_result = reconcile_vector_index(
        manifest=stale,
        source_snapshot=source,
        embedding_profile=profile,
        payload_count=0,
        payload_fingerprint=ready["payload_fingerprint"],
        repository=repository,
        observed_at="2026-09-21T14:02:00Z",
    )
    assert stale_result["manifest"]["status"] == "REBUILD_REQUIRED"


def test_admit_rebuild_in_place_and_replacement_paths():
    source, profile, _building, ready = _parts()
    repository = InMemoryVectorIndexRepository()
    repository.create(ready)
    required = reconcile_vector_index(
        manifest=ready,
        source_snapshot=source,
        embedding_profile=profile,
        payload_count=0,
        payload_fingerprint=ready["payload_fingerprint"],
        repository=repository,
        observed_at="2026-09-21T14:02:00Z",
    )["manifest"]
    in_place = admit_vector_rebuild(
        manifest=required,
        source_snapshot=source,
        embedding_profile=profile,
        repository=repository,
        trace_id="trace-rebuild",
        request_id="request-rebuild",
        observed_at="2026-09-21T14:03:00Z",
    )
    assert in_place["action"] == "REBUILD_IN_PLACE"
    assert in_place["manifest"]["status"] == "BUILDING"
    assert in_place["manifest"]["payload_count"] == 0

    repository = InMemoryVectorIndexRepository()
    repository.create(required)
    changed = build_embedding_profile(
        provider_alias="mock",
        model_profile_id="qwen-test",
        model_revision="v2",
        deployment_id="local",
        vector_dimension=2,
    )
    replacement = admit_vector_rebuild(
        manifest=required,
        source_snapshot=source,
        embedding_profile=changed,
        repository=repository,
        trace_id="trace-replacement",
        request_id="request-replacement",
        observed_at="2026-09-21T14:03:00Z",
    )
    assert replacement["action"] == "CREATE_REPLACEMENT"
    assert replacement["supersedes_vector_index_id"] == required["vector_index_id"]
    assert replacement["manifest"]["vector_index_id"] != required["vector_index_id"]
    assert replacement["manifest"]["status"] == "BUILDING"


def test_admit_rebuild_rejects_wrong_status():
    source, profile, building, _ready = _parts()
    with pytest.raises(ValueError, match="REBUILD_REQUIRED"):
        admit_vector_rebuild(
            manifest=building,
            source_snapshot=source,
            embedding_profile=profile,
            repository=InMemoryVectorIndexRepository(),
            trace_id="trace",
            request_id="request",
            observed_at="2026-09-21T14:03:00Z",
        )
