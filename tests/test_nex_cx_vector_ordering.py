from __future__ import annotations

from nex_cx.vector_ordering import (
    VECTOR_NEAR_TIE_MAX_SCORE_DELTA,
    VECTOR_NEAR_TIE_ORDERING_POLICY_ID,
    order_vector_candidates,
)


def _candidate(content: str, chunk: str, score: float) -> dict[str, object]:
    return {
        "content_object_id": content,
        "chunk_id": chunk,
        "vector_index_id": f"index-{content}",
        "vector_score": score,
    }


def test_near_tie_score_inversion_keeps_stable_identity_order() -> None:
    first = [
        _candidate("content-b", "chunk-b", 0.76449615),
        _candidate("content-a", "chunk-a", 0.76370518),
    ]
    repeated = [
        _candidate("content-b", "chunk-b", 0.76357507),
        _candidate("content-a", "chunk-a", 0.76380866),
    ]

    assert [row["content_object_id"] for row in order_vector_candidates(
        first, score_field="vector_score"
    )] == ["content-a", "content-b"]
    assert [row["content_object_id"] for row in order_vector_candidates(
        repeated, score_field="vector_score"
    )] == ["content-a", "content-b"]


def test_meaningful_score_gap_remains_score_ordered() -> None:
    candidates = [
        _candidate("content-a", "chunk-a", 0.8),
        _candidate(
            "content-z",
            "chunk-z",
            0.8 + VECTOR_NEAR_TIE_MAX_SCORE_DELTA + 0.00000001,
        ),
    ]

    ordered = order_vector_candidates(candidates, score_field="vector_score")

    assert [row["content_object_id"] for row in ordered] == [
        "content-z",
        "content-a",
    ]
    assert ordered[0]["vector_score"] == candidates[1]["vector_score"]


def test_near_tie_groups_are_anchored_and_do_not_chain() -> None:
    candidates = [
        _candidate("content-c", "chunk-c", 0.9000),
        _candidate("content-a", "chunk-a", 0.8994),
        _candidate("content-b", "chunk-b", 0.8988),
    ]

    ordered = order_vector_candidates(candidates, score_field="vector_score")

    assert [row["content_object_id"] for row in ordered] == [
        "content-a",
        "content-c",
        "content-b",
    ]
    assert VECTOR_NEAR_TIE_ORDERING_POLICY_ID.endswith("_v1")
