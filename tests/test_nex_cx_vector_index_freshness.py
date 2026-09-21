from __future__ import annotations

from copy import deepcopy

import pytest

from nex_cx.vector_index_freshness import (
    VECTOR_INDEX_STALE_REASONS,
    VECTOR_INDEX_STATUSES,
    VECTOR_INDEX_TRANSITIONS,
    VectorIndexContractError,
    assess_vector_index_freshness,
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    mark_vector_index_ready,
    transition_vector_index_state,
    validate_vector_index_manifest,
)


NOW = "2026-09-21T00:00:00Z"
LATER = "2026-09-21T00:01:00Z"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _profile(**overrides):
    values = {
        "provider_alias": "embedding-default",
        "model_profile_id": "qwen3_embedding_4b_bf16",
        "model_revision": "Qwen3-Embedding-4B",
        "deployment_id": "vllm-embedding-http",
        "vector_dimension": 2560,
    }
    values.update(overrides)
    return build_embedding_profile(**values)


def _source(**overrides):
    values = {
        "chunk_set_id": "chunk-set-a",
        "chunk_policy_id": "chunk_1000_100",
        "source_markdown_sha256": SHA_A,
        "chunks": [
            {"chunk_id": "chunk-a", "ordinal": 0, "text_sha256": SHA_A},
            {"chunk_id": "chunk-b", "ordinal": 1, "text_sha256": SHA_B},
        ],
    }
    values.update(overrides)
    return build_source_snapshot(**values)


def _manifest():
    return build_vector_index_manifest(
        content_object_id="document-a",
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        source_snapshot=_source(),
        embedding_profile=_profile(),
        trace_id="trace-0932",
        request_id="request-0932",
        observed_at=NOW,
    )


def _receipts():
    return [
        {
            "chunk_id": "chunk-a",
            "embedding_sha256": SHA_A,
            "vector_dimension": 2560,
            "storage_uri": "cx-vector://chunk-a",
        },
        {
            "chunk_id": "chunk-b",
            "embedding_sha256": SHA_B,
            "vector_dimension": 2560,
            "storage_uri": "cx-vector://chunk-b",
        },
    ]


def _ready():
    return mark_vector_index_ready(
        _manifest(), payload_receipts=_receipts(), observed_at=LATER
    )


def test_profile_and_source_fingerprints_are_deterministic() -> None:
    assert _profile() == _profile()
    assert _source() == _source(chunks=list(reversed(_source()["chunk_refs"])))
    assert len(_profile()["profile_fingerprint"]) == 64
    assert len(_source()["source_fingerprint"]) == 64


def test_manifest_is_metadata_only_deterministic_and_owner_scoped() -> None:
    manifest = _manifest()

    assert manifest == _manifest()
    assert manifest["status"] == "BUILDING"
    assert manifest["tenant_ref"]["id"] == "tenant-a"
    assert manifest["owner_subject_ref"]["id"] == "user-a"
    assert manifest["checkpoint_version"] == 0
    serialized = str(manifest).lower()
    assert "embedding':" not in serialized
    assert "source_text" not in serialized
    assert "prompt" not in serialized


def test_ready_transition_verifies_receipts_and_freshness() -> None:
    ready = _ready()

    assert ready["status"] == "READY"
    assert ready["payload_count"] == 2
    assert ready["checkpoint_version"] == 1
    assert ready["payload_fingerprint"] is not None
    assert assess_vector_index_freshness(
        ready,
        source_snapshot=_source(),
        embedding_profile=_profile(),
        payload_count=2,
        payload_fingerprint=ready["payload_fingerprint"],
    ) == {
        "freshness_schema_version": "cx_vector_index_freshness.v1",
        "status": "READY",
        "reason": None,
        "retrieval_usable": True,
        "rebuild_required": False,
    }


