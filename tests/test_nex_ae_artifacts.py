from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import nex_ae_api.artifacts as ae_artifacts
from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    ArtifactHandoffStore,
    HttpCxArtifactSourceClient,
    actor_claims_ref_from_payload,
    artifact_intent_from_payload,
    build_artifact_handoff_record,
    language_from_payload,
    register_artifact_handoff_routes,
    target_formats_from_payload,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class FakeCxArtifactSourceClient:
    def __init__(
        self,
        *,
        generation_record: dict[str, Any] | None = None,
        structured_draft: dict[str, Any] | None = None,
    ) -> None:
        self.generation_record = generation_record or sample_generation_record()
        self.structured_draft = structured_draft or sample_structured_draft()
        self.calls: list[tuple[str, str]] = []

    def get_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("generation", cx_generation_id))
        return self.generation_record

    def get_structured_draft(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(("draft", cx_generation_id))
        return self.structured_draft


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "Idempotency-Key": "artifact-request-001",
    }


def sample_generation_record(*, status: str = "COMPLETED") -> dict[str, Any]:
    return {
        "cx_generation_id": "cx-gen-001",
        "status": status,
        "request_metadata": {
            "structured_draft_id": "draft-001",
            "grounding_required": True,
            "retrieval_package_id": "cx-ret-001",
            "retrieval_package_hash": "d" * 64,
            "selected_evidence_count": 2,
        },
    }


def sample_structured_draft(
    *,
    status: str = "VALIDATED",
    citation_status: str = "VALIDATED",
    cx_generation_id: str = "cx-gen-001",
    structured_draft_id: str = "draft-001",
) -> dict[str, Any]:
    return {
        "structured_draft_schema_version": "cx_structured_draft.v1",
        "structured_draft_id": structured_draft_id,
        "cx_generation_id": cx_generation_id,
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "title": "Grounded report",
        "summary": "Safe summary.",
        "content_hash": "c" * 64,
        "sections": [],
        "citations": [
            {
                "citation_label": "[1]",
                "evidence_id": "evidence-001",
                "retrieval_package_id": "cx-ret-001",
                "valid": True,
                "validation_error": None,
            },
            {
                "citation_label": "[2]",
                "evidence_id": "evidence-002",
                "retrieval_package_id": "cx-ret-001",
                "valid": True,
                "validation_error": None,
            },
        ],
        "validation": {
            "validator_profile_id": "mock-structured-draft-validator-v1",
            "citation_status": citation_status,
            "errors": [] if citation_status == "VALIDATED" else [{"code": "bad"}],
            "warnings": [],
        },
    }


def artifact_payload() -> dict[str, Any]:
    return {
        "cx_generation_id": "cx-gen-001",
        "chat_document_id": "chat-doc-001",
        "interaction_id": "interaction-001",
        "workspace_id": "workspace-001",
        "tenant_id": "tenant-001",
        "owner_user_id": "user-001",
        "artifact_intent": "create_and_export",
        "target_formats": ["MD", "HTML_PREVIEW", "PDF", "MD"],
        "artifact_title": "Generated report",
        "language": "ko",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": "user-001",
            "tenant_id": "tenant-001",
        },
    }


def build_client(
    cx_client: FakeCxArtifactSourceClient | None = None,
) -> tuple[TestClient, ArtifactHandoffStore, FakeCxArtifactSourceClient]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ArtifactHandoffStore()
    client = cx_client or FakeCxArtifactSourceClient()
    register_artifact_handoff_routes(app, store=store, cx_client=client)
    return TestClient(app), store, client


