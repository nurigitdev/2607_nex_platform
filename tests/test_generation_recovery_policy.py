from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_runtime.recovery import (
    DEFAULT_GENERATION_RECOVERY_POLICIES,
    GenerationRecoveryPolicyError,
    recovery_action_allowed,
    recovery_policy_hash,
    register_generation_recovery_policy_routes,
    select_generation_recovery_policy,
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


def test_select_generation_recovery_policy_matches_active_failure_code() -> None:
    policy = select_generation_recovery_policy("mo.provider_timeout")

    assert policy["recovery_policy_schema_version"] == "generation_recovery_policy.v1"
    assert policy["default_action"] == "retry"
    assert policy["retryable"] is True
    assert policy["preserves_retrieval_package"] is True
    assert recovery_action_allowed(policy, "retry")
    assert not recovery_action_allowed(policy, "repair")
    assert len(recovery_policy_hash(policy)) == 64
    assert "provider_url" not in str(policy)


def test_select_generation_recovery_policy_skips_inactive_and_validates_code() -> None:
    inactive = {
        **DEFAULT_GENERATION_RECOVERY_POLICIES[0],
        "status": "INACTIVE",
    }
    with pytest.raises(GenerationRecoveryPolicyError) as missing_exc:
        select_generation_recovery_policy(
            "mo.provider_timeout",
            policies=(inactive,),
        )
    assert missing_exc.value.status_code == 404
    assert missing_exc.value.error_code == "generation.recovery_policy_not_found"

    with pytest.raises(GenerationRecoveryPolicyError) as invalid_exc:
        select_generation_recovery_policy(" ")
    assert invalid_exc.value.status_code == 400
    assert invalid_exc.value.error_code == "generation.recovery_failure_code_invalid"


def test_generation_recovery_policy_route_lists_and_reads_for_ae() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_generation_recovery_policy_routes(app, expected_audience="nex-ae-api")
    client = TestClient(app)

    unauthorized = client.get("/api/v1/recovery/generation-policies")
    listed = client.get(
        "/api/v1/recovery/generation-policies",
        headers=auth_headers("nex-ae-api"),
    )
    read = client.get(
        "/api/v1/recovery/generation-policies/ae.render_job_failed",
        headers=auth_headers("nex-ae-api"),
    )
    missing = client.get(
        "/api/v1/recovery/generation-policies/unknown.failure",
        headers=auth_headers("nex-ae-api"),
    )

    assert unauthorized.status_code == 401
    assert listed.status_code == 200
    assert len(listed.json()["policies"]) == len(DEFAULT_GENERATION_RECOVERY_POLICIES)
    assert read.status_code == 200
    assert read.json()["owner_service"] == "nex-ae-api"
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "generation.recovery_policy_not_found"


def test_generation_recovery_policy_route_uses_expected_audience_for_cx() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_recovery_policy_routes(app, expected_audience="nex-cx")
    client = TestClient(app)

    wrong_audience = client.get(
        "/api/v1/recovery/generation-policies",
        headers=auth_headers("nex-ae-api"),
    )
    ok = client.get(
        "/api/v1/recovery/generation-policies/cx.citation_validation_failed",
        headers=auth_headers("nex-cx"),
    )

    assert wrong_audience.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["default_action"] == "repair"
    assert ok.json()["changed_fields_allowed"] == ["citation_map", "section_blocks"]
