from nex_ae_api.agent_authority import AGENT_AUTHORITY_PROFILES
from nex_oa.memberships import (
    DEFAULT_EMPLOYEE_PRODUCT_SCOPES,
    DEFAULT_MEMBERSHIP_ROLES,
    DEFAULT_MEMBERSHIP_SCOPES,
    InMemoryOaTenantMembershipRegistry,
)
from nex_runtime.canonical_platform_trust import CANONICAL_PLATFORM_TRUST_GRANTS


def test_new_employee_receives_bounded_product_baseline() -> None:
    membership = InMemoryOaTenantMembershipRegistry().ensure_membership(
        {
            "tenant_id": "VO00",
            "subject_id": "employee-1001",
            "tenant_display_name": "VO00",
            "subject_display_name": "Employee 1001",
        }
    )["membership"]

    assert membership["roles"] == list(DEFAULT_MEMBERSHIP_ROLES)
    assert membership["scopes"] == list(DEFAULT_MEMBERSHIP_SCOPES)
    assert set(DEFAULT_EMPLOYEE_PRODUCT_SCOPES).issubset(membership["scopes"])


def test_employee_baseline_excludes_privileged_agent_and_service_authority() -> None:
    forbidden = {
        "approval:read",
        "approval:decide",
        "finance:journal:approve",
        "finance:cost-allocation-plan:approve",
        "project:project:admin",
        "project:membership:manage",
        "project:work-assignment:manage",
        "project:work-code:approve",
        "work:claim",
        "work:delegate",
        "work:result:submit",
        "service:call",
        "work:evidence:ingest",
    }

    assert forbidden.isdisjoint(DEFAULT_MEMBERSHIP_SCOPES)


def test_ia_and_pa_profiles_remain_separate_from_human_membership() -> None:
    assert AGENT_AUTHORITY_PROFILES["IA"].roles == (
        "nex-agent",
        "nex-agent-ia",
    )
    assert AGENT_AUTHORITY_PROFILES["IA"].scopes == (
        "work:claim",
        "work:delegate",
    )
    assert AGENT_AUTHORITY_PROFILES["PA"].roles == (
        "nex-agent",
        "nex-agent-pa",
    )
    assert AGENT_AUTHORITY_PROFILES["PA"].scopes == (
        "work:claim",
        "work:delegate",
        "work:result:submit",
    )
    assert set(AGENT_AUTHORITY_PROFILES["PA"].scopes).isdisjoint(
        DEFAULT_MEMBERSHIP_SCOPES
    )


def test_pa_related_service_trust_uses_service_principals() -> None:
    grants = {
        (grant.owner, grant.audience): set(grant.scopes)
        for grant in CANONICAL_PLATFORM_TRUST_GRANTS
    }

    assert grants[("nex-ae-api", "nex-oa")].issuperset(
        {"service:call", "authorization:read", "identity:lifecycle:write"}
    )
    assert grants[("nex-ae-api", "nex-wc")] == {"service:call"}
    assert grants[("nex-ae-api", "nex-wa")] == {
        "service:call",
        "work:evidence:ingest",
    }
    assert grants[("nex-wc", "nex-oa")].issuperset(
        {"service:call", "authorization:read"}
    )
    assert grants[("nex-wa", "nex-oa")].issuperset(
        {"service:call", "authorization:read", "identity:subject:verify"}
    )
    assert grants[("nex-wa", "nex-eos")].issuperset(
        {"service:call", "project:verify"}
    )
