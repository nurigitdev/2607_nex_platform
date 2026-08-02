from __future__ import annotations

from fastapi.testclient import TestClient

from nex_mo.main import app
from nex_mo.providers import (
    create_mock_embedding_response,
    create_mock_generation_response,
    create_mock_rerank_response,
    list_provider_routes,
    resolve_provider_route,
)
from nex_runtime import issue_mock_service_token


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-cx", audience="nex-mo")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def test_provider_registry_contains_required_mock_capabilities() -> None:
    routes = list_provider_routes()

    assert {route.provider_capability for route in routes} == {
        "embedding",
        "reranking",
        "generation",
    }
    assert resolve_provider_route("general-llm-default", "generation").status == "READY"


def test_provider_routes_endpoint_requires_service_claim() -> None:
    response = TestClient(app).get("/api/v1/provider-routes")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_provider_routes_endpoint_filters_by_capability() -> None:
    response = TestClient(app).get(
        "/api/v1/provider-routes",
        params={"capability": "generation"},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["count"] == 1
    assert payload["data"][0]["alias"] == "general-llm-default"


def test_mock_embeddings_are_deterministic() -> None:
    payload = {"inputs": ["alpha", "alpha"]}

    response = create_mock_embedding_response(payload)

    assert response["data"][0]["embedding"] == response["data"][1]["embedding"]
    assert len(response["data"][0]["embedding"]) == 8
    assert response["usage"]["total_tokens"] == 2


def test_embeddings_endpoint_returns_mock_vectors() -> None:
    response = TestClient(app).post(
        "/api/v1/embeddings",
        json={"inputs": ["alpha", "beta"]},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["alias"] == "mock-embedding-default"
    assert len(response.json()["data"]) == 2


def test_mock_rerank_response_is_sorted_by_score() -> None:
    response = create_mock_rerank_response(
        {
            "query": "quality gate",
            "documents": ["coverage report", "service auth", "provider route"],
        }
    )

    scores = [item["score"] for item in response["results"]]
    assert scores == sorted(scores, reverse=True)


def test_rerank_endpoint_returns_scores() -> None:
    response = TestClient(app).post(
        "/api/v1/rerank",
        json={"query": "trace", "documents": ["alpha", "beta"]},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["alias"] == "mock-reranker-default"
    assert len(response.json()["results"]) == 2


def test_mock_generation_response_is_deterministic() -> None:
    payload = {
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "prompt": "Summarize the contract evidence.",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    }

    first = create_mock_generation_response(
        payload,
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    second = create_mock_generation_response(
        payload,
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert first["mo_generation_id"] == second["mo_generation_id"]
    assert first["runtime_metadata"]["route_id"] == "route-general-llm-default"
    assert "provider_url" not in first["runtime_metadata"]


def test_generations_endpoint_returns_mock_output() -> None:
    response = TestClient(app).post(
        "/api/v1/generations",
        json={
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "messages": [{"role": "user", "content": "Draft the summary."}],
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["finish_reason"] == "STOP"
    assert payload["runtime_metadata"]["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_generations_endpoint_rejects_unknown_alias() -> None:
    response = TestClient(app).post(
        "/api/v1/generations",
        json={"alias": "unknown", "prompt": "hello"},
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "mo.alias_not_found"


def test_generations_endpoint_rejects_raw_provider_fields() -> None:
    response = TestClient(app).post(
        "/api/v1/generations",
        json={"prompt": "hello", "provider_url": "http://localhost:8000"},
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "mo.provider_field_forbidden"


def test_generations_endpoint_rejects_out_of_bounds_tokens() -> None:
    response = TestClient(app).post(
        "/api/v1/generations",
        json={"prompt": "hello", "max_output_tokens": 2048},
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "mo.generation_parameter_out_of_bounds"
