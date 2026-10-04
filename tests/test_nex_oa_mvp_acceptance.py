from __future__ import annotations

from nex_oa.mvp_acceptance import (
    OA_MVP_REQUIREMENTS,
    build_oa_mvp_acceptance_policy,
    evaluate_oa_mvp_acceptance_inputs,
)


def test_policy_freezes_five_requirements_and_profiles() -> None:
    policy = build_oa_mvp_acceptance_policy()

    assert tuple(
        item["requirement_id"] for item in policy["requirements"]
    ) == OA_MVP_REQUIREMENTS
    assert policy["requirement_count"] == 5
    assert policy["blocking_requirement_count"] == 5
    assert policy["browser_access_profile"] == "OPAQUE_OA_BACKED_SESSION"
    assert policy["service_access_profile"] == "RS256_SIGNED_ONLY"
    assert policy["new_tables"] == ()
    assert policy["remote_model_provider_required"] is False


def test_acceptance_inputs_require_exact_passing_gate_set() -> None:
    accepted = evaluate_oa_mvp_acceptance_inputs(
        {
            "repository": True,
            "postgres_restart": True,
            "key_rotation": True,
            "revocation": True,
            "cross_service": True,
            "failure_audit": True,
            "contracts_privacy": True,
            "full_gate": True,
        }
    )
    assert accepted == {
        "status": "ACCEPTED",
        "passed_gate_count": 8,
        "gate_count": 8,
        "missing_gates": [],
        "unexpected_gates": [],
        "failed_gates": [],
    }

    blocked = evaluate_oa_mvp_acceptance_inputs(
        {"repository": True, "unexpected": True}
    )
    assert blocked["status"] == "BLOCKED"
    assert "postgres_restart" in blocked["missing_gates"]
    assert blocked["unexpected_gates"] == ["unexpected"]
    assert "revocation" in blocked["failed_gates"]
