from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_runtime.prompts import (
    PromptRegistryError,
    PromptRegistryStore,
    PromptSeed,
    register_prompt_registry_routes,
    render_prompt_from_binding,
    seed_prompt_registry,
    sha256_text,
)
from nex_ae_api.prompts import AE_GROUNDED_CHAT_BINDING, seed_ae_prompt_registry
from nex_cx.prompts import CX_DOCUMENT_SUMMARY_BINDING, seed_cx_prompt_registry


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers(audience: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=audience)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def test_seed_prompt_registry_is_idempotent() -> None:
    store = PromptRegistryStore()

    first = seed_cx_prompt_registry(store)
    second = seed_cx_prompt_registry(store)

    assert first == second
    assert len(store.templates) == 1
    assert len(store.template_versions) == 1
    assert store.get_binding(CX_DOCUMENT_SUMMARY_BINDING)["purpose"] == "document_summary"


def test_service_prompt_seeds_cover_cx_and_ae_defaults() -> None:
    cx_store = PromptRegistryStore()
    ae_store = PromptRegistryStore()

    seed_cx_prompt_registry(cx_store)
    seed_ae_prompt_registry(ae_store)

    assert cx_store.get_binding(CX_DOCUMENT_SUMMARY_BINDING)["service_id"] == "nex-cx"
    assert ae_store.get_binding(AE_GROUNDED_CHAT_BINDING)["service_id"] == "nex-ae-api"


def test_render_prompt_from_binding_stores_event_without_raw_user_prompt() -> None:
    store = PromptRegistryStore()
    seed_prompt_registry(
        store,
        [
            PromptSeed(
                service_id="nex-cx",
                purpose="test",
                name="test_prompt",
                owner_domain="content",
                binding_key="test.prompt",
                version="v1",
                role="system",
                segment_order=0,
                content="Use {limit} chars.",
                model_capability="summary",
            )
        ],
    )

    result = render_prompt_from_binding(
        store,
        binding_key="test.prompt",
        variables={"limit": 900},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        user_prompt="private user prompt",
        output_text="summary output",
    )

    event = result["render_event"]
    assert result["rendered_prompt"] == "Use 900 chars."
    assert event["rendered_prompt_hash"] == sha256_text("Use 900 chars.")
    assert event["user_prompt_hash"] == sha256_text("private user prompt")
    assert event["output_hash"] == sha256_text("summary output")
    assert event["metadata"]["variable_keys"] == ["limit"]
    assert "private user prompt" not in str(event)
    assert store.get_render_event(event["prompt_render_event_id"]) == event


def test_render_prompt_from_binding_reports_missing_binding_and_version() -> None:
    store = PromptRegistryStore()
    with pytest.raises(PromptRegistryError) as missing_binding:
        render_prompt_from_binding(
            store,
            binding_key="missing",
            variables={},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    store.bindings["broken"] = {
        "binding_key": "broken",
        "status": "ACTIVE",
        "prompt_template_version_id": "missing-version",
        "prompt_binding_id": "binding-001",
        "service_id": "nex-cx",
        "purpose": "test",
    }
    with pytest.raises(PromptRegistryError) as missing_version:
        render_prompt_from_binding(
            store,
            binding_key="broken",
            variables={},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert missing_binding.value.error_code == "prompt.binding_not_found"
    assert missing_version.value.error_code == "prompt.template_version_not_found"


def test_render_prompt_from_binding_reports_missing_variable() -> None:
    store = PromptRegistryStore()
    seed_prompt_registry(
        store,
        [
            PromptSeed(
                service_id="nex-cx",
                purpose="test",
                name="test_prompt",
                owner_domain="content",
                binding_key="test.prompt",
                version="v1",
                role="system",
                segment_order=0,
                content="Use {limit} chars.",
                model_capability="summary",
            )
        ],
    )

    with pytest.raises(PromptRegistryError) as exc:
        render_prompt_from_binding(
            store,
            binding_key="test.prompt",
            variables={},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 422
    assert exc.value.error_code == "prompt.variable_missing"


def test_prompt_registry_routes_list_bindings_and_read_events() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = PromptRegistryStore()
    seed_cx_prompt_registry(store)
    rendered = render_prompt_from_binding(
        store,
        binding_key=CX_DOCUMENT_SUMMARY_BINDING,
        variables={"summary_max_chars": 900, "summary_hard_limit_chars": 1000},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    register_prompt_registry_routes(app, store=store, expected_audience="nex-cx")
    client = TestClient(app)

    bindings_response = client.get("/api/v1/prompts/bindings", headers=auth_headers("nex-cx"))
    event_response = client.get(
        f"/api/v1/prompts/render-events/{rendered['render_event']['prompt_render_event_id']}",
        headers=auth_headers("nex-cx"),
    )

    assert bindings_response.status_code == 200
    assert bindings_response.json()["bindings"][0]["binding_key"] == CX_DOCUMENT_SUMMARY_BINDING
    assert event_response.status_code == 200
    assert event_response.json()["rendered_prompt_hash"] == rendered["render_event"][
        "rendered_prompt_hash"
    ]


def test_prompt_registry_routes_require_auth_and_report_missing_event() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = PromptRegistryStore()
    seed_cx_prompt_registry(store)
    register_prompt_registry_routes(app, store=store, expected_audience="nex-cx")
    client = TestClient(app)

    auth_response = client.get("/api/v1/prompts/bindings")
    missing_response = client.get(
        "/api/v1/prompts/render-events/missing",
        headers=auth_headers("nex-cx"),
    )

    assert auth_response.status_code == 401
    assert auth_response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert missing_response.status_code == 404
    assert missing_response.json()["error_code"] == "prompt.render_event_not_found"