@pytest.mark.parametrize(
    ("source", "profile", "payload_count", "reason"),
    [
        (_source(chunk_set_id="chunk-set-b"), _profile(), 2, "CHUNK_SET_CHANGED"),
        (_source(chunk_policy_id="chunk_800_80"), _profile(), 2, "CHUNK_POLICY_CHANGED"),
        (_source(source_markdown_sha256=SHA_B), _profile(), 2, "SOURCE_CHANGED"),
        (
            _source(
                chunks=[
                    {"chunk_id": "chunk-a", "ordinal": 0, "text_sha256": SHA_B},
                    {"chunk_id": "chunk-b", "ordinal": 1, "text_sha256": SHA_B},
                ]
            ),
            _profile(),
            2,
            "CHUNK_CONTENT_CHANGED",
        ),
        (_source(), _profile(provider_alias="embedding-next"), 2, "PROVIDER_ALIAS_CHANGED"),
        (_source(), _profile(model_profile_id="profile-next"), 2, "MODEL_PROFILE_CHANGED"),
        (_source(), _profile(model_revision="revision-next"), 2, "MODEL_REVISION_CHANGED"),
        (_source(), _profile(deployment_id="deployment-next"), 2, "DEPLOYMENT_CHANGED"),
        (_source(), _profile(vector_dimension=1024), 2, "VECTOR_DIMENSION_CHANGED"),
        (_source(), _profile(), 1, "PAYLOAD_COUNT_MISMATCH"),
    ],
)
def test_freshness_reports_precise_mismatch_reason(
    source, profile, payload_count, reason
) -> None:
    ready = _ready()
    result = assess_vector_index_freshness(
        ready,
        source_snapshot=source,
        embedding_profile=profile,
        payload_count=payload_count,
        payload_fingerprint=ready["payload_fingerprint"],
    )

    assert result["status"] == "STALE"
    assert result["reason"] == reason
    assert result["retrieval_usable"] is False
    assert result["rebuild_required"] is True


def test_freshness_reports_payload_fingerprint_mismatch_and_missing() -> None:
    ready = _ready()
    mismatch = assess_vector_index_freshness(
        ready,
        source_snapshot=_source(),
        embedding_profile=_profile(),
        payload_count=2,
        payload_fingerprint=SHA_A,
    )
    missing = assess_vector_index_freshness(
        None,
        source_snapshot=_source(),
        embedding_profile=_profile(),
        payload_count=0,
        payload_fingerprint=None,
    )

    assert mismatch["reason"] == "PAYLOAD_FINGERPRINT_MISMATCH"
    assert missing["status"] == "MISSING"
    assert missing["reason"] == "INDEX_MISSING"


def test_non_ready_index_is_never_retrieval_usable() -> None:
    building = assess_vector_index_freshness(
        _manifest(),
        source_snapshot=_source(),
        embedding_profile=_profile(),
        payload_count=0,
        payload_fingerprint=None,
    )

    assert building["status"] == "BUILDING"
    assert building["retrieval_usable"] is False
    assert building["rebuild_required"] is False


def test_state_machine_supports_failure_stale_and_rebuild_paths() -> None:
    failed = transition_vector_index_state(
        _manifest(), target_status="FAILED", reason="BUILD_FAILED", observed_at=LATER
    )
    failed_rebuild = transition_vector_index_state(
        failed,
        target_status="REBUILD_REQUIRED",
        reason="BUILD_FAILED",
        observed_at=LATER,
    )
    restarted = transition_vector_index_state(
        failed_rebuild, target_status="BUILDING", reason=None, observed_at=LATER
    )
    stale = transition_vector_index_state(
        _ready(),
        target_status="STALE",
        reason="SOURCE_CHANGED",
        observed_at=LATER,
    )
    stale_rebuild = transition_vector_index_state(
        stale,
        target_status="REBUILD_REQUIRED",
        reason="SOURCE_CHANGED",
        observed_at=LATER,
    )

    assert failed["status"] == "FAILED"
    assert failed_rebuild["status"] == "REBUILD_REQUIRED"
    assert restarted["status"] == "BUILDING"
    assert restarted["payload_count"] == 0
    assert stale["status"] == "STALE"
    assert stale_rebuild["status"] == "REBUILD_REQUIRED"


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (lambda value: value.update(status="UNKNOWN"), "cx.vector_index.status_invalid"),
        (
            lambda value: value.update(vector_index_schema_version="v0"),
            "cx.vector_index.schema_version_invalid",
        ),
        (
            lambda value: value.update(payload={"embedding": [1.0]}),
            "cx.vector_index.private_payload_forbidden",
        ),
        (
            lambda value: value["source_snapshot"].update(source_fingerprint=SHA_B),
            "cx.vector_index.source_fingerprint_invalid",
        ),
        (
            lambda value: value["embedding_profile"].update(profile_fingerprint=SHA_B),
            "cx.vector_index.profile_fingerprint_invalid",
        ),
    ],
)
def test_manifest_validation_fails_closed(mutator, error_code: str) -> None:
    value = deepcopy(_manifest())
    mutator(value)

    with pytest.raises(VectorIndexContractError) as caught:
        validate_vector_index_manifest(value)

    assert caught.value.error_code == error_code


