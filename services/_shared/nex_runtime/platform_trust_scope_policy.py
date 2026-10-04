from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .auth import DEFAULT_SERVICE_SCOPE


PLATFORM_TRUST_SCOPE_POLICY_SCHEMA_VERSION = "platform_trust_scope_policy.v1"
OA_INTROSPECTION_SCOPE = "token:introspect"
ACTIVE_CLAIM_ROUTE_CLASS = "CREDENTIAL"


@dataclass(frozen=True)
class PlatformTrustGrant:
    grant_id: str
    service_id: str
    audience: str
    scopes: tuple[str, ...]
    purpose: str
    consumer_service_id: str
    environment_name: str

    def to_wire(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scopes"] = list(self.scopes)
        return payload


PLATFORM_TRUST_GRANTS = (
    PlatformTrustGrant(
        grant_id="ae_to_oa_call",
        service_id="nex-ae-api",
        audience="nex-oa",
        scopes=(DEFAULT_SERVICE_SCOPE,),
        purpose="oa_user_session",
        consumer_service_id="nex-ae-api",
        environment_name="NEX_AE_TO_OA_SERVICE_TOKEN",
    ),
    PlatformTrustGrant(
        grant_id="ae_to_cx_call",
        service_id="nex-ae-api",
        audience="nex-cx",
        scopes=(DEFAULT_SERVICE_SCOPE,),
        purpose="content_access",
        consumer_service_id="nex-ae-api",
        environment_name="NEX_AE_TO_CX_SERVICE_TOKEN",
    ),
    PlatformTrustGrant(
        grant_id="cx_to_mo_call",
        service_id="nex-cx",
        audience="nex-mo",
        scopes=(DEFAULT_SERVICE_SCOPE,),
        purpose="model_route",
        consumer_service_id="nex-cx",
        environment_name="NEX_CX_TO_MO_SERVICE_TOKEN",
    ),
    PlatformTrustGrant(
        grant_id="ae_to_ag_call",
        service_id="nex-ae-api",
        audience="nex-ag",
        scopes=(DEFAULT_SERVICE_SCOPE,),
        purpose="governance_observation",
        consumer_service_id="nex-ae-api",
        environment_name="NEX_AE_TO_AG_SERVICE_TOKEN",
    ),
    *(
        PlatformTrustGrant(
            grant_id=f"{service_id.replace('nex-', '').replace('-api', '')}_to_oa_introspection",
            service_id=service_id,
            audience="nex-oa",
            scopes=(OA_INTROSPECTION_SCOPE,),
            purpose="token_introspection",
            consumer_service_id=service_id,
            environment_name="NEX_OA_INTROSPECTION_SERVICE_TOKEN",
        )
        for service_id in ("nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
    ),
)


def platform_trust_scope_policy() -> dict[str, Any]:
    grants = [grant.to_wire() for grant in PLATFORM_TRUST_GRANTS]
    return {
        "policy_schema_version": PLATFORM_TRUST_SCOPE_POLICY_SCHEMA_VERSION,
        "active_claim_route_class": ACTIVE_CLAIM_ROUTE_CLASS,
        "grants": grants,
        "grant_count": len(grants),
        "service_ids": sorted({grant["service_id"] for grant in grants}),
        "audiences": sorted({grant["audience"] for grant in grants}),
        "raw_tokens_included": False,
    }


def validate_platform_trust_scope_policy() -> tuple[str, ...]:
    issues: list[str] = []
    grant_ids = [grant.grant_id for grant in PLATFORM_TRUST_GRANTS]
    if len(grant_ids) != len(set(grant_ids)):
        issues.append("grant_id_duplicate")
    for grant in PLATFORM_TRUST_GRANTS:
        if not grant.grant_id or grant.grant_id != grant.grant_id.strip():
            issues.append("grant_id_invalid")
        if grant.service_id not in {"nex-ae-api", "nex-cx", "nex-mo", "nex-ag"}:
            issues.append(f"service_id_invalid:{grant.grant_id}")
        if grant.audience not in {"nex-oa", "nex-cx", "nex-mo", "nex-ag"}:
            issues.append(f"audience_invalid:{grant.grant_id}")
        if grant.consumer_service_id != grant.service_id:
            issues.append(f"consumer_invalid:{grant.grant_id}")
        if grant.scopes not in {
            (DEFAULT_SERVICE_SCOPE,),
            (OA_INTROSPECTION_SCOPE,),
        }:
            issues.append(f"scope_invalid:{grant.grant_id}")
        expected_environment = (
            "NEX_OA_INTROSPECTION_SERVICE_TOKEN"
            if grant.purpose == "token_introspection"
            else {
                ("nex-ae-api", "nex-oa"): "NEX_AE_TO_OA_SERVICE_TOKEN",
                ("nex-ae-api", "nex-cx"): "NEX_AE_TO_CX_SERVICE_TOKEN",
                ("nex-cx", "nex-mo"): "NEX_CX_TO_MO_SERVICE_TOKEN",
                ("nex-ae-api", "nex-ag"): "NEX_AE_TO_AG_SERVICE_TOKEN",
            }.get((grant.service_id, grant.audience))
        )
        if grant.environment_name != expected_environment:
            issues.append(f"environment_invalid:{grant.grant_id}")
    if len(PLATFORM_TRUST_GRANTS) != 8:
        issues.append("grant_inventory_invalid")
    return tuple(sorted(set(issues)))
