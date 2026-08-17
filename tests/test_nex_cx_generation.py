from __future__ import annotations

from copy import deepcopy
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import nex_cx.generation as cx_generation
from nex_cx.generation import (
    GenerationExecutionStore,
    GenerationFacadeError,
    HttpMoGenerationClient,
    assert_grounded_generation_boundary_audit_redacted,
    build_generation_execution_record,
    build_generation_failure_record,
    build_grounded_generation_boundary_audit,
    build_retrieval_package_quality_guard,
    build_mo_generation_payload,
    compatibility_payload_from_generation_request,
    evaluate_grounded_generation_boundary,
    prompt_text_from_payload,
    register_generation_routes,
    retrieval_package_ref_from_payload,
    selected_evidence_ids_from_payload,
    validate_generation_request,
    validate_retrieval_package_quality,
    validate_selected_evidence_ids,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


class FakeMoClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "payload": payload,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return {
            "mo_generation_id": "mo-gen-001",
            "alias": payload["alias"],
            "model_revision": "mock-llm-v1",
            "deployment_id": "mock-generation-local",
            "provider_type": "mock-generation",
            "output": {"type": "text", "text": "Mock CX response."},
            "finish_reason": "STOP",
            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
            "runtime_metadata": {
                "request_id": request_id,
                "trace_id": trace_id,
                "queue_ms": 0,
                "provider_ms": 12,
                "total_ms": 12,
                "route_id": "route-general-llm-default",
                "admission_decision": "ACCEPTED",
                "provider_request_id": "provider-001",
                "provider_url": "http://should-not-leak.local",
            },
        }


class FailingMoClient:
    def __init__(
        self,
        *,
        error_code: str = "mo.provider_timeout",
        retryable: bool = True,
    ) -> None:
        self.error_code = error_code
        self.retryable = retryable
        self.calls: list[dict[str, Any]] = []

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "payload": payload,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        raise GenerationFacadeError(
            status_code=504,
            error_code=self.error_code,
            detail="Provider timed out.",
            retryable=self.retryable,
        )


class FakeRetrievalPackageStore:
    def __init__(self, package: dict[str, Any] | None) -> None:
        self.package = package

    def get_retrieval_package(self, retrieval_package_id: str) -> dict[str, Any] | None:
        if self.package and self.package["retrieval_package_id"] == retrieval_package_id:
            return self.package
        return None


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def build_test_client() -> tuple[TestClient, FakeMoClient, GenerationExecutionStore]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = GenerationExecutionStore()
    mo_client = FakeMoClient()
    register_generation_routes(app, store=store, mo_client=mo_client)
    return TestClient(app), mo_client, store


def grounded_package(*, status: str = "READY", package_hash: str = "d" * 64) -> dict[str, Any]:
    return {
        "retrieval_package_id": "cx-ret-001",
        "package_hash": package_hash,
        "status": status,
        "query_text": "Private retrieval query that must stay outside audit.",
        "evidence_items": [
            {
                "evidence_id": "evidence-001",
                "citation_label": "[1]",
                "text": "Private source evidence that must stay outside audit.",
                "scores": {"final_score": 0.87},
            },
            {
                "evidence_id": "evidence-002",
                "citation_label": "[2]",
                "text": "Second private source evidence that must stay outside audit.",
                "scores": {"final_score": 0.42},
            },
        ],
        "score_summary": {
            "best_score": 0.87,
            "confidence_bucket": "READY",
            "low_confidence_threshold": 0.2,
            "ranker_mix": "weighted_rrf_vector_bm25_with_rerank",
            "rerank_state": "APPLIED",
            "quality_policy_id": "retrieval_quality_v1",
        },
        "retrieval_profile": {
            "confidence_policy": {"low_confidence_threshold": 0.2},
        },
        "source_summary": {
            "source_count": 1,
            "document_count": 1,
            "chunk_count": 2,
        },
        "warnings": ["tokenizer_fallback_used:doc-secret"],
    }


def quality_package(**overrides: Any) -> dict[str, Any]:
    package = deepcopy(grounded_package())
    package.update(overrides)
    return package


def grounded_payload(
    *,
    package_hash: str = "d" * 64,
    selected_evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": "Answer using evidence."}],
        "execution_mode": "GROUNDED_ANSWER",
        "template_id": "none",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "text_answer_v1",
        "provider_capability": "generation",
        "generation_profile": "grounded-answer",
        "retrieval_package_ref": {
            "retrieval_package_id": "cx-ret-001",
            "package_hash": package_hash,
        },
    }
    if selected_evidence_ids is not None:
        payload["selected_evidence_ids"] = selected_evidence_ids
    return payload


def test_build_mo_generation_payload_hashes_prompt_metadata() -> None:
    payload = build_mo_generation_payload(
        {
            "prompt": "Summarize contract evidence.",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        },
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert payload["request_schema_version"] == "cx_mo_generation_request.v1"
    assert payload["alias"] == "general-llm-default"
    assert len(payload["provider_prompt_package_hash"]) == 64
    assert len(payload["metadata"]["generation_request_hash"]) == 64


def test_compatibility_payload_defaults_legacy_generation_to_general_answer() -> None:
    payload = compatibility_payload_from_generation_request({"prompt": "hello"})

    assert payload["execution_mode"] == "GENERAL_ANSWER"
    assert payload["generation_profile"] == "general-answer"
    assert compatibility_payload_from_generation_request(
        {"execution_mode": "GROUNDED_ANSWER"}
    ) == {"execution_mode": "GROUNDED_ANSWER"}
    assert compatibility_payload_from_generation_request(
        {"retrieval_package_ref": {"retrieval_package_id": "cx-ret-001"}}
    ) == {"retrieval_package_ref": {"retrieval_package_id": "cx-ret-001"}}


def test_prompt_text_from_payload_accepts_messages() -> None:
    assert (
        prompt_text_from_payload(
            {"messages": [{"role": "user", "content": "hello"}, {"content": "world"}]}
        )
        == "hello\nworld"
    )


def test_prompt_text_from_payload_rejects_empty_message_content() -> None:
    with pytest.raises(GenerationFacadeError) as exc:
        prompt_text_from_payload({"messages": [{"role": "user"}, {"content": ""}]})

    assert exc.value.error_code == "cx.generation_request_invalid"


def test_generation_endpoint_requires_service_claim() -> None:
    client, _, _ = build_test_client()

    response = client.post("/api/v1/generations", json={"prompt": "hello"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_generation_get_requires_service_claim() -> None:
    client, _, _ = build_test_client()

    response = client.get("/api/v1/generations/cx-gen-001")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_generation_endpoint_calls_mo_and_stores_safe_metadata() -> None:
    client, mo_client, store = build_test_client()

    response = client.post(
        "/api/v1/generations",
        json={
            "prompt": "Summarize private prompt text.",
            "alias": "general-llm-default",
            "provider_capability": "generation",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["mo_generation_id"] == "mo-gen-001"
    assert payload["mo_runtime_metadata"]["route_id"] == "route-general-llm-default"
    assert "provider_url" not in payload["mo_runtime_metadata"]
    assert "Summarize private prompt text." not in str(payload["request_metadata"])
    assert store.get(payload["cx_generation_id"]) == payload
    assert mo_client.calls[0]["payload"]["prompt"] == "Summarize private prompt text."
    assert payload["request_metadata"]["compatibility_rule_id"] == (
        "compat-general-answer-v1"
    )
    assert payload["request_metadata"]["grounding_required"] is False


def test_grounded_generation_endpoint_validates_retrieval_package_and_lineage() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = GenerationExecutionStore()
    mo_client = FakeMoClient()
    register_generation_routes(
        app,
        store=store,
        mo_client=mo_client,
        retrieval_store=FakeRetrievalPackageStore(grounded_package()),
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/generations",
        json=grounded_payload(selected_evidence_ids=["evidence-001"]),
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_metadata"]["compatibility_rule_id"] == (
        "compat-grounded-answer-v1"
    )
    assert payload["request_metadata"]["retrieval_package_id"] == "cx-ret-001"
    assert payload["request_metadata"]["selected_evidence_count"] == 1
    assert store.get(payload["cx_generation_id"]) == payload


def test_grounded_generation_boundary_audit_admits_ready_package_and_stays_raw_safe() -> None:
    payload = grounded_payload(selected_evidence_ids=["evidence-001"])
    payload["messages"] = [
        {"role": "user", "content": "Private grounded prompt must stay outside audit."}
    ]

    decision = evaluate_grounded_generation_boundary(
        payload,
        retrieval_store=FakeRetrievalPackageStore(grounded_package()),
    )

    assert decision.admitted is True
    assert decision.boundary_status == "GROUNDED_ADMITTED"
    assert decision.error is None
    assert decision.audit["audit_schema_version"] == (
        "cx_grounded_generation_boundary_audit.v1"
    )
    assert decision.audit["stage_status"] == {
        "compatibility_rule": "PASS",
        "retrieval_package_ref": "PASS",
        "retrieval_package_store": "PASS",
        "retrieval_package_lookup": "PASS",
        "package_hash": "PASS",
        "package_status": "PASS",
        "selected_evidence": "PASS",
        "retrieval_package_quality": "PASS",
    }
    assert decision.audit["compatibility_rule"] == {
        "compatibility_rule_id": "compat-grounded-answer-v1",
        "execution_mode": "GROUNDED_ANSWER",
        "generation_profile": "grounded-answer",
        "grounding_required": True,
        "citations_required": True,
        "source_trace_required": True,
    }
    assert decision.audit["retrieval_package"]["score_summary"] == {
        "best_score": 0.87,
        "confidence_bucket": "READY",
        "low_confidence_threshold": 0.2,
        "ranker_mix": "weighted_rrf_vector_bm25_with_rerank",
        "rerank_state": "APPLIED",
        "quality_policy_id": "retrieval_quality_v1",
    }
    assert decision.audit["retrieval_package"]["warning_kinds"] == [
        "tokenizer_fallback_used"
    ]
    assert decision.audit["quality_guard"] == {
        "guard_schema_version": "cx_retrieval_package_quality_guard.v1",
        "status": "PASS",
        "blocking_reason": None,
        "failed_checks": [],
        "best_score": 0.87,
        "low_confidence_threshold": 0.2,
        "low_confidence_threshold_source": "score_summary",
        "confidence_bucket": "READY",
        "evidence_item_count": 2,
        "source_summary": {
            "source_count": 1.0,
            "document_count": 1.0,
            "chunk_count": 2.0,
        },
        "no_answer_reason_present": False,
        "blocking_quality_flags": [],
        "warning_kinds": ["tokenizer_fallback_used"],
    }
    serialized = str(decision.audit)
    assert "Private grounded prompt" not in serialized
    assert "Private retrieval query" not in serialized
    assert "Private source evidence" not in serialized
    assert "doc-secret" not in serialized


def test_grounded_generation_boundary_audit_reports_general_generation_not_required() -> None:
    audit = build_grounded_generation_boundary_audit(
        {
            "prompt": "Private general prompt.",
            "execution_mode": "GENERAL_ANSWER",
            "generation_profile": "general-answer",
        },
        retrieval_store=None,
    )

    assert audit["boundary_status"] == "GROUNDING_NOT_REQUIRED"
    assert audit["admitted"] is True
    assert audit["stage_status"]["compatibility_rule"] == "PASS"
    assert audit["stage_status"]["retrieval_package_ref"] == "NOT_REQUIRED"
    assert audit["stage_status"]["retrieval_package_quality"] == "NOT_REQUIRED"
    assert audit["compatibility_rule"]["compatibility_rule_id"] == (
        "compat-general-answer-v1"
    )
    assert audit["retrieval_package"] is None
    assert audit["quality_guard"]["status"] == "NOT_APPLICABLE"
    assert "Private general prompt." not in str(audit)


def test_grounded_generation_boundary_audit_blocks_minimal_ready_package() -> None:
    minimal_package = {
        "retrieval_package_id": "cx-ret-001",
        "package_hash": "d" * 64,
        "status": "READY",
        "score_summary": "not-a-dict",
        "source_summary": "not-a-dict",
        "warnings": [None, 42],
    }

    decision = evaluate_grounded_generation_boundary(
        grounded_payload(),
        retrieval_store=FakeRetrievalPackageStore(minimal_package),
    )

    assert decision.admitted is False
    assert decision.boundary_status == "GROUNDED_BLOCKED"
    assert decision.error is not None
    assert decision.error.error_code == "cx.retrieval_package_quality_blocked"
    assert decision.audit["stage_status"]["retrieval_package_quality"] == "FAIL"
    assert decision.audit["retrieval_package"]["evidence_item_count"] == 0
    assert decision.audit["retrieval_package"]["score_summary"] == {
        "best_score": None,
        "confidence_bucket": None,
        "low_confidence_threshold": None,
        "ranker_mix": None,
        "rerank_state": None,
        "quality_policy_id": None,
    }
    assert decision.audit["retrieval_package"]["warning_count"] == 0
    assert decision.audit["quality_guard"]["status"] == "BLOCKED"
    assert decision.audit["quality_guard"]["blocking_reason"] == (
        "score_summary_missing"
    )
    assert decision.audit["quality_guard"]["failed_checks"] == [
        "score_summary_missing",
        "evidence_items_missing",
        "source_summary_missing",
    ]


def package_with_quality_flag(flag: str) -> dict[str, Any]:
    package = quality_package()
    package["evidence_items"][0]["quality_flags"] = [flag]
    return package


@pytest.mark.parametrize(
    ("package", "expected_failed_check"),
    [
        (quality_package(evidence_items=[]), "evidence_items_missing"),
        (
            quality_package(
                score_summary={
                    "best_score": "bad-score",
                    "confidence_bucket": "READY",
                    "low_confidence_threshold": 0.2,
                    "ranker_mix": "weighted_rrf_vector_bm25_with_rerank",
                    "rerank_state": "APPLIED",
                    "quality_policy_id": "retrieval_quality_v1",
                }
            ),
            "best_score_missing",
        ),
        (
            quality_package(
                score_summary={
                    "best_score": True,
                    "confidence_bucket": "READY",
                    "low_confidence_threshold": 0.2,
                    "ranker_mix": "weighted_rrf_vector_bm25_with_rerank",
                    "rerank_state": "APPLIED",
                    "quality_policy_id": "retrieval_quality_v1",
                }
            ),
            "best_score_missing",
        ),
        (
            quality_package(
                score_summary={
                    "best_score": 0.19,
                    "confidence_bucket": "READY",
                    "low_confidence_threshold": 0.2,
                    "ranker_mix": "weighted_rrf_vector_bm25_with_rerank",
                    "rerank_state": "APPLIED",
                    "quality_policy_id": "retrieval_quality_v1",
                }
            ),
            "best_score_below_threshold",
        ),
        (
            quality_package(
                score_summary={
                    "best_score": 0.87,
                    "confidence_bucket": "LOW_CONFIDENCE",
                    "low_confidence_threshold": 0.2,
                    "ranker_mix": "weighted_rrf_vector_bm25_with_rerank",
                    "rerank_state": "APPLIED",
                    "quality_policy_id": "retrieval_quality_v1",
                }
            ),
            "confidence_bucket_blocked",
        ),
        (
            quality_package(no_answer_reason="no_terms_matched"),
            "no_answer_reason_present",
        ),
        (
            package_with_quality_flag("source_unavailable:private-document-id"),
            "blocking_quality_flags_present",
        ),
        (
            quality_package(
                source_summary={
                    "source_count": 0,
                    "document_count": 1,
                    "chunk_count": 2,
                }
            ),
            "source_summary_empty",
        ),
        (
            quality_package(
                source_summary={
                    "source_count": 1,
                    "document_count": "unknown",
                    "chunk_count": 2,
                }
            ),
            "source_summary_counts_missing",
        ),
    ],
)
def test_retrieval_package_quality_guard_blocks_ready_package_inconsistencies(
    package: dict[str, Any],
    expected_failed_check: str,
) -> None:
    guard = build_retrieval_package_quality_guard(package)

    assert guard["status"] == "BLOCKED"
    assert expected_failed_check in guard["failed_checks"]
    assert "private-document-id" not in str(guard)

    with pytest.raises(GenerationFacadeError) as exc:
        validate_retrieval_package_quality(package)
    assert exc.value.error_code == "cx.retrieval_package_quality_blocked"

    decision = evaluate_grounded_generation_boundary(
        grounded_payload(),
        retrieval_store=FakeRetrievalPackageStore(package),
    )
    assert decision.admitted is False
    assert decision.audit["issues"] == [
        {
            "stage": "retrieval_package_quality",
            "error_code": "cx.retrieval_package_quality_blocked",
            "status_code": 409,
            "retryable": False,
        }
    ]
    assert expected_failed_check in decision.audit["quality_guard"]["failed_checks"]


def test_retrieval_package_quality_guard_resolves_threshold_sources() -> None:
    profile_threshold_package = quality_package()
    profile_threshold_package["score_summary"].pop("low_confidence_threshold")
    profile_threshold_package["retrieval_profile"]["confidence_policy"][
        "low_confidence_threshold"
    ] = 0.9

    profile_guard = build_retrieval_package_quality_guard(profile_threshold_package)

    assert profile_guard["status"] == "BLOCKED"
    assert profile_guard["low_confidence_threshold"] == 0.9
    assert profile_guard["low_confidence_threshold_source"] == "retrieval_profile"
    assert "best_score_below_threshold" in profile_guard["failed_checks"]

    default_threshold_package = quality_package()
    default_threshold_package["score_summary"].pop("low_confidence_threshold")
    default_threshold_package.pop("retrieval_profile")

    default_guard = build_retrieval_package_quality_guard(default_threshold_package)

    assert default_guard["status"] == "PASS"
    assert default_guard["low_confidence_threshold"] == 0.2
    assert default_guard["low_confidence_threshold_source"] == "default"
    validate_retrieval_package_quality(default_threshold_package)


def test_retrieval_package_quality_guard_ignores_nonblocking_flags_and_non_objects() -> None:
    package = quality_package()
    package["evidence_items"].append("not-an-evidence-object")
    package["evidence_items"][0]["quality_flags"] = ["debug_checked"]

    guard = build_retrieval_package_quality_guard(package)

    assert guard["status"] == "PASS"
    assert guard["blocking_quality_flags"] == []
    validate_retrieval_package_quality(package)


def test_grounded_generation_endpoint_blocks_quality_failure_before_mo_call() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = GenerationExecutionStore()
    mo_client = FakeMoClient()
    package = quality_package(evidence_items=[])
    register_generation_routes(
        app,
        store=store,
        mo_client=mo_client,
        retrieval_store=FakeRetrievalPackageStore(package),
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/generations",
        json=grounded_payload(),
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "cx.retrieval_package_quality_blocked"
    assert mo_client.calls == []


@pytest.mark.parametrize(
    ("payload", "retrieval_store", "failed_stage", "error_code"),
    [
        (
            grounded_payload(),
            None,
            "retrieval_package_store",
            "cx.retrieval_package_store_unavailable",
        ),
        (
            grounded_payload(package_hash="e" * 64),
            FakeRetrievalPackageStore(grounded_package()),
            "package_hash",
            "cx.retrieval_package_hash_mismatch",
        ),
        (
            grounded_payload(),
            FakeRetrievalPackageStore(grounded_package(status="LOW_CONFIDENCE")),
            "package_status",
            "cx.retrieval_package_not_ready",
        ),
        (
            grounded_payload(selected_evidence_ids=["missing"]),
            FakeRetrievalPackageStore(grounded_package()),
            "selected_evidence",
            "cx.selected_evidence_not_in_package",
        ),
    ],
)
def test_grounded_generation_boundary_audit_reports_blocked_stages(
    payload: dict[str, Any],
    retrieval_store: FakeRetrievalPackageStore | None,
    failed_stage: str,
    error_code: str,
) -> None:
    decision = evaluate_grounded_generation_boundary(
        payload,
        retrieval_store=retrieval_store,
    )

    assert decision.admitted is False
    assert decision.boundary_status == "GROUNDED_BLOCKED"
    assert decision.error is not None
    assert decision.audit["stage_status"][failed_stage] == "FAIL"
    assert len(decision.audit["issues"]) == 1
    assert decision.audit["issues"][0]["stage"] == failed_stage
    assert decision.audit["issues"][0]["error_code"] == error_code


def test_grounded_generation_boundary_audit_reports_ref_and_compatibility_failures() -> None:
    missing_ref = evaluate_grounded_generation_boundary(
        {
            "prompt": "private grounded prompt",
            "execution_mode": "GROUNDED_ANSWER",
            "generation_profile": "grounded-answer",
        },
        retrieval_store=FakeRetrievalPackageStore(grounded_package()),
    )
    bad_compatibility = evaluate_grounded_generation_boundary(
        {"prompt": "private prompt", "generation_profile": "missing-profile"},
        retrieval_store=None,
    )

    assert missing_ref.audit["issues"][0]["stage"] == "retrieval_package_ref"
    assert missing_ref.audit["issues"][0]["error_code"] == (
        "cx.retrieval_package_ref_required"
    )
    assert bad_compatibility.audit["issues"][0]["stage"] == "compatibility_rule"
    assert bad_compatibility.audit["issues"][0]["error_code"] == (
        "generation.compatibility_rule_not_found"
    )


def test_grounded_generation_boundary_audit_reports_invalid_ref_shape() -> None:
    decision = evaluate_grounded_generation_boundary(
        {
            "prompt": "private grounded prompt",
            "execution_mode": "GROUNDED_ANSWER",
            "generation_profile": "grounded-answer",
            "retrieval_package_ref": [],
        },
        retrieval_store=FakeRetrievalPackageStore(grounded_package()),
    )

    assert decision.admitted is False
    assert decision.audit["issues"][0]["stage"] == "retrieval_package_ref"
    assert decision.audit["issues"][0]["error_code"] == "cx.retrieval_package_ref_invalid"


def test_grounded_generation_boundary_redaction_assertion_catches_request_and_retrieval_leaks() -> None:
    with pytest.raises(ValueError, match="request payload"):
        assert_grounded_generation_boundary_audit_redacted(
            {"leak": "Private request prompt leak."},
            source_payload={"prompt": "Private request prompt leak."},
            retrieval_package=None,
        )

    with pytest.raises(ValueError, match="retrieval payload"):
        assert_grounded_generation_boundary_audit_redacted(
            {"leak": "Private retrieval evidence leak."},
            source_payload={},
            retrieval_package={
                "retrieval_package_id": "cx-ret-001",
                "text": "Private retrieval evidence leak.",
            },
        )


def test_generation_endpoint_stores_failed_record_and_lineage_for_mo_timeout() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = GenerationExecutionStore()
    mo_client = FailingMoClient()
    register_generation_routes(app, store=store, mo_client=mo_client)
    client = TestClient(app)

    response = client.post(
        "/api/v1/generations",
        json={
            "prompt": "Private timeout prompt.",
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "parent_generation_id": "cx-gen-parent-001",
            "root_generation_id": "cx-gen-root-001",
            "attempt_no": 2,
        },
        headers=auth_headers(),
    )

    assert response.status_code == 504
    assert response.json()["error_code"] == "mo.provider_timeout"
    failed_generation_id = mo_client.calls[0]["payload"]["cx_generation_id"]
    record = store.get(failed_generation_id)
    assert record is not None
    assert record["status"] == "FAILED"
    assert record["mo_generation_id"] is None
    assert record["failure"] == {
        "failure_code": "mo.provider_timeout",
        "failure_class": "provider_timeout",
        "owner_service": "nex-cx",
        "failed_stage": "GENERATING",
        "retryable": True,
        "recovery_policy_id": "recovery-mo-provider-timeout-retry-v1",
        "recovery_policy_hash": record["failure"]["recovery_policy_hash"],
        "safe_message": "Generation failed before completion.",
    }
    assert len(record["failure"]["recovery_policy_hash"]) == 64
    assert record["recovery_lineage"]["parent_generation_id"] == "cx-gen-parent-001"
    assert record["recovery_lineage"]["root_generation_id"] == "cx-gen-root-001"
    assert record["recovery_lineage"]["attempt_no"] == 2
    assert record["recovery_lineage"]["lineage_type"] == "retry"
    assert "Private timeout prompt." not in str(record)

    events = store.get_progress_events(failed_generation_id)
    assert events is not None
    assert [event["event_type"] for event in events] == [
        "generation.request.accepted",
        "generation.prompt.packaged",
        "generation.failed",
    ]
    assert events[-1]["job_status"] == "FAILED"
    assert events[-1]["retryable"] is True
    assert events[-1]["details"]["recovery_policy_id"] == (
        "recovery-mo-provider-timeout-retry-v1"
    )
    assert "Private timeout prompt." not in str(events)


def test_generation_endpoint_returns_problem_for_missing_prompt() -> None:
    client, _, _ = build_test_client()

    response = client.post(
        "/api/v1/generations",
        json={"alias": "general-llm-default"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "cx.generation_request_invalid"


def test_grounded_generation_rejects_missing_retrieval_ref() -> None:
    client, _, _ = build_test_client()

    response = client.post(
        "/api/v1/generations",
        json={
            "prompt": "hello",
            "execution_mode": "GROUNDED_ANSWER",
            "generation_profile": "grounded-answer",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "cx.retrieval_package_ref_required"


def test_validate_generation_request_rejects_missing_store_hash_and_not_ready() -> None:
    with pytest.raises(GenerationFacadeError) as missing_store:
        validate_generation_request(grounded_payload(), retrieval_store=None)
    assert missing_store.value.error_code == "cx.retrieval_package_store_unavailable"
    assert missing_store.value.retryable is True

    with pytest.raises(GenerationFacadeError) as missing_package:
        validate_generation_request(
            grounded_payload(),
            retrieval_store=FakeRetrievalPackageStore(None),
        )
    assert missing_package.value.status_code == 404

    with pytest.raises(GenerationFacadeError) as hash_mismatch:
        validate_generation_request(
            grounded_payload(package_hash="e" * 64),
            retrieval_store=FakeRetrievalPackageStore(grounded_package()),
        )
    assert hash_mismatch.value.error_code == "cx.retrieval_package_hash_mismatch"

    with pytest.raises(GenerationFacadeError) as not_ready:
        validate_generation_request(
            grounded_payload(),
            retrieval_store=FakeRetrievalPackageStore(grounded_package(status="NO_ANSWER")),
        )
    assert not_ready.value.error_code == "cx.retrieval_package_not_ready"


def test_retrieval_package_ref_and_selected_evidence_validation() -> None:
    assert retrieval_package_ref_from_payload({}) is None
    assert retrieval_package_ref_from_payload(grounded_payload()) == {
        "retrieval_package_id": "cx-ret-001",
        "package_hash": "d" * 64,
    }
    assert selected_evidence_ids_from_payload({"selected_evidence_ids": None}) == []
    assert selected_evidence_ids_from_payload(
        {"selected_evidence_ids": [" evidence-001 "]}
    ) == ["evidence-001"]
    validate_selected_evidence_ids(
        {"selected_evidence_ids": ["evidence-001"]},
        grounded_package(),
    )

    invalid_refs = [
        {"retrieval_package_ref": []},
        {"retrieval_package_ref": {"retrieval_package_id": "", "package_hash": "d" * 64}},
        {"retrieval_package_ref": {"retrieval_package_id": "x", "package_hash": "bad"}},
    ]
    for payload in invalid_refs:
        try:
            retrieval_package_ref_from_payload(payload)
        except GenerationFacadeError as exc:
            assert exc.error_code == "cx.retrieval_package_ref_invalid"
        else:
            raise AssertionError("expected GenerationFacadeError")

    with pytest.raises(GenerationFacadeError) as invalid_ids:
        selected_evidence_ids_from_payload({"selected_evidence_ids": [""]})
    assert invalid_ids.value.error_code == "cx.selected_evidence_invalid"

    with pytest.raises(GenerationFacadeError) as missing_evidence:
        validate_selected_evidence_ids(
            {"selected_evidence_ids": ["missing"]},
            grounded_package(),
        )
    assert missing_evidence.value.error_code == "cx.selected_evidence_not_in_package"


def test_generation_record_can_be_read_back() -> None:
    client, _, _ = build_test_client()
    created = client.post(
        "/api/v1/generations",
        json={"prompt": "hello"},
        headers=auth_headers(),
    ).json()

    response = client.get(
        f"/api/v1/generations/{created['cx_generation_id']}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["cx_generation_id"] == created["cx_generation_id"]


def test_generation_read_returns_problem_for_unknown_record() -> None:
    client, _, _ = build_test_client()

    response = client.get(
        "/api/v1/generations/missing",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.generation_not_found"


def test_generation_endpoint_rejects_provider_private_fields() -> None:
    client, _, _ = build_test_client()

    response = client.post(
        "/api/v1/generations",
        json={"prompt": "hello", "provider_url": "http://internal"},
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "cx.provider_field_forbidden"


def test_http_mo_generation_client_posts_with_mock_token(
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return httpx.Response(
            200,
            json={
                "mo_generation_id": "mo-gen-001",
                "alias": "general-llm-default",
            },
        )

    monkeypatch.setattr(cx_generation.httpx, "post", fake_post)

    response = HttpMoGenerationClient(base_url="http://mo.test").create_generation(
        {"prompt": "hello"},
        request_id="req-1",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert response["mo_generation_id"] == "mo-gen-001"
    assert calls[0]["args"] == ("http://mo.test/api/v1/generations",)
    assert calls[0]["kwargs"]["headers"]["X-Service-ID"] == "nex-cx"
    assert calls[0]["kwargs"]["headers"]["Authorization"].startswith("Bearer ")


def test_http_mo_generation_client_maps_problem_response(
    monkeypatch,
) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(
            422,
            json={
                "error_code": "mo.capability_not_supported",
                "detail": "Unsupported capability.",
                "retryable": False,
            },
        )

    monkeypatch.setattr(cx_generation.httpx, "post", fake_post)

    try:
        HttpMoGenerationClient(base_url="http://mo.test").create_generation(
            {"prompt": "hello"},
            request_id="req-1",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )
    except GenerationFacadeError as exc:
        assert exc.status_code == 422
        assert exc.error_code == "mo.capability_not_supported"
    else:
        raise AssertionError("expected GenerationFacadeError")


def test_http_mo_generation_client_handles_non_object_problem_response(
    monkeypatch,
) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(503, json=["not", "an", "object"])

    monkeypatch.setattr(cx_generation.httpx, "post", fake_post)

    try:
        HttpMoGenerationClient(base_url="http://mo.test").create_generation(
            {"prompt": "hello"},
            request_id="req-1",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )
    except GenerationFacadeError as exc:
        assert exc.error_code == "mo.request_failed"
    else:
        raise AssertionError("expected GenerationFacadeError")


def test_build_generation_execution_record_keeps_safe_runtime_keys_only() -> None:
    record = build_generation_execution_record(
        source_payload={"prompt": "hello"},
        mo_payload={
            "cx_generation_id": "cx-gen-001",
            "provider_capability": "generation",
            "provider_prompt_package_hash": "a" * 64,
            "metadata": {"generation_request_hash": "b" * 64},
            "response_format": {"type": "text"},
        },
        mo_response={
            "mo_generation_id": "mo-gen-001",
            "alias": "general-llm-default",
            "output": {"text": "answer"},
            "finish_reason": "STOP",
            "runtime_metadata": {
                "request_id": "req",
                "trace_id": "trace",
                "route_id": "route",
                "provider_url": "http://internal",
            },
        },
        request_id="req",
        trace_id="trace",
    )

    assert record["response_metadata"]["output_preview"] == "answer"
    assert "provider_url" not in record["mo_runtime_metadata"]


def test_build_generation_failure_record_uses_safe_policy_lineage_defaults() -> None:
    record = build_generation_failure_record(
        source_payload={"prompt": "private prompt", "attempt_no": 0},
        mo_payload={
            "cx_generation_id": "cx-gen-001",
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "provider_prompt_package_hash": "a" * 64,
            "metadata": {"generation_request_hash": "b" * 64},
            "response_format": {"type": "text"},
        },
        failure=GenerationFacadeError(
            status_code=503,
            error_code="mo.unknown_failure",
            detail="Unknown provider failure.",
            retryable=False,
        ),
        request_id="req",
        trace_id="trace",
    )

    assert record["status"] == "FAILED"
    assert record["failure"]["failure_class"] == "unclassified_failure"
    assert record["failure"]["retryable"] is False
    assert record["failure"]["recovery_policy_id"] is None
    assert record["recovery_lineage"]["lineage_type"] == "failure"
    assert record["recovery_lineage"]["default_recovery_action"] == "cancel"
    assert record["recovery_lineage"]["attempt_no"] == 1
    assert "private prompt" not in str(record)
