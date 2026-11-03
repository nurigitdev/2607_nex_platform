from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

VECTOR_NEAR_TIE_ORDERING_POLICY_ID = "cx_vector_near_tie_stable_identity_v1"
VECTOR_NEAR_TIE_MAX_SCORE_DELTA = 0.001


def order_vector_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    score_field: str,
) -> list[Mapping[str, Any]]:
    """Order meaningful score gaps first and stabilize bounded near ties."""
    score_ordered = sorted(
        candidates,
        key=lambda item: (-float(item[score_field]), *_stable_identity(item)),
    )
    ordered: list[Mapping[str, Any]] = []
    offset = 0
    while offset < len(score_ordered):
        anchor_score = float(score_ordered[offset][score_field])
        boundary = offset + 1
        while boundary < len(score_ordered):
            score_delta = round(
                anchor_score - float(score_ordered[boundary][score_field]),
                8,
            )
            if score_delta > VECTOR_NEAR_TIE_MAX_SCORE_DELTA:
                break
            boundary += 1
        ordered.extend(
            sorted(score_ordered[offset:boundary], key=_stable_identity)
        )
        offset = boundary
    return ordered


def _stable_identity(candidate: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(candidate["content_object_id"]),
        str(candidate["chunk_id"]),
        str(candidate.get("vector_index_id", "")),
    )