def test_build_artifact_handoff_record_copies_only_safe_lineage() -> None:
    record = build_artifact_handoff_record(
        source_payload=artifact_payload(),
        generation_record=sample_generation_record(),
        structured_draft=sample_structured_draft(),
        artifact_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["handoff_schema_version"] == "ae_artifact_handoff.v1"
    assert record["handoff_status"] == "READY_FOR_RENDERING"
    assert record["artifact_title"] == "Generated report"
    assert record["target_formats"] == ["MD", "HTML_PREVIEW", "PDF"]
    assert record["structured_draft_content_hash"] == "c" * 64
    assert len(record["citation_claims_hash"]) == 64
    assert len(record["validation_result_hash"]) == 64
    assert record["quality_summary"]["evidence_ref_count"] == 2
    assert "raw prompt" not in str(record).lower()
    assert "/data/nex-platform" not in str(record)


def test_artifact_handoff_route_fetches_cx_records_and_allows_readback() -> None:
    client, store, cx_client = build_client()

    response = client.post(
        "/api/v1/artifact-handoffs",
        json=artifact_payload(),
        headers=auth_headers(),
    )
    payload = response.json()
    readback = client.get(
        f"/api/v1/artifact-handoffs/{payload['artifact_handoff_id']}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert cx_client.calls == [
        ("generation", "cx-gen-001"),
        ("draft", "cx-gen-001"),
    ]
    assert payload["artifact_request_id"] == "artifact-request-001"
    assert store.get(payload["artifact_handoff_id"]) == payload
    assert readback.status_code == 200
    assert readback.json() == payload


def test_artifact_handoff_route_requires_auth_and_reports_missing() -> None:
    client, _, _ = build_client()

    unauthorized = client.post("/api/v1/artifact-handoffs", json=artifact_payload())
    missing = client.get(
        "/api/v1/artifact-handoffs/missing",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.artifact_handoff_not_found"


def test_artifact_handoff_rejects_unready_generation_and_invalid_draft() -> None:
    with pytest.raises(ArtifactHandoffError) as generation_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(status="FAILED"),
            structured_draft=sample_structured_draft(),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert generation_exc.value.error_code == "ae.source_generation_not_ready"
    assert "COMPLETED" in generation_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as draft_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(),
            structured_draft=sample_structured_draft(status="VALIDATION_FAILED"),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert draft_exc.value.error_code == "ae.citation_validation_required"
    assert "validated" in draft_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as citation_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(),
            structured_draft=sample_structured_draft(citation_status="FAILED"),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert citation_exc.value.error_code == "ae.citation_validation_required"
    assert "Citation validation" in citation_exc.value.detail


def test_artifact_handoff_rejects_source_draft_mismatch() -> None:
    with pytest.raises(ArtifactHandoffError) as generation_id_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(),
            structured_draft=sample_structured_draft(cx_generation_id="cx-gen-other"),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert generation_id_exc.value.error_code == "ae.source_draft_hash_mismatch"
    assert "does not belong" in generation_id_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as draft_id_exc:
        build_artifact_handoff_record(
            source_payload=artifact_payload(),
            generation_record=sample_generation_record(),
            structured_draft=sample_structured_draft(structured_draft_id="draft-other"),
            artifact_request_id=None,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert draft_id_exc.value.error_code == "ae.source_draft_hash_mismatch"
    assert "draft ID" in draft_id_exc.value.detail


def test_artifact_handoff_payload_validation_helpers() -> None:
    assert artifact_intent_from_payload({}) == "create_artifact"
    assert target_formats_from_payload({}) == ["MD", "HTML_PREVIEW"]
    assert language_from_payload({}) == "ko"
    assert actor_claims_ref_from_payload({"owner_user_id": "user-001"}) == {
        "actor_type": "user",
        "actor_id": "user-001",
        "tenant_id": "local-tenant",
    }

    with pytest.raises(ArtifactHandoffError) as intent_exc:
        artifact_intent_from_payload({"artifact_intent": "bad"})
    assert intent_exc.value.error_code == "ae.artifact_intent_invalid"
    assert "artifact intent" in intent_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as formats_exc:
        target_formats_from_payload({"target_formats": []})
    assert formats_exc.value.error_code == "ae.target_formats_invalid"
    assert "target_formats" in formats_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as format_exc:
        target_formats_from_payload({"target_formats": ["TXT"]})
    assert format_exc.value.error_code == "ae.render_format_unsupported"

    with pytest.raises(ArtifactHandoffError) as language_exc:
        language_from_payload({"language": "ja"})
    assert language_exc.value.error_code == "ae.language_invalid"

    with pytest.raises(ArtifactHandoffError) as actor_exc:
        actor_claims_ref_from_payload({"actor_claims_ref": "bad"})
    assert actor_exc.value.error_code == "ae.actor_claims_ref_invalid"


def test_artifact_handoff_route_maps_invalid_payload_to_problem() -> None:
    client, _, _ = build_client()

    response = client.post(
        "/api/v1/artifact-handoffs",
        json={**artifact_payload(), "target_formats": ["TXT"]},
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "ae.render_format_unsupported"


def test_http_cx_artifact_source_client_reads_generation_and_draft(monkeypatch) -> None:
    seen_urls: list[str] = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> httpx.Response:
        seen_urls.append(url)
        assert headers["X-Service-ID"] == "nex-ae-api"
        if url.endswith("/structured-draft"):
            return httpx.Response(status_code=200, json={"structured_draft_id": "draft-001"})
        return httpx.Response(status_code=200, json={"cx_generation_id": "cx-gen-001"})

    monkeypatch.setattr(ae_artifacts.httpx, "get", fake_get)
    client = HttpCxArtifactSourceClient(base_url="http://cx.test")

    assert client.get_generation(
        "cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) == {"cx_generation_id": "cx-gen-001"}
    assert client.get_structured_draft(
        "cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) == {"structured_draft_id": "draft-001"}
    assert seen_urls == [
        "http://cx.test/api/v1/generations/cx-gen-001",
        "http://cx.test/api/v1/generations/cx-gen-001/structured-draft",
    ]


def test_http_cx_artifact_source_client_maps_error_and_bad_json(monkeypatch) -> None:
    def post_error(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            status_code=503,
            json={
                "error_code": "cx.down",
                "detail": "CX unavailable.",
                "retryable": True,
            },
        )

    monkeypatch.setattr(ae_artifacts.httpx, "get", post_error)
    with pytest.raises(ArtifactHandoffError) as exc_info:
        HttpCxArtifactSourceClient(base_url="http://cx.test").get_generation(
            "cx-gen-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert exc_info.value.error_code == "cx.down"
    assert exc_info.value.retryable is True

    def bad_json(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(status_code=500, content=b"broken")

    monkeypatch.setattr(ae_artifacts.httpx, "get", bad_json)
    with pytest.raises(ArtifactHandoffError) as fallback_exc:
        HttpCxArtifactSourceClient(base_url="http://cx.test").get_structured_draft(
            "cx-gen-001",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert fallback_exc.value.error_code == "cx.artifact_source_request_failed"
