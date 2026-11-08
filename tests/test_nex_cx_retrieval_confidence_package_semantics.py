from __future__ import annotations

from copy import deepcopy

import pytest
from nex_cx.retrieval_confidence_package_semantics import (
    MIXED_CANDIDATE_SEMANTICS_ID,
    build_mixed_candidate_calibration_sample,
)
from nex_runtime import (
    CANDIDATE_ROLE_EXPECTED_RELEVANT,
    CANDIDATE_ROLE_IDS,
    LOW_CONFIDENCE_CANDIDATE_ROLES,
    READY_CANDIDATE_ROLES,
)


def _binding() -> dict[str, str]:
    return {
        "embedding_model_revision": "embedding-revision",
        "reranker_model_revision": "hf:" + "2" * 40,
        "ranking_policy_id": "weighted_rrf_vector_bm25_v1",
        "tokenizer_policy_id": "cx-tokenizer-profile:sha256:" + "b" * 64,
        "chunk_policy_id": "chunk_1000_100",
    }


def _case(*, ready: bool = True) -> dict[str, object]:
    label = "ready" if ready else "low-confidence"
    roles = READY_CANDIDATE_ROLES if ready else LOW_CONFIDENCE_CANDIDATE_ROLES
    return {
        "case_id": f"scenario-01-{label}",
        "scenario_id": "scenario-01",
        "expected_ready": ready,
        "query": "private query must not be projected",
        "candidates": [
            {
                "candidate_id": CANDIDATE_ROLE_IDS[role],
                "evidence_role": role,
                "expected_relevant": CANDIDATE_ROLE_EXPECTED_RELEVANT[role],
                "text": f"private {role} text",
            }
            for role in sorted(roles)
        ],
    }


def _evidence(case: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "candidate_id": candidate["candidate_id"],
            "rank": rank,
            "scores": {
                "bm25_rank": rank,
                "vector_rank": rank,
                "rrf_normalized_score": round(1.0 - (rank - 1) * 0.1, 2),
                "channel_support_score": 1.0,
                "rerank_score": round(0.9 - (rank - 1) * 0.1, 2),
            },
            "private_text": "must not be projected",
        }
        for rank, candidate in enumerate(case["candidates"], start=1)  # type: ignore[arg-type]
    ]


def test_builds_one_integrity_bound_package_from_complete_mixed_scope() -> None:
    case = _case()
    first = build_mixed_candidate_calibration_sample(
        case,
        _evidence(case),
        binding=_binding(),
    )
    replay = build_mixed_candidate_calibration_sample(
        case,
        list(reversed(_evidence(case))),
        binding=_binding(),
    )

    assert first["package_semantics_id"] == MIXED_CANDIDATE_SEMANTICS_ID
    assert first["sample_id"] == "scenario-01:positive"
    assert first["expected_ready"] is True
    assert first["retrieval_scope"]["candidate_count"] == 4
    assert first["retrieval_scope"]["single_mixed_candidate_retrieval"] is True
    assert first["retrieval_scope"]["label_filtered_retrieval"] is False
    assert first["feature_package"]["features"]["candidate_count"] == 4
    assert first["sample_hash"] == replay["sample_hash"]
    serialized = str(first)
    assert "private query" not in serialized
    assert "private_text" not in serialized

    low_case = _case(ready=False)
    low = build_mixed_candidate_calibration_sample(
        low_case,
        _evidence(low_case),
        binding=_binding(),
    )
    assert low["sample_id"] == "scenario-01:negative"
    assert low["expected_ready"] is False


@pytest.mark.parametrize(
    "mutation, error",
    [
        (lambda case: case.update(expected_ready="yes"), TypeError),
        (lambda case: case.update(candidates="bad"), TypeError),
        (lambda case: case["candidates"].pop(), ValueError),
        (lambda case: case["candidates"].__setitem__(0, "bad"), TypeError),
        (
            lambda case: case["candidates"][0].update(evidence_role="UNKNOWN"),
            ValueError,
        ),
        (
            lambda case: case["candidates"][0].update(expected_relevant="yes"),
            ValueError,
        ),
        (
            lambda case: case["candidates"].__setitem__(
                0, deepcopy(case["candidates"][1])
            ),
            ValueError,
        ),
        (
            lambda case: case["candidates"][0].update(
                candidate_id="related-non-answer",
                evidence_role="RELATED_NON_ANSWER",
                expected_relevant=False,
            ),
            ValueError,
        ),
        (lambda case: case.update(case_id="wrong-ready"), ValueError),
    ],
)
def test_rejects_invalid_case_semantics(mutation, error: type[Exception]) -> None:
    case = _case()
    mutation(case)
    with pytest.raises(error):
        build_mixed_candidate_calibration_sample(
            case,
            _evidence(_case()),
            binding=_binding(),
        )


def test_rejects_non_mapping_case_and_empty_identity() -> None:
    with pytest.raises(TypeError, match="case is invalid"):
        build_mixed_candidate_calibration_sample(  # type: ignore[arg-type]
            [], [], binding=_binding()
        )
    case = _case()
    case["scenario_id"] = ""
    with pytest.raises(ValueError, match="scenario_id"):
        build_mixed_candidate_calibration_sample(
            case,
            _evidence(_case()),
            binding=_binding(),
        )


@pytest.mark.parametrize(
    "mutation, error, detail",
    [
        (lambda evidence: evidence.pop(), ValueError, "four items"),
        (lambda evidence: evidence.__setitem__(0, "bad"), TypeError, "item"),
        (
            lambda evidence: evidence[0].update(rank=True),
            TypeError,
            "item",
        ),
        (
            lambda evidence: evidence[0].update(scores=[]),
            TypeError,
            "item",
        ),
        (
            lambda evidence: evidence[0].update(
                candidate_id=evidence[1]["candidate_id"]
            ),
            ValueError,
            "scope",
        ),
        (
            lambda evidence: evidence[0].update(rank=2),
            ValueError,
            "ranks",
        ),
    ],
)
def test_rejects_incomplete_or_malformed_retrieval_scope(
    mutation,
    error: type[Exception],
    detail: str,
) -> None:
    case = _case()
    evidence = _evidence(case)
    mutation(evidence)
    with pytest.raises(error, match=detail):
        build_mixed_candidate_calibration_sample(
            case,
            evidence,
            binding=_binding(),
        )
