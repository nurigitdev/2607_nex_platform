from __future__ import annotations

from fastapi.testclient import TestClient

from nex_mo.main import app
from nex_mo.providers import (
    DEFAULT_PROVIDER_ROUTES,
    GENERATION_PROFILE_CANDIDATES,
    ModelProfile,
    ProviderRoute,
    ProviderRouteError,
    build_model_profile_catalog,
    create_mock_embedding_response,
    create_mock_generation_response,
    create_mock_rerank_response,
    list_model_profiles,
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


def test_model_profile_catalog_uses_qwen_defaults() -> None:
    profiles = build_model_profile_catalog({})

    assert [profile.profile_name for profile in profiles] == [
        "qwen3_embedding_4b_bf16",
        "qwen3_reranker_4b_bf16",
        "qwen3_5_122b_a10b_nvfp4",
        "qwen3_6_27b_nvfp4",
        "k_ai_generation_candidate",
    ]
    assert profiles[0].model_path == "/data/nex-platform/models/qwen3-embedding-4b-bf16"
    assert profiles[1].precision == "BF16"
    assert profiles[2].runtime_engine == "vllm"
    assert profiles[2].model_name == "Qwen3.5-122B-A10B-NVFP4"
    assert profiles[2].selected is True
    assert profiles[3].candidate_role == "candidate"
    assert profiles[4].status == "PLANNED"
    assert all(profile.provider_mode == "mock" for profile in profiles)
    assert [profile.status for profile in profiles] == [
        "READY",
        "READY",
        "READY",
        "CONFIGURED",
        "PLANNED",
    ]


def test_model_profile_catalog_accepts_env_overrides() -> None:
    profiles = build_model_profile_catalog(
        {
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_MODEL_ROOT": "/models",
            "NEX_MO_EMBEDDING_PROFILE": "embedding_a",
            "NEX_MO_RERANKER_PROFILE": "reranker_a",
            "NEX_MO_GENERATION_PROFILE": "qwen3_6_27b_nvfp4",
            "NEX_MO_EMBEDDING_MODEL_PATH": "/override/embed",
            "NEX_MO_GENERATION_MODEL_PATH": "/override/generation-selected",
        }
    )

    assert profiles[0].profile_name == "embedding_a"
    assert profiles[0].model_path == "/override/embed"
    assert profiles[0].runtime_engine == "remote_http"
    assert profiles[1].model_path == "/models/qwen3-reranker-4b-bf16"
    assert profiles[2].model_path == "/models/qwen3.5-122b-a10b-nvfp4"
    assert profiles[2].selected is False
    assert profiles[3].model_path == "/override/generation-selected"
    assert profiles[3].selected is True
    assert [profile.status for profile in profiles] == [
        "CONFIGURED",
        "CONFIGURED",
        "CONFIGURED",
        "CONFIGURED",
        "PLANNED",
    ]


def test_generation_model_profiles_support_custom_selected_profile() -> None:
    profiles = build_model_profile_catalog(
        {
            "NEX_MO_MODEL_ROOT": "/models",
            "NEX_MO_GENERATION_PROFILE": "kai_local_trial_v1",
            "NEX_MO_GENERATION_MODEL_NAME": "K-AI local trial v1",
            "NEX_MO_GENERATION_MODEL_PATH": "/models/kai-local-trial-v1",
        }
    )
    generation_profiles = [
        profile for profile in profiles if profile.provider_capability == "generation"
    ]

    assert len(GENERATION_PROFILE_CANDIDATES) == 3
    assert generation_profiles[-1].profile_name == "kai_local_trial_v1"
    assert generation_profiles[-1].model_name == "K-AI local trial v1"
    assert generation_profiles[-1].candidate_role == "custom"
    assert generation_profiles[-1].selected is True
    assert generation_profiles[0].selected is False


def test_model_profile_to_wire_has_no_secret_fields() -> None:
    payload = ModelProfile(
        profile_name="profile",
        provider_capability="embedding",
        alias="mock-embedding-default",
        provider_mode="mock",
        model_name="Qwen3-embedding-4B",
        precision="BF16",
        runtime_engine="local_mock",
        model_path="/data/nex-platform/models/qwen3-embedding-4b-bf16",
        selected=True,
        status="READY",
        candidate_role="primary",
        selection_reason="safe public profile",
        live_health_env="NEX_MO_LIVE_EMBEDDING_HEALTH_URL",
    ).to_wire()

    assert payload["model_path"].endswith("qwen3-embedding-4b-bf16")
    assert payload["live_health_env"] == "NEX_MO_LIVE_EMBEDDING_HEALTH_URL"
    assert "api_key" not in payload
    assert "provider_url" not in payload


def test_list_model_profiles_filters_by_capability() -> None:
    profiles = (
        ModelProfile(
            profile_name="embedding",
            provider_capability="embedding",
            alias="mock-embedding-default",
            provider_mode="mock",
            model_name="embed",
            precision="BF16",
            runtime_engine="local_mock",
            model_path="/models/embed",
            selected=True,
            status="READY",
        ),
        ModelProfile(
            profile_name="generation",
            provider_capability="generation",
            alias="general-llm-default",
            provider_mode="mock",
            model_name="llm",
            precision="NVFP4",
            runtime_engine="vllm",
            model_path="/models/llm",
            selected=True,
            status="READY",
        ),
    )

    assert [profile.profile_name for profile in list_model_profiles("generation", profiles)] == [
        "generation"
    ]
    assert list_model_profiles("unknown", profiles) == []


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


def test_provider_routes_endpoint_lists_embedding_dimensions() -> None:
    response = TestClient(app).get("/api/v1/provider-routes", headers=auth_headers())

    assert response.status_code == 200
    embedding_route = response.json()["data"][0]
    assert embedding_route["embedding_dimensions"] == 8


def test_provider_profiles_endpoint_requires_service_claim() -> None:
    response = TestClient(app).get("/api/v1/provider-profiles")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_provider_profiles_endpoint_lists_selected_profiles() -> None:
    response = TestClient(app).get("/api/v1/provider-profiles", headers=auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["count"] == 5
    assert payload["meta"]["provider_mode"] == "mock"
    assert payload["data"][0]["profile_name"] == "qwen3_embedding_4b_bf16"
    assert payload["data"][0]["selected"] is True


def test_provider_profiles_endpoint_filters_by_capability() -> None:
    response = TestClient(app).get(
        "/api/v1/provider-profiles",
        params={"capability": "reranking"},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["count"] == 1
    assert payload["data"][0]["provider_capability"] == "reranking"


def test_provider_profiles_endpoint_lists_generation_candidates() -> None:
    response = TestClient(app).get(
        "/api/v1/provider-profiles",
        params={"capability": "generation"},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["count"] == 3
    assert [item["profile_name"] for item in payload["data"]] == [
        "qwen3_5_122b_a10b_nvfp4",
        "qwen3_6_27b_nvfp4",
        "k_ai_generation_candidate",
    ]
    assert payload["data"][0]["selected"] is True
    assert payload["data"][1]["candidate_role"] == "candidate"
    assert payload["data"][2]["candidate_role"] == "planned"


def test_resolve_provider_route_rejects_capability_mismatch() -> None:
    try:
        resolve_provider_route("mock-embedding-default", "generation")
    except ProviderRouteError as exc:
        assert exc.status_code == 422
        assert exc.error_code == "mo.capability_not_supported"
    else:
        raise AssertionError("expected ProviderRouteError")


def test_resolve_provider_route_rejects_unready_route() -> None:
    unready = (
        ProviderRoute(
            alias="slow-route",
            provider_capability="generation",
            provider_type="mock-generation",
            model_revision="mock-llm-v1",
            deployment_id="mock-generation-local",
            route_id="route-slow",
            supports_response_formats=("text",),
            max_input_tokens=1,
            max_output_tokens=1,
            status="UNAVAILABLE",
        ),
    )

    try:
        resolve_provider_route("slow-route", "generation", routes=unready)
    except ProviderRouteError as exc:
        assert exc.status_code == 503
        assert exc.retryable is True
    else:
        raise AssertionError("expected ProviderRouteError")


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


def test_embeddings_endpoint_requires_service_claim() -> None:
    response = TestClient(app).post("/api/v1/embeddings", json={"inputs": ["alpha"]})

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_embedding_request_rejects_empty_inputs() -> None:
    response = TestClient(app).post(
        "/api/v1/embeddings",
        json={"inputs": []},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "mo.request_invalid"


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


def test_rerank_endpoint_requires_query() -> None:
    response = TestClient(app).post(
        "/api/v1/rerank",
        json={"documents": ["alpha"]},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "mo.request_invalid"


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


def test_generations_endpoint_rejects_missing_prompt_or_messages() -> None:
    response = TestClient(app).post(
        "/api/v1/generations",
        json={"alias": "general-llm-default"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "mo.request_invalid"


def test_default_provider_routes_remain_three_entries() -> None:
    assert len(DEFAULT_PROVIDER_ROUTES) == 3