@pytest.mark.parametrize(
    "chunks",
    [
        "invalid",
        [{"chunk_id": "chunk-a", "ordinal": 1, "text_sha256": SHA_A}],
        [
            {"chunk_id": "chunk-a", "ordinal": 0, "text_sha256": SHA_A},
            {"chunk_id": "chunk-a", "ordinal": 1, "text_sha256": SHA_B},
        ],
    ],
)
def test_source_snapshot_rejects_invalid_chunk_metadata(chunks) -> None:
    with pytest.raises(VectorIndexContractError):
        _source(chunks=chunks)


@pytest.mark.parametrize(
    "receipts",
    [
        [],
        [
            {
                "chunk_id": "chunk-a",
                "embedding_sha256": SHA_A,
                "vector_dimension": 2560,
                "storage_uri": "cx-vector://chunk-a",
            }
        ],
        [
            {
                "chunk_id": "chunk-a",
                "embedding_sha256": SHA_A,
                "vector_dimension": 3,
                "storage_uri": "cx-vector://chunk-a",
            },
            _receipts()[1],
        ],
        [
            {
                **_receipts()[0],
                "embedding": [1.0],
            },
            _receipts()[1],
        ],
    ],
)
def test_ready_transition_rejects_incomplete_or_private_receipts(receipts) -> None:
    with pytest.raises(VectorIndexContractError):
        mark_vector_index_ready(
            _manifest(), payload_receipts=receipts, observed_at=LATER
        )


def test_invalid_transitions_and_reasons_are_rejected() -> None:
    with pytest.raises(VectorIndexContractError) as ready_error:
        transition_vector_index_state(
            _manifest(), target_status="READY", reason=None, observed_at=LATER
        )
    with pytest.raises(VectorIndexContractError) as transition_error:
        transition_vector_index_state(
            _manifest(), target_status="STALE", reason="SOURCE_CHANGED", observed_at=LATER
        )
    with pytest.raises(VectorIndexContractError) as reason_error:
        transition_vector_index_state(
            _ready(), target_status="STALE", reason="UNKNOWN", observed_at=LATER
        )

    assert ready_error.value.error_code == "cx.vector_index.ready_requires_receipts"
    assert transition_error.value.error_code == "cx.vector_index.transition_invalid"
    assert reason_error.value.error_code == "cx.vector_index.stale_reason_invalid"


def test_building_transition_rejects_reason() -> None:
    failed = transition_vector_index_state(
        _manifest(), target_status="FAILED", reason="BUILD_FAILED", observed_at=LATER
    )
    rebuild = transition_vector_index_state(
        failed,
        target_status="REBUILD_REQUIRED",
        reason="BUILD_FAILED",
        observed_at=LATER,
    )

    with pytest.raises(VectorIndexContractError) as caught:
        transition_vector_index_state(
            rebuild,
            target_status="BUILDING",
            reason="BUILD_FAILED",
            observed_at=LATER,
        )

    assert caught.value.error_code == "cx.vector_index.status_reason_invalid"


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (
            lambda value: value.update(status_reason="SOURCE_CHANGED"),
            "cx.vector_index.status_reason_invalid",
        ),
        (
            lambda value: value.update(
                status="READY",
                payload_count=0,
                payload_fingerprint=None,
                ready_at=LATER,
            ),
            "cx.vector_index.ready_payload_invalid",
        ),
        (
            lambda value: value.update(
                status="READY",
                payload_count=2,
                payload_fingerprint=SHA_A,
                ready_at=None,
            ),
            "cx.vector_index.ready_at_missing",
        ),
    ],
)
def test_manifest_status_invariants_are_enforced(mutator, error_code: str) -> None:
    value = deepcopy(_manifest())
    mutator(value)

    with pytest.raises(VectorIndexContractError) as caught:
        validate_vector_index_manifest(value)

    assert caught.value.error_code == error_code


