from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from nex_cx.drafts import (
    build_citation_claims,
    build_structured_draft,
    citation_labels,
    evidence_index_by_label,
    validate_citation_claims,
)
from nex_cx.generation import (
    GenerationExecutionStore,
    output_text_from_mo_response,
    register_generation_routes,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_runtime.compatibility import DEFAULT_GENERATION_COMPATIBILITY_RULES


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class CitationMoClient:
    def __init__(self, output_text: str = "Grounded answer [1]") -> None:
        self.output_text = output_text

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {
            "mo_generation_id": "mo-gen-001",
            "alias": payload["alias"],
            "output": {"type": "text", "text": self.output_text},
            "finish_reason": "STOP",
            "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
            "runtime_metadata": {
                "request_id": request_id,
                "trace_id": trace_id,
            },
        }


class RetrievalStore:
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
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def retrieval_package() -> dict[str, Any]:
    return {
        "retrieval_package_id": "cx-ret-001",
        "package_hash": "d" * 64,
        "status": "READY",
        "evidence_items": [
            {
                "evidence_id": "evidence-001",
                "citation_label": "[1]",
            },
            {
                "evidence_id": "evidence-002",
                "citation_label": "[2]",
            },
        ],
    }


def grounded_payload() -> dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": "Answer with citation."}],
        "execution_mode": "GROUNDED_ANSWER",
        "template_id": "none",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "text_answer_v1",
        "provider_capability": "generation",
        "generation_profile": "grounded-answer",
        "retrieval_package_ref": {
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "d" * 64,
        },
        "selected_evidence_ids": ["evidence-001"],
    }


def test_citation_labels_are_deduplicated_in_order() -> None:
    assert citation_labels("See [2], [1], [2], and [10].") == ["[2]", "[1]", "[10]"]
    assert citation_labels("No citation") == []


def test_citation_claims_map_to_retrieval_evidence() -> None:
    citations = build_citation_claims(
        output_text="Grounded answer [1] and unknown [3].",
        retrieval_package=retrieval_package(),
    )

    assert citations[0]["evidence_id"] == "evidence-001"
    assert citations[0]["valid"] is True
    assert citations[1]["evidence_id"] is None
    assert citations[1]["validation_error"] == "citation_evidence_not_found"
    assert evidence_index_by_label(None) == {}


def test_structured_draft_validates_citations_and_redacts_full_output() -> None:
    draft = build_structured_draft(
        cx_generation_id="cx-gen-001",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        output_text="Grounded answer [1]",
        compatibility_rule=DEFAULT_GENERATION_COMPATIBILITY_RULES[0],
        retrieval_package=retrieval_package(),
    )

    assert draft["status"] == "VALIDATED"
    assert draft["citations"][0]["evidence_id"] == "evidence-001"
    assert draft["validation"]["errors"] == []
    assert draft["metadata"]["raw_output_stored_in_public_record"] is False
    assert "Grounded answer [1]" not in draft["content_hash"]


def test_structured_draft_records_missing_required_and_mismatch_errors() -> None:
    missing_required = build_structured_draft(
        cx_generation_id="cx-gen-001",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        output_text="Grounded answer without citation.",
        compatibility_rule=DEFAULT_GENERATION_COMPATIBILITY_RULES[0],
        retrieval_package=retrieval_package(),
    )
    mismatch = build_structured_draft(
        cx_generation_id="cx-gen-002",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        output_text="Grounded answer [9]",
        compatibility_rule=DEFAULT_GENERATION_COMPATIBILITY_RULES[0],
        retrieval_package=retrieval_package(),
    )
    no_package_errors = validate_citation_claims(
        citations=[
            {
                "citation_label": "[1]",
                "evidence_id": None,
                "retrieval_package_id": None,
                "valid": False,
                "validation_error": "citation_evidence_not_found",
            }
        ],
        compatibility_rule=DEFAULT_GENERATION_COMPATIBILITY_RULES[0],
        retrieval_package=None,
    )

    assert missing_required["status"] == "VALIDATION_FAILED"
    assert missing_required["validation"]["errors"][0]["code"] == (
        "cx.citation_required_missing"
    )
    assert mismatch["validation"]["errors"][0]["code"] == "cx.citation_evidence_mismatch"
    assert [error["code"] for error in no_package_errors] == [
        "cx.citation_retrieval_package_missing",
        "cx.citation_evidence_mismatch",
    ]


def test_generation_route_saves_structured_draft_and_allows_readback() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = GenerationExecutionStore()
    register_generation_routes(
        app,
        store=store,
        mo_client=CitationMoClient(),
        retrieval_store=RetrievalStore(retrieval_package()),
    )
    client = TestClient(app)

    created = client.post(
        "/api/v1/generations",
        json=grounded_payload(),
        headers=auth_headers(),
    )
    payload = created.json()
    draft = client.get(
        f"/api/v1/generations/{payload['cx_generation_id']}/structured-draft",
        headers=auth_headers(),
    )

    assert created.status_code == 200
    assert payload["request_metadata"]["draft_validation_status"] == "VALIDATED"
    assert draft.status_code == 200
    assert draft.json()["structured_draft_id"] == payload["request_metadata"][
        "structured_draft_id"
    ]
    assert store.get_structured_draft(payload["cx_generation_id"]) == draft.json()


def test_structured_draft_read_requires_auth_and_reports_missing() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_routes(app, store=GenerationExecutionStore(), mo_client=CitationMoClient())
    client = TestClient(app)

    unauthorized = client.get("/api/v1/generations/cx-gen-001/structured-draft")
    missing = client.get(
        "/api/v1/generations/cx-gen-001/structured-draft",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "cx.structured_draft_not_found"


def test_output_text_from_mo_response_handles_missing_output() -> None:
    assert output_text_from_mo_response({"output": {"text": "hello"}}) == "hello"
    assert output_text_from_mo_response({"output": []}) == ""
