from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_runtime.compatibility import (
    DEFAULT_GENERATION_COMPATIBILITY_RULES,
    GenerationCompatibilityError,
    compatibility_key_from_payload,
    compatibility_key_label,
    register_generation_compatibility_routes,
    select_generation_compatibility_rule,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers(audience: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=audience)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def test_compatibility_key_from_payload_uses_defaults_and_nested_refs() -> None:
    assert compatibility_key_from_payload({}) == {
        "execution_mode": "GROUNDED_ANSWER",
        "template_id": "none",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "text_answer_v1",
        "provider_capability": "generation",
        "generation_profile": "grounded-answer",
    }

    key = compatibility_key_from_payload(
        {
            "execution_mode": "REPORT_GENERATION",
            "template_ref": {"template_id": "report"},
            "prompt_contract_ref": {
                "prompt_binding_id": "ae.grounded_chat.default",
            },
            "output_contract": {
                "output_contract_id": "report_generation_v1",
            },
            "metadata": {
                "provider_capability": "generation",
                "generation_profile": "general-document",
            },
        }
    )

    assert key["template_id"] == "report"
    assert key["output_contract_id"] == "report_generation_v1"
    assert key["generation_profile"] == "general-document"


def test_select_generation_compatibility_rule_matches_active_rule() -> None:
    rule = select_generation_compatibility_rule(
        {
            "execution_mode": "DOCUMENT_SUMMARY",
            "template_id": "summary",
            "prompt_binding_id": "cx.document_summary.default",
            "output_contract_id": "document_summary_v1",
            "provider_capability": "generation",
            "generation_profile": "summary",
        }
    )

    assert rule["compatibility_rule_id"] == "compat-document-summary-v1"
    assert rule["grounding_required"] is True


def test_select_generation_compatibility_rule_skips_inactive_and_reports_mismatch() -> None:
    inactive_rule = {
        **DEFAULT_GENERATION_COMPATIBILITY_RULES[0],
        "compatibility_rule_id": "inactive",
        "status": "INACTIVE",
    }
    with pytest.raises(GenerationCompatibilityError) as exc:
        select_generation_compatibility_rule(
            {},
            rules=(inactive_rule,),
        )

    assert exc.value.status_code == 422
    assert exc.value.error_code == "generation.compatibility_rule_not_found"
    assert "execution_mode=GROUNDED_ANSWER" in exc.value.detail


def test_compatibility_key_rejects_invalid_string_values() -> None:
    with pytest.raises(GenerationCompatibilityError) as exc:
        compatibility_key_from_payload({"execution_mode": ""})

    assert exc.value.status_code == 400
    assert exc.value.error_code == "generation.compatibility_key_invalid"


def test_compatibility_key_label_is_stable() -> None:
    label = compatibility_key_label(compatibility_key_from_payload({}))

    assert label.startswith("execution_mode=GROUNDED_ANSWER")
    assert "generation_profile=grounded-answer" in label


def test_generation_compatibility_routes_require_auth_and_list_rules() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_generation_compatibility_routes(app, expected_audience="nex-ae-api")
    client = TestClient(app)

    unauthorized = client.get("/api/v1/compatibility/generation-rules")
    response = client.get(
        "/api/v1/compatibility/generation-rules",
        headers=auth_headers("nex-ae-api"),
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert len(response.json()["rules"]) == 4
    assert response.json()["rules"][0]["compatibility_rule_schema_version"] == (
        "generation_compatibility_rule.v1"
    )


def test_generation_compatibility_route_uses_expected_audience() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_compatibility_routes(app, expected_audience="nex-cx")
    client = TestClient(app)

    wrong_audience = client.get(
        "/api/v1/compatibility/generation-rules",
        headers=auth_headers("nex-ae-api"),
    )
    ok = client.get(
        "/api/v1/compatibility/generation-rules",
        headers=auth_headers("nex-cx"),
    )

    assert wrong_audience.status_code == 401
    assert ok.status_code == 200