@pytest.mark.parametrize(
    ("builder", "error_code"),
    [
        (
            lambda: validate_vector_index_manifest([]),
            "cx.vector_index.manifest_invalid",
        ),
        (
            lambda: build_vector_index_manifest(
                content_object_id="document-a",
                tenant_ref={"id": "tenant-a"},
                owner_subject_ref={"type": "oa.user", "id": "user-a"},
                source_snapshot=_source(),
                embedding_profile=_profile(),
                trace_id="trace-0932",
                request_id="request-0932",
                observed_at=NOW,
            ),
            "cx.vector_index.owner_ref_invalid",
        ),
        (
            lambda: build_vector_index_manifest(
                content_object_id="document-a",
                tenant_ref={"type": "oa.user", "id": "tenant-a"},
                owner_subject_ref={"type": "oa.user", "id": "user-a"},
                source_snapshot=_source(),
                embedding_profile=_profile(),
                trace_id="trace-0932",
                request_id="request-0932",
                observed_at=NOW,
            ),
            "cx.vector_index.owner_ref_invalid",
        ),
        (
            lambda: build_embedding_profile(
                provider_alias=" ",
                model_profile_id="profile",
                model_revision="revision",
                deployment_id="deployment",
                vector_dimension=3,
            ),
            "cx.vector_index.identifier_invalid",
        ),
        (
            lambda: build_embedding_profile(
                provider_alias="alias",
                model_profile_id="profile",
                model_revision="revision",
                deployment_id="deployment",
                vector_dimension=True,
            ),
            "cx.vector_index.integer_invalid",
        ),
        (
            lambda: build_source_snapshot(
                chunk_set_id="chunk-set",
                chunk_policy_id="policy",
                source_markdown_sha256="bad",
                chunks=[],
            ),
            "cx.vector_index.sha256_invalid",
        ),
        (
            lambda: build_source_snapshot(
                chunk_set_id="chunk-set",
                chunk_policy_id="policy",
                source_markdown_sha256=SHA_A,
                chunks=[
                    {
                        "chunk_id": "chunk-a",
                        "ordinal": -1,
                        "text_sha256": SHA_A,
                    }
                ],
            ),
            "cx.vector_index.integer_invalid",
        ),
        (
            lambda: build_vector_index_manifest(
                content_object_id="document-a",
                tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
                owner_subject_ref={"type": "oa.user", "id": "user-a"},
                source_snapshot=None,
                embedding_profile=_profile(),
                trace_id="trace-0932",
                request_id="request-0932",
                observed_at=NOW,
            ),
            "cx.vector_index.source_snapshot_invalid",
        ),
        (
            lambda: build_vector_index_manifest(
                content_object_id="document-a",
                tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
                owner_subject_ref={"type": "oa.user", "id": "user-a"},
                source_snapshot=_source(),
                embedding_profile=None,
                trace_id="trace-0932",
                request_id="request-0932",
                observed_at=NOW,
            ),
            "cx.vector_index.embedding_profile_invalid",
        ),
        (
            lambda: build_vector_index_manifest(
                content_object_id="document-a",
                tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
                owner_subject_ref={"type": "oa.user", "id": "user-a"},
                source_snapshot=_source(),
                embedding_profile=_profile(),
                trace_id="trace-0932",
                request_id="request-0932",
                observed_at=" ",
            ),
            "cx.vector_index.timestamp_invalid",
        ),
    ],
)
def test_low_level_contract_inputs_fail_closed(builder, error_code: str) -> None:
    with pytest.raises(VectorIndexContractError) as caught:
        builder()

    assert caught.value.error_code == error_code


@pytest.mark.parametrize(
    ("receipt_update", "error_code"),
    [
        ({"embedding_sha256": "bad"}, "cx.vector_index.sha256_invalid"),
        ({"vector_dimension": 0}, "cx.vector_index.integer_invalid"),
        ({"storage_uri": "file:///private"}, "cx.vector_index.storage_uri_invalid"),
        ({"chunk_id": " "}, "cx.vector_index.identifier_invalid"),
    ],
)
def test_payload_receipt_fields_fail_closed(receipt_update, error_code: str) -> None:
    receipts = _receipts()
    receipts[0] = {**receipts[0], **receipt_update}

    with pytest.raises(VectorIndexContractError) as caught:
        mark_vector_index_ready(
            _manifest(), payload_receipts=receipts, observed_at=LATER
        )

    assert caught.value.error_code == error_code


def test_chunk_reference_rejects_private_fields() -> None:
    with pytest.raises(VectorIndexContractError) as caught:
        build_source_snapshot(
            chunk_set_id="chunk-set",
            chunk_policy_id="policy",
            source_markdown_sha256=SHA_A,
            chunks=[
                {
                    "chunk_id": "chunk-a",
                    "ordinal": 0,
                    "text_sha256": SHA_A,
                    "chunk_text": "private",
                }
            ],
        )

    assert caught.value.error_code == "cx.vector_index.chunk_ref_invalid"


def test_contract_enumerations_are_frozen() -> None:
    assert VECTOR_INDEX_STATUSES == {
        "BUILDING",
        "READY",
        "STALE",
        "REBUILD_REQUIRED",
        "FAILED",
    }
    assert len(VECTOR_INDEX_STALE_REASONS) == 11
    assert len(VECTOR_INDEX_TRANSITIONS) == 6
