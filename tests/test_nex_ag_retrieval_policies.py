from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from nex_ag.retrieval_policies import (
    register_retrieval_policy_routes,
    summarize_retrieval_policies,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_runtime.retrieval_policies import (
    CURRENT_POLICY_ID,
    DEFAULT_RETRIEVAL_POLICIES,
    RetrievalPolicyError,
    THRESHOLD_DECISION_SCHEMA_VERSION,
    WEIGHTED_RRF_POLICY_ID,
    active_retrieval_policy_record,
    finalize_retrieval_policy,
    list_retrieval_policy_records,
    retrieval_policy_by_id,
    retrieval_policy_hash,
    threshold_decision_checkpoint,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_test_client(
    policies: tuple[dict[str, object], ...] | None = None,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_retrieval_policy_routes(app, policies=policies)
    return TestClient(app)


def copied_default_policy() -> dict[str, object]:
    return deepcopy(DEFAULT_RETRIEVAL_POLICIES[0])


def test_list_retrieval_policy_records_exposes_current_and_candidate() -> None:
    records = list_retrieval_policy_records()

    assert [record["policy_id"] for record in records] == [
        CURRENT_POLICY_ID,
        WEIGHTED_RRF_POLICY_ID,
    ]
    assert records[0]["status"] == "ACTIVE"
    assert records[0]["ranker"]["method"] == "bm25_with_embedding_presence"
    assert records[1]["status"] == "CANDIDATE"
    assert records[1]["ranker"]["method"] == "weighted_rrf"
    assert records[1]["ranker"]["vector_weight"] == 0.7
    assert records[1]["ranker"]["bm25_weight"] == 0.3
    assert all(len(record["policy_hash"]) == 64 for record in records)


def test_active_retrieval_policy_record_returns_current_runtime_policy() -> None:
    policy = active_retrieval_policy_record()

    assert policy["policy_id"] == CURRENT_POLICY_ID
    assert policy["candidate_limits"]["rerank_candidate_limit"] == 50
    assert policy["request_override_policy"]["allowed"] is True
    assert policy["threshold_decision"]["decision_status"] == "OBSERVE"
    assert policy["threshold_decision"]["canonical_low_confidence_threshold"] == (
        policy["confidence"]["low_confidence_threshold"]
    )


def test_retrieval_policy_threshold_decision_checkpoint_is_visible() -> None:
    records = list_retrieval_policy_records()
    decisions = {
        record["policy_id"]: record["threshold_decision"]
        for record in records
    }

    assert decisions[CURRENT_POLICY_ID]["decision_schema_version"] == (
        THRESHOLD_DECISION_SCHEMA_VERSION
    )
    assert decisions[CURRENT_POLICY_ID]["candidate_low_confidence_threshold"] is None
    assert decisions[CURRENT_POLICY_ID]["live_smoke_override_threshold"] == 0.0
    assert decisions[CURRENT_POLICY_ID]["operator_action"] == (
        "collect_live_score_samples"
    )
    assert "Slice 0297 protected_live_rag_score_calibration.v1" in (
        decisions[WEIGHTED_RRF_POLICY_ID]["evidence_sources"]
    )


def test_threshold_decision_checkpoint_helper_builds_review_gate() -> None:
    checkpoint = threshold_decision_checkpoint(
        decision_id="custom_threshold_0001",
        canonical_low_confidence_threshold=0.35,
    )

    assert checkpoint["decision_schema_version"] == THRESHOLD_DECISION_SCHEMA_VERSION
    assert checkpoint["decision_status"] == "OBSERVE"
    assert checkpoint["canonical_low_confidence_threshold"] == 0.35
    assert checkpoint["minimum_live_samples_before_change"] == 20


def test_retrieval_policy_hash_ignores_hash_and_updated_at() -> None:
    policy = finalize_retrieval_policy(DEFAULT_RETRIEVAL_POLICIES[0])
    mutated = {
        **policy,
        "policy_hash": "x" * 64,
        "updated_at": "2099-01-01T00:00:00Z",
    }

    assert retrieval_policy_hash(policy) == retrieval_policy_hash(mutated)


def test_retrieval_policy_by_id_reports_missing_policy() -> None:
    with pytest.raises(RetrievalPolicyError) as exc_info:
        retrieval_policy_by_id("missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "retrieval_policy.not_found"


def test_validate_retrieval_policy_rejects_bad_edges() -> None:
    bad_status = {**DEFAULT_RETRIEVAL_POLICIES[0], "status": "BROKEN"}
    bad_ranker = {
        **DEFAULT_RETRIEVAL_POLICIES[0],
        "ranker": {**DEFAULT_RETRIEVAL_POLICIES[0]["ranker"], "method": "unknown"},
    }
    bad_limits = {
        **DEFAULT_RETRIEVAL_POLICIES[0],
        "candidate_limits": {
            **DEFAULT_RETRIEVAL_POLICIES[0]["candidate_limits"],
            "default_top_k": 99,
            "max_top_k": 10,
        },
    }

    for policy in (bad_status, bad_ranker, bad_limits):
        with pytest.raises(RetrievalPolicyError):
            finalize_retrieval_policy(policy)


def test_validate_retrieval_policy_accepts_legacy_record_without_threshold_decision() -> None:
    policy = copied_default_policy()
    policy.pop("threshold_decision")

    finalized = finalize_retrieval_policy(policy)

    assert "threshold_decision" not in finalized


@pytest.mark.parametrize(
    ("mutator", "expected_detail"),
    [
        (
            lambda policy: policy.update({"policy_schema_version": "retrieval_policy.v2"}),
            "policy_schema_version must be retrieval_policy.v1.",
        ),
        (
            lambda policy: policy.update({"policy_id": "  "}),
            "policy_id must be a non-empty string.",
        ),
        (
            lambda policy: policy.update({"ranker": []}),
            "ranker must be an object.",
        ),
        (
            lambda policy: policy["ranker"].update({"bm25_weight": True}),
            "bm25_weight must be numeric.",
        ),
        (
            lambda policy: policy["ranker"].update({"embedding_presence_weight": 1.5}),
            "embedding_presence_weight must be between 0.0 and 1.0.",
        ),
        (
            lambda policy: policy["candidate_limits"].update({"default_top_k": False}),
            "default_top_k must be a positive integer.",
        ),
        (
            lambda policy: policy["candidate_limits"].update(
                {"vector_candidate_limit": -1}
            ),
            "vector_candidate_limit must be a non-negative integer.",
        ),
        (
            lambda policy: policy["tokenizer_profile"].update({"bm25_tokenizer": ""}),
            "bm25_tokenizer must be a non-empty string.",
        ),
        (
            lambda policy: policy["provider_aliases"].update({"embedding_alias": ""}),
            "embedding_alias must be a non-empty string.",
        ),
        (
            lambda policy: policy.update({"threshold_decision": []}),
            "threshold_decision must be an object.",
        ),
        (
            lambda policy: policy["threshold_decision"].update(
                {"decision_schema_version": "retrieval_threshold_decision.v2"}
            ),
            "decision_schema_version must be retrieval_threshold_decision.v1.",
        ),
        (
            lambda policy: policy["threshold_decision"].update(
                {"decision_status": "BROKEN"}
            ),
            "decision_status must be OBSERVE, ADOPT, or REJECT.",
        ),
        (
            lambda policy: policy["threshold_decision"].update(
                {"candidate_low_confidence_threshold": True}
            ),
            "candidate_low_confidence_threshold must be numeric.",
        ),
        (
            lambda policy: policy["threshold_decision"].update(
                {"minimum_live_samples_before_change": 0}
            ),
            "minimum_live_samples_before_change must be a positive integer.",
        ),
        (
            lambda policy: policy["threshold_decision"].update(
                {"evidence_sources": ["Slice 0297", " "]}
            ),
            "evidence_sources must be a list of non-empty strings.",
        ),
    ],
)
def test_validate_retrieval_policy_reports_specific_field_errors(
    mutator: Callable[[dict[str, object]], None],
    expected_detail: str,
) -> None:
    policy = copied_default_policy()
    mutator(policy)

    with pytest.raises(RetrievalPolicyError) as exc_info:
        finalize_retrieval_policy(policy)

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "retrieval_policy.field_invalid"
    assert exc_info.value.detail == expected_detail


def test_active_retrieval_policy_record_requires_exactly_one_active() -> None:
    no_active = tuple(
        {**policy, "status": "CANDIDATE"} for policy in DEFAULT_RETRIEVAL_POLICIES
    )

    with pytest.raises(RetrievalPolicyError) as exc_info:
        active_retrieval_policy_record(no_active)

    assert exc_info.value.error_code == "retrieval_policy.active_policy_invalid"


def test_summarize_retrieval_policies_counts_statuses() -> None:
    assert summarize_retrieval_policies(
        [
            {"status": "ACTIVE", "threshold_decision": {"decision_status": None}},
            {"status": "CANDIDATE"},
            {"status": "RETIRED"},
        ]
    ) == {
        "total": 3,
        "active": 1,
        "candidate": 1,
        "retired": 1,
        "threshold_decision_observe": 0,
    }


def test_retrieval_policy_list_endpoint_requires_service_claim() -> None:
    response = build_test_client().get("/admin/v1/policies/retrieval")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_retrieval_policy_list_endpoint_returns_registry_projection() -> None:
    response = build_test_client().get(
        "/admin/v1/policies/retrieval",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == "ag_retrieval_policy_registry.v1"
    assert payload["trace_id"] == TRACE_ID
    assert payload["active_policy_id"] == CURRENT_POLICY_ID
    assert payload["summary"] == {
        "total": 2,
        "active": 1,
        "candidate": 1,
        "retired": 0,
        "threshold_decision_observe": 2,
    }
    assert payload["policies"][0]["threshold_decision"]["decision_status"] == "OBSERVE"
    assert "api_key" not in str(payload).lower()


def test_retrieval_policy_list_endpoint_reports_bad_registry() -> None:
    response = build_test_client(policies=()).get(
        "/admin/v1/policies/retrieval",
        headers=auth_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error_code"] == "retrieval_policy.active_policy_invalid"


def test_retrieval_policy_active_endpoint_returns_active_policy() -> None:
    response = build_test_client().get(
        "/admin/v1/policies/retrieval/active",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == "ag_retrieval_policy_detail.v1"
    assert payload["policy"]["policy_id"] == CURRENT_POLICY_ID


def test_retrieval_policy_active_endpoint_requires_service_claim() -> None:
    response = build_test_client().get("/admin/v1/policies/retrieval/active")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_retrieval_policy_detail_endpoint_returns_candidate_policy() -> None:
    response = build_test_client().get(
        f"/admin/v1/policies/retrieval/{WEIGHTED_RRF_POLICY_ID}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["policy"]["ranker"]["vector_weight"] == 0.7
    assert payload["policy"]["tokenizer_profile"]["dictionary_profile"] == "mecab-ko-dic"


def test_retrieval_policy_detail_endpoint_supports_injected_registry() -> None:
    response = build_test_client(policies=DEFAULT_RETRIEVAL_POLICIES).get(
        f"/admin/v1/policies/retrieval/{WEIGHTED_RRF_POLICY_ID}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["policy"]["policy_id"] == WEIGHTED_RRF_POLICY_ID


def test_retrieval_policy_detail_endpoint_requires_service_claim() -> None:
    response = build_test_client().get(
        f"/admin/v1/policies/retrieval/{WEIGHTED_RRF_POLICY_ID}",
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_retrieval_policy_endpoint_reports_not_found_and_bad_registry() -> None:
    missing = build_test_client().get(
        "/admin/v1/policies/retrieval/missing",
        headers=auth_headers(),
    )
    bad_registry = build_test_client(policies=()).get(
        "/admin/v1/policies/retrieval/active",
        headers=auth_headers(),
    )

    assert missing.status_code == 404
    assert missing.json()["error_code"] == "retrieval_policy.not_found"
    assert bad_registry.status_code == 500
    assert bad_registry.json()["error_code"] == "retrieval_policy.active_policy_invalid"
